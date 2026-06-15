export interface DocumentWorkflowStage {
  stage: string;
  label: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped' | string;
}

export interface DocumentItem {
  id: number;
  tenant_id: string;
  title: string;
  author?: string | null;
  file_type?: string | null;
  chunk_count?: number | null;
  ingestion_status?: string | null;
  vector_status?: string | null;
  status_display?: string | null;
  vector_status_display?: string | null;
  failure_reason?: string | null;
  retryable_actions?: string[];
  workflow?: DocumentWorkflowStage[];
  knowledge_base?: string | null;
  uploaded_by?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
  advanced_split_settings?: Record<string, unknown> | null;
}

export interface DocumentChunkItem {
  chunk_id: number;
  chunk_index: number;
  page?: number | null;
  paragraph?: number | null;
  section_title?: string | null;
  snippet: string;
  token_count?: number | null;
}

export interface DocumentFragment {
  document_id: number;
  chunk_id: number;
  title?: string | null;
  uploaded_at?: string | null;
  page?: number | null;
  paragraph?: number | null;
  section_title?: string | null;
  snippet: string;
  content: string;
  previous_context?: string | null;
  next_context?: string | null;
}

export interface PresetItem {
  key: string;
  label: string;
  split_method: string;
  chunk_size: number;
  chunk_overlap: number;
}

export interface ConversationSession {
  id: number;
  tenant_id: string;
  title: string;
  latest_summary?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FeedbackAction {
  key: string;
  label: string;
}

export interface CitationSource {
  document_id?: number;
  chunk_id?: number;
  title?: string;
  page?: number;
  paragraph?: number;
  uploaded_at?: string;
  section_title?: string;
  snippet?: string;
  open_fragment?: {
    document_id?: number;
    chunk_id?: number;
    page?: number;
    section_title?: string;
  };
}

export interface CitationItem {
  claim: string;
  sources: CitationSource[];
}

export interface EvidenceCard {
  rank: number;
  snippet: string;
  highlighted_sentences: string[];
  source: CitationSource;
  view_full_context?: {
    document_id?: number;
    chunk_id?: number;
    preview?: string;
  };
}

export interface AnswerBlock {
  text: string;
  citation_ids: number[];
  uncertainty_flag: boolean;
}

export interface RAGResult {
  query: string;
  answer?: string | null;
  quality_score?: number | null;
  query_analysis?: Record<string, unknown> | null;
  search_results?: Record<string, unknown>[] | null;
  reranked_results?: Record<string, unknown>[] | null;
  retrieval_count: number;
  context?: string | null;
  citations?: CitationItem[] | null;
  evidence_cards?: EvidenceCard[] | null;
  answer_blocks?: AnswerBlock[] | null;
  uncertainty?: { label?: string; message?: string; level?: string } | null;
  refusal?: { should_refuse?: boolean; message?: string; next_steps?: string[] } | null;
  messages: Array<{ role: string; content: string }>;
  error?: string | null;
}

export interface ConversationMessageResponse {
  session: ConversationSession;
  user_message: { id: number; role: string; content: string };
  assistant_message: { id: number; role: string; content: string; metadata?: Record<string, unknown> };
  feedback?: { message_id: number; actions: FeedbackAction[] };
  rag_result: RAGResult;
  context_status?: Record<string, unknown>;
}
