"""
RAG Template Generator: Creates RAG cases from templates and examples.

This module provides functionality to populate RAG collections with synthetic cases
based on predefined templates and user-provided examples (e.g., SQL statements with questions).
"""

import json
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from trusted_data_agent.agent.rag_template_manager import get_template_manager
from trusted_data_agent.llm.document_upload import DocumentUploadHandler
from trusted_data_agent.llm.document_upload_config_manager import DocumentUploadConfigManager

logger = logging.getLogger("rag_template_generator")


class RAGTemplateGenerator:
    """
    Generates RAG cases from templates and user-provided examples.
    
    Supports multiple template types (SQL, API, etc.) and generates complete
    case_*.json files that can be added to RAG collections.
    """
    
    # Single session ID for all template-generated cases
    TEMPLATE_SESSION_ID = "00000000-0000-0000-0000-000000000000"
    
    def __init__(self, rag_retriever):
        """
        Initialize the template generator.
        
        Args:
            rag_retriever: The RAGRetriever instance to use for adding cases
        """
        self.rag_retriever = rag_retriever
        self.template_manager = get_template_manager()
        
        # Load SQL template configuration
        self.sql_template = self.template_manager.get_template("sql_query_v1")
        if self.sql_template:
            self.sql_config = self.template_manager.get_template_config("sql_query_v1")
            logger.info(f"Loaded SQL template configuration: {self.sql_config}")
        else:
            logger.warning("SQL template not found, using hardcoded defaults")
            self.sql_template = None
            self.sql_config = {
                "default_mcp_tool": "base_readQuery",
                "estimated_input_tokens": 150,
                "estimated_output_tokens": 180
            }
    
    def _process_document_upload(self, input_values: Dict[str, Any], template: Dict[str, Any], 
                                 provider_name: str = None, model_name: str = None) -> Dict[str, Any]:
        """
        Process document_file input if present, using DocumentUploadHandler abstraction.
        
        Args:
            input_values: Input values that may contain document_file
            template: Template definition with validation rules
            provider_name: Optional provider name for config lookup
            model_name: Optional model name for capability check
            
        Returns:
            Updated input_values with document_content populated from document_file
        """
        # Check if template uses document upload handler
        validation_rules = template.get("validation_rules", {})
        doc_processing = validation_rules.get("document_processing", {})
        
        if not doc_processing.get("use_upload_handler"):
            return input_values
        
        # Check if document_file is provided
        document_file = input_values.get("document_file")
        if not document_file:
            # No file provided, check if document_content exists
            if not input_values.get("document_content"):
                logger.warning("Neither document_file nor document_content provided")
            return input_values
        
        logger.info(f"Processing document upload: {document_file}")
        
        # Get provider config if available
        effective_config = None
        if provider_name:
            effective_config = DocumentUploadConfigManager.get_effective_config(provider_name)
        
        # Use DocumentUploadHandler to process the file
        handler = DocumentUploadHandler()
        
        try:
            result = handler.prepare_document_for_llm(
                file_path=document_file,
                provider_name=provider_name or "Google",  # Default to Google if not specified
                model_name=model_name,
                effective_config=effective_config
            )
            
            # Populate document_content with extracted/prepared content
            input_values = input_values.copy()
            input_values["document_content"] = result.get("content", "")
            
            logger.info(f"Document processed using method: {result.get('method')}")
            logger.info(f"Extracted content length: {len(result.get('content', ''))} characters")
            
            return input_values
            
        except Exception as e:
            logger.error(f"Document processing failed: {e}", exc_info=True)
            # Set error message as content
            input_values = input_values.copy()
            input_values["document_content"] = f"[Document processing failed: {str(e)}]"
            return input_values
        
    def generate_case_from_template(
        self,
        template_id: str,
        collection_id: int,
        input_values: Dict[str, Any],
        provider_name: str = None,
        model_name: str = None,
        user_uuid: str = None
    ) -> Dict[str, Any]:
        """
        Generate a RAG case from any template using template definition.
        
        Args:
            template_id: The template identifier (e.g., "sql_query_v1")
            collection_id: The collection ID to associate this case with
            input_values: Dictionary of input variable values
                         (e.g., {"user_query": "...", "sql_statement": "...", "database_name": "...", "document_file": "..."})
            provider_name: Optional provider name for document upload configuration
            model_name: Optional model name for document upload capability check
            user_uuid: Optional user ID for case attribution (defaults to template session ID if not provided)
            
        Returns:
            Complete case study dictionary ready to be saved
        """
        # Get template definition
        template = self.template_manager.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # Process document upload if needed
        input_values = self._process_document_upload(input_values, template, provider_name, model_name)
        
        # Get template configuration
        config = self.template_manager.get_template_config(template_id)
        
        # Generate case ID
        case_id = str(uuid.uuid4())
        
        # Build metadata from output_configuration
        output_config = template.get("output_configuration", {})
        metadata = {
            "session_id": output_config.get("session_id", {}).get("value", self.TEMPLATE_SESSION_ID),
            "turn_id": output_config.get("turn_id", {}).get("value", 1),
            "is_success": output_config.get("is_success", {}).get("value", True),
            "task_id": f"template-task-{case_id[:8]}",
            "collection_id": collection_id,
            "had_plan_improvements": False,
            "had_tactical_improvements": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_uuid": user_uuid or self.TEMPLATE_SESSION_ID,
            "user_feedback_score": output_config.get("user_feedback_score", {}).get("value", 0),
            "llm_config": {
                "provider": output_config.get("llm_config", {}).get("provider", {}).get("value", "Template"),
                "model": output_config.get("llm_config", {}).get("model", {}).get("value", template_id),
                "profile_tag": output_config.get("llm_config", {}).get("profile_tag", {}).get("value", None),
                "input_tokens": config.get("estimated_input_tokens", 150),
                "output_tokens": config.get("estimated_output_tokens", 180)
            },
            "is_most_efficient": output_config.get("is_most_efficient", {}).get("value", True),
            "template_generated": output_config.get("template_generated", {}).get("value", True),
            "template_type": output_config.get("template_type", {}).get("value", template.get("template_type"))
        }
        
        # Build strategy from strategy_template
        strategy_template = template.get("strategy_template", {})
        phase_count = strategy_template.get("phase_count", 0)
        phases = []
        
        steps_per_phase = {}
        for phase_def in strategy_template.get("phases", []):
            phase_num = phase_def.get("phase")
            
            # Build phase
            phase = {
                "phase": phase_num,
                "goal": self._build_goal_from_template(phase_def, input_values),
                "relevant_tools": self._get_tools_from_template(phase_def, input_values),
                "arguments": self._build_arguments_from_template(phase_def, input_values)
            }
            
            phases.append(phase)
            steps_per_phase[str(phase_num)] = 1
        
        metadata["strategy_metrics"] = {
            "phase_count": phase_count,
            "steps_per_phase": steps_per_phase,
            "total_steps": len(phases)
        }
        
        # Apply metadata mapping from template
        metadata_mapping = template.get("metadata_mapping", {})
        for key, mapping in metadata_mapping.items():
            source = mapping.get("source")
            condition = mapping.get("condition")
            
            # Check condition (e.g., "if database_name")
            if condition and condition.startswith("if "):
                check_var = condition[3:].strip()
                if check_var not in input_values or not input_values.get(check_var):
                    continue
            
            if source in input_values:
                metadata[key] = input_values[source]
        
        # Build complete case study
        case_study = {
            "case_id": case_id,
            "metadata": metadata,
            "intent": {
                "user_query": input_values.get("user_query", "")
            },
            "successful_strategy": {
                "phases": phases
            }
        }
        
        return case_study
    
    def _build_goal_from_template(self, phase_def: Dict[str, Any], input_values: Dict[str, Any]) -> str:
        """Build phase goal from template with variable substitution."""
        goal_template = phase_def.get("goal_template") or phase_def.get("goal", "")
        
        if not goal_template:
            return "Execute phase"
        
        # Simple variable substitution {variable_name}
        goal = goal_template
        goal_variables = phase_def.get("goal_variables", {})
        
        for var_name, var_config in goal_variables.items():
            condition = var_config.get("condition")
            if condition and condition.startswith("if "):
                check_var = condition[3:].strip()
                if check_var not in input_values or not input_values.get(check_var):
                    # Replace with empty string if condition not met
                    goal = goal.replace(f"{{{var_name}}}", "")
                    continue
            
            # Get value from input
            source = var_config.get("source")
            
            # If no source is specified, this is a conditional formatting variable
            if source is None:
                # Use the format string directly, substituting any referenced variables
                fmt = var_config.get("format", "")
                formatted_value = fmt
                # Replace any variable references in the format string
                for input_key, input_val in input_values.items():
                    formatted_value = formatted_value.replace(f"{{{input_key}}}", str(input_val) if input_val else "")
            else:
                value = input_values.get(source, "")
                
                # Apply transformation
                transform = var_config.get("transform")
                if transform == "truncate":
                    max_length = var_config.get("max_length", 50)
                    if len(str(value)) > max_length:
                        value = str(value)[:max_length] + "..."
                
                # Format
                fmt = var_config.get("format", "{" + source + "}")
                formatted_value = fmt.replace(f"{{{source}}}", str(value))
            
            goal = goal.replace(f"{{{var_name}}}", formatted_value)
        
        return goal
    
    def _get_tools_from_template(self, phase_def: Dict[str, Any], input_values: Dict[str, Any]) -> List[str]:
        """Get relevant tools for phase from template."""
        # Check if tools are static
        if "relevant_tools" in phase_def:
            return phase_def["relevant_tools"]
        
        # Or sourced from input variable
        tools_source = phase_def.get("relevant_tools_source")
        if tools_source and tools_source in input_values:
            tool_value = input_values[tools_source]
            return [tool_value] if isinstance(tool_value, str) else tool_value
        
        return []
    
    def _build_arguments_from_template(self, phase_def: Dict[str, Any], input_values: Dict[str, Any]) -> Dict[str, Any]:
        """Build phase arguments from template."""
        arguments = {}
        args_template = phase_def.get("arguments", {})
        
        for arg_name, arg_config in args_template.items():
            source = arg_config.get("source")
            condition = arg_config.get("condition")
            
            # Check condition
            if condition and condition.startswith("if "):
                check_var = condition[3:].strip()
                if check_var not in input_values or not input_values.get(check_var):
                    continue
            
            # Get value from input
            if source in input_values:
                arguments[arg_name] = input_values[source]
        
        return arguments
    
    # Backwards compatibility wrapper
    def generate_sql_template_case(
        self,
        user_query: str,
        sql_statement: str,
        collection_id: int,
        database_name: Optional[str] = None,
        table_names: Optional[List[str]] = None,
        mcp_tool_name: Optional[str] = None,
        user_uuid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a RAG case from the SQL template (backwards compatibility wrapper).
        
        This method now delegates to generate_case_from_template.
        """
        input_values = {
            "user_query": user_query,
            "sql_statement": sql_statement
        }
        
        if database_name:
            input_values["database_name"] = database_name
        if table_names:
            input_values["table_names"] = table_names
        if mcp_tool_name:
            input_values["mcp_tool_name"] = mcp_tool_name
        
        return self.generate_case_from_template("sql_query_v1", collection_id, input_values, user_uuid=user_uuid)
    
    def populate_collection_from_template(
        self,
        template_id: str,
        collection_id: int,
        examples: List[Tuple[str, str]],
        database_name: Optional[str] = None,
        mcp_tool_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Populate a RAG collection using any template.
        
        Args:
            template_id: Template identifier (e.g., "sql_query_v1", "sql_query_doc_context_v1")
            collection_id: The collection ID to populate
            examples: List of (user_query, sql_statement) tuples
            database_name: Optional database name context
            mcp_tool_name: The MCP tool name (uses template default if not provided)
            
        Returns:
            Summary dictionary with statistics
        """
        # Get template
        template = self.template_manager.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # Get template configuration for defaults
        config = self.template_manager.get_template_config(template_id)
        if not mcp_tool_name:
            mcp_tool_name = config.get("default_mcp_tool", "base_readQuery")
        
        # Validate collection exists
        collection_meta = self.rag_retriever.get_collection_metadata(collection_id)
        if not collection_meta:
            raise ValueError(f"Collection ID {collection_id} does not exist")
        
        logger.info(f"Populating collection {collection_id} ('{collection_meta['name']}') with {len(examples)} examples using template {template_id}...")
        
        results = {
            "collection_id": collection_id,
            "collection_name": collection_meta["name"],
            "template_id": template_id,
            "total_examples": len(examples),
            "successful": 0,
            "failed": 0,
            "case_ids": [],
            "errors": []
        }
        
        collection_dir = self.rag_retriever._ensure_collection_dir(collection_id)
        
        for idx, (user_query, sql_statement) in enumerate(examples, 1):
            try:
                logger.info(f"Processing example {idx}/{len(examples)}: '{user_query[:50]}...'")
                
                # Build input values for template
                input_values = {
                    "user_query": user_query,
                    "sql_statement": sql_statement,
                    "mcp_tool_name": mcp_tool_name
                }
                
                if database_name:
                    input_values["database_name"] = database_name
                
                # Generate case using generic template method
                case_study = self.generate_case_from_template(
                    template_id=template_id,
                    collection_id=collection_id,
                    input_values=input_values
                )
                
                case_id = case_study["case_id"]
                
                # Save to disk
                case_file = collection_dir / f"case_{case_id}.json"
                with open(case_file, 'w', encoding='utf-8') as f:
                    json.dump(case_study, f, indent=2)
                
                # Add to ChromaDB
                if collection_id in self.rag_retriever.collections:
                    collection = self.rag_retriever.collections[collection_id]
                    
                    # Prepare metadata
                    metadata = self.rag_retriever._prepare_chroma_metadata(case_study)
                    document = user_query
                    
                    # Upsert to ChromaDB
                    collection.upsert(
                        ids=[case_id],
                        documents=[document],
                        metadatas=[metadata]
                    )
                    logger.debug(f"Added case {case_id[:8]}... to ChromaDB")
                
                results["successful"] += 1
                results["case_ids"].append(case_id)
                
            except Exception as e:
                logger.error(f"Failed to process example {idx}: {e}", exc_info=True)
                results["failed"] += 1
                results["errors"].append({
                    "example_index": idx,
                    "user_query": user_query,
                    "error": str(e)
                })
        
        logger.info(
            f"Population complete for collection {collection_id}: "
            f"{results['successful']} successful, {results['failed']} failed"
        )
        
        return results
    
    def populate_collection_from_sql_examples(
        self,
        collection_id: int,
        examples: List[Tuple[str, str]],
        database_name: Optional[str] = None,
        mcp_tool_name: str = "base_readQuery"
    ) -> Dict[str, Any]:
        """
        Populate a RAG collection with multiple SQL examples.
        DEPRECATED: Use populate_collection_from_template instead.
        
        Args:
            collection_id: The collection ID to populate
            examples: List of (user_query, sql_statement) tuples
            database_name: Optional database name context
            mcp_tool_name: The MCP tool name for SQL execution
            
        Returns:
            Summary dictionary with statistics
        """
        # Delegate to generic method with sql_query_v1 template
        return self.populate_collection_from_template(
            template_id="sql_query_v1",
            collection_id=collection_id,
            examples=examples,
            database_name=database_name,
            mcp_tool_name=mcp_tool_name
        )
    
    def validate_sql_examples(self, examples: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        """
        Validate SQL examples before generating cases.
        
        Args:
            examples: List of (user_query, sql_statement) tuples
            
        Returns:
            List of validation issues (empty list if all valid)
        """
        issues = []
        
        for idx, (user_query, sql_statement) in enumerate(examples, 1):
            # Check for empty values
            if not user_query or not user_query.strip():
                issues.append({
                    "example_index": idx,
                    "field": "user_query",
                    "issue": "Empty or whitespace-only query"
                })
            
            if not sql_statement or not sql_statement.strip():
                issues.append({
                    "example_index": idx,
                    "field": "sql_statement",
                    "issue": "Empty or whitespace-only SQL statement"
                })
            
            # Basic SQL validation - check for SQL keywords (expanded list for Teradata)
            if sql_statement and sql_statement.strip():
                sql_upper = sql_statement.strip().upper()
                # Check for SQL keywords - expanded to include Teradata-specific and common SQL commands
                sql_keywords = [
                    'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER',
                    'MERGE', 'GRANT', 'REVOKE', 'SHOW', 'DESCRIBE', 'EXPLAIN',
                    'SET', 'CALL', 'EXECUTE', 'EXEC', 'BEGIN', 'COMMIT', 'ROLLBACK',
                    'WITH', 'REPLACE', 'LOCK', 'UNLOCK', 'TRUNCATE', 'RENAME',
                    'COMMENT', 'HELP', 'DATABASE', 'TABLE', 'VIEW', 'INDEX', 'PROCEDURE'
                ]
                if not any(keyword in sql_upper for keyword in sql_keywords):
                    issues.append({
                        "example_index": idx,
                        "field": "sql_statement",
                        "issue": "Does not appear to contain valid SQL keywords"
                    })
        
        return issues
    
    def get_template_info(self, template_type: str) -> Dict[str, Any]:
        """
        Get information about a specific template type.
        
        Args:
            template_type: The template type (e.g., 'sql_query')
            
        Returns:
            Template information dictionary
        """
        templates = {
            "sql_query": {
                "name": "SQL Query Constructor - Database Context",
                "description": "Two-phase plan for executing SQL queries and generating reports",
                "phases": [
                    {
                        "phase": 1,
                        "description": "Execute SQL statement using MCP tool",
                        "required_inputs": ["sql_statement"],
                        "default_tool": "base_readQuery"
                    },
                    {
                        "phase": 2,
                        "description": "Generate final report from results",
                        "required_inputs": [],
                        "default_tool": "TDA_FinalReport"
                    }
                ],
                "required_example_fields": ["user_query", "sql_statement"],
                "optional_fields": ["database_name", "table_names", "mcp_tool_name"]
            }
        }
        
        return templates.get(template_type, {})
