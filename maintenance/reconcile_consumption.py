#!/usr/bin/env python3
"""
Reconciliation tool for consumption tracking.

Validates database consumption data against file-based session storage (source of truth).
Detects drift and auto-corrects if drift < 5% threshold.

Usage:
    python maintenance/reconcile_consumption.py [--dry-run] [--fix] [--threshold 5.0]
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from collections import defaultdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from trusted_data_agent.auth.models import UserConsumption, User
from trusted_data_agent.auth.consumption_manager import ConsumptionManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConsumptionReconciler:
    """Reconciles database consumption data with file-based source of truth."""
    
    def __init__(self, db_path: str, sessions_dir: str, threshold: float = 5.0):
        """
        Initialize reconciler.
        
        Args:
            db_path: Path to SQLite database
            sessions_dir: Path to tda_sessions directory
            threshold: Acceptable drift percentage (default 5.0%)
        """
        self.db_path = db_path
        self.sessions_dir = Path(sessions_dir)
        self.threshold = threshold
        
        # Setup database
        engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Session = sessionmaker(bind=engine)
        self.session = Session()
        self.manager = ConsumptionManager(self.session)
    
    def scan_user_sessions(self, user_id: str) -> Dict:
        """
        Scan all session files for a user and calculate totals.
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with aggregated metrics
        """
        user_dir = self.sessions_dir / user_id
        
        if not user_dir.exists():
            logger.warning(f"No session directory for user {user_id}")
            return self._empty_metrics()
        
        metrics = self._empty_metrics()
        
        for session_file in user_dir.glob('*.json'):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                
                metrics['total_sessions'] += 1
                metrics['total_input_tokens'] += session_data.get('input_tokens', 0)
                metrics['total_output_tokens'] += session_data.get('output_tokens', 0)
                
                # Analyze workflow history
                workflow_history = session_data.get('last_turn_data', {}).get('workflow_history', [])
                for turn in workflow_history:
                    if turn.get('isValid', True):
                        metrics['total_turns'] += 1
                        
                        status = turn.get('status', 'success')
                        if status == 'success':
                            metrics['successful_turns'] += 1
                        elif status in ['failure', 'error']:
                            metrics['failed_turns'] += 1
                        
                        # RAG metrics
                        if turn.get('rag_source_collection_id'):
                            metrics['rag_guided_turns'] += 1
                            metrics['rag_output_tokens_saved'] += turn.get('rag_efficiency_gain', 0)
                
            except Exception as e:
                logger.error(f"Error processing {session_file}: {e}")
        
        metrics['total_tokens'] = metrics['total_input_tokens'] + metrics['total_output_tokens']
        
        return metrics
    
    def _empty_metrics(self) -> Dict:
        """Return empty metrics dict."""
        return {
            'total_sessions': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_tokens': 0,
            'successful_turns': 0,
            'failed_turns': 0,
            'total_turns': 0,
            'rag_guided_turns': 0,
            'rag_output_tokens_saved': 0
        }
    
    def calculate_drift(self, db_value: int, file_value: int) -> float:
        """
        Calculate drift percentage.
        
        Args:
            db_value: Value from database
            file_value: Value from files (source of truth)
            
        Returns:
            Drift percentage (absolute)
        """
        if file_value == 0:
            return 0.0 if db_value == 0 else 100.0
        
        return abs((db_value - file_value) / file_value * 100)
    
    def reconcile_user(self, user_id: str, fix: bool = False) -> Dict:
        """
        Reconcile consumption data for a single user.
        
        Args:
            user_id: User ID
            fix: If True, auto-correct drift if within threshold
            
        Returns:
            Dictionary with reconciliation results
        """
        # Get DB data
        consumption = self.session.query(UserConsumption).filter_by(user_id=user_id).first()
        
        if not consumption:
            logger.warning(f"No consumption record in DB for user {user_id}")
            return {
                'user_id': user_id,
                'status': 'missing_db_record',
                'drift': None
            }
        
        # Scan files
        file_metrics = self.scan_user_sessions(user_id)
        
        # Calculate drift for critical fields
        drifts = {
            'total_tokens': self.calculate_drift(consumption.total_tokens, file_metrics['total_tokens']),
            'total_input_tokens': self.calculate_drift(consumption.total_input_tokens, file_metrics['total_input_tokens']),
            'total_output_tokens': self.calculate_drift(consumption.total_output_tokens, file_metrics['total_output_tokens']),
            'total_sessions': self.calculate_drift(consumption.total_sessions, file_metrics['total_sessions']),
            'total_turns': self.calculate_drift(consumption.total_turns, file_metrics['total_turns']),
            'successful_turns': self.calculate_drift(consumption.successful_turns, file_metrics['successful_turns']),
            'rag_guided_turns': self.calculate_drift(consumption.rag_guided_turns, file_metrics['rag_guided_turns'])
        }
        
        max_drift = max(drifts.values())
        
        result = {
            'user_id': user_id,
            'status': 'ok' if max_drift <= self.threshold else 'drift_detected',
            'max_drift_percent': round(max_drift, 2),
            'drifts': {k: round(v, 2) for k, v in drifts.items()},
            'db_values': {
                'total_tokens': consumption.total_tokens,
                'total_sessions': consumption.total_sessions,
                'total_turns': consumption.total_turns
            },
            'file_values': {
                'total_tokens': file_metrics['total_tokens'],
                'total_sessions': file_metrics['total_sessions'],
                'total_turns': file_metrics['total_turns']
            }
        }
        
        # Auto-fix if requested and drift is within threshold
        if fix and max_drift > 0 and max_drift <= self.threshold:
            logger.info(f"Auto-correcting drift for user {user_id} (drift: {max_drift:.2f}%)")
            
            # Update DB with file values
            consumption.total_tokens = file_metrics['total_tokens']
            consumption.total_input_tokens = file_metrics['total_input_tokens']
            consumption.total_output_tokens = file_metrics['total_output_tokens']
            consumption.total_sessions = file_metrics['total_sessions']
            consumption.total_turns = file_metrics['total_turns']
            consumption.successful_turns = file_metrics['successful_turns']
            consumption.failed_turns = file_metrics['failed_turns']
            consumption.rag_guided_turns = file_metrics['rag_guided_turns']
            consumption.rag_output_tokens_saved = file_metrics['rag_output_tokens_saved']
            consumption.last_updated_at = datetime.now(timezone.utc)
            
            self.session.commit()
            result['status'] = 'corrected'
            result['action'] = 'auto_corrected'
        
        elif max_drift > self.threshold:
            result['action'] = 'manual_review_required'
            logger.warning(f"User {user_id} exceeds drift threshold ({max_drift:.2f}% > {self.threshold}%) - manual review required")
        
        return result
    
    def reconcile_all_users(self, fix: bool = False) -> Tuple[List[Dict], Dict]:
        """
        Reconcile all users with consumption records.
        
        Args:
            fix: If True, auto-correct drift if within threshold
            
        Returns:
            Tuple of (results list, summary dict)
        """
        users = self.session.query(UserConsumption).all()
        
        results = []
        summary = {
            'total_users': len(users),
            'ok': 0,
            'drift_detected': 0,
            'corrected': 0,
            'manual_review_required': 0,
            'missing_db_record': 0
        }
        
        for consumption in users:
            result = self.reconcile_user(consumption.user_id, fix=fix)
            results.append(result)
            
            status = result['status']
            if status in summary:
                summary[status] += 1
            
            if result.get('action') == 'auto_corrected':
                summary['corrected'] += 1
            elif result.get('action') == 'manual_review_required':
                summary['manual_review_required'] += 1
        
        return results, summary
    
    def print_report(self, results: List[Dict], summary: Dict) -> None:
        """Print reconciliation report."""
        print("\n" + "="*70)
        print("CONSUMPTION RECONCILIATION REPORT")
        print("="*70)
        print(f"Total Users:              {summary['total_users']}")
        print(f"Status OK:                {summary['ok']} ({summary['ok']/summary['total_users']*100:.1f}%)")
        print(f"Drift Detected:           {summary['drift_detected']}")
        print(f"Auto-Corrected:           {summary['corrected']}")
        print(f"Manual Review Required:   {summary['manual_review_required']}")
        print(f"Missing DB Records:       {summary['missing_db_record']}")
        print("="*70)
        
        # Show top 10 users with highest drift
        drift_users = [r for r in results if r['status'] in ['drift_detected', 'corrected']]
        if drift_users:
            drift_users.sort(key=lambda x: x['max_drift_percent'], reverse=True)
            
            print("\nTop 10 Users with Highest Drift:")
            print("-"*70)
            for i, user in enumerate(drift_users[:10], 1):
                print(f"{i}. User {user['user_id']}: {user['max_drift_percent']}% drift")
                print(f"   Status: {user['status']}, Action: {user.get('action', 'none')}")
                print(f"   DB tokens: {user['db_values']['total_tokens']:,}, File tokens: {user['file_values']['total_tokens']:,}")
        
        print("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Reconcile consumption tracking with file storage')
    parser.add_argument('--db-path', default='tda_auth.db', help='Path to SQLite database')
    parser.add_argument('--sessions-dir', default='tda_sessions', help='Path to sessions directory')
    parser.add_argument('--threshold', type=float, default=5.0, help='Acceptable drift percentage (default 5.0)')
    parser.add_argument('--dry-run', action='store_true', help='Check without fixing')
    parser.add_argument('--fix', action='store_true', help='Auto-correct drift within threshold')
    parser.add_argument('--user', help='Reconcile specific user only')
    
    args = parser.parse_args()
    
    if args.dry_run and args.fix:
        parser.error("Cannot specify both --dry-run and --fix")
    
    try:
        reconciler = ConsumptionReconciler(args.db_path, args.sessions_dir, args.threshold)
        
        if args.user:
            # Reconcile single user
            result = reconciler.reconcile_user(args.user, fix=args.fix and not args.dry_run)
            print(json.dumps(result, indent=2))
        else:
            # Reconcile all users
            results, summary = reconciler.reconcile_all_users(fix=args.fix and not args.dry_run)
            reconciler.print_report(results, summary)
            
            # Exit with error code if manual review required
            if summary['manual_review_required'] > 0:
                logger.error(f"{summary['manual_review_required']} users require manual review")
                return 1
        
        logger.info("Reconciliation completed successfully")
        return 0
    
    except Exception as e:
        logger.exception(f"Reconciliation failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
