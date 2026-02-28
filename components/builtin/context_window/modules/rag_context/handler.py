"""
RAG Context module.

Wraps the champion case retrieval from planner.py and rag_retriever.py.
Retrieves proven execution strategies from planner repositories via
semantic search, providing the LLM with successful patterns to follow.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class RAGContextModule(ContextModule):
    """
    Contributes RAG champion cases to the context window.

    Retrieves proven execution strategies from planner repositories
    (ChromaDB collections) using semantic similarity search. These
    champion cases provide the LLM with templates for successful
    tool usage patterns, reducing planning errors and token usage.

    Condensation strategy: fewer examples (reduce k parameter).
    Purgeable: clears RAG collection data.
    """

    @property
    def module_id(self) -> str:
        return "rag_context"

    def applies_to(self, profile_type: str) -> bool:
        return profile_type == "tool_enabled"

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Retrieve champion cases within the token budget.

        Queries planner repositories for semantically similar past successes
        and formats them for injection into the strategic planning prompt.
        """
        session_data = ctx.session_data
        profile_config = ctx.profile_config
        user_uuid = ctx.user_uuid

        # Get the current query from session data
        query = session_data.get("current_query", "")
        if not query:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"cases_retrieved": 0, "reason": "no_query"},
                condensable=False,
            )

        # Determine max examples based on budget
        char_budget = tokens_to_chars(budget)
        max_examples = min(5, max(1, char_budget // 2000))  # ~2000 chars per case

        try:
            from trusted_data_agent.agent.rag_retriever import RAGRetriever

            retriever = RAGRetriever()

            # Get accessible collection IDs from profile config
            rag_config = profile_config.get("ragConfig", {})
            collection_ids = set()
            for coll in rag_config.get("collections", []):
                coll_id = coll.get("id", "")
                if coll_id:
                    collection_ids.add(coll_id)

            if not collection_ids:
                return Contribution(
                    content="",
                    tokens_used=0,
                    metadata={"cases_retrieved": 0, "reason": "no_collections"},
                    condensable=False,
                )

            cases = await retriever.retrieve_examples(
                query=query,
                k=max_examples,
                min_score=0.7,
                allowed_collection_ids=collection_ids,
                repository_type="planner",
            )

            if not cases:
                return Contribution(
                    content="",
                    tokens_used=0,
                    metadata={"cases_retrieved": 0, "reason": "no_matches"},
                    condensable=False,
                )

            # Format champion cases
            content = self._format_cases(cases, char_budget)
            tokens = estimate_tokens(content)

            return Contribution(
                content=content,
                tokens_used=tokens,
                metadata={
                    "cases_retrieved": len(cases),
                    "collections_searched": len(collection_ids),
                    "top_score": cases[0].get("similarity_score", 0) if cases else 0,
                },
                condensable=True,
            )

        except Exception as e:
            logger.error(f"RAGContextModule: retrieval failed: {e}")
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"cases_retrieved": 0, "error": str(e)},
                condensable=False,
            )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """Condense by reducing to fewer examples."""
        if not content:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"condensed": True, "cases_retrieved": 0},
            )

        # Simple approach: truncate to target
        char_budget = tokens_to_chars(target_tokens)
        if len(content) > char_budget:
            # Find last complete case separator before budget
            truncated = content[:char_budget]
            last_sep = truncated.rfind("\n---\n")
            if last_sep > 0:
                truncated = truncated[:last_sep]
            content = truncated

        tokens = estimate_tokens(content)
        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={"condensed": True, "strategy": "fewer_examples"},
        )

    async def purge(
        self,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """Purge RAG retrieval cache."""
        return {
            "purged": True,
            "details": "RAG retrieval cache cleared (stateless — no persistent cache)",
        }

    def _format_cases(self, cases: list, char_budget: int) -> str:
        """Format champion cases for context injection."""
        lines = ["--- CHAMPION CASES ---"]
        lines.append(
            "The following proven execution strategies were retrieved from "
            "successful past queries. Use them as templates when applicable.\n"
        )

        total_chars = sum(len(line) for line in lines)
        included = 0

        for case in cases:
            case_text = self._format_single_case(case)
            if total_chars + len(case_text) > char_budget and included > 0:
                break
            lines.append(case_text)
            total_chars += len(case_text)
            included += 1

        return "\n".join(lines)

    def _format_single_case(self, case: dict) -> str:
        """Format a single champion case."""
        parts = []
        score = case.get("similarity_score", 0)
        collection = case.get("collection_name", "unknown")
        content = case.get("content", case.get("summary", ""))

        parts.append(f"Champion Case (score: {score:.2f}, collection: {collection}):")
        parts.append(content)
        parts.append("---")

        return "\n".join(parts)
