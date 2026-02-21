"""
Pre-built regex patterns for common extraction tasks.

Extension authors can import and reuse these instead of writing their own.
These patterns are battle-tested from the built-in #extract extension.
"""

from __future__ import annotations

import re

# --- Numbers with optional units ---
# Matches: "CPU Usage: 94.5%", "Total: 1,234 rows", "Disk: 500 GB"
NUMBER_WITH_UNIT = re.compile(
    r"(?:^|[•\-\*]|\.\s+)"             # line start, bullet, or sentence boundary
    r"\s*([A-Za-z][\w\s/]*?)"          # label (starts with letter)
    r"[\s:=–\-]+?"                      # separator (colon, equals, dash)
    r"(\d{1,3}(?:[,]\d{3})*(?:\.\d+)?)"  # number (with optional commas/decimals)
    r"\s*"
    r"(%|GB|MB|TB|KB|PB|ms|μs|ns|seconds?|minutes?|hours?|days?|rows?|items?|records?|bytes?|connections?|queries|requests?|users?|sessions?|threads?|cores?|nodes?)?"
    r"(?:\s|$|[,.\)])",
    re.MULTILINE | re.IGNORECASE,
)

# --- Percentages ---
# Matches: "94.5%", "100%", "0.01%"
PERCENTAGE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# --- Identifiers (UPPER_CASE names) ---
# Matches: "DATABASE_NAME", "SYS.TABLE_A", "PROD_SERVER_01"
IDENTIFIER = re.compile(r"\b([A-Z][A-Z0-9_]{2,}(?:\.[A-Za-z_]\w*)?)\b")

# --- SQL statements ---
# Matches complete SQL statements (greedy, multi-line)
SQL_STATEMENT = re.compile(
    r"\b(SELECT\s.+?(?:;|\Z))",
    re.IGNORECASE | re.DOTALL,
)

# --- Key-value pairs ---
# Matches: "key: value", "key = value", "key → value"
KEY_VALUE = re.compile(
    r"^\s*([A-Za-z][\w\s]*?)\s*[:=→]\s*(.+?)$",
    re.MULTILINE,
)

# --- Email addresses ---
EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b")

# --- URLs ---
URL = re.compile(r"https?://[^\s<>\"')\]]+")

# --- Common stopwords for entity filtering ---
# Upper-case words that are NOT meaningful entity names
ENTITY_STOPWORDS = {
    "THE", "AND", "FOR", "NOT", "ARE", "BUT", "ALL", "ANY",
    "CAN", "HAS", "HER", "WAS", "ONE", "OUR", "OUT", "SQL",
    "CPU", "RAM", "GPU", "SSD", "HDD", "API", "URL", "HTML",
    "CSS", "PDF", "CSV", "JSON", "XML", "HTTP", "HTTPS",
    "LLM", "RAG", "MCP", "SSE", "JWT", "TDA",
}
