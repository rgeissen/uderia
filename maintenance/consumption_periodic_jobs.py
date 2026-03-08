#!/usr/bin/env python3
"""
Periodic maintenance jobs for consumption tracking.

Scheduled jobs:
- Hourly: Reset hourly rate limit counters
- Daily: Reset daily rate limit counters, update 24h velocity metrics
- Monthly: Archive previous period, start new period, cleanup old turn records

Usage:
    # Run all jobs (checks timestamps and runs only what's needed)
    python maintenance/consumption_periodic_jobs.py
    
    # Run specific job
    python maintenance/consumption_periodic_jobs.py --job hourly
    python maintenance/consumption_periodic_jobs.py --job daily
    python maintenance/consumption_periodic_jobs.py --job monthly
    
    # Dry run
    python maintenance/consumption_periodic_jobs.py --dry-run

Setup cron (recommended):
    # Hourly job (every hour at :05)
    5 * * * * cd /path/to/uderia && python maintenance/consumption_periodic_jobs.py --job hourly
    
    # Daily job (every day at 00:05)
    5 0 * * * cd /path/to/uderia && python maintenance/consumption_periodic_jobs.py --job daily
    
    # Monthly job (1st of month at 00:10)
    10 0 1 * * cd /path/to/uderia && python maintenance/consumption_periodic_jobs.py --job monthly
    
    # Or run all jobs frequently and let script decide what to run
    */5 * * * * cd /path/to/uderia && python maintenance/consumption_periodic_jobs.py
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from trusted_data_agent.auth.models import UserConsumption
from trusted_data_agent.auth.consumption_manager import ConsumptionManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConsumptionPeriodicJobs:
    """Manages periodic maintenance jobs for consumption tracking."""
    
    def __init__(self, db_path: str):
        """
        Initialize job runner.
        
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        
        # Setup database
        engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Session = sessionmaker(bind=engine)
        self.session = Session()
        self.manager = ConsumptionManager(self.session)
    
    def run_hourly_reset(self, dry_run: bool = False) -> dict:
        """
        Reset hourly rate limit counters for all users.
        Only resets counters that are past their hour_reset_at timestamp.
        
        Args:
            dry_run: If True, don't commit changes
            
        Returns:
            Dictionary with job results
        """
        logger.info("Running hourly rate limit reset...")
        
        now = datetime.now(timezone.utc)
        updated_count = 0
        
        # Query all users whose hour_reset_at is in the past
        consumptions = self.session.query(UserConsumption).filter(
            UserConsumption.hour_reset_at <= now
        ).all()
        
        for consumption in consumptions:
            # Track peak before reset
            if consumption.requests_this_hour > consumption.peak_requests_per_hour:
                consumption.peak_requests_per_hour = consumption.requests_this_hour
            
            # Reset counter
            consumption.requests_this_hour = 0
            
            # Set next reset time (top of next hour)
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            consumption.hour_reset_at = next_hour
            
            consumption.last_updated_at = now
            updated_count += 1
        
        if not dry_run:
            self.session.commit()
            logger.info(f"Reset hourly counters for {updated_count} users")
        else:
            self.session.rollback()
            logger.info(f"DRY RUN: Would reset hourly counters for {updated_count} users")
        
        return {
            'job': 'hourly_reset',
            'updated_count': updated_count,
            'timestamp': now.isoformat()
        }
    
    def run_daily_reset(self, dry_run: bool = False) -> dict:
        """
        Reset daily rate limit counters and update 24h velocity metrics.
        Only resets counters that are past their day_reset_at timestamp.
        
        Args:
            dry_run: If True, don't commit changes
            
        Returns:
            Dictionary with job results
        """
        logger.info("Running daily rate limit reset and velocity update...")
        
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        updated_count = 0
        
        # Query all users whose day_reset_at is in the past
        consumptions = self.session.query(UserConsumption).filter(
            UserConsumption.day_reset_at <= now
        ).all()
        
        for consumption in consumptions:
            # Track peak before reset
            if consumption.requests_today > consumption.peak_requests_per_day:
                consumption.peak_requests_per_day = consumption.requests_today
            
            # Reset daily counter
            consumption.requests_today = 0
            
            # Set next reset time (start of next day)
            next_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            consumption.day_reset_at = next_day
            
            # Update 24h velocity metrics
            # Count sessions/turns created in last 24 hours
            from trusted_data_agent.auth.models import ConsumptionTurn
            
            turns_last_24h = self.session.query(ConsumptionTurn).filter(
                ConsumptionTurn.user_id == consumption.user_id,
                ConsumptionTurn.created_at >= yesterday
            ).count()
            
            consumption.turns_last_24h = turns_last_24h
            
            # Update sessions_last_24h (approximate - count unique session_ids in last 24h)
            from sqlalchemy import func, distinct
            sessions_last_24h = self.session.query(
                func.count(distinct(ConsumptionTurn.session_id))
            ).filter(
                ConsumptionTurn.user_id == consumption.user_id,
                ConsumptionTurn.created_at >= yesterday
            ).scalar() or 0
            
            consumption.sessions_last_24h = sessions_last_24h
            
            consumption.last_updated_at = now
            updated_count += 1
        
        if not dry_run:
            self.session.commit()
            logger.info(f"Reset daily counters and updated velocity for {updated_count} users")
        else:
            self.session.rollback()
            logger.info(f"DRY RUN: Would reset daily counters for {updated_count} users")
        
        return {
            'job': 'daily_reset',
            'updated_count': updated_count,
            'timestamp': now.isoformat()
        }
    
    def run_monthly_rollover(self, dry_run: bool = False) -> dict:
        """
        Archive previous period and start new period for all users.
        Only processes users whose current_period is in the past.
        
        Args:
            dry_run: If True, don't commit changes
            
        Returns:
            Dictionary with job results
        """
        logger.info("Running monthly period rollover...")
        
        now = datetime.now(timezone.utc)
        current_period = now.strftime("%Y-%m")
        archived_count = 0
        
        # Query all users whose period needs rollover
        consumptions = self.session.query(UserConsumption).filter(
            UserConsumption.current_period != current_period
        ).all()
        
        for consumption in consumptions:
            try:
                self.manager.rollover_period(consumption.user_id)
                archived_count += 1
            except Exception as e:
                logger.error(f"Failed to rollover period for user {consumption.user_id}: {e}")
        
        if not dry_run:
            logger.info(f"Archived and rolled over {archived_count} user periods")
        else:
            logger.info(f"DRY RUN: Would archive and rollover {archived_count} user periods")
        
        # Cleanup old turn records (keep last 90 days)
        cleanup_count = 0
        if not dry_run:
            try:
                cleanup_count = self.manager.cleanup_old_turns(days_to_keep=90)
            except Exception as e:
                logger.error(f"Failed to cleanup old turns: {e}")
        
        return {
            'job': 'monthly_rollover',
            'archived_count': archived_count,
            'cleanup_count': cleanup_count,
            'timestamp': now.isoformat()
        }
    
    def run_all_jobs(self, dry_run: bool = False) -> dict:
        """
        Run all jobs that are needed based on current time.
        Each job checks its own conditions.
        
        Args:
            dry_run: If True, don't commit changes
            
        Returns:
            Dictionary with all job results
        """
        results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'jobs_run': []
        }
        
        # Always try hourly reset (it checks timestamps internally)
        try:
            hourly_result = self.run_hourly_reset(dry_run)
            if hourly_result['updated_count'] > 0:
                results['jobs_run'].append(hourly_result)
        except Exception as e:
            logger.error(f"Hourly reset failed: {e}")
        
        # Always try daily reset (it checks timestamps internally)
        try:
            daily_result = self.run_daily_reset(dry_run)
            if daily_result['updated_count'] > 0:
                results['jobs_run'].append(daily_result)
        except Exception as e:
            logger.error(f"Daily reset failed: {e}")
        
        # Always try monthly rollover (it checks periods internally)
        try:
            monthly_result = self.run_monthly_rollover(dry_run)
            if monthly_result['archived_count'] > 0:
                results['jobs_run'].append(monthly_result)
        except Exception as e:
            logger.error(f"Monthly rollover failed: {e}")
        
        return results


def main():
    parser = argparse.ArgumentParser(description='Run consumption tracking periodic jobs')
    parser.add_argument('--db-path', default='tda_auth.db', help='Path to SQLite database')
    parser.add_argument('--job', choices=['hourly', 'daily', 'monthly', 'all'], default='all',
                       help='Which job to run (default: all)')
    parser.add_argument('--dry-run', action='store_true', help='Check without committing changes')
    
    args = parser.parse_args()
    
    try:
        jobs = ConsumptionPeriodicJobs(args.db_path)
        
        if args.job == 'hourly':
            result = jobs.run_hourly_reset(dry_run=args.dry_run)
            logger.info(f"Hourly job completed: {result}")
        
        elif args.job == 'daily':
            result = jobs.run_daily_reset(dry_run=args.dry_run)
            logger.info(f"Daily job completed: {result}")
        
        elif args.job == 'monthly':
            result = jobs.run_monthly_rollover(dry_run=args.dry_run)
            logger.info(f"Monthly job completed: {result}")
        
        else:  # all
            results = jobs.run_all_jobs(dry_run=args.dry_run)
            logger.info(f"All jobs completed: {len(results['jobs_run'])} jobs ran")
            for job_result in results['jobs_run']:
                logger.info(f"  - {job_result['job']}: updated {job_result.get('updated_count', job_result.get('archived_count', 0))} records")
        
        return 0
    
    except Exception as e:
        logger.exception(f"Periodic jobs failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
