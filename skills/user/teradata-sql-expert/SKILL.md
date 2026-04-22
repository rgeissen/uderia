---
name: teradata-sql-expert
description: Teradata-specific SQL conversion rules and best practices for writing correct, idiomatic Teradata SQL.
user-invokable: true
---

If you would like to create SQL, you must follow the following conversion rules:

**Conversion Rules:**

1. Never use Limit:
   - Always use "SELECT TOP n ..." instead of "LIMIT n" to restrict rows.
   - Combine with QUALIFY for OFFSET handling when needed.

2. Boolean literals:
   - Replace "true" with 1.
   - Replace "false" with 0.
   - If schema convention uses 'Y'/'N', replace accordingly.

3. LIMIT / OFFSET:
   - Replace "LIMIT n OFFSET m" with:
     SELECT TOP n ...
     QUALIFY ROW_NUMBER() OVER (ORDER BY ...) > m
   - If only "LIMIT n" is used, replace with "TOP n".

4. String concatenation:
   - SQLAlchemy: "col1 || col2".
   - Teradata: Use "col1 || col2" if both are string types.
   - Otherwise CAST non-strings to VARCHAR before concatenation.

5. Autoincrement / identity columns:
   - Replace "AUTO_INCREMENT" or similar with:
     GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647).

6. CAST usage:
   - Always explicitly CAST when mixing data types.
   - Examples:
     - Concatenation: CAST(int_col AS VARCHAR(50)) || str_col
     - Comparisons: CAST(date_col AS VARCHAR(10)) = '2025-01-01'
     - Numeric/string: CAST(str_col AS INTEGER) for math operations

7. Datetime functions:
   - Replace "NOW()" with "CURRENT_TIMESTAMP".

8. Case-insensitive LIKE:
   - Replace "ILIKE" with "UPPER(col) LIKE UPPER(pattern)".

9. Schema handling:
   - Interpret "schema.table" as "database.table".

10. Identifier quoting:
    - Unquoted identifiers become uppercase.
    - Double quotes preserve case sensitivity.

11. LISTAGG(DISTINCT ...):
    - Teradata does not support LISTAGG(DISTINCT ...). Use a subquery with DISTINCT instead.

12. SQL Completeness (CRITICAL):
    - Always include all filtering (WHERE), sorting (ORDER BY), and row limiting (TOP n) directly in the SQL query.
    - Never delegate sorting, ranking, or filtering of query results to a separate phase or to TDA_LLMTask.
    - The database engine is always more accurate and efficient than an LLM for numerical operations.
    - Example: For "top 5 customers by revenue", use:
      SELECT TOP 5 C.CustomerID, C.FirstName, C.LastName, SUM(S.TotalAmount) AS TotalRevenue
      FROM database.Sales S JOIN database.Customers C ON S.CustomerID = C.CustomerID
      GROUP BY C.CustomerID, C.FirstName, C.LastName
      ORDER BY TotalRevenue DESC

**Result Reporting (CRITICAL — applies to your final answer):**

When your query returns rows, always include the actual data values in your answer text — not only a count or a generic summary.

- **Enumeration results** (users, tables, databases, columns, views, objects): list each name explicitly in your answer.
  - Good: "The system has 53 registered users: DBC, SysAdmin, viewpoint, TDaaS_FLOW1, TDaaS_CloudAvailabilityS1, ..."
  - Bad: "There are 53 registered users on the system."
  - If the result has more than 30 rows, list the first 30 and state "… and N more."

- **Count/aggregate results**: always include representative examples alongside the count.

- **Single-column results**: list all values (up to 30) directly in the answer text.

- **Multi-column results**: for the primary identifier column (the first meaningful column), list the values. Include other columns only when directly relevant to the question.

Never reduce a result set to only a count when the user asked which or what specific items exist.
