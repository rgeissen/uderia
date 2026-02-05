import axios from 'axios';

/**
 * Flow Builder API Client
 */
export const flowApi = {
  /**
   * Create axios instance with auth
   */
  createClient(baseUrl, token) {
    return axios.create({
      baseURL: baseUrl,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
  },

  // ==================== Flows ====================

  async createFlow(baseUrl, token, data) {
    const client = this.createClient(baseUrl, token);
    const response = await client.post('/api/v1/flows', data);
    return response.data;
  },

  async listFlows(baseUrl, token) {
    const client = this.createClient(baseUrl, token);
    const response = await client.get('/api/v1/flows');
    return response.data.flows || [];
  },

  async getFlow(baseUrl, token, flowId) {
    const client = this.createClient(baseUrl, token);
    const response = await client.get(`/api/v1/flows/${flowId}`);
    return response.data;
  },

  async updateFlow(baseUrl, token, flowId, data) {
    const client = this.createClient(baseUrl, token);
    const response = await client.put(`/api/v1/flows/${flowId}`, data);
    return response.data;
  },

  async deleteFlow(baseUrl, token, flowId) {
    const client = this.createClient(baseUrl, token);
    await client.delete(`/api/v1/flows/${flowId}`);
  },

  async duplicateFlow(baseUrl, token, flowId, name) {
    const client = this.createClient(baseUrl, token);
    const response = await client.post(`/api/v1/flows/${flowId}/duplicate`, { name });
    return response.data;
  },

  async validateFlow(baseUrl, token, flowId) {
    const client = this.createClient(baseUrl, token);
    const response = await client.post(`/api/v1/flows/${flowId}/validate`);
    return response.data;
  },

  // ==================== Execution ====================

  async executeFlow(baseUrl, token, flowId, input) {
    const client = this.createClient(baseUrl, token);
    const response = await client.post(`/api/v1/flows/${flowId}/execute`, { input });
    return response.data;
  },

  async getExecution(baseUrl, token, executionId) {
    const client = this.createClient(baseUrl, token);
    const response = await client.get(`/api/v1/flow-executions/${executionId}`);
    return response.data;
  },

  async listExecutions(baseUrl, token, flowId, limit = 20) {
    const client = this.createClient(baseUrl, token);
    const response = await client.get(`/api/v1/flows/${flowId}/executions`, {
      params: { limit }
    });
    return response.data.executions || [];
  },

  async cancelExecution(baseUrl, token, executionId) {
    const client = this.createClient(baseUrl, token);
    await client.post(`/api/v1/flow-executions/${executionId}/cancel`);
  },

  async respondToHuman(baseUrl, token, executionId, nodeId, response) {
    const client = this.createClient(baseUrl, token);
    const result = await client.post(`/api/v1/flow-executions/${executionId}/respond`, {
      node_id: nodeId,
      response
    });
    return result.data;
  },

  /**
   * Create SSE connection for execution streaming
   */
  streamExecution(baseUrl, token, executionId, onEvent, onError, onComplete) {
    const url = `${baseUrl}/api/v1/flow-executions/${executionId}/stream`;

    // Use fetch with streaming for SSE
    const controller = new AbortController();

    fetch(url, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'text/event-stream'
      },
      signal: controller.signal
    }).then(async response => {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events
        const lines = buffer.split('\n');
        buffer = lines.pop(); // Keep incomplete line in buffer

        let eventType = 'message';
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const data = line.slice(5).trim();
            if (data) {
              try {
                const parsed = JSON.parse(data);
                onEvent(eventType, parsed);

                if (eventType === 'done') {
                  onComplete && onComplete();
                }
              } catch (e) {
                console.warn('Failed to parse SSE data:', data);
              }
            }
          }
        }
      }

      onComplete && onComplete();
    }).catch(error => {
      if (error.name !== 'AbortError') {
        onError && onError(error);
      }
    });

    // Return abort function
    return () => controller.abort();
  },

  // ==================== Templates ====================

  async listTemplates(baseUrl, token) {
    const client = this.createClient(baseUrl, token);
    const response = await client.get('/api/v1/flow-templates');
    return response.data.templates || [];
  },

  async createFromTemplate(baseUrl, token, templateId, name, description) {
    const client = this.createClient(baseUrl, token);
    const response = await client.post('/api/v1/flows/from-template', {
      template_id: templateId,
      name,
      description
    });
    return response.data;
  },

  // ==================== Profiles (proxied from Uderia) ====================

  async getProfiles(baseUrl, token) {
    const client = this.createClient(baseUrl, token);
    const response = await client.get('/api/v1/profiles');
    return response.data.profiles || [];
  }
};

export default flowApi;
