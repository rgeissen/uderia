"""
Knowledge Context module.

Wraps the knowledge document retrieval from planner.py.
Retrieves domain-specific reference documents from knowledge repositories
via semantic search, providing the LLM with factual grounding.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class KnowledgeContextModule(ContextModule):
    """
    Contributes knowledge documents to the context window.

    Retrieves domain-specific documents from knowledge repositories
    (ChromaDB collections) via semantic search. These documents
    provide factual grounding for the LLM's responses.

    Condensation strategy: fewer documents, shorter excerpts.
    Purgeable: clears knowledge retrieval cache.
    """

    @property
    def module_id(self) -> str:
        return "knowledge_context"

    def applies_to(self, profile_type: str) -> bool:
        return profile_type in ("tool_enabled", "llm_only", "rag_focused")

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Retrieve knowledge documents within the token budget.

        Queries knowledge repositories for semantically relevant documents
        and formats them for injection into the planning prompt.
        """
        session_data = ctx.session_data
        profile_config = ctx.profile_config
        user_uuid = ctx.user_uuid

        # Check if knowledge is enabled for this profile
        knowledge_config = profile_config.get("knowledgeConfig", {})
        if not knowledge_config.get("enabled", False):
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"docs_retrieved": 0, "reason": "knowledge_disabled"},
                condensable=False,
            )

        query = session_data.get("current_query", "")
        if not query:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"docs_retrieved": 0, "reason": "no_query"},
                condensable=False,
            )

        # Get knowledge config parameters
        max_docs = knowledge_config.get("maxDocs", 5)
        min_score = knowledge_config.get("minRelevanceScore", 0.7)
        max_tokens = min(budget, knowledge_config.get("maxTokens", 2000))

        # Get collection IDs
        collection_ids = set()
        for coll in knowledge_config.get("collections", []):
            coll_id = coll.get("id", "")
            if coll_id:
                collection_ids.add(coll_id)

        if not collection_ids:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"docs_retrieved": 0, "reason": "no_collections"},
                condensable=False,
            )

        try:
            from trusted_data_agent.core.config import APP_STATE

            retriever = APP_STATE.get("rag_retriever_instance")
            if not retriever:
                return Contribution(
                    content="",
                    tokens_used=0,
                    metadata={"docs_retrieved": 0, "reason": "no_retriever_instance"},
                    condensable=False,
                )

            docs = await retriever.retrieve_examples(
                query=query,
                k=max_docs,
                min_score=min_score,
                allowed_collection_ids=collection_ids,
                repository_type="knowledge",
            )

            if not docs:
                # Distinguish: collection empty (broken state) vs. no relevant match (normal)
                empty_collections = []
                for coll_id in collection_ids:
                    try:
                        count = await retriever.get_collection_count(int(coll_id))
                        if count == 0:
                            empty_collections.append(str(coll_id))
                    except Exception:
                        pass  # Unknown state — don't block

                if empty_collections:
                    warning = (
                        "--- KNOWLEDGE BASE UNAVAILABLE ---\n"
                        f"WARNING: The knowledge repository (collection ID(s): {', '.join(empty_collections)}) "
                        "has no indexed content. The document upload may have failed or the knowledge base "
                        "has not been populated yet.\n"
                        "CRITICAL INSTRUCTION: Do NOT answer this question from your training data or "
                        "model memory. Instead, explicitly tell the user that the knowledge repository "
                        "is empty and must be re-populated before you can answer accurately."
                    )
                    tokens = estimate_tokens(warning)
                    return Contribution(
                        content=warning,
                        tokens_used=tokens,
                        metadata={
                            "docs_retrieved": 0,
                            "reason": "collection_empty",
                            "empty_collections": empty_collections,
                        },
                        condensable=False,
                    )

                # For rag_focused profiles the knowledge repository is the ONLY authoritative
                # source. If RAG returned nothing, the LLM must NOT silently fall back to
                # training-data memory — that produces hallucinated column names, fabricated
                # citations, and wrong schema information.
                # For tool_enabled / llm_only profiles the knowledge repo is supplementary,
                # so the silent empty-return is fine.
                if ctx.profile_type == "rag_focused":
                    no_match_warning = (
                        "--- NO DOCUMENTATION FOUND ---\n"
                        "WARNING: The knowledge repository was searched but returned no "
                        "relevant documentation for this query.\n"
                        "CRITICAL INSTRUCTION: You must NOT answer this question from your "
                        "training data or model memory. Your role as a knowledge expert is "
                        "to answer ONLY from the retrieved documentation above. Since no "
                        "documentation was retrieved, you must respond with: "
                        "'I cannot find this specific information in the knowledge "
                        "repository. Please consult the official documentation directly or "
                        "ask the database executor to inspect the live schema.'"
                    )
                    tokens = estimate_tokens(no_match_warning)
                    return Contribution(
                        content=no_match_warning,
                        tokens_used=tokens,
                        metadata={"docs_retrieved": 0, "reason": "no_matches_rag_focused"},
                        condensable=False,
                    )

                # Normal case for non-rag_focused profiles: no relevant matches — fine
                return Contribution(
                    content="",
                    tokens_used=0,
                    metadata={"docs_retrieved": 0, "reason": "no_matches"},
                    condensable=False,
                )

            # Format documents within budget
            char_budget = tokens_to_chars(max_tokens)
            content = self._format_documents(docs, char_budget)
            tokens = estimate_tokens(content)

            return Contribution(
                content=content,
                tokens_used=tokens,
                metadata={
                    "docs_retrieved": len(docs),
                    "collections_searched": len(collection_ids),
                    "top_score": docs[0].get("similarity_score", 0) if docs else 0,
                },
                condensable=True,
            )

        except Exception as e:
            logger.error(f"KnowledgeContextModule: retrieval failed: {e}")
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"docs_retrieved": 0, "error": str(e)},
                condensable=False,
            )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """Condense by truncating to fewer documents."""
        if not content:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"condensed": True, "docs_retrieved": 0},
            )

        char_budget = tokens_to_chars(target_tokens)
        if len(content) > char_budget:
            truncated = content[:char_budget]
            last_sep = truncated.rfind("\n---\n")
            if last_sep > 0:
                truncated = truncated[:last_sep]
            content = truncated

        tokens = estimate_tokens(content)
        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={"condensed": True, "strategy": "fewer_documents"},
        )

    async def purge(
        self,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """Purge knowledge retrieval cache."""
        return {
            "purged": True,
            "details": "Knowledge retrieval cache cleared (stateless — no persistent cache)",
        }

    def _format_documents(self, docs: list, char_budget: int) -> str:
        """Format knowledge documents for context injection."""
        lines = ["--- KNOWLEDGE CONTEXT ---"]
        lines.append(
            "The following domain knowledge documents were retrieved. "
            "Use this information to provide accurate, grounded responses.\n"
        )

        total_chars = sum(len(line) for line in lines)
        included = 0

        for doc in docs:
            doc_text = self._format_single_document(doc)
            if total_chars + len(doc_text) > char_budget and included > 0:
                break
            lines.append(doc_text)
            total_chars += len(doc_text)
            included += 1

        return "\n".join(lines)

    def _format_single_document(self, doc: dict) -> str:
        """Format a single knowledge document."""
        parts = []
        score = doc.get("similarity_score", 0)
        collection = doc.get("collection_name", "unknown")
        content = doc.get("content", doc.get("summary", ""))

        parts.append(f"Knowledge Document (score: {score:.2f}, source: {collection}):")
        parts.append(content)
        parts.append("---")

        return "\n".join(parts)
