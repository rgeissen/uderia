"""
Cost Management Service for LLM Token Pricing.

Provides functionality for:
- Syncing pricing data from LiteLLM
- Managing model cost database
- Calculating actual costs based on token usage
- Providing fallback pricing for unknown models
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import LLMModelCost

logger = logging.getLogger(__name__)


class CostManager:
    """Manages LLM model pricing and cost calculations."""
    
    def __init__(self):
        """Initialize cost manager."""
        self._litellm_available = False
        try:
            import litellm
            self._litellm = litellm
            self._litellm_available = True
            logger.info("LiteLLM library loaded successfully")
        except ImportError:
            logger.warning("LiteLLM library not available - will use manual pricing only")
            self._litellm = None
        
        # Load bootstrap costs from tda_config.json if not already loaded
        self._ensure_bootstrap_costs_loaded()
    
    def sync_from_litellm(self, check_availability: bool = True, user_uuid: str = None) -> Dict[str, any]:
        """
        Check model availability and sync pricing data.

        Args:
            check_availability: If True, query provider APIs to mark deprecated models (runs first)
            user_uuid: User UUID for credential lookup (required if check_availability=True)

        Returns:
            Dictionary with sync results: {
                'synced': int,
                'errors': List[str],
                'new_models': List[str],
                'updated_models': List[str],
                'availability_checked': bool,
                'deprecated_count': int,
                'undeprecated_count': int,
                'skipped_providers': List[str]
            }
        """
        if not self._litellm_available:
            return {
                'synced': 0,
                'errors': ['LiteLLM library not available'],
                'new_models': [],
                'updated_models': []
            }

        results = {
            'synced': 0,
            'errors': [],
            'new_models': [],
            'updated_models': [],
            'availability_checked': check_availability,
            'deprecated_count': 0,
            'undeprecated_count': 0,
            'skipped_providers': []
        }

        # PHASE 1: Provider Availability Check (runs first to mark deprecated models)
        if check_availability:
            if not user_uuid:
                results['errors'].append("check_availability=True requires user_uuid")
                return results

            logger.info("Phase 1: Checking model availability across providers...")
            availability_results = self._check_model_availability(user_uuid)
            results['deprecated_count'] = availability_results['deprecated_count']
            results['undeprecated_count'] = availability_results['undeprecated_count']
            results['skipped_providers'] = availability_results['skipped_providers']
            if availability_results.get('errors'):
                results['errors'].extend(availability_results['errors'])

        # PHASE 2: LiteLLM Pricing Sync (runs second to update pricing data)
        try:
            logger.info("Phase 2: Syncing pricing data from LiteLLM...")
            # Access LiteLLM's model cost dictionary
            model_cost_dict = getattr(self._litellm, 'model_cost', {})

            if not model_cost_dict:
                results['errors'].append('LiteLLM model_cost dictionary is empty')
                return results

            with get_db_session() as db:
                for model_name, cost_info in model_cost_dict.items():
                    try:
                        # Extract pricing info from LiteLLM format
                        input_cost = cost_info.get('input_cost_per_token', 0) * 1_000_000
                        output_cost = cost_info.get('output_cost_per_token', 0) * 1_000_000

                        if input_cost == 0 and output_cost == 0:
                            continue  # Skip models with no pricing info

                        # Determine provider from model name (LiteLLM format: provider/model or just model)
                        if '/' in model_name:
                            provider, model = model_name.split('/', 1)
                        else:
                            # Try to infer provider from model name
                            provider = self._infer_provider_from_model(model_name)
                            model = model_name

                        # Check if entry exists
                        stmt = select(LLMModelCost).where(
                            LLMModelCost.provider == provider,
                            LLMModelCost.model == model
                        )
                        existing = db.execute(stmt).scalar_one_or_none()

                        if existing:
                            # Update only if it's from LiteLLM (not manual or config_default)
                            # This preserves user manual entries and configured defaults
                            if not existing.is_manual_entry and existing.source not in ('manual', 'config_default'):
                                existing.input_cost_per_million = input_cost
                                existing.output_cost_per_million = output_cost
                                existing.source = 'litellm'
                                existing.last_updated = datetime.now(timezone.utc)
                                results['updated_models'].append(f"{provider}/{model}")
                        else:
                            # Create new entry
                            new_cost = LLMModelCost(
                                id=str(uuid.uuid4()),
                                provider=provider,
                                model=model,
                                input_cost_per_million=input_cost,
                                output_cost_per_million=output_cost,
                                is_manual_entry=False,
                                is_fallback=False,
                                source='litellm',
                                last_updated=datetime.now(timezone.utc)
                            )
                            db.add(new_cost)
                            results['new_models'].append(f"{provider}/{model}")

                        results['synced'] += 1

                    except Exception as e:
                        error_msg = f"Error processing model {model_name}: {str(e)}"
                        logger.warning(error_msg)
                        results['errors'].append(error_msg)

                db.commit()
                logger.info(f"LiteLLM sync completed: {results['synced']} models processed")

        except Exception as e:
            error_msg = f"Failed to sync from LiteLLM: {str(e)}"
            logger.error(error_msg, exc_info=True)
            results['errors'].append(error_msg)

        return results
    
    def _infer_provider_from_model(self, model_name: str) -> str:
        """Infer provider from model name patterns."""
        model_lower = model_name.lower()
        
        if 'gpt' in model_lower or 'o1' in model_lower:
            return 'OpenAI'
        elif 'claude' in model_lower:
            return 'Anthropic'
        elif 'gemini' in model_lower or 'palm' in model_lower:
            return 'Google'
        elif 'titan' in model_lower or 'nova' in model_lower:
            return 'Amazon'
        elif 'llama' in model_lower or 'mistral' in model_lower or 'phi' in model_lower:
            return 'Ollama'
        elif 'gemma' in model_lower:
            return 'Friendli'
        else:
            return 'Unknown'
    
    def _normalize_model_name(self, model: str) -> str:
        """
        Normalize model name by stripping ARN prefixes and regional identifiers.
        
        Examples:
            arn:aws:bedrock:eu-central-1:123:inference-profile/eu.amazon.nova-lite-v1:0 
                -> amazon.nova-lite-v1:0
            us.amazon.nova-pro-v1:0 -> amazon.nova-pro-v1:0
            eu.anthropic.claude-3-5-sonnet-20241022-v2:0 -> anthropic.claude-3-5-sonnet-20241022-v2:0
        
        Args:
            model: Raw model identifier
        
        Returns:
            Normalized model name suitable for cost table lookup
        """
        # Strip ARN prefix if present
        if model.startswith('arn:'):
            # Extract model name from ARN: arn:aws:bedrock:region:account:inference-profile/MODEL
            parts = model.split('/')
            if len(parts) > 1:
                model = parts[-1]  # Get the last part after final /
        
        # Strip regional prefix (us., eu., etc.)
        if '.' in model:
            parts = model.split('.', 1)
            # Check if first part is a region code (2-3 letter region identifiers)
            if len(parts[0]) <= 3 and parts[0].isalpha():
                model = parts[1]  # Remove regional prefix
        
        return model
    
    def get_model_cost(self, provider: str, model: str) -> Optional[Tuple[float, float]]:
        """
        Get pricing for a specific model.
        
        Args:
            provider: Provider name (e.g., 'Google', 'Anthropic', 'Amazon')
            model: Model name (e.g., 'gemini-2.5-flash', ARN, or inference profile)
        
        Returns:
            Tuple of (input_cost_per_million, output_cost_per_million) or None if not found
        """
        # Normalize model name to strip ARNs and regional prefixes
        normalized_model = self._normalize_model_name(model)
        
        with get_db_session() as db:
            # Try exact match first
            stmt = select(LLMModelCost).where(
                LLMModelCost.provider == provider,
                LLMModelCost.model == model
            )
            cost_entry = db.execute(stmt).scalar_one_or_none()
            
            if cost_entry:
                return (cost_entry.input_cost_per_million, cost_entry.output_cost_per_million)
            
            # Try normalized model name
            if normalized_model != model:
                stmt = select(LLMModelCost).where(
                    LLMModelCost.provider == provider,
                    LLMModelCost.model == normalized_model
                )
                cost_entry = db.execute(stmt).scalar_one_or_none()
                
                if cost_entry:
                    logger.debug(f"Found cost for normalized model: {model} -> {normalized_model}")
                    return (cost_entry.input_cost_per_million, cost_entry.output_cost_per_million)
            
            return None
    
    def get_fallback_cost(self) -> Tuple[float, float]:
        """
        Get fallback pricing for unknown models.

        Returns:
            Tuple of (input_cost_per_million, output_cost_per_million)
        """
        with get_db_session() as db:
            stmt = select(LLMModelCost).where(LLMModelCost.is_fallback == True)
            fallback = db.execute(stmt).first()

            if fallback and fallback[0]:
                return (fallback[0].input_cost_per_million, fallback[0].output_cost_per_million)

            # Hardcoded fallback if database entry doesn't exist (based on Gemini Flash pricing)
            return (0.10, 0.40)
    
    def calculate_cost(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate actual cost for token usage.
        
        Args:
            provider: Provider name
            model: Model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
        
        Returns:
            Cost in USD
        """
        # Get model-specific pricing or fallback
        costs = self.get_model_cost(provider, model)
        if not costs:
            logger.debug(f"No pricing found for {provider}/{model}, using fallback")
            costs = self.get_fallback_cost()
        
        input_cost_per_million, output_cost_per_million = costs
        
        # Calculate cost
        input_cost = (input_tokens / 1_000_000) * input_cost_per_million
        output_cost = (output_tokens / 1_000_000) * output_cost_per_million
        
        return input_cost + output_cost
    
    def get_all_costs(self, include_fallback: bool = False) -> List[Dict]:
        """
        Get all model costs from database.
        
        Args:
            include_fallback: Whether to include fallback entries
        
        Returns:
            List of cost dictionaries
        """
        with get_db_session() as db:
            stmt = select(LLMModelCost)
            if not include_fallback:
                stmt = stmt.where(LLMModelCost.is_fallback == False)
            stmt = stmt.order_by(LLMModelCost.provider, LLMModelCost.model)
            
            results = db.execute(stmt).scalars().all()
            return [cost.to_dict() for cost in results]
    
    def update_model_cost(self, cost_id: str, input_cost: float, output_cost: float, notes: Optional[str] = None) -> bool:
        """
        Update model cost (manual override).
        
        Args:
            cost_id: Cost entry ID
            input_cost: New input cost per million tokens
            output_cost: New output cost per million tokens
            notes: Optional admin notes
        
        Returns:
            True if updated successfully
        """
        with get_db_session() as db:
            try:
                stmt = select(LLMModelCost).where(LLMModelCost.id == cost_id)
                cost_entry = db.execute(stmt).scalar_one_or_none()
                
                if not cost_entry:
                    return False
                
                cost_entry.input_cost_per_million = input_cost
                cost_entry.output_cost_per_million = output_cost
                cost_entry.is_manual_entry = True
                cost_entry.source = 'manual'
                cost_entry.last_updated = datetime.now(timezone.utc)
                
                if notes:
                    cost_entry.notes = notes
                
                db.commit()
                logger.info(f"Updated cost for {cost_entry.provider}/{cost_entry.model}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to update model cost: {e}", exc_info=True)
                db.rollback()
                return False
    
    def add_manual_cost(self, provider: str, model: str, input_cost: float, output_cost: float, notes: Optional[str] = None) -> Optional[str]:
        """
        Add a manual cost entry for a model not in LiteLLM.
        
        Args:
            provider: Provider name
            model: Model name
            input_cost: Input cost per million tokens
            output_cost: Output cost per million tokens
            notes: Optional notes
        
        Returns:
            New cost entry ID or None if failed
        """
        with get_db_session() as db:
            try:
                # Check if already exists
                stmt = select(LLMModelCost).where(
                    LLMModelCost.provider == provider,
                    LLMModelCost.model == model
                )
                existing = db.execute(stmt).scalar_one_or_none()
                
                if existing:
                    logger.warning(f"Cost entry for {provider}/{model} already exists")
                    return None
                
                new_cost = LLMModelCost(
                    id=str(uuid.uuid4()),
                    provider=provider,
                    model=model,
                    input_cost_per_million=input_cost,
                    output_cost_per_million=output_cost,
                    is_manual_entry=True,
                    is_fallback=False,
                    source='manual',
                    last_updated=datetime.now(timezone.utc),
                    notes=notes
                )
                
                db.add(new_cost)
                db.commit()
                
                logger.info(f"Added manual cost entry for {provider}/{model}")
                return new_cost.id
                
            except Exception as e:
                logger.error(f"Failed to add manual cost: {e}", exc_info=True)
                db.rollback()
                return None
    
    def delete_model_cost(self, cost_id: str) -> bool:
        """
        Delete a model cost entry.
        
        Args:
            cost_id: Cost entry ID
        
        Returns:
            True if deleted successfully
        """
        with get_db_session() as db:
            try:
                stmt = select(LLMModelCost).where(LLMModelCost.id == cost_id)
                cost_entry = db.execute(stmt).scalar_one_or_none()
                
                if not cost_entry:
                    return False
                
                # Don't delete fallback entries
                if cost_entry.is_fallback:
                    logger.warning("Cannot delete fallback cost entry")
                    return False
                
                db.delete(cost_entry)
                db.commit()
                
                logger.info(f"Deleted cost entry for {cost_entry.provider}/{cost_entry.model}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to delete model cost: {e}", exc_info=True)
                db.rollback()
                return False
    
    def update_fallback_cost(self, input_cost: float, output_cost: float) -> bool:
        """
        Update the fallback cost for unknown models.
        
        Args:
            input_cost: New input cost per million tokens
            output_cost: New output cost per million tokens
        
        Returns:
            True if updated successfully
        """
        with get_db_session() as db:
            try:
                stmt = select(LLMModelCost).where(LLMModelCost.is_fallback == True)
                fallback = db.execute(stmt).scalar_one_or_none()
                
                if not fallback:
                    # Create fallback entry if it doesn't exist
                    fallback = LLMModelCost(
                        id='fallback-default',
                        provider='fallback',
                        model='default',
                        input_cost_per_million=input_cost,
                        output_cost_per_million=output_cost,
                        is_manual_entry=True,
                        is_fallback=True,
                        source='system_default',
                        last_updated=datetime.now(timezone.utc),
                        notes='Default fallback pricing for unknown models'
                    )
                    db.add(fallback)
                else:
                    fallback.input_cost_per_million = input_cost
                    fallback.output_cost_per_million = output_cost
                    fallback.last_updated = datetime.now(timezone.utc)
                
                db.commit()
                logger.info(f"Updated fallback cost to ${input_cost}/${output_cost} per 1M tokens")
                return True
                
            except Exception as e:
                logger.error(f"Failed to update fallback cost: {e}", exc_info=True)
                db.rollback()
                return False
    
    def _ensure_bootstrap_costs_loaded(self):
        """
        Load default costs from tda_config.json if not already loaded.
        This is called during CostManager initialization to ensure bootstrap costs
        are available without requiring manual sync.
        """
        import json
        from pathlib import Path
        
        try:
            # Check if we already have config_default entries
            with get_db_session() as db:
                stmt = select(LLMModelCost).where(LLMModelCost.source == 'config_default').limit(1)
                existing = db.execute(stmt).scalar_one_or_none()
                
                if existing:
                    logger.debug("Bootstrap costs already loaded")
                    return
            
            # Load from tda_config.json
            config_path = Path(__file__).parent.parent.parent.parent / 'tda_config.json'
            
            if not config_path.exists():
                logger.warning(f"tda_config.json not found at {config_path} - skipping bootstrap costs")
                return
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            default_costs = config.get('default_model_costs', [])
            
            if not default_costs:
                logger.debug("No default_model_costs in tda_config.json")
                return
            
            # Load bootstrap costs
            with get_db_session() as db:
                loaded_count = 0
                
                for cost_entry in default_costs:
                    provider = cost_entry.get('provider')
                    model = cost_entry.get('model')
                    input_cost = cost_entry.get('input_cost_per_million')
                    output_cost = cost_entry.get('output_cost_per_million')
                    notes = cost_entry.get('notes', '')
                    is_fallback = cost_entry.get('is_fallback', False)

                    if not all([provider, model, input_cost is not None, output_cost is not None]):
                        continue

                    # Check if entry already exists (don't overwrite)
                    stmt = select(LLMModelCost).where(
                        LLMModelCost.provider == provider,
                        LLMModelCost.model == model
                    )
                    existing = db.execute(stmt).scalar_one_or_none()

                    if existing:
                        continue

                    # Read is_deprecated from config (defaults to False if not present)
                    is_deprecated = cost_entry.get('is_deprecated', False)

                    # Insert config default
                    import uuid
                    new_cost = LLMModelCost(
                        id=str(uuid.uuid4()),
                        provider=provider,
                        model=model,
                        input_cost_per_million=input_cost,
                        output_cost_per_million=output_cost,
                        is_manual_entry=False,
                        is_fallback=is_fallback,
                        is_deprecated=is_deprecated,
                        source='config_default',
                        last_updated=datetime.now(timezone.utc),
                        notes=notes
                    )
                    db.add(new_cost)
                    loaded_count += 1
                
                db.commit()
                
                if loaded_count > 0:
                    logger.info(f"Loaded {loaded_count} bootstrap costs from tda_config.json")

        except Exception as e:
            logger.warning(f"Failed to load bootstrap costs: {e}")

    def _check_model_availability(self, user_uuid: str) -> Dict[str, any]:
        """
        Check model availability across providers and update is_deprecated flags.

        Args:
            user_uuid: User UUID for credential lookup

        Returns:
            Dictionary with deprecation statistics
        """
        import asyncio
        from trusted_data_agent.auth.encryption import decrypt_credentials

        results = {
            'deprecated_count': 0,
            'undeprecated_count': 0,
            'skipped_providers': [],
            'errors': []
        }

        # Providers to check (exclude Friendli, Azure, and Ollama per requirements)
        CHECKABLE_PROVIDERS = ['Google', 'Anthropic', 'OpenAI', 'Amazon']

        # Import list_models dynamically to avoid circular imports
        from trusted_data_agent.llm.handler import list_models

        with get_db_session() as db:
            for provider in CHECKABLE_PROVIDERS:
                try:
                    # 1. Get credentials for this provider
                    credentials = decrypt_credentials(user_uuid, provider)
                    if not credentials:
                        logger.warning(f"No credentials for {provider}, skipping availability check")
                        results['skipped_providers'].append(provider)
                        continue

                    # 2. Query provider API for available models
                    # Note: list_models is async, need to run in sync context
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        available_models_response = loop.run_until_complete(
                            list_models(provider, credentials)
                        )
                    finally:
                        loop.close()

                    # Extract just model names (list_models returns [{"name": ..., "recommended": ...}])
                    available_model_names = {m['name'] for m in available_models_response}

                    # 3. Query database for all models from this provider
                    # Exclude: config_default (Friendli), manual entries, fallback
                    stmt = select(LLMModelCost).where(
                        LLMModelCost.provider == provider,
                        LLMModelCost.source != 'config_default',
                        LLMModelCost.is_manual_entry == False,
                        LLMModelCost.is_fallback == False
                    )
                    db_models = db.execute(stmt).scalars().all()

                    # 4. Update is_deprecated flags based on availability
                    for db_model in db_models:
                        model_name = db_model.model

                        # Normalize model names for comparison (handles Bedrock ARNs)
                        normalized_db_model = self._normalize_model_name(model_name)
                        normalized_available = {self._normalize_model_name(m) for m in available_model_names}

                        is_available = (
                            model_name in available_model_names or
                            normalized_db_model in normalized_available
                        )

                        # Update deprecation status if changed
                        if is_available and db_model.is_deprecated:
                            # Model came back online - un-deprecate
                            db_model.is_deprecated = False
                            db_model.last_updated = datetime.now(timezone.utc)
                            results['undeprecated_count'] += 1
                            logger.info(f"Un-deprecated {provider}/{model_name} (returned to provider API)")

                        elif not is_available and not db_model.is_deprecated:
                            # Model disappeared - mark deprecated
                            db_model.is_deprecated = True
                            db_model.last_updated = datetime.now(timezone.utc)
                            if not db_model.notes:
                                db_model.notes = ''
                            deprecation_note = f"\n[Auto-deprecated {datetime.now(timezone.utc).isoformat()}]: Not found in provider API"
                            db_model.notes += deprecation_note
                            results['deprecated_count'] += 1
                            logger.info(f"Deprecated {provider}/{model_name} (missing from provider API)")

                    db.commit()
                    logger.info(f"Completed availability check for {provider}: {len(db_models)} models checked")

                except Exception as e:
                    error_msg = f"Failed to check availability for {provider}: {str(e)}"
                    logger.warning(error_msg, exc_info=True)
                    results['skipped_providers'].append(provider)
                    results['errors'].append(error_msg)
                    # Continue with next provider (don't fail entire sync)
                    continue

        logger.info(
            f"Availability check completed: {results['deprecated_count']} deprecated, "
            f"{results['undeprecated_count']} un-deprecated, {len(results['skipped_providers'])} providers skipped"
        )

        return results


# Singleton instance
_cost_manager = None

def get_cost_manager() -> CostManager:
    """Get singleton CostManager instance."""
    global _cost_manager
    if _cost_manager is None:
        _cost_manager = CostManager()
    return _cost_manager

