import type { CommandResponse, ExecutionCommandRequest, ExecutionDashboardSnapshot } from '../types/models';

const API_BASE = '/api';

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  getSnapshot: () => fetchJson<ExecutionDashboardSnapshot>('/snapshot'),
  sendCommand: (payload: ExecutionCommandRequest) =>
    fetchJson<CommandResponse>('/commands', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
