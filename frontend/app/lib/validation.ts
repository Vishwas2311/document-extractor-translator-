import type {
  BoundingRegion,
  DocumentCreateResponse,
  DocumentDetail,
  DocumentListResponse,
  DocumentStatus,
  DocumentSummary,
  HealthStatus,
  PageResult,
  PageSummary,
  SessionStatus,
  TableCell,
  TableResult,
  TextBlock,
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
  "extracting",
  "normalizing",
  "translating",
  "validating",
  "exporting",
  "completed",
  "needs_review",
  "failed",
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
  if (
    !isObject(value) ||
    !isString(value.status) ||
    !isObject(value.azure_configured) ||
    !isBoolean(value.azure_configured.document_intelligence) ||
    !isBoolean(value.azure_configured.openai)
  ) {
    return false;
  }
  // New readiness fields are optional so older backends still validate.
  if (value.auth_required !== undefined && !isBoolean(value.auth_required)) return false;
  if (
    value.default_processing_profile !== undefined &&
    !isString(value.default_processing_profile)
  ) {
    return false;
  }
  if (value.default_data_class !== undefined && !isString(value.default_data_class)) return false;
  if (
    value.openai_deployment_configured !== undefined &&
    !isBoolean(value.openai_deployment_configured)
  ) {
    return false;
  }
  return true;
}

export function isSessionStatus(value: unknown): value is SessionStatus {
  return (
    isObject(value) &&
    isBoolean(value.authenticated) &&
    isBoolean(value.auth_required) &&
    (value.subject === null || isString(value.subject)) &&
    isString(value.security_label) &&
    isString(value.data_policy)
  );
}
