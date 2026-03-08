# src/trusted_data_agent/agent/rag_llm_generator.py
"""
RAG LLM Generator - Uses LLM to auto-generate question/SQL pairs for RAG collections
"""

import json
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


async def generate_sql_examples_with_llm(
    llm_instance,
    subject: str,
    count: int,
    database_name: Optional[str] = None
) -> List[Tuple[str, str]]:
    """
    Generate question/SQL pairs using LLM based on a subject.
    
    Args:
        llm_instance: The LLM instance to use for generation
        subject: The subject/topic for which to generate examples
        count: Number of examples to generate (1-20)
        database_name: Optional database name for context
        
    Returns:
        List of tuples [(user_query, sql_statement), ...]
    """
    logger.info(f"Generating {count} SQL examples for subject: '{subject}'")
    
    # Build the prompt
    db_context = f" targeting the '{database_name}' database" if database_name else ""
    
    prompt = f"""You are an expert SQL developer. Generate {count} realistic and diverse examples of natural language questions paired with their corresponding SQL queries{db_context}.

Subject/Topic: {subject}

Requirements:
1. Each example should have:
   - A natural language question (user_query)
   - A valid SQL query (sql_statement)
2. Make queries diverse covering different SQL operations (SELECT, COUNT, AVG, SUM, GROUP BY, JOIN, WHERE, etc.)
3. Use realistic table and column names related to the subject
4. Questions should be clear and specific
5. SQL should be syntactically correct and follow best practices
6. Vary complexity from simple to moderately complex queries

Output Format (JSON array):
[
    {{
        "user_query": "Natural language question here",
        "sql_statement": "SELECT * FROM table_name WHERE condition"
    }},
    ...
]

Generate EXACTLY {count} examples. Output only the JSON array, no additional text."""

    try:
        # Call LLM
        response = await llm_instance.generate_text(prompt=prompt)
        
        if not response:
            logger.error("LLM returned empty response")
            return []
        
        # Extract JSON from response
        response_text = response.strip()
        
        # Try to find JSON array in response
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']')
        
        if start_idx == -1 or end_idx == -1:
            logger.error(f"No JSON array found in LLM response: {response_text[:200]}")
            return []
        
        json_str = response_text[start_idx:end_idx + 1]
        
        # Parse JSON
        try:
            examples_data = json.loads(json_str)
        except json.JSONDecodeError as je:
            logger.error(f"Failed to parse LLM JSON response: {je}")
            logger.debug(f"JSON string: {json_str[:500]}")
            return []
        
        if not isinstance(examples_data, list):
            logger.error(f"Expected list, got {type(examples_data)}")
            return []
        
        # Convert to tuple format
        examples = []
        for idx, ex in enumerate(examples_data):
            if not isinstance(ex, dict):
                logger.warning(f"Example {idx} is not a dict, skipping")
                continue
            
            user_query = ex.get("user_query", "").strip()
            sql_statement = ex.get("sql_statement", "").strip()
            
            if not user_query or not sql_statement:
                logger.warning(f"Example {idx} missing required fields, skipping")
                continue
            
            # Basic SQL validation
            sql_upper = sql_statement.upper()
            if not any(keyword in sql_upper for keyword in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH']):
                logger.warning(f"Example {idx} doesn't appear to be valid SQL, skipping")
                continue
            
            examples.append((user_query, sql_statement))
        
        logger.info(f"Successfully generated {len(examples)} SQL examples")
        
        if len(examples) < count:
            logger.warning(f"Only generated {len(examples)} examples, requested {count}")
        
        return examples
        
    except Exception as e:
        logger.error(f"Error generating SQL examples with LLM: {e}", exc_info=True)
        return []
