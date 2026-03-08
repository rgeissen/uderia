## TDA DAG (tda_00_execute_questions)

This README documents the modern TDA Airflow DAG for automating queries with the Uderia Platform. It uses the profile-based architecture with Bearer token authentication and async polling.

## Files

- `tda_00_execute_questions.py`
  - **Purpose**: Read a `questions.txt` file (one question per line) and run a session/submit/poll workflow for each question using Bearer token authentication and profile-based configuration.
  - **Files used**: `questions.txt` (placed in the same directory as the DAG). Lines starting with `#` are ignored.
  - **Key Airflow artifacts used**:
    - Connection: `tda_api_conn` — base URL of TDA API (e.g., `http://localhost:5050`).
    - Variables (required):
      - `tda_api_key` — A valid TDA API key.
    - Variables (optional):
      - `tda_session_id` — reuse an existing session instead of creating a new one.
      - `tda_profile_id` — override the default profile for query execution.
  - **Behavior**:
    - At DAG-parse time, the DAG reads `questions.txt` and creates tasks for each question.
    - **Task 0** (`get_api_key`): Retrieves the TDA API key from the `tda_api_key` Airflow Variable.
    - **Task 1** (`get_or_create_session`): Creates a new session or reuses the existing one if `tda_session_id` is set.
    - **Task 2+** (`submit_query_Qx` + `poll_query_Qx`): For each question:
      - Submits the question to the session with optional profile override.
      - Polls the task status asynchronously until completion.
    - Uses Bearer token authentication on all requests (no legacy X-TDA-User-UUID headers).
    - Tasks are chained so each question executes serially.

- `questions.txt`
  - Sample file (one question per line). Edit this file to change which questions the DAG will run on the next DAG parse.

## How to run

1. **Set up the Airflow Connection** (Admin → Connections):
   - Connection ID: `tda_api_conn`
   - Host: Base URL of TDA API (e.g., `http://localhost:5050`)
   - Leave other fields empty

2. **Create required Airflow Variables** (Admin → Variables):
   - `tda_api_key` (required): A valid TDA API key for authentication.

3. **Create optional Airflow Variables** (for advanced scenarios):
   - `tda_session_id` (optional): Reuse an existing session ID
   - `tda_profile_id` (optional): Override the default profile (profile-1234567890-abcdef)

4. **Edit `questions.txt`** with one question per line. Example:
   ```
   # This is a comment
   How many users are in the system?
   What is the database version?
   ```

5. **Trigger the DAG** in the Airflow UI or via CLI.

## How to find Profile IDs

Use the TDA Configuration UI (Credentials → Profiles tab) to:
1. Navigate to the **Profiles** tab
2. Click the **copy button** next to each profile badge to copy its ID
3. Use the copied ID in the `tda_profile_id` Airflow Variable

Alternatively, use the REST API:
```bash
curl -X GET http://localhost:5050/api/v1/profiles \
  -H "Authorization: Bearer {tda_api_key}"
```

## Troubleshooting

- **Authentication errors**: Ensure `tda_api_key` is a valid TDA API key.
- **Profile not found**: Verify the profile ID format (e.g., `profile-1234567890-abcdef`) in the `tda_profile_id` Variable.
- **Session not found**: If using `tda_session_id`, ensure the session ID is valid and hasn't expired.
- **Task failures**: Check the Airflow task logs for detailed error messages from the TDA API.

## Notes & recommendations

- **DAG parse vs run-time**: The questions file is read at DAG parse time. If you edit `questions.txt`, wait for the scheduler to reparse the DAG for changes to take effect.
- **Session reuse**: Set `tda_session_id` to reuse a session across multiple DAG runs for consistency.
- **Profile override**: Use `tda_profile_id` to temporarily override the default profile for specific DAG runs.

For many questions, consider converting the DAG to dynamic task mapping or using a single-task iterator to reduce scheduler load.
