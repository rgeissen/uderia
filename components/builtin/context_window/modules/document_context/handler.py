"""
Document Context module.

Wraps the document loading logic from executor.py:load_document_context().
Extracts text from user-uploaded files (PDF, text, etc.) and formats
it for LLM context with per-file and total character truncation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from ..base import AssemblyContext, Contribution, ContextModule
from ..token_estimator import estimate_tokens, tokens_to_chars

logger = logging.getLogger("quart.app")


class DocumentContextModule(ContextModule):
    """
    Contributes uploaded document text to the context window.

    Loads extracted text from user-uploaded files (PDFs, text documents)
    and formats it with document boundaries. Applies per-file and total
    character limits to stay within budget.

    Condensation strategy: per-file truncation, then drop lower-priority files.
    Purgeable: clears extracted text cache for the session.
    """

    @property
    def module_id(self) -> str:
        return "document_context"

    def applies_to(self, profile_type: str) -> bool:
        return profile_type in ("tool_enabled", "llm_only", "rag_focused")

    async def contribute(
        self,
        budget: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """
        Load and format uploaded documents within the token budget.

        Reads the upload manifest for the session and extracts text
        from attached documents, applying truncation limits.
        """
        session_data = ctx.session_data
        user_uuid = ctx.user_uuid
        session_id = ctx.session_id

        # Get attachments from session data
        attachments = session_data.get("attachments", [])
        if not attachments:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"doc_count": 0, "reason": "no_attachments"},
                condensable=False,
            )

        char_budget = tokens_to_chars(budget)

        try:
            content, doc_count, truncation_events = self._load_documents(
                user_uuid=user_uuid,
                session_id=session_id,
                attachments=attachments,
                max_total_chars=char_budget,
            )
        except Exception as e:
            logger.error(f"DocumentContextModule: load failed: {e}")
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"doc_count": 0, "error": str(e)},
                condensable=False,
            )

        if not content:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"doc_count": 0, "reason": "no_content_extracted"},
                condensable=False,
            )

        tokens = estimate_tokens(content)

        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={
                "doc_count": doc_count,
                "truncation_events": len(truncation_events),
                "total_chars": len(content),
            },
            condensable=True,
        )

    async def condense(
        self,
        content: str,
        target_tokens: int,
        ctx: AssemblyContext,
    ) -> Contribution:
        """Condense by truncating document content."""
        if not content:
            return Contribution(
                content="",
                tokens_used=0,
                metadata={"condensed": True, "doc_count": 0},
            )

        char_budget = tokens_to_chars(target_tokens)
        if len(content) > char_budget:
            # Try to truncate at a document boundary
            truncated = content[:char_budget]
            last_boundary = truncated.rfind("\n=== END DOCUMENT")
            if last_boundary > 0:
                truncated = truncated[:last_boundary]
            content = truncated + "\n... (documents truncated)"

        tokens = estimate_tokens(content)
        return Contribution(
            content=content,
            tokens_used=tokens,
            metadata={"condensed": True, "strategy": "truncation"},
        )

    async def purge(
        self,
        session_id: str,
        user_uuid: str,
    ) -> Dict[str, Any]:
        """Purge uploaded document cache for the session."""
        if not session_id or not user_uuid:
            return {"purged": False, "reason": "session_id and user_uuid required"}

        upload_dir = Path(f"tda_sessions/{user_uuid}/uploads/{session_id}")
        if upload_dir.exists():
            import shutil
            shutil.rmtree(upload_dir)
            return {
                "purged": True,
                "details": f"Cleared upload cache for session {session_id}",
            }
        return {"purged": False, "reason": "No upload cache found"}

    def _load_documents(
        self,
        user_uuid: str,
        session_id: str,
        attachments: list,
        max_total_chars: int,
        per_file_max_chars: int = 50_000,
    ) -> tuple:
        """
        Load extracted text from uploaded documents.

        Returns:
            (formatted_content, doc_count, truncation_events)
        """
        manifest_path = Path(
            f"tda_sessions/{user_uuid}/uploads/{session_id}/manifest.json"
        )

        if not manifest_path.exists():
            return "", 0, []

        with open(manifest_path) as f:
            manifest = json.load(f)

        lines = ["--- UPLOADED DOCUMENTS ---\n"]
        total_chars = len(lines[0])
        doc_count = 0
        truncation_events = []

        for attachment in attachments:
            file_id = attachment.get("file_id", "")
            filename = attachment.get("filename", "unknown")

            file_info = manifest.get(file_id, {})
            extracted_text = file_info.get("extracted_text", "")

            if not extracted_text:
                continue

            # Per-file truncation
            if len(extracted_text) > per_file_max_chars:
                extracted_text = extracted_text[:per_file_max_chars]
                truncation_events.append({
                    "file": filename,
                    "original_chars": len(file_info.get("extracted_text", "")),
                    "truncated_to": per_file_max_chars,
                })

            doc_header = f"=== DOCUMENT: {filename} ===\n"
            doc_footer = f"\n=== END DOCUMENT: {filename} ===\n"
            doc_text = doc_header + extracted_text + doc_footer

            # Total truncation check
            if total_chars + len(doc_text) > max_total_chars and doc_count > 0:
                break

            lines.append(doc_text)
            total_chars += len(doc_text)
            doc_count += 1

        return "\n".join(lines), doc_count, truncation_events
