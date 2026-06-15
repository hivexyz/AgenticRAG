import { http } from './http';
import type { DocumentChunkItem, DocumentFragment, DocumentItem, PresetItem } from '../types';

export async function fetchDocuments(params: Record<string, string | number | undefined>) {
  const response = await http.get<DocumentItem[]>('/documents/', { params });
  return response.data;
}

export async function fetchDocumentPresets() {
  const response = await http.get<{ presets: PresetItem[]; default: string; vector_storage_label: string }>('/documents/management/presets');
  return response.data;
}

export async function createTextDocument(payload: Record<string, unknown>) {
  const response = await http.post<DocumentItem>('/documents/', payload);
  return response.data;
}

export async function uploadDocumentFile(formData: FormData) {
  const response = await http.post<DocumentItem>('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

export async function fetchDocumentChunks(documentId: number, tenantId: string) {
  const response = await http.get<DocumentChunkItem[]>(`/documents/${documentId}/chunks`, {
    params: { tenant_id: tenantId },
  });
  return response.data;
}

export async function fetchFragment(documentId: number, chunkId: number, tenantId: string) {
  const response = await http.get<DocumentFragment>(`/documents/${documentId}/chunks/${chunkId}`, {
    params: { tenant_id: tenantId },
  });
  return response.data;
}

export async function reindexDocument(documentId: number, tenantId: string) {
  const response = await http.post<DocumentItem>(`/documents/${documentId}/reindex`, null, {
    params: { tenant_id: tenantId, async_reindex: false },
  });
  return response.data;
}

export async function bulkDeleteDocuments(tenantId: string, documentIds: number[]) {
  const response = await http.post('/documents/bulk-delete', { tenant_id: tenantId, document_ids: documentIds });
  return response.data;
}
