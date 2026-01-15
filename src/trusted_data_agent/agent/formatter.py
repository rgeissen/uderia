# trusted_data_agent/agent/formatter.py
import re
import uuid
import json
from trusted_data_agent.agent.response_models import CanonicalResponse, KeyMetric, Observation, PromptReportResponse, Synthesis

class OutputFormatter:
    """
    Parses structured response data to generate professional,
    failure-safe HTML for the UI.
    """
    def __init__(self, collected_data: list | dict, canonical_response: CanonicalResponse = None, prompt_report_response: PromptReportResponse = None, llm_response_text: str = None, original_user_input: str = None, active_prompt_name: str = None, rag_focused_sources: list = None):
        self.collected_data = collected_data
        self.original_user_input = original_user_input
        self.active_prompt_name = active_prompt_name
        self.processed_data_indices = set()

        self.canonical_report = canonical_response
        self.prompt_report = prompt_report_response
        self.llm_response_text = llm_response_text
        self.rag_focused_sources = rag_focused_sources

    def _render_key_metric(self, metric: KeyMetric) -> str:
        """Renders the KeyMetric object into an HTML card."""
        if not metric:
            return ""

        metric_value = str(metric.value)
        metric_label = metric.label
        is_numeric = re.fullmatch(r'[\d,.]+', metric_value) is not None
        value_class = "text-4xl" if is_numeric else "text-2xl"
        label_class = "text-base"
        return f"""
<div class="key-metric-card bg-gray-900/50 p-4 rounded-lg mb-4 text-center">
    <div class="{value_class} font-bold text-white">{metric_value}</div>
    <div class="{label_class} text-gray-400 mt-1">{metric_label}</div>
</div>
"""

    def _render_direct_answer(self, answer: str) -> str:
        """
        Renders the direct answer text as a paragraph, but only if no key
        metric is present, to avoid redundancy in the UI.
        """
        if self.canonical_report and self.canonical_report.key_metric:
            return ""
        if not answer:
            return ""
        return f'<p class="text-gray-300 mb-4">{self._process_inline_markdown(answer)}</p>'

    def _render_observations(self, observations: list[Observation]) -> str:
        """Renders a list of Observation objects into an HTML list."""
        if not observations:
            return ""

        html_parts = [
            '<h3 class="text-lg font-bold text-white mb-3 border-b border-gray-700 pb-2">Key Observations</h3>',
            '<ul class="list-disc list-outside space-y-2 text-gray-300 mb-4 pl-5">'
        ]
        for obs in observations:
            html_parts.append(f'<li>{self._process_inline_markdown(obs.text)}</li>')

        html_parts.append('</ul>')
        return "".join(html_parts)

    def _render_synthesis(self, synthesis_items: list[Synthesis]) -> str:
        """Renders a list of Synthesis objects into an HTML list."""
        if not synthesis_items:
            return ""

        html_parts = [
            '<h3 class="text-lg font-bold text-white mb-3 border-b border-gray-700 pb-2">Agent\'s Analysis</h3>',
            '<ul class="list-disc list-outside space-y-2 text-gray-300 mb-4 pl-5">'
        ]
        for item in synthesis_items:
            html_parts.append(f'<li>{self._process_inline_markdown(item.text)}</li>')

        html_parts.append('</ul>')
        return "".join(html_parts)

    def _process_inline_markdown(self, text_content: str) -> str:
        """Handles basic inline markdown like code backticks and bolding."""
        if not isinstance(text_content, str):
            return ""
        # Handle escaped underscores first if necessary
        text_content = text_content.replace(r'\_', '_')
        # Process code backticks
        text_content = re.sub(r'`(.*?)`', r'<code class="bg-gray-900/70 text-teradata-orange rounded-md px-1.5 py-0.5 font-mono text-sm">\1</code>', text_content)
        # Process bold markdown (ensure it doesn't interfere with other markdown like italics if added later)
        text_content = re.sub(r'(?<!\*)\*\*(?!\*)(.*?)(?<!\*)\*\*(?!\*)', r'<strong>\1</strong>', text_content)
        return text_content


    def _render_standard_markdown(self, text: str) -> str:
        """
        Renders a block of text by processing standard markdown elements,
        including special key-value formats, fenced code blocks (handling SQL DDL
        specifically), and tables. Now more robust to LLM formatting errors.
        """
        if not isinstance(text, str):
            return ""

        lines = text.strip().split('\n')
        html_output = []
        list_level_stack = []
        in_code_block = False
        code_lang = ""
        code_content = []
        in_table = False
        table_headers = []
        table_rows = []

        def get_indent_level(line_text):
            return len(line_text) - len(line_text.lstrip(' '))

        def is_table_separator(line_text):
            return re.match(r'^\s*\|?\s*:?-+:?\s*\|?(\s*:?-+:?\s*\|?)*\s*$', line_text)

        def parse_table_row(line_text):
            # Remove leading/trailing pipes and whitespace, then split by pipe
            cells = [cell.strip() for cell in line_text.strip().strip('|').split('|')]
            return cells

        ddl_pattern = re.compile(r'^\s*CREATE\s+(MULTISET\s+)?TABLE', re.IGNORECASE)

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped_line = line.lstrip(' ') # Use lstrip for most checks, preserve original indent

            # --- Code Block Processing (Enhanced Robustness) ---
            # Check for closing fence (potentially inline)
            if in_code_block and line.strip().endswith('```'):
                content_before_fence = line.strip()[:-3].strip()
                if content_before_fence:
                    code_content.append(content_before_fence + '\n') # Add the preceding content

                full_code_content = "".join(code_content)
                is_sql_ddl = (code_lang == 'sql' and ddl_pattern.match(full_code_content))

                if is_sql_ddl:
                    mock_tool_result = {
                        "results": [{'Request Text': full_code_content}],
                        "metadata": {}
                    }
                    html_output.append(self._render_ddl(mock_tool_result, 0)) # Index doesn't matter here
                else:
                    sanitized_code = full_code_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    # --- MODIFICATION START: Remove onclick, add data-copy-type ---
                    html_output.append(f"""
<div class="sql-code-block mb-4">
    <div class="sql-header">
        <span>{code_lang.upper() if code_lang else 'Code'}</span>
        <button class="copy-button" data-copy-type="code">
             <svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5-.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zM-1 7a.5.5 0 0 1 .5-.5h15a.5.5 0 0 1 0 1H-.5A.5.5 0 0 1-1 7z"/></svg> Copy
        </button>
    </div>
    <pre><code class="language-{code_lang}">{sanitized_code}</code></pre>
</div>""")
                    # --- MODIFICATION END ---
                in_code_block = False
                code_content = []
                code_lang = ""
                i += 1
                continue

            # Check for opening fence (potentially after list item/bolding)
            opening_fence_match = re.match(r'^(.*?)(```\s*(\w*))$', stripped_line)
            if not in_code_block and opening_fence_match:
                content_before_fence = opening_fence_match.group(1).strip()
                fence_with_lang = opening_fence_match.group(2)
                lang_match = re.match(r'```\s*(\w*)', fence_with_lang)
                code_lang = lang_match.group(1).lower() if lang_match and lang_match.group(1) else ""

                # If there was content before the fence (e.g., list marker), render it first
                if content_before_fence:
                     # Check if it looks like a list item that should be rendered
                     list_marker_match = re.match(r'^([*-])\s+(\*\*.*?\*\*:\s*)?$', content_before_fence) # Handle bolded keys too
                     if list_marker_match:
                         # Render the list item part first, then start the code block
                         current_indent = get_indent_level(line)
                         while list_level_stack and current_indent < list_level_stack[-1]:
                             html_output.append('</ul>')
                             list_level_stack.pop()
                         if not list_level_stack or current_indent > list_level_stack[-1]:
                            html_output.append('<ul class="list-disc list-outside space-y-2 text-gray-300 mb-4 pl-5">')
                            list_level_stack.append(current_indent)
                         # Render the list item marker, potentially empty content if just marker
                         html_output.append(f'<li>{self._process_inline_markdown(content_before_fence[1:].strip())}') # Render content after marker
                         # No closing </li> yet, code block will be nested effectively

                     else: # Not a list item, treat as paragraph before code
                         html_output.append(f'<p class="text-gray-300 mb-4">{self._process_inline_markdown(content_before_fence)}</p>')

                # Now start the code block state
                in_code_block = True
                i += 1
                continue

            if in_code_block:
                code_content.append(line + '\n')
                i += 1
                continue

            # --- Table Detection and Processing (Must come *after* code block check) ---
            if '|' in line and i + 1 < len(lines) and is_table_separator(lines[i+1]):
                if not in_table: # Start of a new table
                    in_table = True
                    table_headers = parse_table_row(line)
                    table_rows = []
                    i += 2 # Skip header and separator line
                    continue

            if in_table:
                if '|' in line:
                    table_rows.append(parse_table_row(line))
                    i += 1
                    continue
                else: # End of table block
                    in_table = False
                    # Render the collected table
                    html_output.append("<div class='table-container mb-4'><table class='assistant-table'><thead><tr>")
                    html_output.extend(f'<th>{self._process_inline_markdown(h)}</th>' for h in table_headers)
                    html_output.append("</tr></thead><tbody>")
                    for row in table_rows:
                        html_output.append("<tr>")
                        # Ensure row length matches header length for consistent rendering
                        for k in range(len(table_headers)):
                            cell_content = row[k] if k < len(row) else ""
                            html_output.append(f'<td>{self._process_inline_markdown(cell_content)}</td>')
                        html_output.append("</tr>")
                    html_output.append("</tbody></table></div>")
                    # Decrement i because the current line (ending the table) needs processing
                    # i -= 1 -- No, the current line WASN'T part of the table, process it normally next

            # --- Standard Markdown Processing (Lists, Headings, Paragraphs) ---
            # Use stripped_line for matching content patterns
            current_indent = get_indent_level(line)

            key_value_match = re.match(r'^\s*\*\*\*(.*?):\*\*\*\s*(.*)$', stripped_line)
            list_item_match = re.match(r'^([*-])\s+(.*)$', stripped_line)

            # Close nested lists if indent decreases or non-list item found
            while list_level_stack and (not list_item_match or current_indent < list_level_stack[-1]):
                html_output.append('</ul>')
                list_level_stack.pop()

            if key_value_match:
                key = key_value_match.group(1).strip()
                value = key_value_match.group(2).strip()
                processed_value = self._process_inline_markdown(value)
                html_output.append(f"""
<div class="grid grid-cols-1 md:grid-cols-[1fr,3fr] gap-x-4 gap-y-1 py-2 border-b border-gray-800">
    <dt class="text-sm font-medium text-gray-400">{key}:</dt>
    <dd class="text-sm text-gray-200 mt-0">{processed_value}</dd>
</div>""")
            elif list_item_match:
                # Open new list level if needed
                if not list_level_stack or current_indent > list_level_stack[-1]:
                    html_output.append('<ul class="list-disc list-outside space-y-2 text-gray-300 mb-4 pl-5">')
                    list_level_stack.append(current_indent)

                content = list_item_match.group(2).strip()
                nested_kv_match = re.match(r'^\s*\*\*\*(.*?):\*\*\*\s*(.*)$', content)

                if nested_kv_match:
                    key = nested_kv_match.group(1).strip()
                    value = nested_kv_match.group(2).strip()
                    processed_value = self._process_inline_markdown(value)
                    # Render key-value pair without standard list bullet
                    html_output.append(f"""
<li class="list-none -ml-5">
    <div class="grid grid-cols-1 md:grid-cols-[1fr,3fr] gap-x-4 gap-y-1 py-1">
        <dt class="text-sm font-medium text-gray-400">{key}:</dt>
        <dd class="text-sm text-gray-200 mt-0">{processed_value}</dd>
    </div>
</li>""")
                elif content: # Standard list item content
                    html_output.append(f'<li>{self._process_inline_markdown(content)}</li>')
                # Handle empty list items (e.g., "* ") if necessary, currently skipped

            else: # Not a list, key-value, table, or code block line
                heading_match = re.match(r'^(#{1,6})\s+(.*)$', stripped_line)
                hr_match = re.match(r'^-{3,}$', stripped_line)

                if heading_match:
                    level = len(heading_match.group(1))
                    content = self._process_inline_markdown(heading_match.group(2).strip())
                    if level == 1:
                        html_output.append(f'<h2 class="text-xl font-bold text-white mb-3 border-b border-gray-700 pb-2">{content}</h2>')
                    elif level == 2:
                        html_output.append(f'<h3 class="text-lg font-bold text-white mb-3 border-b border-gray-700 pb-2">{content}</h3>')
                    else: # Treat h3-h6 similarly for styling simplicity
                        html_output.append(f'<h4 class="text-base font-semibold text-white mt-4 mb-2">{content}</h4>')
                elif hr_match:
                    html_output.append('<hr class="border-gray-600 my-4">')
                elif stripped_line: # Treat as a paragraph if it's not empty
                    html_output.append(f'<p class="text-gray-300 mb-4">{self._process_inline_markdown(stripped_line)}</p>')
                # Ignore effectively empty lines (only whitespace)

            i += 1

        # --- Cleanup after loop ---
        if in_table: # Render any pending table if the text ended mid-table
            html_output.append("<div class='table-container mb-4'><table class='assistant-table'><thead><tr>")
            html_output.extend(f'<th>{self._process_inline_markdown(h)}</th>' for h in table_headers)
            html_output.append("</tr></thead><tbody>")
            for row in table_rows:
                html_output.append("<tr>")
                for k in range(len(table_headers)):
                    cell_content = row[k] if k < len(row) else ""
                    html_output.append(f'<td>{self._process_inline_markdown(cell_content)}</td>')
                html_output.append("</tr>")
            html_output.append("</tbody></table></div>")

        while list_level_stack: # Close any remaining open lists
            html_output.append('</ul>')
            list_level_stack.pop()

        return "".join(html_output)


    def _render_json_synthesis(self, data: list) -> str:
        """
        Renders a list of JSON objects into a structured HTML format,
        intelligently detecting title and summary keys.
        """
        html_parts = ['<div class="space-y-4">']
        for item in data:
            if not isinstance(item, dict):
                continue

            title_keys = ['table_name', 'name', 'title', 'header']
            summary_keys = ['summary', 'description', 'text', 'content']

            title = next((item[key] for key in title_keys if key in item), None)
            summary = next((item[key] for key in summary_keys if key in item), None)

            html_parts.append('<div class="bg-gray-900/50 p-4 rounded-lg">')
            if title:
                html_parts.append(f'<h4 class="text-md font-semibold text-teradata-orange mb-2"><code>{title}</code></h4>')
            if summary:
                html_parts.append(f'<p class="text-gray-300 text-sm">{self._process_inline_markdown(summary)}</p>')
            html_parts.append('</div>')

        html_parts.append('</div>')
        return "".join(html_parts)

    def _render_synthesis_content(self, text_content: str) -> str:
        """
        Intelligently renders synthesis content. If the content is valid JSON,
        it's formatted as a structured list. Otherwise, it's treated as markdown.
        """
        if not isinstance(text_content, str):
            return ""

        try:
            # Look for JSON structures (list or object) within the text
            match = re.search(r'\[.*\]|\{.*\}', text_content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return self._render_json_synthesis(data)
                # Could add handling for single JSON objects here if needed
        except json.JSONDecodeError:
            pass # If JSON parsing fails, fall back to markdown rendering

        # Fallback: Render as standard markdown
        return self._render_standard_markdown(text_content)

    def _render_ddl(self, tool_result: dict, index: int) -> str:
        """
        Renders DDL statements found within a tool result. Handles cases
        where the 'results' list might contain multiple DDL statements.
        Now wrapped in response-card div.
        """
        if not isinstance(tool_result, dict) or "results" not in tool_result: return ""
        results = tool_result.get("results")
        if not isinstance(results, list) or not results: return ""

        html_parts = []
        ddl_key = 'Request Text' # Key where DDL is expected

        for result_item in results:
            if not isinstance(result_item, dict) or ddl_key not in result_item:
                continue

            ddl_text = result_item.get(ddl_key, '')
            if not ddl_text:
                continue

            # Sanitize for HTML display
            ddl_text_sanitized = ddl_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            # Try to extract table name for header
            metadata = tool_result.get("metadata", {})
            table_name = metadata.get("table") # Prefer metadata if available
            if not table_name:
                 # Fallback: Regex to find table name in DDL text
                 name_match = re.search(r'TABLE\s+([\w."]+)', ddl_text, re.IGNORECASE)
                 table_name = name_match.group(1) if name_match else "DDL"

            # Wrap each DDL block in response-card for consistent styling
            # --- MODIFICATION START: Remove onclick, add data-copy-type ---
            html_parts.append(f"""
<div class="response-card mb-4">
    <div class="sql-code-block">
        <div class="sql-header">
            <span>SQL DDL: {table_name}</span>
            <button class="copy-button" data-copy-type="code">
                 <svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5-.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zM-1 7a.5.5 0 0 1 .5-.5h15a.5.5 0 0 1 0 1H-.5A.5.5 0 0 1-1 7z"/></svg> Copy
            </button>
        </div>
        <pre><code class="language-sql">{ddl_text_sanitized}</code></pre>
    </div>
</div>""")
            # --- MODIFICATION END ---

        self.processed_data_indices.add(index) # Mark this tool result index as processed
        return "".join(html_parts)

    def _render_table(self, tool_result: dict, index: int, default_title: str) -> str:
        if not isinstance(tool_result, dict) or "results" not in tool_result: return ""
        results = tool_result.get("results")
        if not isinstance(results, list) or not results: return ""
        # Filter to ensure we only process list of dictionaries
        dict_results = [item for item in results if isinstance(item, dict)]
        if not dict_results: return "" # Skip if results are not dictionaries

        metadata = tool_result.get("metadata", {})
        title = metadata.get("tool_name", default_title)

        # Handle special case: single 'response' key (often from TDA_LLMTask)
        is_single_text_response = (
            len(dict_results) == 1 and
            "response" in dict_results[0] and
            len(dict_results[0].keys()) == 1
        )

        if is_single_text_response:
            response_text = dict_results[0].get("response", "")
            self.processed_data_indices.add(index)
            # Render this single response using the synthesis renderer for consistency
            return f"<div class='response-card'>{self._render_synthesis_content(response_text)}</div>"

        # Standard table rendering
        headers = dict_results[0].keys() # Assume consistent keys based on the first row
        # Ensure table data is safely encoded for the data attribute
        try:
             table_data_json = json.dumps(dict_results)
        except (TypeError, ValueError):
             table_data_json = json.dumps([{"error": "Could not serialize table data"}])

        # --- MODIFICATION START: Remove onclick, add data-copy-type ---
        html = f"""
        <div class="response-card mb-4">
            <div class="flex justify-between items-center mb-2">
                <h4 class="text-lg font-semibold text-white">Data: Result for <code>{title}</code></h4>
                <button class="copy-button" data-copy-type="table" data-table='{table_data_json.replace("'", "&apos;")}'>
                    <svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5-.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zM-1 7a.5.5 0 0 1 .5-.5h15a.5.5 0 0 1 0 1H-.5A.5.5 0 0 1-1 7z"/></svg> Copy Table
                </button>
            </div>
            <div class='table-container'>
                <table class='assistant-table'>
                    <thead><tr>{''.join(f'<th>{self._process_inline_markdown(h)}</th>' for h in headers)}</tr></thead>
                    <tbody>
        """
        # --- MODIFICATION END ---
        for row in dict_results:
            html += "<tr>"
            for header in headers:
                cell_data = str(row.get(header, '')) # Ensure data is string
                # Sanitize cell data for HTML
                sanitized_cell = cell_data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html += f"<td>{sanitized_cell}</td>"
            html += "</tr>"
        html += "</tbody></table></div></div>"
        self.processed_data_indices.add(index)
        return html

    def _render_chart_with_details(self, chart_data: dict, table_data: dict, chart_index: int, table_index: int) -> str:
        chart_id = f"chart-render-target-{uuid.uuid4()}"
        # Safely encode the spec JSON for the data attribute
        try:
             chart_spec_json = json.dumps(chart_data.get("spec", {}))
        except (TypeError, ValueError):
             chart_spec_json = json.dumps({"error": "Could not serialize chart spec"})

        table_html = ""
        results = table_data.get("results")
        # Ensure results are list of dicts for table rendering
        if isinstance(results, list) and results and all(isinstance(item, dict) for item in results):
            headers = results[0].keys()
            # Safely encode table data for the data attribute
            try:
                 table_data_json = json.dumps(results)
            except (TypeError, ValueError):
                 table_data_json = json.dumps([{"error": "Could not serialize table data"}])

            # --- MODIFICATION START: Remove onclick, add data-copy-type ---
            table_html += f"""
            <div class="flex justify-between items-center mt-4 mb-2">
                <h5 class="text-md font-semibold text-white">Chart Data</h5>
                <button class="copy-button" data-copy-type="table" data-table='{table_data_json.replace("'", "&apos;")}'>
                    <svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5-.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zM-1 7a.5.5 0 0 1 .5-.5h15a.5.5 0 0 1 0 1H-.5A.5.5 0 0 1-1 7z"/></svg> Copy Table
                </button>
            </div>
            """
            # --- MODIFICATION END ---

            table_html += "<div class='table-container'><table class='assistant-table'><thead><tr>"
            table_html += ''.join(f'<th>{self._process_inline_markdown(h)}</th>' for h in headers)
            table_html += "</tr></thead><tbody>"
            for row in results:
                table_html += "<tr>"
                for header in headers:
                    cell_data = str(row.get(header, ''))
                    sanitized_cell = cell_data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    table_html += f"<td>{sanitized_cell}</td>"
                table_html += "</tr>"
            table_html += "</tbody></table></div>"

        self.processed_data_indices.add(chart_index)
        self.processed_data_indices.add(table_index)

        return f"""
        <div class="response-card mb-4">
            <div id="{chart_id}" class="chart-render-target" data-spec='{chart_spec_json.replace("'", "&apos;")}'></div>
            <details class="mt-4">
                <summary class="text-sm font-semibold text-gray-400 cursor-pointer hover:text-white">Show Details</summary>
                {table_html}
            </details>
        </div>
        """

    def _format_workflow_report(self) -> tuple[str, dict]:
        tts_payload = { "direct_answer": "", "key_observations": "", "synthesis": "" }
        if self.canonical_report:
            tts_payload = {
                "direct_answer": self.canonical_report.direct_answer or "",
                "key_observations": " ".join([obs.text for obs in self.canonical_report.key_observations]),
                "synthesis": " ".join([synth.text for synth in self.canonical_report.synthesis])
            }

        summary_html_parts = []
        if self.canonical_report:
            if self.canonical_report.key_metric:
                summary_html_parts.append(self._render_key_metric(self.canonical_report.key_metric))

            summary_html_parts.append(self._render_direct_answer(self.canonical_report.direct_answer))

            if self.canonical_report.synthesis:
                summary_html_parts.append(self._render_synthesis(self.canonical_report.synthesis))

            if self.canonical_report.key_observations:
                summary_html_parts.append(self._render_observations(self.canonical_report.key_observations))

        html = ""
        if summary_html_parts:
             html += f"<div class='response-card summary-card mb-4'>{''.join(summary_html_parts)}</div>" # Added mb-4

        # Normalize collected_data structure
        data_to_process = {}
        if isinstance(self.collected_data, dict):
            data_to_process = self.collected_data
        elif isinstance(self.collected_data, list):
            # If it's a list, assume it's for the primary context
            context_key = f"Plan Results: {self.active_prompt_name or 'Ad-hoc'}"
            data_to_process[context_key] = self.collected_data
        if not data_to_process:
            return html or "<div class='response-card summary-card'><p>No data collected.</p></div>", tts_payload


        for context_key, all_items_for_context in data_to_process.items():
            if not isinstance(all_items_for_context, list): # Skip if data is malformed
                 continue

            synthesis_items = []
            collateral_items = []

            for item in all_items_for_context:
                tool_name = item.get("metadata", {}).get("tool_name") if isinstance(item, dict) else None
                if tool_name == 'TDA_LLMTask':
                    synthesis_items.append(item)
                else:
                    collateral_items.append(item)

            # Sanitize key for display
            display_key = context_key.replace("Workflow: ", "").replace(">", "&gt;").replace("Plan Results: ", "")

            if synthesis_items:
                synthesis_html = ""
                for i, item in enumerate(synthesis_items):
                    if isinstance(item, dict) and "results" in item and isinstance(item["results"], list) and item["results"]:
                        # Assuming single result from TDA_LLMTask for synthesis
                        response_text = item["results"][0].get("response", "")
                        if response_text:
                            # Render synthesis content within its own response card
                            synthesis_html += f"<div class='response-card mb-4'>{self._render_synthesis_content(response_text)}</div>"
                            # Mark this specific item index as processed *relative to the original list*
                            # This requires knowing the original index. We might need to adjust how processing is tracked.
                            # For simplicity now, we assume _format_workflow_report processes everything it receives.


                if synthesis_html:
                    html += f"<details class='response-card bg-white/5 open:bg-white/10 mb-4 rounded-lg border border-white/10'><summary class='p-4 font-bold text-lg text-white cursor-pointer hover:bg-white/10 rounded-t-lg'>Synthesis Report for: <code>{display_key}</code></summary><div class='p-4'>{synthesis_html}</div></details>" # Added padding

            if collateral_items:
                collateral_html = ""
                # We need original indices if processed_data_indices is used across different render calls.
                # Assuming this function gets the full, unprocessed list for this context.
                indices_in_context = [idx for idx, item in enumerate(all_items_for_context) if item in collateral_items]

                # Pair up charts and tables greedily
                paired_indices = set()
                chart_table_pairs = []
                temp_collateral = [(idx, item) for idx, item in zip(indices_in_context, collateral_items)]

                i = 0
                while i < len(temp_collateral):
                    orig_idx_i, item_i = temp_collateral[i]
                    if orig_idx_i in paired_indices:
                        i += 1
                        continue

                    is_chart = isinstance(item_i, dict) and item_i.get("type") == "chart"
                    is_table_data = isinstance(item_i, dict) and "results" in item_i and isinstance(item_i["results"], list)

                    if is_chart and i > 0: # Look back for table data
                        orig_idx_prev, prev_item = temp_collateral[i-1]
                        if orig_idx_prev not in paired_indices and isinstance(prev_item, dict) and "results" in prev_item and isinstance(prev_item["results"], list):
                            chart_table_pairs.append((item_i, prev_item, orig_idx_i, orig_idx_prev))
                            paired_indices.add(orig_idx_i)
                            paired_indices.add(orig_idx_prev)
                    elif is_table_data and i + 1 < len(temp_collateral): # Look ahead for chart
                        orig_idx_next, next_item = temp_collateral[i+1]
                        if orig_idx_next not in paired_indices and isinstance(next_item, dict) and next_item.get("type") == "chart":
                             chart_table_pairs.append((next_item, item_i, orig_idx_next, orig_idx_i))
                             paired_indices.add(orig_idx_i)
                             paired_indices.add(orig_idx_next)
                    i += 1

                # Render paired charts and tables first
                for chart_data, table_data, chart_idx, table_idx in chart_table_pairs:
                     collateral_html += self._render_chart_with_details(chart_data, table_data, chart_idx, table_idx)
                     self.processed_data_indices.add(chart_idx) # Mark using original indices
                     self.processed_data_indices.add(table_idx)

                # Render remaining unpaired items
                for orig_idx, item in temp_collateral:
                    if orig_idx in paired_indices or orig_idx in self.processed_data_indices: # Check global processed set too
                        continue

                    tool_name = item.get("metadata", {}).get("tool_name") if isinstance(item, dict) else None

                    # Handle list case (e.g., from column iteration orchestrator)
                    if isinstance(item, list) and item and isinstance(item[0], dict):
                        # Attempt to render as a single table if possible (e.g., results from multiple columns)
                        # Check if all items are successful results for the same tool
                        first_tool = item[0].get("metadata", {}).get("tool_name")
                        if all(isinstance(sub, dict) and sub.get('status') == 'success' and sub.get("metadata", {}).get("tool_name") == first_tool for sub in item):
                            combined_results = []
                            metadata = item[0].get("metadata", {}) # Use metadata from first item
                            for sub_item in item:
                                combined_results.extend(sub_item.get("results", []))

                            if combined_results:
                                table_to_render = {"results": combined_results, "metadata": metadata}
                                collateral_html += self._render_table(table_to_render, orig_idx, first_tool or "Iteration Result")
                            else: # If results were empty despite success
                                collateral_html += f"<div class='response-card mb-4'><p class='text-sm text-gray-400 italic'>Step produced no data results for '{display_key}'.</p></div>"
                        else: # Render individual statuses if mixed success/failure/skip
                             collateral_html += "<div class='response-card mb-4 space-y-2'>"
                             collateral_html += f"<h5 class='text-md font-semibold text-white'>Iteration Results for {first_tool or 'Step'}:</h5>"
                             for sub_item in item:
                                 if isinstance(sub_item, dict):
                                      status = sub_item.get('status', 'unknown')
                                      meta = sub_item.get('metadata', {})
                                      sub_tool = meta.get('tool_name', 'N/A')
                                      item_context = meta.get('column_name', meta.get('item', 'N/A'))
                                      if status == 'success':
                                           collateral_html += f"<p class='text-sm text-green-400'> - Success: {sub_tool} for {item_context}</p>"
                                      elif status == 'skipped':
                                           reason = sub_item.get('results', [{}])[0].get('reason', 'No reason provided.')
                                           collateral_html += f"<p class='text-sm text-yellow-400 italic'> - Skipped: {sub_tool} for {item_context}. Reason: {reason}</p>"
                                      elif status == 'error':
                                           error_msg = sub_item.get('error_message', sub_item.get('data', 'Unknown error'))
                                           collateral_html += f"<p class='text-sm text-red-400 italic'> - Error: {sub_tool} for {item_context}. Details: {error_msg}</p>"
                             collateral_html += "</div>"

                        self.processed_data_indices.add(orig_idx)
                        continue # Move to next item in temp_collateral

                    # Handle dictionary items (standard tool results, errors, skips)
                    elif isinstance(item, dict):
                        if item.get("type") == "business_description":
                            collateral_html += f"<div class='response-card mb-4'><h4 class='text-lg font-semibold text-white mb-2'>Business Description</h4><p class='text-gray-300'>{self._process_inline_markdown(item.get('description',''))}</p></div>"
                            self.processed_data_indices.add(orig_idx)
                        elif tool_name == 'base_tableDDL':
                            collateral_html += self._render_ddl(item, orig_idx) # Already adds mb-4
                        elif "results" in item:
                            collateral_html += self._render_table(item, orig_idx, f"Result for {tool_name or 'step'}") # Already adds mb-4
                        elif item.get("status") == "skipped":
                            reason = item.get('reason', item.get('results', [{}])[0].get('reason', 'No reason provided.'))
                            collateral_html += f"<div class='response-card mb-4'><p class='text-sm text-gray-400 italic'>Skipped Step: <strong>{tool_name or 'N/A'}</strong>. Reason: {self._process_inline_markdown(reason)}</p></div>"
                            self.processed_data_indices.add(orig_idx)
                        elif item.get("status") == "error":
                            error_msg = item.get('error_message', item.get('data', ''))
                            collateral_html += f"<div class='response-card mb-4'><p class='text-sm text-red-400 italic'>Error in Step: <strong>{tool_name or 'N/A'}</strong>. Details: {self._process_inline_markdown(str(error_msg))}</p></div>"
                            self.processed_data_indices.add(orig_idx)
                        # Add handling for chart type if unpaired
                        elif item.get("type") == "chart":
                             chart_id = f"chart-render-target-{uuid.uuid4()}"
                             chart_spec_json = json.dumps(item.get("spec", {}))
                             collateral_html += f'''<div class="response-card mb-4"><div id="{chart_id}" class="chart-render-target" data-spec='{chart_spec_json.replace("'", "&apos;")}'></div></div>'''
                             self.processed_data_indices.add(orig_idx)


                if collateral_html:
                    html += f"<details class='response-card bg-white/5 open:bg-white/10 mb-4 rounded-lg border border-white/10'><summary class='p-4 font-bold text-lg text-white cursor-pointer hover:bg-white/10 rounded-t-lg'>Collateral Report for: <code>{display_key}</code></summary><div class='p-4'>{collateral_html}</div></details>" # Added padding

        return html or "<div class='response-card summary-card'><p>Workflow completed, but no renderable output was generated.</p></div>", tts_payload


    def _format_standard_query_report(self) -> tuple[str, dict]:
        summary_html_parts = []
        tts_payload = {"direct_answer": "", "key_observations": "", "synthesis": ""}

        if self.canonical_report:
            if self.canonical_report.key_metric:
                summary_html_parts.append(self._render_key_metric(self.canonical_report.key_metric))
            summary_html_parts.append(self._render_direct_answer(self.canonical_report.direct_answer))
            if self.canonical_report.synthesis:
                summary_html_parts.append(self._render_synthesis(self.canonical_report.synthesis))
            if self.canonical_report.key_observations:
                summary_html_parts.append(self._render_observations(self.canonical_report.key_observations))

            tts_payload = {
                "direct_answer": self.canonical_report.direct_answer or "",
                "key_observations": " ".join([obs.text for obs in self.canonical_report.key_observations]),
                "synthesis": " ".join([synth.text for synth in self.canonical_report.synthesis])
            }
        elif self.llm_response_text:
            # Use the robust markdown renderer for plain text fallback
            summary_html_parts.append(self._render_standard_markdown(self.llm_response_text))
            tts_payload["direct_answer"] = self.llm_response_text

        summary_html = f'<div class="response-card summary-card mb-4">{"".join(summary_html_parts)}</div>' if summary_html_parts else "" # Added mb-4

        # Normalize data source structure
        data_source = []
        if isinstance(self.collected_data, dict):
            # Flatten dictionary values into a single list
            for item_list in self.collected_data.values():
                if isinstance(item_list, list):
                     data_source.extend(item_list)
        elif isinstance(self.collected_data, list):
            data_source = self.collected_data

        if not data_source:
            return summary_html or "<div class='response-card summary-card'><p>No data collected.</p></div>", tts_payload

        primary_chart_html = ""
        collateral_html_content = ""
        paired_indices = set() # Track indices used in chart-table pairs

        # --- Pair charts and tables ---
        chart_table_pairs = []
        for i, item_i in enumerate(data_source):
            if i in paired_indices: continue

            is_chart = isinstance(item_i, dict) and item_i.get("type") == "chart"
            is_table_data = isinstance(item_i, dict) and "results" in item_i and isinstance(item_i["results"], list)

            if is_chart and i > 0: # Look back for table
                 prev_item = data_source[i-1]
                 if (i-1) not in paired_indices and isinstance(prev_item, dict) and "results" in prev_item and isinstance(prev_item["results"], list):
                     chart_table_pairs.append((item_i, prev_item, i, i-1))
                     paired_indices.add(i)
                     paired_indices.add(i-1)
            elif is_table_data and i + 1 < len(data_source): # Look ahead for chart
                 next_item = data_source[i+1]
                 if (i+1) not in paired_indices and isinstance(next_item, dict) and next_item.get("type") == "chart":
                      chart_table_pairs.append((next_item, item_i, i+1, i))
                      paired_indices.add(i)
                      paired_indices.add(i+1)

        # Render the first paired chart-table as the primary chart
        if chart_table_pairs:
             first_pair = chart_table_pairs.pop(0)
             primary_chart_html = self._render_chart_with_details(*first_pair)
             # Mark these indices globally as processed
             self.processed_data_indices.add(first_pair[2])
             self.processed_data_indices.add(first_pair[3])


        # Render remaining collateral (unpaired items and remaining pairs)
        # Add remaining pairs back to be rendered individually if needed
        for chart_data, table_data, chart_idx, table_idx in chart_table_pairs:
             collateral_html_content += self._render_chart_with_details(chart_data, table_data, chart_idx, table_idx)
             self.processed_data_indices.add(chart_idx)
             self.processed_data_indices.add(table_idx)


        for i, tool_result in enumerate(data_source):
            if i in paired_indices or i in self.processed_data_indices: # Check global set too
                continue

            if not isinstance(tool_result, dict):
                continue # Skip non-dictionary items

            metadata = tool_result.get("metadata", {})
            tool_name = metadata.get("tool_name")

            if tool_name == 'base_tableDDL':
                collateral_html_content += self._render_ddl(tool_result, i) # Adds mb-4
            elif "results" in tool_result:
                # Render table, handles single text response internally
                collateral_html_content += self._render_table(tool_result, i, tool_name or "Result") # Adds mb-4
            elif tool_result.get("type") == "chart": # Render unpaired chart
                 chart_id = f"chart-render-target-{uuid.uuid4()}"
                 chart_spec_json = json.dumps(tool_result.get("spec", {}))
                 # --- MODIFICATION START: Fix the unterminated string literal error ---
                 collateral_html_content += f"""<div class="response-card mb-4"><div id="{chart_id}" class="chart-render-target" data-spec='{chart_spec_json.replace("'", "&apos;")}'></div></div>"""
                 # --- MODIFICATION END ---
                 self.processed_data_indices.add(i)
            elif tool_result.get("status") == "skipped":
                reason = tool_result.get('reason', tool_result.get('results', [{}])[0].get('reason', 'No reason provided.'))
                collateral_html_content += f"<div class='response-card mb-4'><p class='text-sm text-gray-400 italic'>Skipped Step: <strong>{tool_name or 'N/A'}</strong>. Reason: {self._process_inline_markdown(reason)}</p></div>"
                self.processed_data_indices.add(i)
            elif tool_result.get("status") == "error":
                error_msg = tool_result.get('error_message', tool_result.get('data', ''))
                collateral_html_content += f"<div class='response-card mb-4'><p class='text-sm text-red-400 italic'>Error in Step: <strong>{tool_name or 'N/A'}</strong>. Details: {self._process_inline_markdown(str(error_msg))}</p></div>"
                self.processed_data_indices.add(i)


        final_html_parts = []
        final_html_parts.append(summary_html)
        final_html_parts.append(primary_chart_html) # Already includes mb-4 if present

        if collateral_html_content:
            display_key = self.active_prompt_name or "Ad-hoc Query"
            # Wrap collateral in a details section
            collateral_wrapper = (
                f"<details class='response-card bg-white/5 open:bg-white/10 mb-4 rounded-lg border border-white/10'>"
                f"<summary class='p-4 font-bold text-lg text-white cursor-pointer hover:bg-white/10 rounded-t-lg'>Collateral Report for: <code>{display_key}</code></summary>"
                f"<div class='p-4'>{collateral_html_content}</div>" # Add padding
                f"</details>"
            )
            final_html_parts.append(collateral_wrapper)

        return "".join(final_html_parts) or "<div class='response-card summary-card'><p>Query completed, but no renderable output was generated.</p></div>", tts_payload


    def _format_complex_prompt_report(self) -> tuple[str, dict]:
        report = self.prompt_report
        if not report:
            return "<div class='response-card mb-4'><p>Error: Report data is missing.</p></div>", {}

        tts_payload = {
            "direct_answer": f"Report: {report.title}. Summary: {report.executive_summary}",
            "key_observations": "" # Could potentially synthesize key points from sections here later
        }

        # --- Render Main Report Content ---
        html_parts = [f"<div class='response-card summary-card mb-4'>"] # Added mb-4
        html_parts.append(f'<h2 class="text-xl font-bold text-white mb-3 border-b border-gray-700 pb-2">{self._process_inline_markdown(report.title)}</h2>')
        html_parts.append('<h3 class="text-lg font-semibold text-white mb-2">Executive Summary</h3>')
        html_parts.append(f'<div class="prose prose-invert max-w-none">{self._render_standard_markdown(report.executive_summary)}</div>') # Use markdown renderer

        if report.report_sections:
            for section in report.report_sections:
                # Add top border for separation
                html_parts.append(f'<h3 class="text-lg font-semibold text-white mt-6 mb-2 border-t border-gray-700 pt-4">{self._process_inline_markdown(section.title)}</h3>')
                # Render section content using the robust markdown renderer
                html_parts.append(f'<div class="prose prose-invert max-w-none">{self._render_standard_markdown(section.content)}</div>')

        html_parts.append("</div>") # Close summary-card

        # --- Render Collateral Data ---
        data_source = []
        if isinstance(self.collected_data, dict):
            for item_list in self.collected_data.values():
                 if isinstance(item_list, list):
                     data_source.extend(item_list)
        elif isinstance(self.collected_data, list):
            data_source = self.collected_data

        synthesis_items = []
        collateral_items = []
        # Filter out the main report generation tool results
        report_tool_names = {"TDA_ComplexPromptReport", "TDA_FinalReport"}
        for item in data_source:
            if not isinstance(item, dict): continue # Skip malformed items

            tool_name = item.get("metadata", {}).get("tool_name")
            if tool_name in report_tool_names:
                continue # Skip the report result itself
            elif tool_name == 'TDA_LLMTask':
                synthesis_items.append(item)
            else:
                 collateral_items.append(item)

        display_key = self.active_prompt_name or "Complex Prompt Execution" # More specific key

        # Render Synthesis separately if present
        if synthesis_items:
            synthesis_html_content = ""
            for i, item in enumerate(synthesis_items):
                 # We need the original index if using self.processed_data_indices globally
                 # For simplicity, assume indices passed here are relative to synthesis_items
                 if isinstance(item, dict) and "results" in item and isinstance(item["results"], list) and item["results"]:
                    response_text = item["results"][0].get("response", "")
                    if response_text:
                        synthesis_html_content += f"<div class='response-card mb-4'>{self._render_synthesis_content(response_text)}</div>"
                        # If tracking processed indices globally, need original index mapping

            if synthesis_html_content:
                html_parts.append(f"<details class='response-card bg-white/5 open:bg-white/10 mb-4 rounded-lg border border-white/10'><summary class='p-4 font-bold text-lg text-white cursor-pointer hover:bg-white/10 rounded-t-lg'>Intermediate Synthesis for: <code>{display_key}</code></summary><div class='p-4'>{synthesis_html_content}</div></details>")

        # Render Collateral (similar logic to standard report)
        if collateral_items:
            collateral_html_content = ""
            # Assuming indices passed here are relative to collateral_items
            # Pair charts and tables within collateral
            paired_indices_collateral = set()
            chart_table_pairs_collateral = []
            temp_collateral_indexed = list(enumerate(collateral_items)) # Use relative indices

            k = 0
            while k < len(temp_collateral_indexed):
                rel_idx_k, item_k = temp_collateral_indexed[k]
                if rel_idx_k in paired_indices_collateral:
                    k += 1
                    continue

                is_chart = isinstance(item_k, dict) and item_k.get("type") == "chart"
                is_table = isinstance(item_k, dict) and "results" in item_k

                if is_chart and k > 0: # Look back
                    rel_idx_prev, prev_item = temp_collateral_indexed[k-1]
                    if rel_idx_prev not in paired_indices_collateral and isinstance(prev_item, dict) and "results" in prev_item:
                         chart_table_pairs_collateral.append((item_k, prev_item, rel_idx_k, rel_idx_prev))
                         paired_indices_collateral.add(rel_idx_k)
                         paired_indices_collateral.add(rel_idx_prev)
                elif is_table and k + 1 < len(temp_collateral_indexed): # Look ahead
                     rel_idx_next, next_item = temp_collateral_indexed[k+1]
                     if rel_idx_next not in paired_indices_collateral and isinstance(next_item, dict) and next_item.get("type") == "chart":
                          chart_table_pairs_collateral.append((next_item, item_k, rel_idx_next, rel_idx_k))
                          paired_indices_collateral.add(rel_idx_k)
                          paired_indices_collateral.add(rel_idx_next)
                k+=1

            # Render pairs
            for chart_data, table_data, chart_rel_idx, table_rel_idx in chart_table_pairs_collateral:
                 # Need original indices if using global tracking
                 collateral_html_content += self._render_chart_with_details(chart_data, table_data, chart_rel_idx, table_rel_idx) # Pass relative indices for now

            # Render unpaired collateral
            for rel_idx, tool_result in temp_collateral_indexed:
                if rel_idx in paired_indices_collateral:
                    continue
                # Assuming index 'rel_idx' hasn't been processed globally if not paired locally
                metadata = tool_result.get("metadata", {})
                tool_name = metadata.get("tool_name")
                if tool_name == 'base_tableDDL':
                    collateral_html_content += self._render_ddl(tool_result, rel_idx)
                elif isinstance(tool_result, dict) and "results" in tool_result:
                    collateral_html_content += self._render_table(tool_result, rel_idx, tool_name or "Result")
                elif isinstance(tool_result, dict) and tool_result.get("status") == "skipped":
                     reason = tool_result.get('reason', tool_result.get('results', [{}])[0].get('reason', 'No reason provided.'))
                     collateral_html_content += f"<div class='response-card mb-4'><p class='text-sm text-gray-400 italic'>Skipped Step: <strong>{tool_name or 'N/A'}</strong>. Reason: {self._process_inline_markdown(reason)}</p></div>"
                     # Mark processed if needed: self.processed_data_indices.add(original_index)
                elif isinstance(tool_result, dict) and tool_result.get("status") == "error":
                     error_msg = tool_result.get('error_message', tool_result.get('data', ''))
                     collateral_html_content += f"<div class='response-card mb-4'><p class='text-sm text-red-400 italic'>Error in Step: <strong>{tool_name or 'N/A'}</strong>. Details: {self._process_inline_markdown(str(error_msg))}</p></div>"
                     # Mark processed if needed: self.processed_data_indices.add(original_index)


            if collateral_html_content:
                html_parts.append(
                    f"<details class='response-card bg-white/5 open:bg-white/10 mb-4 rounded-lg border border-white/10'>"
                    f"<summary class='p-4 font-bold text-lg text-white cursor-pointer hover:bg-white/10 rounded-t-lg'>Collateral Data for: <code>{display_key}</code></summary>"
                    f"<div class='p-4'>{collateral_html_content}</div>" # Add padding
                    f"</details>"
                )

        final_html = "".join(html_parts)
        return final_html, tts_payload

    def _render_rag_sources(self, sources: list) -> str:
        """Render expandable source cards for RAG focused profiles."""
        html_parts = [
            '<style>',
            '/* RAG Source Buttons - Override any theme styles */',
            '.rag-sources-section button { ',
            '  background: #374151 !important; ',
            '  background-image: none !important; ',
            '  color: white !important; ',
            '  border: none !important; ',
            '  font-size: 10px !important; ',
            '  padding: 3px 8px !important; ',
            '  border-radius: 4px !important; ',
            '}',
            '.rag-sources-section button:hover { background: #4B5563 !important; }',
            '</style>',
            '<div class="rag-sources-section mt-6">',
            '<button ',
            'onclick="const container = this.closest(\'.rag-sources-section\').querySelector(\'.rag-sources-container\'); ',
            'container.classList.toggle(\'hidden\'); ',
            'this.textContent = container.classList.contains(\'hidden\') ? \'Show Sources\' : \'Hide Sources\';">',
            'Show Sources',
            '</button>',
            '<div class="rag-sources-container hidden space-y-3 mt-3">',
            '<h3 class="text-lg font-bold text-white mb-3">Source Documents</h3>'
        ]

        for idx, doc in enumerate(sources):
            metadata = doc.get("metadata", {})
            collection_name = doc.get("collection_name", "Unknown")

            # Try title first (user-friendly name), then filename
            source_name = metadata.get("title") or metadata.get("filename")

            # If no title or filename, check if this is an imported collection
            if not source_name:
                if "(Imported)" in collection_name or metadata.get("source") == "import":
                    source_name = "No Document Source (Imported)"
                else:
                    source_name = "Unknown Source"
            similarity_score = doc.get("similarity_score", 0)
            content = doc.get("content", "")

            preview = content[:200] + "..." if len(content) > 200 else content
            preview_html = self._process_inline_markdown(preview)
            full_content_html = self._render_standard_markdown(content)

            score_color = "bg-green-700" if similarity_score >= 0.8 else "bg-yellow-700"

            html_parts.append(f"""
<div class="rag-source-card bg-gray-900/50 rounded-lg p-4 border border-gray-800">
    <div class="flex items-start justify-between mb-2">
        <div class="flex-1">
            <span class="text-sm font-semibold text-white">{source_name}</span>
            <span class="text-xs px-2 py-0.5 rounded {score_color} text-white ml-2">
                {similarity_score:.2f}
            </span>
            <div class="text-xs text-gray-400">Collection: {collection_name}</div>
        </div>
        <button
            onclick="this.closest('.rag-source-card').querySelector('.rag-source-preview').classList.toggle('hidden');
                     this.closest('.rag-source-card').querySelector('.rag-source-full').classList.toggle('hidden');
                     this.textContent = this.textContent === 'Expand' ? 'Collapse' : 'Expand';">
            Expand
        </button>
    </div>

    <div class="rag-source-preview text-sm text-gray-300 mt-2">{preview_html}</div>
    <div class="rag-source-full hidden text-sm text-gray-300 mt-2 border-t border-gray-700 pt-3">
        {full_content_html}
    </div>
</div>
""")

        html_parts.append('</div></div>')
        return "".join(html_parts)

    def render(self) -> tuple[str, dict]:
        """
        Main rendering method. Routes to the appropriate formatting strategy.

        Returns:
            A tuple containing:
            - final_html (str): The complete HTML string for the UI.
            - tts_payload (dict): The structured payload for the TTS engine.
        """
        self.processed_data_indices = set() # Reset for each render call

        # NEW: RAG Focused Sources Rendering
        if self.rag_focused_sources and len(self.rag_focused_sources) > 0:
            html_parts = []
            tts_text_parts = []

            # 1. Render LLM synthesis summary
            if self.llm_response_text:
                summary_html = self._render_standard_markdown(self.llm_response_text)
                html_parts.append(f"""
<div class="rag-synthesis-section mb-6">
    <h3 class="text-lg font-bold text-white mb-3">Summary</h3>
    <div class="text-gray-300">{summary_html}</div>
</div>
""")
                tts_text_parts.append(self.llm_response_text)

            # 2. Render source documents (expandable)
            sources_html = self._render_rag_sources(self.rag_focused_sources)
            html_parts.append(sources_html)

            tts_text_parts.append(f"Based on {len(self.rag_focused_sources)} source documents.")

            return "".join(html_parts), {"text": " ".join(tts_text_parts)}

        if isinstance(self.prompt_report, PromptReportResponse):
            final_html, tts_payload = self._format_complex_prompt_report()
        # --- MODIFICATION START: Prioritize canonical_report even if active_prompt_name exists ---
        elif isinstance(self.canonical_report, CanonicalResponse):
             # Decide format based on whether it was a prompt run or ad-hoc
             if self.active_prompt_name:
                 final_html, tts_payload = self._format_workflow_report() # Workflow often implies multiple steps
             else:
                 final_html, tts_payload = self._format_standard_query_report() # Ad-hoc usually simpler
        # --- MODIFICATION END ---
        elif self.llm_response_text: # Fallback for simple text response
            final_html, tts_payload = self._format_standard_query_report()
        else: # Default if nothing else fits
            final_html = "<div class='response-card summary-card mb-4'><p>The agent has completed its work.</p></div>"
            tts_payload = {"direct_answer": "The agent has completed its work.", "key_observations": "", "synthesis": ""}

        return final_html, tts_payload
