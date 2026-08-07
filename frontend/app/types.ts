export type DocumentStatus =
  | "queued"
  | "uploaded"
  | "classifying"
  | "extracting"
  | "normalizing"
  | "translating"
  | "validating"
  | "exporting"
  | "completed"
  | "needs_review"
  | "failed"
  | "cancelled";

export type TranslationStatus =
  | "not_required"
  | "pending"
  | "translated"
  | "failed"
  | "filtered"
  | "needs_review";

export interface Point {
  x: number;
  y: number;
}

export interface BoundingRegion {
  page_number: number;
  polygon: Point[];
}

export interface TextSpan {
  offset: number;
  length: number;
}

export interface TextBlock {
  block_id: string;
  reading_order: number;
  spans?: TextSpan[];
  role?: string | null;
  source_text: string;
  translated_text?: string | null;
  source_language: string;
  ocr_confidence?: number | null;
  translation_status: TranslationStatus;
  bounding_regions: BoundingRegion[];
  review_required?: boolean;
  warnings?: string[];
}

export interface TableCell {
  cell_id: string;
  row_index: number;
  column_index: number;
  row_span: number;
  column_span: number;
  kind?: string | null;
  spans?: TextSpan[];
  content: string;
  source_language: string;
  translated_content?: string | null;
  translation_status: TranslationStatus;
  review_required?: boolean;
  warnings?: string[];
  bounding_regions: BoundingRegion[];
}

export interface TableResult {
  table_id: string;
  row_count: number;
  column_count: number;
  cells: TableCell[];
  bounding_regions: BoundingRegion[];
}

export interface PageResult {
  schema_version: string;
  document_id: string;
  document_status: string;
  page: {
    page_number: number;
    page_count: number;
    width: number;
    height: number;
    unit: string;
    angle: number;
    source_text: string;
    translated_text?: string | null;
  };
  blocks: TextBlock[];
  tables: TableResult[];
  warnings: string[];
}

export interface DocumentDetail {
  id: string;
  original_filename: string;
  content_type: string;
  status: DocumentStatus;
  page_count?: number | null;
  pages_ready?: number | null;
  translation_batches_done?: number | null;
  translation_batches_total?: number | null;
  current_stage: string;
  progress_percent: number;
  safe_error_message?: string | null;
  created_at: string;
  updated_at: string;
  pages?: PageResult[];
  demo?: boolean;
  processing_profile?: string | null;
  data_class?: string | null;
  financial_extraction_mode?: string;
  financial_page_count?: number | null;
  uncertain_page_count?: number | null;
  financial_table_count?: number | null;
  financial_issue_count?: number | null;
  financial_result_sha256?: string | null;
  financial_review_status?: "approved" | "rejected" | null;
  financial_reviewed_by?: string | null;
  financial_reviewed_at?: string | null;
  organization_id?: string;
  owner_subject?: string;
  assigned_reviewer_subject?: string | null;
  document_review_status?: "draft" | "needs_review" | "in_review" | "approved" | "rejected";
  translation_result_sha256?: string | null;
  translation_review_status?: "approved" | "rejected" | null;
  translation_reviewed_by?: string | null;
  translation_reviewed_at?: string | null;
  queue_position?: number | null;
  active_jobs?: number | null;
  worker_slots?: number | null;
}

export interface DocumentCreateResponse {
  document_id: string;
  status: DocumentStatus;
  status_url: string;
  processing_profile?: string | null;
  data_class?: string | null;
}

export interface PageSummary {
  page_number: number;
  width: number;
  height: number;
  unit: string;
  angle: number;
  block_count: number;
  table_count: number;
  review_required: boolean;
  financial_label?: string | null;
  financial_confidence?: number | null;
  financial_disposition?: "financial" | "non_financial" | "uncertain" | null;
  financial_selected?: boolean;
  financial_reason?: string[];
  financial_table_count?: number;
  validation_issue_count?: number;
}

export interface FinancialPageClassification {
  page_number: number;
  label: string;
  confidence: number;
  disposition: "financial" | "non_financial" | "uncertain";
  selected: boolean;
  review_required: boolean;
  reasons: string[];
  candidates: Array<{ label: string; confidence: number }>;
  source: "azure_custom_classifier" | "layout_rules" | "adjacent_page";
}

export interface FinancialClassificationResult {
  schema_version: string;
  document_id: string;
  classifier_id: string;
  classifier_version: string;
  selection_policy_fingerprint: string;
  source_page_count: number;
  pages: FinancialPageClassification[];
}

export interface FinancialValidationIssue {
  issue_id: string;
  severity: "warning" | "error";
  code: string;
  message: string;
  page_number?: number | null;
  table_id?: string | null;
  cell_id?: string | null;
}

export interface FinancialCell {
  cell_id: string;
  row_index: number;
  column_index: number;
  row_span: number;
  column_span: number;
  kind?: string | null;
  source_language: string;
  translated_text?: string | null;
  source_page: number;
  review_required: boolean;
  warnings: string[];
  value: {
    raw_text: string;
    normalized_value?: string | null;
    value_type: "amount" | "percentage" | "text" | "empty";
    semantic_type:
      | "monetary_amount"
      | "percentage"
      | "percentage_range"
      | "quantity"
      | "measurement"
      | "phone_number"
      | "date_or_time"
      | "account_number"
      | "identifier"
      | "text"
      | "empty"
      | "unknown_numeric";
    currency?: string | null;
    currency_candidates: string[];
    currency_source?: "explicit_code" | "symbol" | "page_context" | null;
    currency_ambiguous: boolean;
    negative: boolean;
    ambiguous: boolean;
    requires_normalized_correction: boolean;
    requires_currency_correction: boolean;
    review_reason_code?:
      | "ambiguous_monetary_separator"
      | "ambiguous_currency"
      | "malformed_monetary_value"
      | null;
    normalization_status:
      | "parsed"
      | "ambiguous"
      | "unparsed"
      | "empty"
      | "not_applicable";
  };
  bounding_regions: BoundingRegion[];
  origin: "provider" | "reconstructed";
  source_block_ids: string[];
  reconciliation_candidate_id?: string | null;
}

export interface FinancialTable {
  table_id: string;
  source_pages: number[];
  financial_type: string;
  row_count: number;
  column_count: number;
  currencies: string[];
  cells: FinancialCell[];
  merge_policy:
    | "provider_table_atomic_v1"
    | "provider_table_with_reconciliation_v1";
  complete: boolean;
  missing_source_pages: number[];
  classification_override_pages: number[];
  review_required: boolean;
  provider_row_count?: number | null;
  provider_column_count?: number | null;
  integrity_status: "provider" | "reconciled" | "suspected_incomplete";
  reconciliation_candidate_id?: string | null;
  relevance: "financial" | "uncertain";
}

export type FinancialContentType =
  | "heading"
  | "paragraph"
  | "key_value"
  | "list_item"
  | "table";

export interface FinancialContentItem {
  item_id: string;
  item_type: FinancialContentType;
  reading_order: number;
  source_pages: number[];
  source_language: string;
  source_text?: string | null;
  translated_text?: string | null;
  role?: string | null;
  key?: string | null;
  value?: string | null;
  table_id?: string | null;
  translated_key?: string | null;
  translated_value?: string | null;
  relevance: "financial" | "supporting" | "uncertain";
  bounding_regions: BoundingRegion[];
  review_required: boolean;
  warnings: string[];
}


export interface FinancialResult {
  schema_version: string;
  document_id: string;
  processing_version: string;
  source_page_count: number;
  selected_pages: number[];
  uncertain_pages: number[];
  tables: FinancialTable[];
  content_items?: FinancialContentItem[];
  validation: {
    schema_version: string;
    document_id: string;
    issue_count: number;
    error_count: number;
    warning_count: number;
    review_required: boolean;
    issues: FinancialValidationIssue[];
  };
  reconciliation_candidate_ids: string[];
}

export interface FinancialCorrection {
  cell_id: string;
  normalized_value?: string | null;
  currency?: string | null;
  reason: string;
}

export interface FinancialStructureDecision {
  candidate_id: string;
  decision: "accepted" | "rejected";
  reason: string;
}

export interface FinancialReviewRecord {
  id: string;
  document_id: string;
  decision: "approved" | "rejected";
  reviewer_subject: string;
  note?: string | null;
  corrections: FinancialCorrection[];
  structure_decisions: FinancialStructureDecision[];
  processing_version: string;
  result_schema_version: string;
  result_sha256: string;
  active_result: boolean;
  created_at: string;
}

export interface FinancialReviewHistory {
  items: FinancialReviewRecord[];
}

export interface TranslationCorrection {
  target_kind: "block" | "cell";
  target_id: string;
  page_number: number;
  corrected_translated_text: string;
  reason: string;
}

export interface TranslationReviewRecord {
  id: string;
  document_id: string;
  decision: "approved" | "rejected";
  reviewer_subject: string;
  note?: string | null;
  corrections: TranslationCorrection[];
  processing_version: string;
  result_schema_version: string;
  result_sha256: string;
  active_result: boolean;
  created_at: string;
}

export interface TranslationReviewHistory {
  items: TranslationReviewRecord[];
}

export interface DocumentSummary {
  id: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  status: DocumentStatus;
  current_stage: string;
  progress_percent: number;
  page_count?: number | null;
  pages_ready?: number | null;
  translation_batches_done?: number | null;
  translation_batches_total?: number | null;
  source_languages: string[];
  target_language: string;
  processing_profile?: string | null;
  data_class?: string | null;
  financial_extraction_mode?: string;
  financial_page_count?: number | null;
  uncertain_page_count?: number | null;
  financial_table_count?: number | null;
  financial_issue_count?: number | null;
  financial_result_sha256?: string | null;
  financial_review_status?: "approved" | "rejected" | null;
  financial_reviewed_by?: string | null;
  financial_reviewed_at?: string | null;
  error_code?: string | null;
  safe_error_message?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface DocumentListResponse {
  items: DocumentSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface HealthStatus {
  status: string;
  azure_configured: {
    document_intelligence: boolean;
    openai: boolean;
  };
  /** Present on the current backend; optional for older local evaluation builds. */
  auth_required?: boolean;
  default_processing_profile?: string;
  default_data_class?: string;
  openai_deployment_configured?: boolean;
  database?: string;
  storage?: string;
  worker?: string;
  limits?: {
    max_upload_size_mb: number;
    max_document_pages: number;
    di_page_range_size?: number;
    di_range_concurrency?: number;
    translation_concurrency?: number;
    job_poll_timeout_minutes?: number;
  };
}

export interface SessionStatus {
  authenticated: boolean;
  auth_required: boolean;
  subject: string | null;
  organization_id?: string | null;
  roles?: string[];
  security_label: string;
  data_policy: string;
}

export type RetryMode = "resume" | "retranslate" | "reprocess";
