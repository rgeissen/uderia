# Uderia Platform (TDA) Flowise Integration

## 1. Overview
This document details the architecture and configuration of the Flowise workflow used to interface with the Uderia Platform (TDA) REST API. The workflow handles user sessions, submits asynchronous queries, and polls for results using a direct Bearer token.

---
## 2. Agent Flow
The agent flow is provided as an exemplary script that can be imported into the Flowise environment:
- **TDA Conversation Agent:** [TDA Conversation Agents.json](./scripts/TDA%20Conversation%20Agents.json)

---

## 3. Workflow: TDA Conversation
**Purpose:** This is the primary user interface flow. It handles the asynchronous "Submit & Poll" pattern required by the TDA API, manages session state, and parses complex JSON responses. It uses a direct Bearer token for authentication.

### 3.1. Script Reference
The agent flow is defined in [TDA Conversation Agents.json](./scripts/TDA%20Conversation%20Agents.json).

### 3.2 Visual Architecture
*(Reference: Screenshot 2025-11-15 at 18.36.36.png)*
> **Note:** Insert the screenshot of the TDA Conversation flow here.

### 3.3 Node Configuration

#### **Node 1: Start Node**
Accepts runtime variables from the chat interface or calling application.

* **Variables:**
    * `baseUrl`: The TDA server address (e.g., `http://192.168.0.100:5050`).
    * `apiToken`: Direct API token for authentication.
    * `prompt`: The natural language query from the user.
    * `sessionId`: (Optional) An existing session ID to maintain context for multi-turn conversations.
    * `profileId`: (Optional) Profile ID override to use a specific LLM/MCP combination (uses default if not provided).

#### **Node 2: Custom Function (TDA Request)**
Executes the modern REST API interaction logic with Bearer token authentication.

* **Authentication Flow:**
    1.  **Headers:** All API calls use `Authorization: Bearer {apiToken}`. The `$apiToken` is passed directly from the Start Node.

* **Session & Query Logic:**
    1.  **Session Check:** If `$sessionId` is empty/null, creates a new session via `POST /api/v1/sessions`.
    2.  **Reuse:** If `$sessionId` is provided, reuses that existing session (enables multi-turn conversations).
    3.  **Submit Query:** Sends the `$prompt` to `POST /api/v1/sessions/{sessionId}/query` with optional `profile_id` override in the payload.
    4.  **Receive Task:** Returns `task_id` and `status_url`.

* **Polling Logic:**
    1.  **Poll Interval:** Checks status every 2 seconds.
    2.  **Max Polls:** 360 polls (12-minute timeout).
    3.  **Status Handling:**
        * `complete`: Task finished, extract `result`.
        * `error`: Task failed, throw error with details.
        * `cancelled`: Task was cancelled by user/system.
        * `pending` / `processing`: Continue polling.

* **Output Variables:**
    * `baseUrl`: Original base URL.
    * `prompt`: Original prompt text.
    * `sessionId`: Session ID (newly created or reused).
    * `taskId`: Task ID from query submission.
    * `result`: Full result object containing `tts_payload`.
    * `finalAnswer`: Direct answer or executive summary extracted from result.
    * `turnId`: Turn ID from result.
    * `profileTag`: Profile tag from result.

#### **Node 3: Custom Function (Response Extractor)**
Parses the raw output from the TDA Request node to isolate TTS payload data and preserve metadata.

* **Input Variables:**
    * `$apiResponse`: Output from Node 2 (TDA Request).
    * Flow state variables for reference: `$baseUrl`, `$apiToken`, `$sessionId`, `$prompt`.

* **Script Logic:**
    ```javascript
    // Parse the API response from TDA Request
    let responseObj = $apiResponse;

    // If it's a string, parse it
    if (typeof $apiResponse === 'string') {
        try {
            responseObj = JSON.parse($apiResponse);
        } catch (e) {
            return { error: "Failed to parse apiResponse" };
        }
    }

    // Check if we have an error
    if (responseObj && responseObj.error) {
        return { error: responseObj.error };
    }

    // Extract the result object
    if (responseObj && responseObj.result) {
        const result = responseObj.result;
        
        // Check for tts_payload in the result
        if (result && result.tts_payload) {
            const payload = result.tts_payload;
            
            // Return the extracted tts_payload with the key fields
            return {
                direct_answer: payload.direct_answer || '',
                key_observations: payload.key_observations || '',
                synthesis: payload.synthesis || '',
                baseUrl: responseObj.baseUrl,
                prompt: responseObj.prompt,
                sessionId: responseObj.sessionId,
                taskId: responseObj.taskId,
                turnId: responseObj.turnId,
                profileTag: responseObj.profileTag
            };
        } else {
            // If no tts_payload, return the result as-is with main fields
            return {
                direct_answer: result.direct_answer || '',
                key_observations: result.key_observations || '',
                synthesis: result.synthesis || '',
                baseUrl: responseObj.baseUrl,
                prompt: responseObj.prompt,
                sessionId: responseObj.sessionId,
                taskId: responseObj.taskId,
                turnId: responseObj.turnId,
                profileTag: responseObj.profileTag
            };
        }
    } else {
        return { error: "Invalid response structure" };
    }
    ```

* **Output:** Structured object with extracted TTS payload and session metadata for downstream nodes.

#### **Node 4: Formatter (Optional)**
Converts the JSON object from Node 3 into a human-readable Markdown string for the chat window.

* **Input:** `$cleanData` (Output from Response Extractor).
* **Output:** Formatted Markdown with Answer, Key Observations, and Synthesis sections.

---

## 4. Troubleshooting

| Error | Probable Cause | Solution |
| :--- | :--- | :--- |
| **Token failed: 401 Unauthorized** | Invalid or expired API token. | Verify the `apiToken` is valid and hasn't expired. Regenerate if necessary from the TDA admin panel. |
| **Session failed** | The API token is invalid or does not have permissions for the session endpoint. | Verify the `apiToken` is correct and has the necessary rights. |
| **Session {id} not found or expired** | The provided `sessionId` no longer exists. | Clear the `sessionId` input to force creation of a new session. |
| **Query failed: 404** | Session ID is invalid or expired. | Retry without providing a `sessionId` to create a fresh session. |
| **Task error** | Query execution failed in TDA backend. | Check TDA logs and verify profile configuration. |
| **Task timeout** | Query complexity exceeds polling limit (360 polls × 2s = 12 minutes). | Increase `maxPolls` in the TDA Request custom function. Simplify query if possible. |
| **Failed to parse apiResponse** | Response Extractor received invalid data format. | Verify TDA Request node output. Check for errors in the result object. |
| **tts_payload not found** | Result doesn't contain expected TTS data structure. | Verify the profile being used returns TTS payload. Check agent execution logs. |
| **baseUrl is not defined** | Flow state variable not properly initialized. | Ensure Start node has `baseUrl` set in initial Flow State. |
| **Invalid response structure** | Result object structure doesn't match expectations. | Check TDA API response format. Verify profile configuration. |
