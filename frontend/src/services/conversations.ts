import { http } from './http';
import type { ConversationMessageResponse, ConversationSession } from '../types';

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
