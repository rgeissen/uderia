"""
Document upload configuration management.

Provides CRUD operations for DocumentUploadConfig stored in the database.
Integrates with DocumentUploadHandler to apply admin overrides.
"""

import json
import logging
from typing import Optional, Dict, List, Any

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import DocumentUploadConfig

logger = logging.getLogger("quart.app")


class DocumentUploadConfigManager:
    """
    Manages document upload configurations stored in the database.
    
    Provides methods to get, update, and reset provider configurations.
    Admin overrides stored here take precedence over defaults in DocumentUploadConfig class.
    """
    
    @staticmethod
    def get_config(provider: str) -> Optional[DocumentUploadConfig]:
        """
        Get document upload configuration for a specific provider.
        
        Args:
            provider: Provider name (e.g., 'Google', 'Anthropic')
            
        Returns:
            DocumentUploadConfig object or None if not found
        """
        try:
            with get_db_session() as session:
                config = session.query(DocumentUploadConfig).filter_by(provider=provider).first()
                if config:
                    # Detach from session to prevent lazy loading issues
                    session.expunge(config)
                return config
        except Exception as e:
            logger.error(f"Error getting document upload config for {provider}: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_all_configs() -> List[DocumentUploadConfig]:
        """
        Get all document upload configurations.
        
        Returns:
            List of DocumentUploadConfig objects
        """
        try:
            with get_db_session() as session:
                configs = session.query(DocumentUploadConfig).all()
                # Detach from session
                for config in configs:
                    session.expunge(config)
                return configs
        except Exception as e:
            logger.error(f"Error getting all document upload configs: {e}", exc_info=True)
            return []
    
    @staticmethod
    def update_config(
        provider: str,
        use_native_upload: Optional[bool] = None,
        enabled: Optional[bool] = None,
        max_file_size_mb: Optional[int] = None,
        supported_formats_override: Optional[List[str]] = None,
        notes: Optional[str] = None
    ) -> Optional[DocumentUploadConfig]:
        """
        Update document upload configuration for a provider.
        
        Args:
            provider: Provider name
            use_native_upload: Whether to use native upload API (overrides default)
            enabled: Whether document upload is enabled for this provider
            max_file_size_mb: Override default file size limit (None = use provider default)
            supported_formats_override: Override supported formats (None = use provider default)
            notes: Admin notes about the configuration change
            
        Returns:
            Updated DocumentUploadConfig object or None on error
        """
        try:
            with get_db_session() as session:
                config = session.query(DocumentUploadConfig).filter_by(provider=provider).first()
                
                if not config:
                    # Create new config if it doesn't exist
                    config = DocumentUploadConfig(provider=provider)
                    session.add(config)
                
                # Update fields if provided
                if use_native_upload is not None:
                    config.use_native_upload = use_native_upload
                if enabled is not None:
                    config.enabled = enabled
                if max_file_size_mb is not None:
                    config.max_file_size_mb = max_file_size_mb
                if supported_formats_override is not None:
                    # Store as JSON string
                    config.supported_formats_override = json.dumps(supported_formats_override)
                if notes is not None:
                    config.notes = notes
                
                session.commit()
                session.refresh(config)
                session.expunge(config)
                
                logger.info(f"Updated document upload config for {provider}")
                return config
                
        except Exception as e:
            logger.error(f"Error updating document upload config for {provider}: {e}", exc_info=True)
            return None
    
    @staticmethod
    def reset_to_defaults(provider: str) -> Optional[DocumentUploadConfig]:
        """
        Reset provider configuration to defaults (remove overrides).
        
        Args:
            provider: Provider name
            
        Returns:
            Reset DocumentUploadConfig object or None on error
        """
        try:
            with get_db_session() as session:
                config = session.query(DocumentUploadConfig).filter_by(provider=provider).first()
                
                if config:
                    # Reset to defaults
                    config.use_native_upload = True
                    config.enabled = True
                    config.max_file_size_mb = None
                    config.supported_formats_override = None
                    config.notes = 'Reset to defaults'
                    
                    session.commit()
                    session.refresh(config)
                    session.expunge(config)
                    
                    logger.info(f"Reset document upload config for {provider} to defaults")
                    return config
                else:
                    logger.warning(f"No config found for {provider}, creating default")
                    return DocumentUploadConfigManager.update_config(
                        provider=provider,
                        use_native_upload=True,
                        enabled=True,
                        notes='Created with defaults'
                    )
                    
        except Exception as e:
            logger.error(f"Error resetting document upload config for {provider}: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_effective_config(provider: str) -> Dict[str, Any]:
        """
        Get effective configuration for a provider, merging database overrides with defaults.
        
        This is the primary method to use when preparing documents for upload.
        Returns merged configuration with database overrides applied.
        
        Args:
            provider: Provider name
            
        Returns:
            Dictionary with effective configuration:
            {
                'provider': str,
                'enabled': bool,
                'use_native_upload': bool,
                'capability': str,  # From PROVIDER_CAPABILITIES
                'max_file_size_mb': int,
                'supported_formats': List[str],
                'has_overrides': bool,
                'notes': str or None
            }
        """
        from trusted_data_agent.llm.document_upload import DocumentUploadHandler
        
        try:
            # Get database config
            db_config = DocumentUploadConfigManager.get_config(provider)
            
            # Get default capability info
            default_info = DocumentUploadHandler.get_capability_info(provider)
            
            # Merge configurations
            effective_config = {
                'provider': provider,
                'enabled': db_config.enabled if db_config else True,
                'use_native_upload': db_config.use_native_upload if db_config else True,
                'capability': default_info.get('capability', 'NOT_SUPPORTED'),
                'max_file_size_mb': default_info.get('max_file_size_mb', 10),
                'supported_formats': default_info.get('supported_formats', []),
                'has_overrides': False,
                'notes': None
            }
            
            # Apply database overrides if present
            if db_config:
                if db_config.max_file_size_mb is not None:
                    effective_config['max_file_size_mb'] = db_config.max_file_size_mb
                    effective_config['has_overrides'] = True
                
                if db_config.supported_formats_override:
                    try:
                        formats_override = json.loads(db_config.supported_formats_override)
                        effective_config['supported_formats'] = formats_override
                        effective_config['has_overrides'] = True
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in supported_formats_override for {provider}")
                
                effective_config['notes'] = db_config.notes
            
            return effective_config
            
        except Exception as e:
            logger.error(f"Error getting effective config for {provider}: {e}", exc_info=True)
            # Return safe defaults on error
            return {
                'provider': provider,
                'enabled': True,
                'use_native_upload': True,
                'capability': 'TEXT_EXTRACTION',
                'max_file_size_mb': 10,
                'supported_formats': ['pdf', 'docx', 'txt'],
                'has_overrides': False,
                'notes': None
            }
    
    @staticmethod
    def delete_config(provider: str) -> bool:
        """
        Delete document upload configuration for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            with get_db_session() as session:
                config = session.query(DocumentUploadConfig).filter_by(provider=provider).first()
                if config:
                    session.delete(config)
                    session.commit()
                    logger.info(f"Deleted document upload config for {provider}")
                    return True
                else:
                    logger.warning(f"No config found for {provider} to delete")
                    return False
        except Exception as e:
            logger.error(f"Error deleting document upload config for {provider}: {e}", exc_info=True)
            return False
