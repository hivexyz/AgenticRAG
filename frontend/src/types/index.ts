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
  content_hash?: string | null;
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

export interface WikiPageItem {
  id: number;
  tenant_id: string;
  knowledge_base?: string | null;
  slug: string;
  title: string;
  summary?: string | null;
  content: string;
  source_document_id?: number | null;
  source_chunk_ids?: number[];
  metadata?: Record<string, unknown> | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WikiPageRevisionItem {
  id: number;
  tenant_id: string;
  page_id: number;
  action: string;
  title: string;
  summary?: string | null;
  content: string;
  knowledge_base?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface WikiCompileJobItem {
  id: number;
  tenant_id: string;
  status: 'pending' | 'processing' | 'completed' | 'partial_failed' | 'failed' | string;
  document_ids: number[];
  success_count: number;
  failure_count: number;
  metadata?: {
    pages?: WikiPageItem[];
    failures?: Array<{ document_id: number; error: string }>;
  } | Record<string, unknown> | null;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WikiTopicIndexItem {
  knowledge_base: string;
  page_count: number;
  pages: Array<{
    id: number;
    title: string;
    summary?: string | null;
    updated_at?: string | null;
  }>;
}

export interface WikiTopicIndexResponse {
  tenant_id: string;
  knowledge_bases: WikiTopicIndexItem[];
}

export interface WikiPageLinkItem {
  id: number;
  tenant_id: string;
  source_page_id: number;
  target_page_id: number;
  source_title?: string | null;
  target_title?: string | null;
  link_type: string;
  evidence?: string | null;
  created_at?: string | null;
}

export interface WikiPageLinksResponse {
  page_id: number;
  outgoing: WikiPageLinkItem[];
  incoming: WikiPageLinkItem[];
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

export interface FeedbackRecord {
  id: number;
  tenant_id: string;
  session_id?: number | null;
  message_id?: number | null;
  feedback_type: string;
  rating: 'up' | 'down' | string;
  reason?: string | null;
  comment?: string | null;
  corrected_answer?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface CitationSource {
  source_type?: string;
  wiki_page_id?: number;
  wiki_slug?: string;
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
  citation_scope?: 'sentence' | 'global' | string;
  citation_note?: string;
  uncertainty_flag: boolean;
}

export interface QualityEvaluation {
  groundedness?: number;
  relevance?: number;
  quality_score?: number;
  status?: string;
  reason?: string;
  missing_information?: string[];
}

export interface MultiHopTraceItem {
  hop?: number;
  purpose?: string;
  rendered_queries?: string[];
  extracted_slots?: Record<string, string | null>;
  dense_results?: number;
  sparse_results?: number;
  wiki_results?: number;
  fused_results?: number;
  elapsed_ms?: number;
  errors?: string[];
  stopped_reason?: string | null;
}

export interface RAGResult {
  query: string;
  answer?: string | null;
  quality_score?: number | null;
  quality_evaluation?: QualityEvaluation | null;
  quality_evaluation_status?: string | null;
  standalone_query?: string | null;
  query_rewrites?: string[] | null;
  query_analysis?: Record<string, unknown> | null;
  query_plan?: Record<string, unknown> | null;
  search_results?: Record<string, unknown>[] | null;
  reranked_results?: Record<string, unknown>[] | null;
  retrieval_count: number;
  retrieval_attempts?: Record<string, unknown>[] | null;
  context?: string | null;
  multi_hop_trace?: MultiHopTraceItem[] | null;
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

export interface FeedbackHitChunk {
  document_id?: number | null;
  chunk_id?: number | null;
  wiki_page_id?: number | null;
  title?: string | null;
  source_type?: string | null;
  page?: number | null;
  section_title?: string | null;
  snippet?: string;
}

export interface GoldenSetCandidate {
  id: string;
  question: string;
  must_hit_chunk_ids: number[];
  reference_answer: string;
  must_mention: string[];
  expected_refusal: boolean;
  source_feedback_id: number;
  reason?: string | null;
}

export interface FeedbackBadcaseItem {
  feedback: FeedbackRecord;
  user_query?: string | null;
  assistant_answer?: string | null;
  query_plan?: Record<string, unknown> | null;
  query_analysis?: Record<string, unknown> | null;
  standalone_query?: string | null;
  query_rewrites?: string[];
  quality_score?: number | null;
  quality_evaluation?: QualityEvaluation | null;
  multi_hop_trace?: MultiHopTraceItem[];
  retrieval_count?: number | null;
  retrieval_attempts?: Record<string, unknown>[];
  context_status?: Record<string, unknown> | null;
  citations?: CitationItem[];
  answer_blocks?: AnswerBlock[];
  evidence_cards?: EvidenceCard[];
  hit_chunks: FeedbackHitChunk[];
  document_ids: number[];
  documents: DocumentItem[];
  golden_candidate: GoldenSetCandidate;
  wiki_recompile_document_ids: number[];
}

export interface FeedbackBadcaseResponse {
  tenant_id: string;
  summary: {
    total: number;
    reason_counts: Record<string, number>;
  };
  items: FeedbackBadcaseItem[];
}

export interface GoldenSetAppendResponse {
  added: boolean;
  path: string;
  candidate: GoldenSetCandidate;
}

export interface FeedbackWikiRecompileResponse {
  feedback_id: number;
  job: WikiCompileJobItem;
  document_ids: number[];
}
