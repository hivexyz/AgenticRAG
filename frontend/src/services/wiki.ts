import { http } from './http';
import type { WikiCompileJobItem, WikiPageItem, WikiPageLinksResponse, WikiPageRevisionItem, WikiTopicIndexResponse } from '../types';

export async function fetchWikiPages(params: Record<string, string | number | undefined>) {
  const response = await http.get<WikiPageItem[]>('/wiki/', { params });
  return response.data;
}

export async function fetchWikiTopicIndex(params: Record<string, string | number | undefined>) {
  const response = await http.get<WikiTopicIndexResponse>('/wiki/index/summary', { params });
  return response.data;
}

export async function fetchWikiPage(pageId: number, tenantId: string) {
  const response = await http.get<WikiPageItem>(`/wiki/${pageId}`, {
    params: { tenant_id: tenantId },
  });
  return response.data;
}

export async function fetchWikiPageRevisions(pageId: number, tenantId: string) {
  const response = await http.get<WikiPageRevisionItem[]>(`/wiki/${pageId}/revisions`, {
    params: { tenant_id: tenantId, limit: 20 },
  });
  return response.data;
}

export async function fetchWikiPageLinks(pageId: number, tenantId: string) {
  const response = await http.get<WikiPageLinksResponse>(`/wiki/${pageId}/links`, {
    params: { tenant_id: tenantId },
  });
  return response.data;
}

export async function rebuildWikiLinks(tenantId: string, knowledgeBase?: string) {
  const response = await http.post<{ tenant_id: string; knowledge_base?: string | null; page_count: number; link_count: number }>('/wiki/links/rebuild', null, {
    params: { tenant_id: tenantId, knowledge_base: knowledgeBase || undefined },
  });
  return response.data;
}

export async function compileWikiPage(tenantId: string, documentId: number) {
  const response = await http.post<WikiPageItem>('/wiki/compile', {
    tenant_id: tenantId,
    document_id: documentId,
  });
  return response.data;
}

export async function bulkCompileWikiPages(tenantId: string, documentIds: number[], asyncCompile = false) {
  const response = await http.post<{
    success_count: number;
    failure_count: number;
    pages: WikiPageItem[];
    failures: Array<{ document_id: number; error: string }>;
  } | WikiCompileJobItem>('/wiki/compile/bulk', {
    tenant_id: tenantId,
    document_ids: documentIds,
    async_compile: asyncCompile,
  });
  return response.data;
}

export async function fetchWikiCompileJob(jobId: number, tenantId: string) {
  const response = await http.get<WikiCompileJobItem>(`/wiki/compile/jobs/${jobId}`, {
    params: { tenant_id: tenantId },
  });
  return response.data;
}

export async function updateWikiPage(pageId: number, tenantId: string, payload: Partial<Pick<WikiPageItem, 'title' | 'summary' | 'content' | 'knowledge_base'>> & { expected_updated_at?: string | null }) {
  const response = await http.put<WikiPageItem>(`/wiki/${pageId}`, {
    tenant_id: tenantId,
    ...payload,
  });
  return response.data;
}

export async function deleteWikiPage(pageId: number, tenantId: string) {
  const response = await http.delete<{ deleted: boolean; page_id: number }>(`/wiki/${pageId}`, {
    params: { tenant_id: tenantId },
  });
  return response.data;
}
