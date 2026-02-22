"""
#pdf extension — Export LLM answer as downloadable PDF.

Generates a clean PDF document from the LLM answer with
Markdown-aware formatting (headings, bullet points, code blocks).
The PDF is base64-encoded and delivered as a browser download.

Genie-aware: When running under a genie coordinator profile,
supports scope-based content via the param:
    #pdf              → Non-genie: full answer; Genie: all nodes (children + coordinator)
    #pdf:coordinator  → Coordinator synthesis only
    #pdf:children     → Child profile responses only
    #pdf:all          → All nodes (children + coordinator)
    #pdf:My Report    → Custom title (genie: defaults to scope "all")

Tier: Extension (full context access for genie support).
"""

import base64
import re
from datetime import datetime
from typing import Optional

from trusted_data_agent.extensions.base import Extension
from trusted_data_agent.extensions.models import (
    ExtensionContext,
    ExtensionResult,
    OutputTarget,
)

_SCOPES = {"coordinator", "children", "all"}


class PdfExportExtension(Extension):

    name = "pdf"
    description = "Exports the LLM answer as a downloadable PDF document"
    content_type = "application/pdf"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.CHAT_APPEND

    async def execute(
        self,
        context: ExtensionContext,
        param: Optional[str] = None,
    ) -> ExtensionResult:
        try:
            from fpdf import FPDF
        except ImportError:
            return ExtensionResult(
                extension_name=self.name,
                content=None,
                content_type="text/plain",
                success=False,
                error="fpdf2 is required for the PDF extension. Install with: pip install fpdf2",
            )

        # Parse param: check for scope keyword, otherwise use as title
        scope = "all"
        title = None
        if param:
            if param.lower() in _SCOPES:
                scope = param.lower()
            else:
                title = param

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)

        if context.genie:
            # Genie execution — scope-based multi-section PDF
            nodes = context.genie.get_content(scope=scope)
            if not title:
                title = f"@{context.genie.coordinator_profile_tag} — Expert Report"

            # Cover page
            pdf.add_page()
            _render_cover(pdf, title, timestamp, context, scope)

            # One section per content node
            for node in nodes:
                pdf.add_page()
                _render_section_header(pdf, node)
                _render_markdown_body(pdf, node.text)

        else:
            # Non-genie — single-section PDF (classic behavior)
            if not title:
                title = "LLM Answer Export"
            pdf.add_page()
            _render_title(pdf, title, timestamp)
            _render_markdown_body(pdf, context.answer_text)

        pdf_bytes = pdf.output()

        # Sanitize filename
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_").lower()
        if not safe_title:
            safe_title = "export"

        return ExtensionResult(
            extension_name=self.name,
            content={
                "data": base64.b64encode(pdf_bytes).decode("ascii"),
                "filename": f"{safe_title}.pdf",
                "pages": pdf.page,
                "size_bytes": len(pdf_bytes),
            },
            content_type="application/pdf",
            success=True,
            output_target=OutputTarget.CHAT_APPEND.value,
            metadata={
                "param": param,
                "scope": scope if context.genie else None,
                "is_genie": context.genie is not None,
                "sections": len(context.genie.get_content(scope=scope)) if context.genie else 1,
            },
        )


# ---------------------------------------------------------------------------
# PDF rendering helpers
# ---------------------------------------------------------------------------

def _render_cover(pdf, title: str, timestamp: str, context: ExtensionContext, scope: str):
    """Render a cover page for genie multi-section PDFs."""
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(25, 25, 25)
    pdf.ln(20)
    pdf.multi_cell(0, 12, _sanitize_latin1(title), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 5, f"Generated {timestamp}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.cell(
        0, 5,
        f"Scope: {scope}  |  Profiles invoked: {', '.join(context.genie.profiles_invoked)}",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.cell(
        0, 5,
        f"LLM steps: {context.genie.coordinator_llm_steps}  |  "
        f"Duration: {context.genie.coordination_duration_ms:,}ms",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(6)

    # Separator
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(8)

    # Table of contents
    nodes = context.genie.get_content(scope=scope)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 8, "Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", size=11)
    for i, node in enumerate(nodes, 1):
        badge = "Coordinator" if node.node_type == "coordinator" else f"@{node.profile_tag}"
        duration = f"  ({node.duration_ms:,}ms)" if node.duration_ms else ""
        pdf.cell(
            0, 6,
            _sanitize_latin1(f"  {i}. {node.label}{duration}  [{badge}]"),
            new_x="LMARGIN", new_y="NEXT",
        )


def _render_section_header(pdf, node):
    """Render a section header for a genie content node."""
    # Section badge
    if node.node_type == "coordinator":
        pdf.set_fill_color(245, 158, 11)   # amber
        badge_text = "COORDINATOR"
    else:
        pdf.set_fill_color(59, 130, 246)    # blue
        badge_text = f"@{node.profile_tag}"

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(255, 255, 255)
    badge_w = pdf.get_string_width(f"  {badge_text}  ") + 4
    pdf.cell(badge_w, 6, f"  {badge_text}  ", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Section title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(25, 25, 25)
    pdf.multi_cell(0, 9, _sanitize_latin1(node.label), new_x="LMARGIN", new_y="NEXT")

    # Section metadata
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(140, 140, 140)
    meta_parts = [f"Type: {node.profile_type}"]
    if node.duration_ms:
        meta_parts.append(f"Duration: {node.duration_ms:,}ms")
    if not node.success:
        meta_parts.append(f"ERROR: {node.metadata.get('error', 'unknown')}")
    pdf.cell(0, 5, "  |  ".join(meta_parts), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)


def _render_title(pdf, title: str, timestamp: str):
    """Render the title block for a non-genie (single section) PDF."""
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(25, 25, 25)
    pdf.cell(0, 12, _sanitize_latin1(title), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 5, f"Generated {timestamp}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(8)


def _render_markdown_body(pdf, text: str):
    """Render Markdown-formatted text into the PDF body."""
    pdf.set_text_color(40, 40, 40)
    in_code_block = False

    for line in text.split("\n"):
        stripped = line.strip()

        # --- Code block toggle ---
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            if in_code_block:
                pdf.ln(3)
                pdf.set_font("Courier", size=9)
                pdf.set_fill_color(242, 242, 242)
                pdf.set_draw_color(220, 220, 220)
                y = pdf.get_y()
                pdf.line(12, y, 198, y)
            else:
                y = pdf.get_y()
                pdf.line(12, y, 198, y)
                pdf.ln(3)
                pdf.set_font("Helvetica", size=11)
            continue

        # --- Inside code block ---
        if in_code_block:
            safe = _sanitize_latin1(line)
            pdf.cell(
                0, 5, f"  {safe}",
                new_x="LMARGIN", new_y="NEXT", fill=True,
            )
            continue

        # --- Headings (strip markdown markers, render bold) ---
        if stripped.startswith("### "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(35, 35, 35)
            pdf.multi_cell(
                0, 6, _prepare_for_md(stripped[4:]),
                new_x="LMARGIN", new_y="NEXT", markdown=True,
            )
            pdf.set_font("Helvetica", size=11)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(1)

        elif stripped.startswith("## "):
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(
                0, 7, _prepare_for_md(stripped[3:]),
                new_x="LMARGIN", new_y="NEXT", markdown=True,
            )
            pdf.set_font("Helvetica", size=11)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(1)

        elif stripped.startswith("# "):
            pdf.ln(6)
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(25, 25, 25)
            pdf.multi_cell(
                0, 8, _prepare_for_md(stripped[2:]),
                new_x="LMARGIN", new_y="NEXT", markdown=True,
            )
            pdf.set_font("Helvetica", size=11)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(2)

        # --- Bullet points ---
        elif stripped.startswith(("- ", "* ", "+ ")):
            pdf.set_font("Helvetica", size=11)
            text = _prepare_for_md(stripped[2:])
            pdf.set_x(16)
            pdf.multi_cell(
                0, 6, f"\xb7  {text}",
                new_x="LMARGIN", new_y="NEXT", markdown=True,
            )

        # --- Numbered lists ---
        elif re.match(r"^\d+\.\s", stripped):
            pdf.set_font("Helvetica", size=11)
            text = _prepare_for_md(stripped)
            pdf.set_x(14)
            pdf.multi_cell(
                0, 6, text,
                new_x="LMARGIN", new_y="NEXT", markdown=True,
            )

        # --- Empty line ---
        elif stripped == "":
            pdf.ln(4)

        # --- Regular paragraph ---
        else:
            pdf.set_font("Helvetica", size=11)
            pdf.multi_cell(
                0, 6, _prepare_for_md(stripped),
                new_x="LMARGIN", new_y="NEXT", markdown=True,
            )

    # Close unclosed code block
    if in_code_block:
        pdf.set_font("Helvetica", size=11)


# ---------------------------------------------------------------------------
# Text sanitization helpers
# ---------------------------------------------------------------------------

def _prepare_for_md(text: str) -> str:
    """Prepare text for fpdf2 markdown rendering.

    fpdf2's markdown=True natively renders **bold** and *italic*.
    We only strip inline code backticks and link syntax, keeping
    bold/italic markers intact for the PDF engine.
    """
    text = re.sub(r"`(.+?)`", r"\1", text)           # inline code -> plain
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # [link](url) -> link text
    return _sanitize_latin1(text)


# Common Unicode -> ASCII replacements for Helvetica (latin-1 only)
_UNICODE_MAP = {
    "\u2022": "\xb7",  # bullet
    "\u2013": "-",      # en-dash
    "\u2014": "--",     # em-dash
    "\u2018": "'",      # left single quote
    "\u2019": "'",      # right single quote
    "\u201c": '"',      # left double quote
    "\u201d": '"',      # right double quote
    "\u2026": "...",    # ellipsis
    "\u2192": "->",     # right arrow
    "\u2190": "<-",     # left arrow
    "\u2713": "[x]",    # check mark
    "\u2717": "[ ]",    # cross
    "\u00a0": " ",      # non-breaking space
}


def _sanitize_latin1(text: str) -> str:
    """Replace Unicode characters unsupported by Helvetica (latin-1 only)."""
    for char, replacement in _UNICODE_MAP.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")
