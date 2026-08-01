export type DocumentStatus =
  | "queued"
  | "uploaded"
  | "extracting"
  | "normalizing"
  | "translating"
  | "validating"
  | "exporting"
  | "completed"
  | "needs_review"
  | "failed";

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
  current_stage: string;
  progress_percent: number;
  safe_error_message?: string | null;
  created_at: string;
  updated_at: string;
  pages?: PageResult[];
  demo?: boolean;
}

export interface DocumentCreateResponse {
  document_id: string;
  status: DocumentStatus;
  status_url: string;
}
