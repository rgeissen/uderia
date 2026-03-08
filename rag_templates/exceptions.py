"""
Custom exceptions for the RAG template system.

This module provides a hierarchy of exceptions specific to template operations,
allowing for more precise error handling and better debugging.
"""


class TemplateError(Exception):
    """
    Base exception for all template-related errors.
    
    All template-specific exceptions inherit from this class, allowing
    callers to catch all template errors with a single except clause.
    """
    pass


class TemplateNotFoundError(TemplateError):
    """
    Raised when a requested template ID is not found in the registry.
    
    Attributes:
        template_id (str): The ID of the template that was not found
        message (str): Human-readable error message
    """
    def __init__(self, template_id: str, message: str = None):
        self.template_id = template_id
        if message is None:
            message = f"Template '{template_id}' not found in registry"
        super().__init__(message)


class TemplateValidationError(TemplateError):
    """
    Raised when a template fails validation checks.
    
    This is a base class for validation-related errors. Use more specific
    subclasses (like SchemaValidationError) when appropriate.
    
    Attributes:
        template_id (str): The ID of the template that failed validation
        details (dict): Additional details about the validation failure
        message (str): Human-readable error message
    """
    def __init__(self, template_id: str, message: str, details: dict = None):
        self.template_id = template_id
        self.details = details or {}
        super().__init__(message)


class SchemaValidationError(TemplateValidationError):
    """
    Raised when a template fails JSON schema validation.
    
    This exception is raised when a template's structure doesn't match
    the expected JSON schema (planner-schema.json or knowledge-template-schema.json).
    
    Attributes:
        template_id (str): The ID of the template that failed validation
        schema_errors (list): List of validation errors from jsonschema
        message (str): Human-readable error message
    """
    def __init__(self, template_id: str, schema_errors: list):
        self.schema_errors = schema_errors
        
        # Format schema errors into readable message
        error_details = []
        for error in schema_errors:
            path = " -> ".join(str(p) for p in error.path) if error.path else "root"
            error_details.append(f"  - {path}: {error.message}")
        
        message = f"Template '{template_id}' failed schema validation:\n" + "\n".join(error_details)
        details = {"schema_errors": [{"path": list(e.path), "message": e.message} for e in schema_errors]}
        
        super().__init__(template_id, message, details)


class TemplateRegistryError(TemplateError):
    """
    Raised when there are issues with the template registry file.
    
    This includes problems like:
    - Registry file not found
    - Registry file contains invalid JSON
    - Registry structure doesn't match expected format
    
    Attributes:
        message (str): Human-readable error message
        original_error (Exception): The underlying exception that caused this error (optional)
    """
    def __init__(self, message: str, original_error: Exception = None):
        self.original_error = original_error
        if original_error:
            message = f"{message}: {str(original_error)}"
        super().__init__(message)


class TemplateLoadError(TemplateError):
    """
    Raised when a template file cannot be loaded.
    
    This includes problems like:
    - Template file not found
    - Template file contains invalid JSON
    - Template file is not readable
    
    Attributes:
        template_id (str): The ID of the template that failed to load
        file_path (str): The path to the template file (if known)
        message (str): Human-readable error message
        original_error (Exception): The underlying exception that caused this error (optional)
    """
    def __init__(self, template_id: str, message: str, file_path: str = None, original_error: Exception = None):
        self.template_id = template_id
        self.file_path = file_path
        self.original_error = original_error
        
        full_message = f"Failed to load template '{template_id}'"
        if file_path:
            full_message += f" from '{file_path}'"
        full_message += f": {message}"
        if original_error:
            full_message += f" ({type(original_error).__name__}: {str(original_error)})"
            
        super().__init__(full_message)


class ToolValidationError(TemplateValidationError):
    """
    Raised when a template references invalid or unknown MCP tools.
    
    This exception is raised when a template's strategy phases reference
    MCP tools that don't exist or aren't available.
    
    Attributes:
        template_id (str): The ID of the template with invalid tools
        invalid_tools (list): List of invalid tool names
        phase (str): The phase where invalid tools were found (optional)
        message (str): Human-readable error message
    """
    def __init__(self, template_id: str, invalid_tools: list, phase: str = None):
        self.invalid_tools = invalid_tools
        self.phase = phase
        
        tools_str = ", ".join(f"'{tool}'" for tool in invalid_tools)
        message = f"Template '{template_id}' references invalid MCP tools: {tools_str}"
        if phase:
            message += f" in phase '{phase}'"
        
        details = {"invalid_tools": invalid_tools, "phase": phase}
        super().__init__(template_id, message, details)
