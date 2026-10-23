import { getAuthHeaders, http } from './http';
import type { ConversationMessageResponse, ConversationSession } from '../types';

export interface ConversationStreamEvent {
  event: string;
  [key: string]: unknown;
}

interface StreamHandlers {
  onEvent: (event: ConversationStreamEvent) => void;
}

function apiUrl(path: string) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1';
  return `${baseURL.replace(/\/$/, '')}${path}`;
}

export async function createConversation(payload: { tenant_id: string; title: string }) {
  const response = await http.post<ConversationSession>('/conversations/', payload);
  return response.data;
}

export async function fetchConversations(tenantId: string) {
  const response = await http.get<ConversationSession[]>('/conversations/', {
    params: { tenant_id: tenantId },
  });
  return response.data;
}

export async function fetchConversationMessages(sessionId: number, tenantId: string) {
  const response = await http.get<Array<{ id: number; role: string; content: string; metadata?: Record<string, unknown> }>>(`/conversations/${sessionId}/messages`, {
    params: { tenant_id: tenantId },
  });
  return response.data;
}

export async function sendConversationMessage(sessionId: number, payload: { tenant_id: string; content: string }) {
  const response = await http.post<ConversationMessageResponse>(`/conversations/${sessionId}/messages`, payload);
  return response.data;
}

function dispatchSseBlock(block: string, handlers: StreamHandlers) {
  const lines = block.split(/\r?\n/);
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim());
    }
  }
  if (!dataLines.length) return;
  const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
  handlers.onEvent({ event, ...data });
}

export async function streamConversationMessage(
  sessionId: number,
  payload: { tenant_id: string; content: string },
  handlers: StreamHandlers,
  signal?: AbortSignal,
) {
  const response = await fetch(apiUrl(`/conversations/${sessionId}/messages/stream`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    let detail = `流式请求失败：${response.status}`;
    try {
      const errorBody = await response.json();
      detail = errorBody?.detail || detail;
    } catch {
      // Keep the generic HTTP error when the response body is not JSON.
    }
    throw new Error(detail);
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf('\n\n');
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (block) {
        dispatchSseBlock(block, handlers);
      }
      boundary = buffer.indexOf('\n\n');
    }
  }
  const tail = buffer.trim();
  if (tail) {
    dispatchSseBlock(tail, handlers);
  }
}
