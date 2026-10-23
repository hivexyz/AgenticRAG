import { http } from './http';
import type { FeedbackBadcaseResponse, FeedbackWikiRecompileResponse, GoldenSetAppendResponse } from '../types';

export async function submitFeedback(payload: Record<string, unknown>) {
  const response = await http.post('/feedback/answers', payload);
  return response.data;
}

export async function fetchFeedbackBadcases(params: {
  tenant_id: string;
  rating?: string;
  reason?: string;
  limit?: number;
}) {
  const response = await http.get<FeedbackBadcaseResponse>('/feedback/badcases', { params });
  return response.data;
}

export async function addFeedbackToGoldenSet(feedbackId: number, tenantId: string) {
  const response = await http.post<GoldenSetAppendResponse>(`/feedback/answers/${feedbackId}/golden-set`, {
    tenant_id: tenantId,
    append_to_file: true,
  });
  return response.data;
}

export async function triggerFeedbackWikiRecompile(feedbackId: number, tenantId: string, documentIds?: number[]) {
  const response = await http.post<FeedbackWikiRecompileResponse>(`/feedback/answers/${feedbackId}/wiki-recompile`, {
    tenant_id: tenantId,
    document_ids: documentIds,
  });
  return response.data;
}
