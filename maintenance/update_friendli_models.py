#!/usr/bin/env python3
"""
Manage Friendli serverless models in the database.

This script allows administrators to:
- List all models with their status
- Add new models
- Mark models as deprecated
- Re-activate deprecated models
- Update model properties
- Re-sync from tda_config.json

Usage:
    python maintenance/update_friendli_models.py list
    python maintenance/update_friendli_models.py add "model-org/model-name" --billing-type token --notes "Description"
    python maintenance/update_friendli_models.py deprecate "model-org/model-name"
    python maintenance/update_friendli_models.py activate "model-org/model-name"
    python maintenance/update_friendli_models.py update "model-org/model-name" --billing-type time --notes "New notes"
    python maintenance/update_friendli_models.py sync  # Re-sync from tda_config.json (adds new, preserves manual)
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import ProviderAvailableModel


def list_models(args):
    """List all Friendli serverless models."""
    with get_db_session() as session:
        models = session.query(ProviderAvailableModel).filter_by(
            provider='Friendli',
            endpoint_type='serverless'
        ).order_by(ProviderAvailableModel.status, ProviderAvailableModel.billing_type, ProviderAvailableModel.model_id).all()

        if not models:
            print("No Friendli serverless models found in database.")
            print("Run 'python maintenance/update_friendli_models.py sync' to bootstrap from config.")
            return

        print(f"\n{'Model ID':<55} {'Billing':<8} {'Status':<12} {'Source':<15}")
        print("-" * 95)

        active_count = 0
        deprecated_count = 0
        for m in models:
            if m.status == 'active':
                status_icon = "✅"
                active_count += 1
            elif m.status == 'deprecated':
                status_icon = "⚠️ "
                deprecated_count += 1
            else:
                status_icon = "🔜"

            print(f"{status_icon} {m.model_id:<52} {m.billing_type:<8} {m.status:<12} {m.source:<15}")

        print(f"\nTotal: {len(models)} models ({active_count} active, {deprecated_count} deprecated)")


def add_model(args):
    """Add a new Friendli serverless model."""
    with get_db_session() as session:
        # Check if exists
        existing = session.query(ProviderAvailableModel).filter_by(
            provider='Friendli',
            model_id=args.model_id,
            endpoint_type='serverless'
        ).first()

        if existing:
            print(f"Model already exists: {args.model_id}")
            print(f"  Status: {existing.status}, Billing: {existing.billing_type}")
            print("Use 'update' command to modify existing models.")
            return

        # Generate display name from model_id if not provided
        display_name = args.display_name
        if not display_name:
            # Extract last part and clean it up
            display_name = args.model_id.split('/')[-1].replace('-', ' ').replace('_', ' ')

        model = ProviderAvailableModel(
            provider='Friendli',
            model_id=args.model_id,
            display_name=display_name,
            billing_type=args.billing_type,
            status='active',
            endpoint_type='serverless',
            notes=args.notes or '',
            source='manual',
            is_active=True
        )
        session.add(model)
        session.commit()

        print(f"✅ Added model: {args.model_id}")
        print(f"   Display name: {display_name}")
        print(f"   Billing type: {args.billing_type}")
        if args.notes:
            print(f"   Notes: {args.notes}")


def deprecate_model(args):
    """Mark a model as deprecated."""
    with get_db_session() as session:
        model = session.query(ProviderAvailableModel).filter_by(
            provider='Friendli',
            model_id=args.model_id,
            endpoint_type='serverless'
        ).first()

        if not model:
            print(f"Model not found: {args.model_id}")
            return

        if model.status == 'deprecated':
            print(f"Model is already deprecated: {args.model_id}")
            return

        old_status = model.status
        model.status = 'deprecated'
        # Append deprecation note
        deprecation_note = f"[Deprecated {datetime.now().strftime('%Y-%m-%d')}]"
        if model.notes:
            model.notes = f"{model.notes} {deprecation_note}"
        else:
            model.notes = deprecation_note
        session.commit()

        print(f"⚠️  Deprecated model: {args.model_id}")
        print(f"   Previous status: {old_status}")


def activate_model(args):
    """Re-activate a deprecated model."""
    with get_db_session() as session:
        model = session.query(ProviderAvailableModel).filter_by(
            provider='Friendli',
            model_id=args.model_id,
            endpoint_type='serverless'
        ).first()

        if not model:
            print(f"Model not found: {args.model_id}")
            return

        if model.status == 'active':
            print(f"Model is already active: {args.model_id}")
            return

        old_status = model.status
        model.status = 'active'
        model.is_active = True
        session.commit()

        print(f"✅ Activated model: {args.model_id}")
        print(f"   Previous status: {old_status}")


def update_model(args):
    """Update model properties."""
    with get_db_session() as session:
        model = session.query(ProviderAvailableModel).filter_by(
            provider='Friendli',
            model_id=args.model_id,
            endpoint_type='serverless'
        ).first()

        if not model:
            print(f"Model not found: {args.model_id}")
            return

        updated = False

        if args.billing_type and args.billing_type != model.billing_type:
            print(f"   Billing: {model.billing_type} -> {args.billing_type}")
            model.billing_type = args.billing_type
            updated = True

        if args.notes is not None:  # Allow empty string to clear notes
            old_notes = model.notes or '(none)'
            new_notes = args.notes or '(none)'
            print(f"   Notes: {old_notes} -> {new_notes}")
            model.notes = args.notes
            updated = True

        if args.display_name:
            old_display = model.display_name or '(none)'
            print(f"   Display name: {old_display} -> {args.display_name}")
            model.display_name = args.display_name
            updated = True

        if updated:
            # Mark as manually modified if it was a config default
            if model.source == 'config_default':
                model.source = 'manual'
                print(f"   Source: config_default -> manual")
            session.commit()
            print(f"✅ Updated model: {args.model_id}")
        else:
            print("No changes specified. Use --billing-type, --display-name, or --notes to update.")


def sync_from_config(args):
    """Sync models from tda_config.json, preserving existing entries."""
    import json

    config_path = Path(__file__).parent.parent / 'tda_config.json'
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return

    with open(config_path, 'r') as f:
        config = json.load(f)

    friendli_models = config.get('friendli_serverless_models', [])
    if not friendli_models:
        print("No friendli_serverless_models found in tda_config.json")
        return

    added = 0
    skipped = 0

    with get_db_session() as session:
        for model_data in friendli_models:
            model_id = model_data.get('model_id')
            if not model_id:
                continue

            existing = session.query(ProviderAvailableModel).filter_by(
                provider='Friendli',
                model_id=model_id,
                endpoint_type='serverless'
            ).first()

            if existing:
                skipped += 1
                continue

            model = ProviderAvailableModel(
                provider='Friendli',
                model_id=model_id,
                display_name=model_data.get('display_name'),
                billing_type=model_data.get('billing_type', 'token'),
                status=model_data.get('status', 'active'),
                endpoint_type='serverless',
                notes=model_data.get('notes', ''),
                source='config_default',
                is_active=True
            )
            session.add(model)
            added += 1
            print(f"  + {model_id}")

        session.commit()

    print(f"\n✅ Sync complete: {added} added, {skipped} already exist")


def main():
    parser = argparse.ArgumentParser(
        description='Manage Friendli serverless models in the database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list
  %(prog)s add "new-org/new-model" --billing-type token --notes "New model"
  %(prog)s deprecate "old-org/old-model"
  %(prog)s activate "old-org/old-model"
  %(prog)s update "model-org/model" --billing-type time
  %(prog)s sync
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # List command
    list_parser = subparsers.add_parser('list', help='List all Friendli serverless models')
    list_parser.set_defaults(func=list_models)

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new model')
    add_parser.add_argument('model_id', help='Model ID (e.g., "meta-llama/Llama-3.3-70B-Instruct")')
    add_parser.add_argument('--billing-type', choices=['token', 'time', 'free'], default='token',
                           help='Billing type (default: token)')
    add_parser.add_argument('--display-name', help='Human-readable display name (auto-generated if not provided)')
    add_parser.add_argument('--notes', help='Additional notes about the model')
    add_parser.set_defaults(func=add_model)

    # Deprecate command
    dep_parser = subparsers.add_parser('deprecate', help='Mark a model as deprecated (hidden from dropdown)')
    dep_parser.add_argument('model_id', help='Model ID to deprecate')
    dep_parser.set_defaults(func=deprecate_model)

    # Activate command
    act_parser = subparsers.add_parser('activate', help='Re-activate a deprecated model')
    act_parser.add_argument('model_id', help='Model ID to activate')
    act_parser.set_defaults(func=activate_model)

    # Update command
    upd_parser = subparsers.add_parser('update', help='Update model properties')
    upd_parser.add_argument('model_id', help='Model ID to update')
    upd_parser.add_argument('--billing-type', choices=['token', 'time', 'free'],
                           help='New billing type')
    upd_parser.add_argument('--display-name', help='New human-readable display name')
    upd_parser.add_argument('--notes', help='New notes (use empty string to clear)')
    upd_parser.set_defaults(func=update_model)

    # Sync command
    sync_parser = subparsers.add_parser('sync', help='Sync from tda_config.json (adds new models, preserves existing)')
    sync_parser.set_defaults(func=sync_from_config)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == '__main__':
    main()
