"""
RAG Template Manager: Loads and manages RAG case generation templates.

This module provides functionality to load template definitions from JSON files,
validate them, and make them available for case generation at runtime.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import sys

# Import custom exceptions
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from rag_templates.exceptions import (
    TemplateError,
    TemplateNotFoundError,
    TemplateValidationError,
    SchemaValidationError,
    TemplateRegistryError,
    TemplateLoadError
)

logger = logging.getLogger("rag_template_manager")

# Try to import jsonschema for validation
try:
    import jsonschema
    from jsonschema import Draft7Validator
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.warning("jsonschema not available - template validation will be limited")


class RAGTemplateManager:
    """
    Manages RAG Collection Templates loaded from JSON files.
    
    Templates define how RAG collections are created and populated. Two types:
    
    1. Planner Templates (Execution Strategies):
       - template_type: sql_query, api_request, custom_workflow, etc.
       - Define multi-phase execution strategies
       - Generate case studies with successful execution traces
       - Schema: planner-schema.json
    
    2. Knowledge Templates (Document Storage):
       - template_type: knowledge_repository
       - Define document chunking and embedding strategies
       - Store documents with semantic search capability
       - Schema: knowledge-template-schema.json
    
    Type Taxonomy:
    - template_type: How the template executes/processes (strategy identifier)
    - repository_type: How collection data is stored in DB (planner|knowledge)
    - category: UI grouping for template display (Database, Knowledge Management)
    
    Loads template definitions from the rag_templates directory and provides
    access to template metadata and configurations.
    """
    
    def __init__(self, templates_dir: Optional[Path] = None, plugin_dirs: Optional[List[Path]] = None):
        """
        Initialize the template manager.
        
        Args:
            templates_dir: Path to the templates directory. If None, uses default location.
            plugin_dirs: Additional plugin directories to scan. If None, uses default locations.
        """
        if templates_dir is None:
            # Default: rag_templates/ at project root
            script_dir = Path(__file__).resolve().parent
            project_root = script_dir.parent.parent.parent
            templates_dir = project_root / "rag_templates"
        
        self.templates_dir = templates_dir
        self.templates_subdir = templates_dir / "templates"
        self.registry_file = templates_dir / "template_registry.json"
        
        # Plugin directories (for modular template loading)
        self.plugin_directories = [self.templates_subdir]  # Built-in templates
        if plugin_dirs:
            self.plugin_directories.extend(plugin_dirs)
        else:
            # Add default user/system plugin directories if they exist
            user_plugins = Path.home() / ".tda" / "templates"
            if user_plugins.exists():
                self.plugin_directories.append(user_plugins)
                logger.info(f"User plugin directory found: {user_plugins}")
        
        self.registry: Dict[str, Any] = {}
        self.templates: Dict[str, Dict[str, Any]] = {}
        self.plugin_manifests: Dict[str, Dict[str, Any]] = {}  # Store plugin metadata
        
        # Load JSON schemas for validation
        self.schemas: Dict[str, Any] = {}
        self._load_schemas()
        
        # Ensure directories exist
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.templates_subdir.mkdir(parents=True, exist_ok=True)
        
        # Load templates
        self._load_registry()
        self._load_templates()
    
    def _load_schemas(self):
        """Load JSON schemas for template validation."""
        schemas_dir = self.templates_dir / "schemas"
        
        if not JSONSCHEMA_AVAILABLE:
            logger.warning("jsonschema library not installed - skipping schema loading")
            return
        
        if not schemas_dir.exists():
            logger.warning(f"Schemas directory not found: {schemas_dir}")
            return
        
        # Load planner template schema
        planner_schema_file = schemas_dir / "planner-schema.json"
        if planner_schema_file.exists():
            try:
                with open(planner_schema_file, 'r', encoding='utf-8') as f:
                    self.schemas['planner'] = json.load(f)
                logger.info("Loaded planner template schema")
            except Exception as e:
                logger.error(f"Failed to load planner schema: {e}", exc_info=True)
        
        # Load knowledge template schema
        knowledge_schema_file = schemas_dir / "knowledge-template-schema.json"
        if knowledge_schema_file.exists():
            try:
                with open(knowledge_schema_file, 'r', encoding='utf-8') as f:
                    self.schemas['knowledge'] = json.load(f)
                logger.info("Loaded knowledge template schema")
            except Exception as e:
                logger.error(f"Failed to load knowledge schema: {e}", exc_info=True)
    
    def _load_registry(self):
        """Load the template registry from disk."""
        if not self.registry_file.exists():
            logger.warning(f"Template registry not found at {self.registry_file}. Creating empty registry.")
            self.registry = {
                "registry_version": "1.0.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "templates": []
            }
            return
        
        try:
            with open(self.registry_file, 'r', encoding='utf-8') as f:
                self.registry = json.load(f)
            logger.info(f"Loaded template registry with {len(self.registry.get('templates', []))} template(s)")
        except json.JSONDecodeError as e:
            raise TemplateRegistryError(
                f"Registry file contains invalid JSON",
                original_error=e
            )
        except Exception as e:
            raise TemplateRegistryError(
                f"Failed to load template registry from {self.registry_file}",
                original_error=e
            )
    
    def _load_templates(self):
        """Load all active templates from registry."""
        for template_entry in self.registry.get("templates", []):
            template_id = template_entry.get("template_id")
            template_file = template_entry.get("template_file")
            plugin_directory = template_entry.get("plugin_directory")
            status = template_entry.get("status", "active")
            
            # Skip deprecated templates, but load all others (active, beta, coming_soon)
            if status == "deprecated":
                logger.debug(f"Skipping deprecated template {template_id}")
                continue
            
            # Support both old flat structure and new plugin directory structure
            if plugin_directory:
                # Extract just the filename from template_file if it contains path
                template_filename = Path(template_file).name if template_file else f"{template_id}.json"
                template_path = self.templates_subdir / plugin_directory / template_filename
                manifest_path = self.templates_subdir / plugin_directory / "manifest.json"
            else:
                template_path = self.templates_subdir / template_file
                manifest_path = None
            
            if not template_path.exists():
                logger.error(f"Template file not found: {template_path}")
                continue
            
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Template {template_id} contains invalid JSON: {e}")
                continue
            except Exception as e:
                logger.error(f"Failed to load template {template_id}: {e}", exc_info=True)
                continue
            
            try:
                
                # Try to load manifest if it exists
                if manifest_path and manifest_path.exists():
                    try:
                        with open(manifest_path, 'r', encoding='utf-8') as mf:
                            manifest_data = json.load(mf)
                            self.plugin_manifests[template_id] = manifest_data
                            logger.info(f"Loaded plugin manifest for {template_id}: {manifest_data.get('display_name')} v{manifest_data.get('version')}")
                    except Exception as me:
                        logger.warning(f"Failed to load manifest for {template_id}: {me}")
                elif not manifest_path:
                    # Old structure - look for manifest in same directory
                    fallback_manifest = template_path.parent / "manifest.json"
                    if fallback_manifest.exists():
                        try:
                            with open(fallback_manifest, 'r', encoding='utf-8') as mf:
                                manifest_data = json.load(mf)
                                self.plugin_manifests[template_id] = manifest_data
                                logger.debug(f"Loaded fallback manifest for {template_id}")
                        except Exception as me:
                            logger.warning(f"Failed to load fallback manifest for {template_id}: {me}")
                
                # Validate required fields - will raise TemplateValidationError if invalid
                self._validate_template(template_data)
                
                # Preserve status from registry entry
                template_data['status'] = status
                self.templates[template_id] = template_data
                logger.info(f"Loaded template: {template_id} ({template_data.get('template_name')}) with status: {status}")
                
            except TemplateValidationError:
                # Already logged by _validate_template
                continue
            except Exception as e:
                logger.error(f"Unexpected error loading template {template_id}: {e}", exc_info=True)
                continue
    
    def _validate_template(self, template_data: Dict[str, Any], strict: bool = False, validate_tools: bool = True) -> None:
        """
        Validate that a template has required fields and matches JSON schema.
        
        Performs multiple levels of validation:
        1. JSON schema validation (if jsonschema available and schema loaded)
        2. Fallback basic field validation
        3. MCP tool name validation (if validate_tools=True)
        
        Template Type Taxonomy:
        - template_type: Strategy/execution type (sql_query, api_request, knowledge_repository)
                        Determines how the template executes or processes data
        - repository_type: Storage model in collections table (planner, knowledge)
                          Determines database schema for collection storage
        - category: UI grouping for display (Database, Knowledge Management, etc.)
                   Used for organizing templates in user interface
        
        Schema Selection Logic:
        - knowledge_repository → knowledge schema (document storage)
        - all other types → planner schema (execution strategies)
        
        Args:
            template_data: Template dictionary to validate
            strict: If True, fail on unknown tools. If False, only warn.
            validate_tools: If True, validate MCP tool names. Set False to skip tool validation.
        
        Raises:
            SchemaValidationError: If JSON schema validation fails
            TemplateValidationError: If basic field validation fails
            ToolValidationError: If tool validation fails and strict=True
        """
        template_id = template_data.get("template_id", "unknown")
        template_type = template_data.get("template_type", "")
        
        # Determine which schema to use based on template_type
        # template_type="knowledge_repository" uses knowledge schema
        # template_type="knowledge_graph" has no JSON schema yet (uses basic validation)
        # All other template_types (sql_query, api_request, etc.) use planner schema
        schema_type = None
        if template_type == "knowledge_repository":
            schema_type = "knowledge"
        elif template_type == "knowledge_graph":
            schema_type = None  # No JSON schema — use basic validation
        else:
            schema_type = "planner"
        
        # Try JSON schema validation first
        if JSONSCHEMA_AVAILABLE and schema_type in self.schemas:
            try:
                schema = self.schemas[schema_type]
                validator = Draft7Validator(schema)
                errors = list(validator.iter_errors(template_data))
                
                if errors:
                    logger.error(f"Template schema validation failed for {template_id}:")
                    for error in errors[:5]:  # Show first 5 errors
                        path = ".".join(str(p) for p in error.path) if error.path else "root"
                        logger.error(f"  - {path}: {error.message}")
                    if len(errors) > 5:
                        logger.error(f"  ... and {len(errors) - 5} more errors")
                    raise SchemaValidationError(template_id, errors)
                
                logger.debug(f"Template passed JSON schema validation ({schema_type} schema)")
                
            except SchemaValidationError:
                raise  # Re-raise our custom exception
            except Exception as e:
                logger.warning(f"Schema validation failed with exception: {e}. Falling back to basic validation.")
                # Fallback to basic validation
                self._validate_template_basic(template_data, template_type)
        else:
            # Fallback to basic validation
            self._validate_template_basic(template_data, template_type)
        
        # Validate tool names (after schema/basic validation passes)
        if validate_tools:
            self._validate_tool_names(template_data, strict=strict)
    
    def _validate_tool_names(self, template_data: Dict[str, Any], strict: bool = False) -> List[str]:
        """
        Validate MCP tool names referenced in template phases.
        
        Checks:
        1. TDA core tools (always valid): TDA_FinalReport, TDA_Charting, TDA_*
        2. Tools available in APP_STATE (from live MCP server)
        3. Tool name format and patterns
        
        Args:
            template_data: Template dictionary to validate
            strict: If True, raise exception for invalid tools. If False, log warning only.
            
        Returns:
            List of invalid tool names found
            
        Raises:
            ToolValidationError: If strict=True and invalid tools found
        """
        from trusted_data_agent.core.config import APP_STATE
        from rag_templates.exceptions import ToolValidationError
        
        template_id = template_data.get("template_id", "unknown")
        template_type = template_data.get("template_type")
        
        # Knowledge repository templates don't use tools
        if template_type == "knowledge_repository":
            return []
        
        # TDA core tools that are always valid (client-side tools)
        TDA_CORE_TOOLS = {
            "TDA_FinalReport",
            "TDA_Charting",
            "TDA_WorkflowControl",
            "TDA_SessionMemory"
        }
        
        # Extract all tool names from phases
        tool_names_found = set()
        strategy_template = template_data.get("strategy_template", {})
        phases = strategy_template.get("phases", [])
        
        for phase in phases:
            # Static tool list
            relevant_tools = phase.get("relevant_tools", [])
            if isinstance(relevant_tools, list):
                tool_names_found.update(relevant_tools)
            
            # Dynamic tool from input variable
            relevant_tools_source = phase.get("relevant_tools_source")
            if relevant_tools_source:
                # This will be resolved at runtime, so we can't validate the actual name
                # But we can validate that the source variable exists
                input_vars = template_data.get("input_variables", {})
                if relevant_tools_source not in input_vars:
                    logger.warning(
                        f"Template {template_id} phase {phase.get('phase')} references "
                        f"tool source '{relevant_tools_source}' but it's not in input_variables"
                    )
        
        if not tool_names_found:
            logger.debug(f"Template {template_id} has no explicit tool references")
            return []
        
        # Get available tools from APP_STATE (loaded from MCP server)
        available_mcp_tools = set()
        if APP_STATE.get('mcp_tools'):
            available_mcp_tools = set(APP_STATE['mcp_tools'].keys())
            logger.debug(f"Validating against {len(available_mcp_tools)} MCP tools from APP_STATE")
        else:
            logger.debug(
                f"APP_STATE['mcp_tools'] not available - cannot validate against MCP server. "
                f"This is normal during initial template loading before MCP server connection."
            )
        
        # Validate each tool
        invalid_tools = []
        for tool_name in tool_names_found:
            # Check if it's a TDA core tool
            if tool_name.startswith("TDA_") and tool_name in TDA_CORE_TOOLS:
                continue
            
            # Check if it's in available MCP tools
            if available_mcp_tools and tool_name in available_mcp_tools:
                continue
            
            # Check for wildcard TDA_ tools (future compatibility)
            if tool_name.startswith("TDA_"):
                logger.info(f"Template {template_id} uses TDA tool '{tool_name}' (assuming valid)")
                continue
            
            # Tool not found
            if available_mcp_tools:  # Only mark as invalid if we have MCP tools to check against
                invalid_tools.append(tool_name)
                logger.warning(f"Template {template_id} references unknown tool: {tool_name}")
            else:
                # MCP server not available, can't validate - assume valid
                logger.debug(f"Cannot validate tool '{tool_name}' - MCP server not loaded")
        
        # Handle invalid tools based on strict mode
        if invalid_tools:
            if strict:
                raise ToolValidationError(template_id, invalid_tools)
            else:
                logger.warning(
                    f"Template {template_id} references {len(invalid_tools)} unknown tool(s): "
                    f"{', '.join(invalid_tools)}. This may cause runtime errors."
                )
        
        return invalid_tools
    
    def _validate_template_basic(self, template_data: Dict[str, Any], template_type: str) -> None:
        """
        Basic field validation fallback when JSON schema validation unavailable.
        
        Validates based on template_type:
        - knowledge_repository: Requires repository_configuration
        - All others (planner types): Require input_variables, output_configuration, strategy_template
        
        Raises:
            TemplateValidationError: If required fields are missing
        """
        template_id = template_data.get("template_id", "unknown")
        
        # Common required fields for all templates
        common_required = [
            "template_id",
            "template_name",
            "template_type"
        ]
        
        missing_fields = [field for field in common_required if field not in template_data]
        if missing_fields:
            message = f"Template missing required fields: {', '.join(missing_fields)}"
            logger.error(message)
            raise TemplateValidationError(template_id, message, {"missing_fields": missing_fields})
        
        # Knowledge repository templates have different required fields
        if template_type == "knowledge_repository":
            knowledge_required = ["repository_configuration"]
            missing_fields = [field for field in knowledge_required if field not in template_data]
            if missing_fields:
                message = f"Knowledge template missing required fields: {', '.join(missing_fields)}"
                logger.error(message)
                raise TemplateValidationError(template_id, message, {"missing_fields": missing_fields})
        elif template_type == "knowledge_graph":
            # Knowledge graph templates use extraction_phases instead of strategy_template
            kg_required = [
                "input_variables",
                "extraction_phases"
            ]
            missing_fields = [field for field in kg_required if field not in template_data]
            if missing_fields:
                message = f"Knowledge graph template missing required fields: {', '.join(missing_fields)}"
                logger.error(message)
                raise TemplateValidationError(template_id, message, {"missing_fields": missing_fields})
        else:
            # Planner templates (sql_query, api_request, custom_workflow, etc.)
            # These define execution strategies with phases
            planner_required = [
                "input_variables",
                "output_configuration",
                "strategy_template"
            ]
            missing_fields = [field for field in planner_required if field not in template_data]
            if missing_fields:
                message = f"Planner template missing required fields: {', '.join(missing_fields)}"
                logger.error(message)
                raise TemplateValidationError(template_id, message, {"missing_fields": missing_fields})
    
    def get_template(self, template_id: str) -> Dict[str, Any]:
        """
        Get a template by ID.
        
        Args:
            template_id: The unique template identifier
            
        Returns:
            Template data dictionary
            
        Raises:
            TemplateNotFoundError: If template_id is not found
        """
        template = self.templates.get(template_id)
        if template is None:
            raise TemplateNotFoundError(template_id)
        return template
    
    def get_all_templates(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all loaded templates.
        
        Returns:
            Dictionary mapping template IDs to template data
        """
        return self.templates.copy()
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        Get a list of all templates with basic metadata.
        Prefers display_name from manifest over template_name from template data.
        
        Returns:
            List of template metadata dictionaries including type taxonomy info
        """
        templates_list = []
        for template_id, template_data in self.templates.items():
            # Get manifest data if available
            manifest = self.plugin_manifests.get(template_id, {})
            
            # Get category from registry
            category = None
            for template_entry in self.registry.get("templates", []):
                if template_entry.get("template_id") == template_id:
                    category = template_entry.get("category")
                    break
            
            templates_list.append({
                "template_id": template_id,
                "template_name": template_data.get("template_name"),
                "display_name": manifest.get("display_name", template_data.get("template_name")),
                "template_type": template_data.get("template_type"),
                "description": manifest.get("description", template_data.get("description")),
                "status": template_data.get("status", "active"),
                "version": manifest.get("version", template_data.get("template_version")),
                "category": category
            })
        
        return templates_list
    
    def get_template_config(self, template_id: str) -> Dict[str, Any]:
        """
        Get the editable configuration for a template.
        
        Args:
            template_id: The template identifier
            
        Returns:
            Dictionary of editable configuration values
            
        Raises:
            TemplateNotFoundError: If template_id is not found
        """
        template = self.get_template(template_id)  # Will raise TemplateNotFoundError if not found
        
        output_config = template.get("output_configuration", {})
        editable_config = {}
        
        # Extract editable values
        for key, value in output_config.items():
            if isinstance(value, dict) and value.get("editable"):
                editable_config[key] = value.get("value")
            elif key == "estimated_tokens" and isinstance(value, dict):
                editable_config["estimated_input_tokens"] = value.get("input_tokens", {}).get("value", 150)
                editable_config["estimated_output_tokens"] = value.get("output_tokens", {}).get("value", 180)
        
        # Add default MCP tool if available
        input_vars = template.get("input_variables", {})
        if "mcp_tool_name" in input_vars:
            editable_config["default_mcp_tool"] = input_vars["mcp_tool_name"].get("default")
        
        if "mcp_context_prompt" in input_vars:
            editable_config["default_mcp_context_prompt"] = input_vars["mcp_context_prompt"].get("default")
        
        return editable_config
    
    def update_template_config(self, template_id: str, config: Dict[str, Any]):
        """
        Update editable configuration for a template (runtime only, not persisted).
        
        Args:
            template_id: The template identifier
            config: Dictionary of configuration values to update
            
        Raises:
            TemplateNotFoundError: If template_id is not found
        """
        template = self.get_template(template_id)  # Will raise TemplateNotFoundError if not found
        
        output_config = template.get("output_configuration", {})
        
        # Update editable values
        if "estimated_input_tokens" in config and "estimated_tokens" in output_config:
            output_config["estimated_tokens"]["input_tokens"]["value"] = config["estimated_input_tokens"]
        
        if "estimated_output_tokens" in config and "estimated_tokens" in output_config:
            output_config["estimated_tokens"]["output_tokens"]["value"] = config["estimated_output_tokens"]
        
        if "default_mcp_tool" in config:
            input_vars = template.get("input_variables", {})
            if "mcp_tool_name" in input_vars:
                input_vars["mcp_tool_name"]["default"] = config["default_mcp_tool"]
        
        if "default_mcp_context_prompt" in config:
            input_vars = template.get("input_variables", {})
            if "mcp_context_prompt" in input_vars:
                input_vars["mcp_context_prompt"]["default"] = config["default_mcp_context_prompt"]
        
        logger.info(f"Updated runtime configuration for template {template_id}")
    
    def discover_plugins(self) -> List[Dict[str, Any]]:
        """
        Discover all available plugins from configured directories.
        
        Returns:
            List of plugin metadata dictionaries
        """
        discovered = []
        
        for plugin_dir in self.plugin_directories:
            if not plugin_dir.exists():
                continue
                
            logger.debug(f"Scanning plugin directory: {plugin_dir}")
            
            # Look for manifest.json files
            for manifest_file in plugin_dir.rglob("manifest.json"):
                try:
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    
                    # Check if template file exists
                    template_file = manifest_file.parent / manifest.get("files", {}).get("template", "")
                    if not template_file.exists():
                        logger.warning(f"Template file not found for manifest: {manifest_file}")
                        continue
                    
                    discovered.append({
                        "manifest": manifest,
                        "manifest_path": str(manifest_file),
                        "template_path": str(template_file),
                        "plugin_dir": str(manifest_file.parent),
                        "is_builtin": plugin_dir == self.templates_subdir
                    })
                    
                except Exception as e:
                    logger.error(f"Failed to parse manifest {manifest_file}: {e}")
        
        logger.info(f"Discovered {len(discovered)} plugin(s)")
        return discovered
    
    def get_plugin_info(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Get plugin manifest information for a template.
        
        Args:
            template_id: The template identifier
            
        Returns:
            Plugin manifest dictionary or None
        """
        return self.plugin_manifests.get(template_id)
    
    def reload_templates(self):
        """Reload all templates from disk."""
        self.templates.clear()
        self.plugin_manifests.clear()
        self._load_registry()
        self._load_templates()
        logger.info("Templates reloaded")


# Singleton instance
_template_manager_instance: Optional[RAGTemplateManager] = None


def get_template_manager() -> RAGTemplateManager:
    """Get or create the singleton template manager instance."""
    global _template_manager_instance
    if _template_manager_instance is None:
        _template_manager_instance = RAGTemplateManager()
    return _template_manager_instance
