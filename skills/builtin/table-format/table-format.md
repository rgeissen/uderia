# Table Format

Format all data and results as clean Markdown tables.

## Rules

- Present any tabular data using Markdown table syntax with header row and alignment
- Use right-alignment for numeric columns, left-alignment for text
- Include a summary row (totals, averages) when appropriate
- If the data has more than 20 rows, show the first 15 rows and add a "... and N more rows" note
- For single values, still present them in a mini table with descriptive headers
- Never present data as bullet lists or inline text when a table would be clearer

## Format

```markdown
| Column A | Column B | Count |
|:---------|:---------|------:|
| Value 1  | Desc     |   42  |
| Value 2  | Desc     |   17  |
| **Total**|          | **59**|
```

## When Not to Use Tables

- Pure text explanations (no data)
- Single-sentence answers
- Code blocks or SQL queries
