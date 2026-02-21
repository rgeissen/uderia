"""
#pdf extension — Export LLM answer as downloadable PDF.

Generates a clean PDF document from the LLM answer with
Markdown-aware formatting (headings, bullet points, code blocks).
The PDF is base64-encoded and delivered as a browser download.

Tier: Simple (SimpleExtension) — only needs answer_text.

Usage:
    #pdf              → Export answer as PDF (auto-generated title)
    #pdf:My Report    → Export with custom document title
"""

import base64
import re
from datetime import datetime
from typing import Optional

from trusted_data_agent.extensions.base import SimpleExtension
from trusted_data_agent.extensions.models import OutputTarget


class PdfExportExtension(SimpleExtension):

    name = "pdf"
    description = "Exports the LLM answer as a downloadable PDF document"
    content_type = "application/pdf"

    @property
    def output_target(self) -> OutputTarget:
        return OutputTarget.CHAT_APPEND

    def transform(self, answer_text: str, param: Optional[str] = None) -> dict:
        try:
            from fpdf import FPDF
        except ImportError:
            raise RuntimeError(
                "fpdf2 is required for the PDF extension. "
                "Install it with: pip install fpdf2"
            )

        title = param or "LLM Answer Export"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # ── Title ──────────────────────────────────────────────
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(25, 25, 25)
        pdf.cell(0, 12, _sanitize_latin1(title), new_x="LMARGIN", new_y="NEXT")

        # Timestamp
        pdf.set_font("Helvetica", size=9)
        pdf.set_text_color(140, 140, 140)
        pdf.cell(0, 5, f"Generated {timestamp}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # Separator line
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(8)

        # ── Body ───────────────────────────────────────────────
        pdf.set_text_color(40, 40, 40)
        in_code_block = False

        for line in answer_text.split("\n"):
            stripped = line.strip()

            # --- Code block toggle ---
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                if in_code_block:
                    pdf.ln(3)
                    pdf.set_font("Courier", size=9)
                    pdf.set_fill_color(242, 242, 242)
                    pdf.set_draw_color(220, 220, 220)
                    # Top border of code block
                    y = pdf.get_y()
                    pdf.line(12, y, 198, y)
                else:
                    # Bottom border of code block
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

            # --- Bullet points (indented with bullet character) ---
            elif stripped.startswith(("- ", "* ", "+ ")):
                pdf.set_font("Helvetica", size=11)
                text = _prepare_for_md(stripped[2:])
                # Use bullet dot (latin-1 \xb7 = middle dot)
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

        pdf_bytes = pdf.output()

        # Sanitize filename
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_").lower()
        if not safe_title:
            safe_title = "export"

        return {
            "data": base64.b64encode(pdf_bytes).decode("ascii"),
            "filename": f"{safe_title}.pdf",
            "pages": pdf.page,
            "size_bytes": len(pdf_bytes),
        }


def _prepare_for_md(text: str) -> str:
    """Prepare text for fpdf2 markdown rendering.

    fpdf2's markdown=True natively renders **bold** and *italic*.
    We only strip inline code backticks and link syntax, keeping
    bold/italic markers intact for the PDF engine.
    """
    text = re.sub(r"`(.+?)`", r"\1", text)           # inline code → plain
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # [link](url) → link text
    return _sanitize_latin1(text)


# Common Unicode → ASCII replacements for Helvetica (latin-1 only)
_UNICODE_MAP = {
    "\u2022": "\xb7",  # bullet • → middle dot ·
    "\u2013": "-",      # en-dash –
    "\u2014": "--",     # em-dash —
    "\u2018": "'",      # left single quote '
    "\u2019": "'",      # right single quote '
    "\u201c": '"',      # left double quote "
    "\u201d": '"',      # right double quote "
    "\u2026": "...",    # ellipsis …
    "\u2192": "->",     # right arrow →
    "\u2190": "<-",     # left arrow ←
    "\u2713": "[x]",    # check mark ✓
    "\u2717": "[ ]",    # cross ✗
    "\u00a0": " ",      # non-breaking space
}


def _sanitize_latin1(text: str) -> str:
    """Replace Unicode characters unsupported by Helvetica (latin-1 only)."""
    for char, replacement in _UNICODE_MAP.items():
        text = text.replace(char, replacement)
    # Drop any remaining non-latin-1 characters
    return text.encode("latin-1", errors="replace").decode("latin-1")
