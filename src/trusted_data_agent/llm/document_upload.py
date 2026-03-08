"""
LLM Document Upload Abstraction Layer

Provides a unified interface for uploading documents to LLM providers,
with automatic fallback to text extraction when native upload is not supported.

Supports:
- Google Gemini: Native PDF/image upload via File API
- Anthropic Claude: Native PDF upload via base64 encoding
- AWS Bedrock (Claude): Native PDF support
- OpenAI GPT-4o/Vision: Native image/PDF for vision models
- Other providers: Automatic text extraction fallback
"""

import base64
import io
import logging
from typing import Dict, Any, List, Tuple, Optional
from enum import Enum

app_logger = logging.getLogger('tda')


class DocumentUploadCapability(Enum):
    """Document upload capability levels for LLM providers."""
    NATIVE_FULL = "native_full"          # Full native document support (PDFs, images)
    NATIVE_VISION_ONLY = "native_vision" # Vision models only (images, some PDFs)
    TEXT_EXTRACTION = "text_extraction"  # Fallback to text extraction
    NOT_SUPPORTED = "not_supported"      # No document support


class DocumentUploadConfig:
    """Configuration for document upload capabilities by provider."""
    
    # Provider capability definitions
    PROVIDER_CAPABILITIES = {
        "Google": {
            "capability": DocumentUploadCapability.NATIVE_FULL,
            "supported_formats": [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"],
            "max_file_size_mb": 20,
            "requires_file_api": True,
            "description": "Google Gemini with native File API support"
        },
        "Anthropic": {
            "capability": DocumentUploadCapability.NATIVE_FULL,
            "supported_formats": [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"],
            "max_file_size_mb": 32,
            "requires_base64": True,
            "description": "Anthropic Claude with native PDF/image support"
        },
        "Amazon": {
            "capability": DocumentUploadCapability.NATIVE_FULL,
            "supported_formats": [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"],
            "max_file_size_mb": 25,
            "requires_base64": True,
            "model_filter": ["claude"],  # Only Claude models on Bedrock
            "description": "AWS Bedrock with Claude models"
        },
        "OpenAI": {
            "capability": DocumentUploadCapability.NATIVE_VISION_ONLY,
            "supported_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
            "max_file_size_mb": 20,
            "model_filter": ["gpt-4o", "gpt-4-vision", "gpt-4-turbo"],
            "description": "OpenAI GPT-4o/Vision models only"
        },
        "Azure": {
            "capability": DocumentUploadCapability.NATIVE_VISION_ONLY,
            "supported_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
            "max_file_size_mb": 20,
            "model_filter": ["gpt-4o", "gpt-4-vision", "gpt-4-turbo"],
            "description": "Azure OpenAI with vision-enabled deployments"
        },
        "Friendli": {
            "capability": DocumentUploadCapability.TEXT_EXTRACTION,
            "supported_formats": [],
            "max_file_size_mb": 0,
            "description": "Friendli AI - text extraction fallback"
        },
        "Ollama": {
            "capability": DocumentUploadCapability.TEXT_EXTRACTION,
            "supported_formats": [],
            "max_file_size_mb": 0,
            "description": "Ollama - text extraction fallback (model-dependent)"
        }
    }
    
    @classmethod
    def get_capability(cls, provider: str, model: str = None) -> DocumentUploadCapability:
        """
        Get the document upload capability for a provider/model combination.
        
        Args:
            provider: LLM provider name
            model: Optional model name for filtering
            
        Returns:
            DocumentUploadCapability enum value
        """
        config = cls.PROVIDER_CAPABILITIES.get(provider, {})
        capability = config.get("capability", DocumentUploadCapability.TEXT_EXTRACTION)
        
        # Check model filter if specified
        if model and "model_filter" in config:
            model_lower = model.lower()
            if not any(filter_str in model_lower for filter_str in config["model_filter"]):
                # Model doesn't match filter, downgrade to text extraction
                return DocumentUploadCapability.TEXT_EXTRACTION
        
        return capability
    
    @classmethod
    def supports_native_upload(cls, provider: str, model: str = None) -> bool:
        """Check if provider/model supports any form of native document upload."""
        capability = cls.get_capability(provider, model)
        return capability in [DocumentUploadCapability.NATIVE_FULL, 
                             DocumentUploadCapability.NATIVE_VISION_ONLY]
    
    @classmethod
    def get_supported_formats(cls, provider: str, model: str = None) -> List[str]:
        """Get list of supported file formats for native upload."""
        if not cls.supports_native_upload(provider, model):
            return []
        config = cls.PROVIDER_CAPABILITIES.get(provider, {})
        return config.get("supported_formats", [])
    
    @classmethod
    def get_max_file_size(cls, provider: str, model: str = None) -> int:
        """Get maximum file size in bytes for native upload."""
        if not cls.supports_native_upload(provider, model):
            return 0
        config = cls.PROVIDER_CAPABILITIES.get(provider, {})
        return config.get("max_file_size_mb", 0) * 1024 * 1024


class DocumentUploadHandler:
    """
    Handles document upload for LLM providers with automatic method selection.
    Can be used as instance or with static methods.
    """
    
    def __init__(self, provider: str = None, model: str = None, llm_instance: Any = None):
        """
        Initialize handler. Parameters are optional for static method usage.
        
        Args:
            provider: LLM provider name (optional)
            model: Model name (optional)
            llm_instance: LLM instance (optional)
        """
        self.provider = provider
        self.model = model
        self.llm_instance = llm_instance
        self.capability = DocumentUploadConfig.get_capability(provider, model) if provider else None
    
    def _get_mime_type(self, file_extension: str) -> str:
        """Get MIME type for file extension."""
        mime_types = {
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        return mime_types.get(file_extension.lower(), 'application/octet-stream')
    
    def prepare_document_for_llm(self, file_path: str, provider_name: str, 
                                 model_name: str = None, effective_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Prepare a document for LLM consumption (simplified interface for REST endpoints).
        
        Args:
            file_path: Path to the document file
            provider_name: LLM provider name
            model_name: Model name (optional)
            effective_config: Effective configuration from database (optional)
            
        Returns:
            Dictionary with document preparation result:
            {
                'method': str,  # 'native_google', 'native_anthropic', 'text_extraction'
                'content': str,  # Extracted text (for text_extraction method)
                'content_type': str,  # MIME type
                'file_size': int,  # File size in bytes
                'filename': str  # Original filename
            }
        """
        import os
        
        # Check if native upload should be used
        use_native = effective_config['use_native_upload'] if effective_config else True
        capability = DocumentUploadConfig.get_capability(provider_name, model_name)
        
        # Get file info
        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
        file_extension = os.path.splitext(filename)[1]
        content_type = self._get_mime_type(file_extension)
        
        result = {
            'filename': filename,
            'file_size': file_size,
            'content_type': content_type
        }
        
        # Decide method
        if use_native and capability in [DocumentUploadCapability.NATIVE_FULL, 
                                         DocumentUploadCapability.NATIVE_VISION_ONLY]:
            # Native upload methods (future: implement actual upload)
            if provider_name == "Google":
                result['method'] = 'native_google'
                # For now, also extract text as fallback
                text_result = self._extract_text_from_document(file_path)
                result.update(text_result)
            elif provider_name == "Anthropic":
                result['method'] = 'native_anthropic'
                # For now, also extract text as fallback
                text_result = self._extract_text_from_document(file_path)
                result.update(text_result)
            elif provider_name in ["OpenAI", "Azure"]:
                result['method'] = 'native_vision'
                # For now, also extract text as fallback
                text_result = self._extract_text_from_document(file_path)
                result.update(text_result)
            else:
                # Fallback to text extraction
                result['method'] = 'text_extraction'
                text_result = self._extract_text_from_document(file_path)
                result.update(text_result)
        else:
            # Text extraction fallback
            result['method'] = 'text_extraction'
            text_result = self._extract_text_from_document(file_path)
            result.update(text_result)
        
        return result
    
    def _extract_text_from_document(self, file_path: str) -> Dict[str, Any]:
        """
        Extract text from a document file (simplified for static usage).
        
        Args:
            file_path: Path to the document file
            
        Returns:
            Dictionary with extracted content
        """
        import os
        
        file_extension = os.path.splitext(file_path)[1]
        filename = os.path.basename(file_path)
        
        try:
            if file_extension.lower() == '.pdf':
                try:
                    from PyPDF2 import PdfReader
                    with open(file_path, 'rb') as f:
                        pdf_reader = PdfReader(f)
                        text = "\n".join([page.extract_text() for page in pdf_reader.pages])
                    return {'content': text if text.strip() else "[PDF text extraction failed]"}
                except ImportError:
                    app_logger.warning("PyPDF2 not installed, cannot extract PDF text")
                    return {'content': "[PDF text extraction not available - PyPDF2 not installed]"}
            
            elif file_extension.lower() in ['.doc', '.docx']:
                try:
                    from docx import Document
                    doc = Document(file_path)
                    text = "\n".join([para.text for para in doc.paragraphs])
                    return {'content': text if text.strip() else "[Word document text extraction failed]"}
                except ImportError:
                    app_logger.warning("python-docx not installed, cannot extract Word text")
                    return {'content': "[Word text extraction not available - python-docx not installed]"}
            
            elif file_extension.lower() in ['.txt', '.md', '.markdown']:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                return {'content': text}
            
            else:
                return {'content': f"[Unsupported file format: {file_extension}]"}
                
        except Exception as e:
            app_logger.error(f"Text extraction failed for {filename}: {e}")
            return {'content': f"[Text extraction failed: {str(e)}]"}
    
    @staticmethod
    def get_capability_info(provider: str, model: str = None) -> Dict[str, Any]:
        """
        Get comprehensive capability information for a provider/model.
        
        Returns:
            Dictionary with capability details for admin UI
        """
        capability = DocumentUploadConfig.get_capability(provider, model)
        config = DocumentUploadConfig.PROVIDER_CAPABILITIES.get(provider, {})
        
        return {
            "provider": provider,
            "model": model,
            "capability": capability.value,
            "supports_native": DocumentUploadConfig.supports_native_upload(provider, model),
            "supported_formats": DocumentUploadConfig.get_supported_formats(provider, model),
            "max_file_size_mb": config.get("max_file_size_mb", 0),
            "description": config.get("description", "Unknown"),
            "requires_file_api": config.get("requires_file_api", False),
            "requires_base64": config.get("requires_base64", False)
        }
