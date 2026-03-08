# This is the auto-populate endpoint to add to rest_routes.py
# Add this right before the @rest_api_bp.route("/v1/rag/templates", methods=["GET"]) line (around line 874)

@rest_api_bp.route("/v1/rag/collections/<int:collection_id>/auto-populate", methods=["POST"])
async def auto_populate_collection_with_llm(collection_id: int):
    """
    Auto-populate a RAG collection by using LLM to generate question/SQL pairs based on a subject.
    
    Request body:
    {
        "subject": "customer analytics",  // Required: subject/topic for generation
        "count": 5,                       // Required: number of examples to generate (1-20)
        "database_name": "mydb"           // Optional: database context
    }
    """
    try:
        data = await request.get_json()
        
        # Validate required fields
        subject = data.get("subject", "").strip()
        count = data.get("count")
        
        if not subject:
            return jsonify({"status": "error", "message": "subject is required"}), 400
        
        if not count or not isinstance(count, int) or count < 1 or count > 20:
            return jsonify({"status": "error", "message": "count must be an integer between 1 and 20"}), 400
        
        # Check if LLM is configured
        llm_instance = APP_STATE.get("llm")
        if not llm_instance:
            return jsonify({"status": "error", "message": "LLM is not configured. Cannot auto-generate examples."}), 503
        
        # Get RAG retriever
        retriever = APP_STATE.get("rag_retriever_instance")
        if not retriever:
            return jsonify({"status": "error", "message": "RAG retriever not initialized"}), 500
        
        # Get collection metadata for MCP server info
        collections_list = APP_STATE.get("rag_collections", [])
        collection_meta = next((c for c in collections_list if c["id"] == collection_id), None)
        
        if not collection_meta:
            return jsonify({"status": "error", "message": f"Collection {collection_id} not found"}), 404
        
        database_name = data.get("database_name", "").strip() or None
        
        app_logger.info(f"Auto-populating collection {collection_id} with {count} LLM-generated examples on subject: '{subject}'")
        
        # Import the auto-population function
        from trusted_data_agent.agent.rag_llm_generator import generate_sql_examples_with_llm
        
        # Generate examples using LLM
        generated_examples = await generate_sql_examples_with_llm(
            llm_instance=llm_instance,
            subject=subject,
            count=count,
            database_name=database_name
        )
        
        if not generated_examples:
            return jsonify({
                "status": "error",
                "message": "LLM failed to generate examples"
            }), 500
        
        # Now populate the collection using the generated examples
        from trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator
        generator = RAGTemplateGenerator(retriever)
        
        # Get MCP tool name from template config
        from trusted_data_agent.agent.rag_template_manager import get_template_manager
        template_manager = get_template_manager()
        template_config = template_manager.get_template_config("sql_query_v1")
        mcp_tool_name = template_config.get("mcp_tool_name", "base_readQuery")
        
        results = generator.populate_collection_from_sql_examples(
            collection_id=collection_id,
            examples=generated_examples,
            database_name=database_name,
            mcp_tool_name=mcp_tool_name
        )
        
        return jsonify({
            "status": "success",
            "message": f"Successfully auto-generated and populated {results['successful']} cases",
            "results": results
        }), 200
        
    except ValueError as ve:
        app_logger.error(f"Validation error in auto-populate: {ve}")
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        app_logger.error(f"Error auto-populating collection with LLM: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
