import type {
  BoundingRegion,
  DocumentCreateResponse,
  DocumentDetail,
  DocumentListResponse,
  DocumentStatus,
  DocumentSummary,
  FinancialResult,
  FinancialReviewHistory,
  FinancialReviewRecord,
  HealthDependencies,
  HealthStatus,
  PageResult,
  PageSummary,
  SessionStatus,
  TableCell,
  TableResult,
  TextBlock,
  TranslationReviewHistory,
  TranslationReviewRecord,
} from "../types";

// Runtime guards for API responses. The backend schema can drift from these types
// (partial writes, in-flight migrations, bugs) and `fetch(...).json()` only ever
// returns `unknown` in truth - trusting it via a blind `as T` cast lets a malformed
// response reach deep into rendering before it throws, as a cryptic TypeError with no
// context. These guards fail once, at the trust boundary, with a message that says
// what request produced the bad data.

const DOCUMENT_STATUSES = new Set<DocumentStatus>([
  "queued",
  "uploaded",
  "classifying",
  "extracting",
  "normalizing",
  "translating",
  "validating",
  "exporting",
  "completed",
  "needs_review",
  "failed",
  "cancelled",
]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isDocumentStatus(value: unknown): value is DocumentStatus {
  return isString(value) && DOCUMENT_STATUSES.has(value as DocumentStatus);
}

function isPoint(value: unknown): boolean {
  return isObject(value) && isFiniteNumber(value.x) && isFiniteNumber(value.y);
}

function isBoundingRegion(value: unknown): value is BoundingRegion {
  return (
    isObject(value) &&
    isFiniteNumber(value.page_number) &&
    Array.isArray(value.polygon) &&
    value.polygon.every(isPoint)
  );
}

function isBoundingRegionArray(value: unknown): value is BoundingRegion[] {
  return Array.isArray(value) && value.every(isBoundingRegion);
}

function isTextBlock(value: unknown): value is TextBlock {
  return (
    isObject(value) &&
    isString(value.block_id) &&
    isFiniteNumber(value.reading_order) &&
    isString(value.source_text) &&
    isString(value.source_language) &&
    isString(value.translation_status) &&
    isBoundingRegionArray(value.bounding_regions)
  );
}

function isTableCell(value: unknown): value is TableCell {
  return (
    isObject(value) &&
    isString(value.cell_id) &&
    isFiniteNumber(value.row_index) &&
    isFiniteNumber(value.column_index) &&
    isFiniteNumber(value.row_span) &&
    isFiniteNumber(value.column_span) &&
    isString(value.content) &&
    isString(value.source_language) &&
    isString(value.translation_status) &&
    isBoundingRegionArray(value.bounding_regions)
  );
}

function isTableResult(value: unknown): value is TableResult {
  return (
    isObject(value) &&
    isString(value.table_id) &&
    isFiniteNumber(value.row_count) &&
    isFiniteNumber(value.column_count) &&
    Array.isArray(value.cells) &&
    value.cells.every(isTableCell) &&
    isBoundingRegionArray(value.bounding_regions)
  );
}

export function isPageResult(value: unknown): value is PageResult {
  if (!isObject(value) || !isObject(value.page)) return false;
  const page = value.page;
  return (
    isString(value.schema_version) &&
    isString(value.document_id) &&
    isString(value.document_status) &&
    isFiniteNumber(page.page_number) &&
    isFiniteNumber(page.page_count) &&
    isFiniteNumber(page.width) &&
    isFiniteNumber(page.height) &&
    isString(page.unit) &&
    isFiniteNumber(page.angle) &&
    isString(page.source_text) &&
    Array.isArray(value.blocks) &&
    value.blocks.every(isTextBlock) &&
    Array.isArray(value.tables) &&
    value.tables.every(isTableResult) &&
    isStringArray(value.warnings)
  );
}

export function isDocumentDetail(value: unknown): value is DocumentDetail {
  return (
    isObject(value) &&
    isString(value.id) &&
    isString(value.original_filename) &&
    isString(value.content_type) &&
    isDocumentStatus(value.status) &&
    isString(value.current_stage) &&
    isFiniteNumber(value.progress_percent) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

export function isDocumentCreateResponse(value: unknown): value is DocumentCreateResponse {
  return (
    isObject(value) &&
    isString(value.document_id) &&
    isDocumentStatus(value.status) &&
    isString(value.status_url)
  );
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

export function isPageSummary(value: unknown): value is PageSummary {
  return (
    isObject(value) &&
    isFiniteNumber(value.page_number) &&
    isFiniteNumber(value.width) &&
    isFiniteNumber(value.height) &&
    isString(value.unit) &&
    isFiniteNumber(value.angle) &&
    isFiniteNumber(value.block_count) &&
    isFiniteNumber(value.table_count) &&
    isBoolean(value.review_required)
  );
}

export function isFinancialResult(value: unknown): value is FinancialResult {
  return (
    isObject(value) &&
    isString(value.schema_version) &&
    isString(value.document_id) &&
    isString(value.processing_version) &&
    isFiniteNumber(value.source_page_count) &&
    Array.isArray(value.selected_pages) &&
    value.selected_pages.every(isFiniteNumber) &&
    Array.isArray(value.uncertain_pages) &&
    value.uncertain_pages.every(isFiniteNumber) &&
    Array.isArray(value.tables) &&
    Array.isArray(value.reconciliation_candidate_ids) &&
    value.reconciliation_candidate_ids.every(isString) &&
    (value.content_items === undefined || Array.isArray(value.content_items)) &&
    isObject(value.validation) &&
    isFiniteNumber(value.validation.issue_count) &&
    Array.isArray(value.validation.issues)
  );
}

export function isFinancialReviewRecord(value: unknown): value is FinancialReviewRecord {
  return (
    isObject(value) &&
    isString(value.id) &&
    isString(value.document_id) &&
    (value.decision === "approved" || value.decision === "rejected") &&
    isString(value.reviewer_subject) &&
    Array.isArray(value.corrections) &&
    Array.isArray(value.structure_decisions) &&
    isString(value.processing_version) &&
    isString(value.result_schema_version) &&
    isString(value.result_sha256) &&
    isBoolean(value.active_result) &&
    isString(value.created_at)
  );
}

export function isFinancialReviewHistory(value: unknown): value is FinancialReviewHistory {
  return (
    isObject(value) &&
    Array.isArray(value.items) &&
    value.items.every(isFinancialReviewRecord)
  );
}

export function isTranslationReviewRecord(value: unknown): value is TranslationReviewRecord {
  return (
    isObject(value) &&
    isString(value.id) &&
    isString(value.document_id) &&
    (value.decision === "approved" || value.decision === "rejected") &&
    isString(value.reviewer_subject) &&
    Array.isArray(value.corrections) &&
    isString(value.processing_version) &&
    isString(value.result_schema_version) &&
    isString(value.result_sha256) &&
    isBoolean(value.active_result) &&
    isString(value.created_at)
  );
}

export function isTranslationReviewHistory(value: unknown): value is TranslationReviewHistory {
  return (
    isObject(value) &&
    Array.isArray(value.items) &&
    value.items.every(isTranslationReviewRecord)
  );
}

export function isPageSummaryArray(value: unknown): value is PageSummary[] {
  return Array.isArray(value) && value.every(isPageSummary);
}

export function isDocumentSummary(value: unknown): value is DocumentSummary {
  return (
    isObject(value) &&
    isString(value.id) &&
    isString(value.original_filename) &&
    isString(value.content_type) &&
    isFiniteNumber(value.file_size) &&
    isDocumentStatus(value.status) &&
    isString(value.current_stage) &&
    isFiniteNumber(value.progress_percent) &&
    isStringArray(value.source_languages) &&
    isString(value.target_language) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

export function isDocumentListResponse(value: unknown): value is DocumentListResponse {
  return (
    isObject(value) &&
    Array.isArray(value.items) &&
    value.items.every(isDocumentSummary) &&
    isFiniteNumber(value.page) &&
    isFiniteNumber(value.page_size) &&
    isFiniteNumber(value.total)
  );
}

export function isHealthStatus(value: unknown): value is HealthStatus {
  if (!isObject(value) || !isString(value.status)) return false;
  // /health/ready is deliberately minimal (status plus optional subsystem probes);
  // configuration detail lives behind auth on /health/dependencies.
  if (value.database !== undefined && !isString(value.database)) return false;
  if (value.storage !== undefined && !isString(value.storage)) return false;
  if (value.worker !== undefined && !isString(value.worker)) return false;
  if (value.limits !== undefined) {
    if (
      !isObject(value.limits) ||
      !isFiniteNumber(value.limits.max_upload_size_mb) ||
      !isFiniteNumber(value.limits.max_document_pages) ||
      (value.limits.job_poll_timeout_minutes !== undefined &&
        !isFiniteNumber(value.limits.job_poll_timeout_minutes))
    ) {
      return false;
    }
  }
  return true;
}

export function isHealthDependencies(value: unknown): value is HealthDependencies {
  return (
    isObject(value) &&
    isObject(value.document_intelligence) &&
    isBoolean(value.document_intelligence.configured) &&
    isObject(value.azure_openai) &&
    isBoolean(value.azure_openai.configured) &&
    (value.azure_openai.deployment === undefined ||
      value.azure_openai.deployment === null ||
      isString(value.azure_openai.deployment))
  );
}

export function isSessionStatus(value: unknown): value is SessionStatus {
  return (
    isObject(value) &&
    isBoolean(value.authenticated) &&
    isBoolean(value.auth_required) &&
    (value.subject === null || isString(value.subject)) &&
    (value.organization_id === undefined ||
      value.organization_id === null ||
      isString(value.organization_id)) &&
    (value.roles === undefined ||
      (Array.isArray(value.roles) && value.roles.every(isString))) &&
    isString(value.security_label) &&
    isString(value.data_policy)
  );
}
