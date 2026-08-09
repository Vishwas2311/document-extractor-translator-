"use client";

import {
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { demoDocument, demoPages } from "./demo-data";
import {
  API_BASE,
  checkHealth,
  checkSession,
  cancelDocument,
  createFinancialReview,
  createTranslationReview,
  deleteDocument,
  downloadArtifact,
  fetchSourceBlobUrl,
  getBilingualDocument,
  getFinancialResult,
  getFinancialReviews,
  getTranslationReviews,
  getDocument,
  getPage,
  isTerminal,
  listDocuments,
  listPageSummaries,
  retryDocument,
  uploadDocument,
} from "./lib/api";
import { selectInspectorBanner } from "./lib/inspector-banner";
import { describeError, useActionError } from "./lib/useActionError";
import { PdfPage } from "./pdf-page";
import type {
  BoundingRegion,
  DocumentDetail,
  DocumentSummary,
  FinancialContentItem,
  FinancialResult,
  FinancialReviewRecord,
  HealthStatus,
  PageResult,
  PageSummary,
  SessionStatus,
  TableCell,
  TableResult,
  TextBlock,
  TranslationReviewRecord,
} from "./types";

const ALLOWED_UPLOAD_EXTENSIONS = new Set([
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".bmp",
]);
const MAX_UPLOAD_BYTES_FALLBACK = 150 * 1024 * 1024;
const CURRENT_FINANCIAL_RESULT_SCHEMA = "financial-result-1.4";

function fileExtension(filename: string): string {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}

function validateUploadFile(file: File, maxUploadBytes = MAX_UPLOAD_BYTES_FALLBACK): string | null {
  if (!ALLOWED_UPLOAD_EXTENSIONS.has(fileExtension(file.name))) {
    return "The selected file is not supported. Upload PDF, PNG, JPEG, TIFF, or BMP.";
  }
  if (file.size === 0) {
    return "The selected file is empty.";
  }
  if (file.size > maxUploadBytes) {
    const limitMb = Math.round(maxUploadBytes / (1024 * 1024));
    return `The selected file exceeds the ${limitMb} MB upload limit.`;
  }
  return null;
}

/** Convert page geometry units to CSS pixels at the given zoom. */
function dimensionToCssPixels(value: number, unit: string, zoom = 1): number {
  const normalized = unit.toLowerCase();
  if (normalized === "inch" || normalized === "inches" || normalized === "in") {
    return value * 96 * zoom;
  }
  if (normalized === "pixel" || normalized === "pixels" || normalized === "px") {
    return value * zoom;
  }
  if (normalized === "point" || normalized === "points" || normalized === "pt") {
    return value * (96 / 72) * zoom;
  }
  // Azure Document Intelligence commonly reports inches; fall back safely.
  return value * 96 * zoom;
}

function isPdfContentType(contentType: string): boolean {
  return contentType === "application/pdf" || contentType.includes("pdf");
}

function isImageContentType(contentType: string): boolean {
  return (
    contentType === "image/png" ||
    contentType === "image/jpeg" ||
    contentType === "image/jpg" ||
    contentType === "image/bmp"
  );
}

type InspectorTab = "financial" | "page" | "json";
type PageView = "financial" | "review" | "all";
type ContentLanguageView = "source" | "english";

type IconName =
  | "close"
  | "trash"
  | "folder"
  | "plus"
  | "refresh"
  | "download"
  | "flag"
  | "arrowUp"
  | "arrowRight"
  | "arrowLeft"
  | "table"
  | "copy"
  | "minus"
  | "rotateLeft"
  | "rotateRight";

const iconPaths: Record<IconName, ReactNode> = {
  close: (
    <>
      <line x1="18" x2="6" y1="6" y2="18" />
      <line x1="6" x2="18" y1="6" y2="18" />
    </>
  ),
  trash: (
    <>
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <line x1="10" x2="10" y1="11" y2="17" />
      <line x1="14" x2="14" y1="11" y2="17" />
    </>
  ),
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />,
  plus: (
    <>
      <line x1="12" x2="12" y1="5" y2="19" />
      <line x1="5" x2="19" y1="12" y2="12" />
    </>
  ),
  refresh: (
    <>
      <path d="M21 12a9 9 0 1 1-2.8-6.5" />
      <polyline points="21 4 21 10 15 10" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v11" />
      <polyline points="7 10 12 15 17 10" />
      <path d="M5 19h14" />
    </>
  ),
  flag: (
    <>
      <path d="M5 21V4" />
      <path d="M5 5h12l-2.2 4L17 13H5" />
    </>
  ),
  arrowUp: (
    <>
      <line x1="12" x2="12" y1="19" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </>
  ),
  arrowRight: (
    <>
      <line x1="5" x2="19" y1="12" y2="12" />
      <polyline points="12 5 19 12 12 19" />
    </>
  ),
  arrowLeft: (
    <>
      <line x1="19" x2="5" y1="12" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </>
  ),
  table: (
    <>
      <rect height="16" rx="2" width="18" x="3" y="4" />
      <line x1="3" x2="21" y1="10" y2="10" />
      <line x1="9" x2="9" y1="4" y2="20" />
    </>
  ),
  copy: (
    <>
      <rect height="11" rx="1.5" width="11" x="9" y="9" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </>
  ),
  minus: <line x1="5" x2="19" y1="12" y2="12" />,
  rotateLeft: (
    <>
      <path d="M9 4H5v4" />
      <path d="M5.2 13a8 8 0 1 0 2.1-8.6L5 8" />
    </>
  ),
  rotateRight: (
    <>
      <path d="M15 4h4v4" />
      <path d="M18.8 13a8 8 0 1 1-2.1-8.6L19 8" />
    </>
  ),
};

function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className ?? "icon"}
      fill="none"
      height="16"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      width="16"
    >
      {iconPaths[name]}
    </svg>
  );
}

const statusLabels: Record<string, string> = {
  queued: "Queued",
  uploaded: "Uploaded",
  classifying: "Finding financial pages",
  extracting: "Extracting text",
  normalizing: "Normalizing layout",
  translating: "Translating",
  validating: "Validating",
  exporting: "Preparing exports",
  completed: "Completed",
  needs_review: "Review suggested",
  failed: "Failed",
  cancelled: "Cancelled",
};

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const timeoutId = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timeoutId);
        reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

function regionFor(block: TextBlock, pageNumber: number): BoundingRegion | undefined {
  return block.bounding_regions.find((region) => region.page_number === pageNumber);
}

function regionRectangle(region: BoundingRegion) {
  const xs = region.polygon.map((point) => point.x);
  const ys = region.polygon.map((point) => point.y);
  return {
    left: Math.min(...xs),
    top: Math.min(...ys),
    right: Math.max(...xs),
    bottom: Math.max(...ys),
  };
}

function coveredByRegion(blockRegion: BoundingRegion, tableRegion: BoundingRegion) {
  const block = regionRectangle(blockRegion);
  const table = regionRectangle(tableRegion);
  const intersectionWidth = Math.max(0, Math.min(block.right, table.right) - Math.max(block.left, table.left));
  const intersectionHeight = Math.max(0, Math.min(block.bottom, table.bottom) - Math.max(block.top, table.top));
  const blockArea = Math.max((block.right - block.left) * (block.bottom - block.top), 0.0001);
  return (intersectionWidth * intersectionHeight) / blockArea >= 0.72;
}

function normalizedTableText(value: string) {
  return value.replace(/\s+/g, "").trim().toLocaleLowerCase();
}

function blockIsRepresentedByTable(
  block: TextBlock,
  tables: TableResult[],
  pageNumber: number,
) {
  const blockRegion = regionFor(block, pageNumber);
  const normalizedBlock = normalizedTableText(block.source_text);
  if (!normalizedBlock) return false;

  return tables.some((table) => {
    const tableRegion = table.bounding_regions.find((region) => region.page_number === pageNumber);
    if (blockRegion && tableRegion && coveredByRegion(blockRegion, tableRegion)) {
      return true;
    }

    return table.cells.some((cell) => {
      if (normalizedTableText(cell.content) !== normalizedBlock) return false;
      const cellRegion = cell.bounding_regions.find((region) => region.page_number === pageNumber);
      return !blockRegion || !cellRegion || coveredByRegion(blockRegion, cellRegion);
    });
  });
}

function standaloneBlocksForPage(page: PageResult) {
  return page.blocks.filter(
    (block) => !blockIsRepresentedByTable(block, page.tables, page.page.page_number),
  );
}

type OrderedPageContent =
  | { kind: "block"; block: TextBlock }
  | { kind: "table"; table: TableResult; tableIndex: number };

function firstSpanOffset(spans: Array<{ offset: number }> | undefined) {
  if (!spans?.length) return undefined;
  return Math.min(...spans.map((span) => span.offset));
}

function findSelectedCell(page: PageResult | undefined, selectedId: string | null) {
  if (!page || !selectedId) return null;
  for (let tableIndex = 0; tableIndex < page.tables.length; tableIndex += 1) {
    const table = page.tables[tableIndex];
    const cell = table.cells.find((candidate) => candidate.cell_id === selectedId);
    if (cell) return { cell, table, tableIndex };
  }
  return null;
}

function topForRegions(regions: BoundingRegion[], pageNumber: number) {
  const pageRegions = regions.filter((region) => region.page_number === pageNumber);
  if (!pageRegions.length) return undefined;
  return Math.min(...pageRegions.flatMap((region) => region.polygon.map((point) => point.y)));
}

function tableSpanOffset(table: TableResult) {
  const offsets = table.cells
    .map((cell) => firstSpanOffset(cell.spans))
    .filter((offset): offset is number => offset !== undefined);
  return offsets.length ? Math.min(...offsets) : undefined;
}

function tableTop(table: TableResult, pageNumber: number) {
  const explicitTop = topForRegions(table.bounding_regions, pageNumber);
  if (explicitTop !== undefined) return explicitTop;

  const cellTops = table.cells
    .map((cell) => topForRegions(cell.bounding_regions, pageNumber))
    .filter((top): top is number => top !== undefined);
  return cellTops.length ? Math.min(...cellTops) : undefined;
}

function orderedPageContent(page: PageResult, blocks: TextBlock[]): OrderedPageContent[] {
  const buckets = Array.from({ length: blocks.length + 1 }, () => [] as Array<{
    table: TableResult;
    tableIndex: number;
    offset?: number;
    top?: number;
  }>);
  const pageNumber = page.page.page_number;

  page.tables.forEach((table, tableIndex) => {
    const offset = tableSpanOffset(table);
    const top = tableTop(table, pageNumber);
    let insertionIndex = blocks.length;

    const blocksHaveOffsets = blocks.some((block) => firstSpanOffset(block.spans) !== undefined);
    if (offset !== undefined && blocksHaveOffsets) {
      const followingBlock = blocks.findIndex((block) => {
        const blockOffset = firstSpanOffset(block.spans);
        return blockOffset !== undefined && blockOffset > offset;
      });
      if (followingBlock >= 0) insertionIndex = followingBlock;
    } else if (top !== undefined) {
      const followingBlock = blocks.findIndex((block) => {
        const blockTop = topForRegions(block.bounding_regions, pageNumber);
        return blockTop !== undefined && blockTop > top;
      });
      if (followingBlock >= 0) insertionIndex = followingBlock;
    }

    buckets[insertionIndex].push({ table, tableIndex, offset, top });
  });

  for (const bucket of buckets) {
    bucket.sort((left, right) => {
      if (left.offset !== undefined && right.offset !== undefined) return left.offset - right.offset;
      if (left.top !== undefined && right.top !== undefined) return left.top - right.top;
      return left.tableIndex - right.tableIndex;
    });
  }

  const ordered: OrderedPageContent[] = [];
  blocks.forEach((block, index) => {
    ordered.push(...buckets[index].map(({ table, tableIndex }) => ({ kind: "table" as const, table, tableIndex })));
    ordered.push({ kind: "block", block });
  });
  ordered.push(...buckets[blocks.length].map(({ table, tableIndex }) => ({ kind: "table" as const, table, tableIndex })));
  return ordered;
}
function boundsFor(region: BoundingRegion, page: PageResult) {
  const xs = region.polygon.map((point) => point.x);
  const ys = region.polygon.map((point) => point.y);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  const right = Math.max(...xs);
  const bottom = Math.max(...ys);
  return {
    left: `${(left / page.page.width) * 100}%`,
    top: `${(top / page.page.height) * 100}%`,
    width: `${((right - left) / page.page.width) * 100}%`,
    height: `${((bottom - top) / page.page.height) * 100}%`,
  };
}

function polygonFor(region: BoundingRegion, page: PageResult) {
  return region.polygon
    .map((point) => (point.x / page.page.width) * 100 + "% " + (point.y / page.page.height) * 100 + "%")
    .join(", ");
}

function displayLanguage(language: string) {
  const labels: Record<string, string> = {
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    mixed: "Mixed languages",
    en: "English",
    und: "Unknown language",
    zxx: "No linguistic content",
  };
  if (labels[language]) return labels[language];
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(language) ?? language;
  } catch {
    return language;
  }
}

function stripListMarker(text: string) {
  return text.replace(/^\s*(?:[-•‣▪◦]|\d+[.)])\s+/, "");
}

function thumbnailZoom(dimensions: { width: number; unit: string }) {
  const widthInCssPixels = dimensionToCssPixels(dimensions.width, dimensions.unit, 1);
  const widthInPdfPoints = widthInCssPixels * (72 / 96);
  return 78 / Math.max(widthInPdfPoints, 1);
}

interface RailItem {
  pageNumber: number;
  width: number;
  height: number;
  unit: string;
  reviewRequired: boolean;
  ready: boolean;
  financialSelected: boolean;
  financialDisposition: PageSummary["financial_disposition"];
  financialLabel: string | null;
  financialConfidence: number | null;
  validationIssueCount: number;
}

function progressLabel(document: DocumentDetail): string {
  const stage = document.current_stage;
  const percent = document.progress_percent;
  const ready = document.pages_ready;
  const total = document.page_count;
  const batchesDone = document.translation_batches_done;
  const batchesTotal = document.translation_batches_total;
  if (document.status === "queued" && document.queue_position != null) {
    return `Waiting in queue · position ${document.queue_position}` +
      (document.worker_slots != null ? ` · ${document.active_jobs ?? 0}/${document.worker_slots} workers busy` : "") +
      ` · ${percent}%`;
  }
  if (
    (stage === "translating" || stage === "Translating") &&
    batchesTotal != null &&
    batchesTotal > 0
  ) {
    return `${stage} · batch ${batchesDone ?? 0}/${batchesTotal} · ${percent}%`;
  }
  if (total && ready != null && ready >= 0 && (stage === "extracting" || stage === "normalizing" || stage === "Extracting" || stage === "Normalizing")) {
    return `${stage} · pages ${ready}/${total} · ${percent}%`;
  }
  if (ready != null && total && ready < total && !isTerminal(document.status)) {
    return `${stage} · pages ready ${ready}/${total} · ${percent}%`;
  }
  return `${stage} · ${percent}%`;
}

function VirtualPdfThumb(props: {
  authSrc: string;
  pageNumber: number;
  rotation: number;
  src: string;
  zoom: number;
  width: number;
  height: number;
  unit: string;
}) {
  const hostRef = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const root = host.closest(".thumbnail-scroll");
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        setVisible(Boolean(entry?.isIntersecting));
      },
      {
        root: root instanceof Element ? root : null,
        rootMargin: "160px 0px",
        threshold: 0.01,
      },
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  return (
    <span
      className="thumbnail-paper is-pdf"
      ref={hostRef}
      style={{
        aspectRatio: `${props.width} / ${props.height}`,
        height: "auto",
      }}
    >
      {visible ? (
        <PdfPage
          authSrc={props.authSrc}
          compact
          pageNumber={props.pageNumber}
          rotation={props.rotation}
          src={props.src}
          zoom={props.zoom}
        />
      ) : (
        <span className="thumb-placeholder" aria-hidden="true" />
      )}
    </span>
  );
}

function DemoThumbnail({ page }: { page: PageResult }) {
  return (
    <span className="demo-thumbnail-page" aria-hidden="true">
      <span className="demo-thumbnail-header">
        <span className="demo-thumbnail-logo">YC</span>
        <span className="demo-thumbnail-brand-name">Youth Care</span>
        <span className="demo-thumbnail-confidential">PRIVATE</span>
      </span>
      <span className="demo-thumbnail-rule" />
      {page.blocks.map((block) => {
        const region = regionFor(block, page.page.page_number);
        if (!region) return null;
        return (
          <span
            className={"demo-thumbnail-text " + (block.role === "title" ? "is-title" : "")}
            dir="auto"
            key={block.block_id}
            style={boundsFor(region, page)}
          >
            {block.source_text}
          </span>
        );
      })}
      {page.tables.map((table) => {
        const region = table.bounding_regions.find(
          (candidate) => candidate.page_number === page.page.page_number,
        );
        if (!region) return null;
        return (
          <span
            className="demo-thumbnail-table"
            key={table.table_id}
            style={{
              ...boundsFor(region, page),
              gridTemplateColumns: "repeat(" + table.column_count + ", minmax(0, 1fr))",
              gridTemplateRows: "repeat(" + table.row_count + ", minmax(0, 1fr))",
            }}
          >
            {table.cells.map((cell) => (
              <span
                className={"demo-thumbnail-cell " + (cell.kind === "columnHeader" ? "is-header" : "")}
                dir="auto"
                key={cell.cell_id}
                style={{
                  gridColumn: cell.column_index + 1 + " / span " + cell.column_span,
                  gridRow: cell.row_index + 1 + " / span " + cell.row_span,
                }}
              >
                {cell.content}
              </span>
            ))}
          </span>
        );
      })}
      <span className="demo-thumbnail-footer">
        <span />
        <span>{page.page.page_number}</span>
      </span>
    </span>
  );
}

function StatusBadge({ document }: { document: DocumentDetail }) {
  return (
    <span className={"status-badge status-" + document.status}>
      <span className="status-dot" />
      {statusLabels[document.status] ?? document.status}
    </span>
  );
}

function tooltipIdFor(block: TextBlock, page: PageResult) {
  return `region-tooltip-${page.page.page_number}-${block.reading_order}`;
}

function RegionTooltip({
  block,
  page,
  region,
}: {
  block: TextBlock;
  page: PageResult;
  region: BoundingRegion;
}) {
  const xs = region.polygon.map((point) => point.x);
  const ys = region.polygon.map((point) => point.y);
  const left = Math.min(...xs);
  const right = Math.max(...xs);
  const top = Math.min(...ys);
  const bottom = Math.max(...ys);
  const placeAbove = top / page.page.height > 0.28;
  const anchorX = ((left + right) / 2 / page.page.width) * 100;
  const anchorY = ((placeAbove ? top : bottom) / page.page.height) * 100;
  const translation = block.translated_text?.trim();

  return (
    <div
      className="region-tooltip"
      data-placement={placeAbove ? "above" : "below"}
      id={tooltipIdFor(block, page)}
      role="tooltip"
      style={{
        left: `clamp(154px, ${anchorX}%, calc(100% - 154px))`,
        top: `${anchorY}%`,
      }}
    >
      <div className="region-tooltip-heading">
        <span>English translation</span>
        <span className="region-tooltip-language">{displayLanguage(block.source_language)}</span>
      </div>
      <p className={translation ? "region-tooltip-translation" : "region-tooltip-pending"}>
        {translation || "Translation pending — configure Azure OpenAI to generate the English text."}
      </p>
      <div className="region-tooltip-divider" />
      <span className="region-tooltip-label">Original</span>
      <p className="region-tooltip-source" dir="auto">{block.source_text}</p>
    </div>
  );
}
function cellRegionFor(
  table: TableResult,
  cell: TableCell,
  pageNumber: number,
): BoundingRegion | undefined {
  const explicitRegion = cell.bounding_regions.find(
    (region) => region.page_number === pageNumber,
  );
  if (explicitRegion) return explicitRegion;

  const tableRegion = table.bounding_regions.find(
    (region) => region.page_number === pageNumber,
  );
  if (!tableRegion || table.column_count <= 0 || table.row_count <= 0) return undefined;

  const bounds = regionRectangle(tableRegion);
  const tableWidth = bounds.right - bounds.left;
  const tableHeight = bounds.bottom - bounds.top;
  const left = bounds.left + tableWidth * (cell.column_index / table.column_count);
  const right = bounds.left + tableWidth * (
    Math.min(cell.column_index + cell.column_span, table.column_count) / table.column_count
  );
  const top = bounds.top + tableHeight * (cell.row_index / table.row_count);
  const bottom = bounds.top + tableHeight * (
    Math.min(cell.row_index + cell.row_span, table.row_count) / table.row_count
  );

  return {
    page_number: pageNumber,
    polygon: [
      { x: left, y: top },
      { x: right, y: top },
      { x: right, y: bottom },
      { x: left, y: bottom },
    ],
  };
}

function cellTooltipIdFor(cell: TableCell, page: PageResult) {
  return `table-cell-tooltip-${page.page.page_number}-${cell.cell_id}`;
}

function TableCellTooltip({
  cell,
  page,
  region,
  tableIndex,
}: {
  cell: TableCell;
  page: PageResult;
  region: BoundingRegion;
  tableIndex: number;
}) {
  const bounds = regionRectangle(region);
  const placeAbove = bounds.top / page.page.height > 0.28;
  const anchorX = ((bounds.left + bounds.right) / 2 / page.page.width) * 100;
  const anchorY = ((placeAbove ? bounds.top : bounds.bottom) / page.page.height) * 100;
  const translation = cell.translated_content?.trim();

  return (
    <div
      className="region-tooltip table-cell-tooltip"
      data-placement={placeAbove ? "above" : "below"}
      id={cellTooltipIdFor(cell, page)}
      role="tooltip"
      style={{
        left: `clamp(154px, ${anchorX}%, calc(100% - 154px))`,
        top: `${anchorY}%`,
      }}
    >
      <div className="region-tooltip-heading">
        <span>Table {tableIndex + 1} · Row {cell.row_index + 1} · Column {cell.column_index + 1}</span>
        <span className="region-tooltip-language">
          {cell.kind === "columnHeader" ? "Header" : displayLanguage(cell.source_language)}
        </span>
      </div>
      <p className={translation ? "region-tooltip-translation" : "region-tooltip-pending"}>
        {translation || "Translation pending — configure Azure OpenAI to generate the English text."}
      </p>
      <div className="region-tooltip-divider" />
      <span className="region-tooltip-label">Original</span>
      <p className="region-tooltip-source" dir="auto">{cell.content}</p>
    </div>
  );
}

function TableCellOverlays({
  page,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
}: {
  page: PageResult;
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}) {
  const cells = page.tables.flatMap((table, tableIndex) =>
    table.cells.map((cell) => ({
      cell,
      region: cellRegionFor(table, cell, page.page.page_number),
      table,
      tableIndex,
    })),
  );
  const hoveredCell = cells.find(({ cell }) => cell.cell_id === hoveredId);

  return (
    <>
      {page.tables.map((table, tableIndex) => {
        const region = table.bounding_regions.find(
          (candidate) => candidate.page_number === page.page.page_number,
        );
        if (!region) return null;
        const active = table.cells.some(
          (cell) => cell.cell_id === hoveredId || cell.cell_id === selectedId,
        );
        return (
          <div
            className={"table-region-outline " + (active ? "is-active" : "")}
            key={"outline-" + table.table_id}
            style={boundsFor(region, page)}
          >
            <span>Table {tableIndex + 1} · {table.row_count} × {table.column_count}</span>
          </div>
        );
      })}
      {cells.map(({ cell, region, tableIndex }) => {
        if (!region) return null;
        const hovered = hoveredId === cell.cell_id;
        const selected = selectedId === cell.cell_id;
        return (
          <button
            aria-describedby={hovered ? cellTooltipIdFor(cell, page) : undefined}
            aria-label={`Inspect Table ${tableIndex + 1}, row ${cell.row_index + 1}, column ${cell.column_index + 1}`}
            className={"table-cell-overlay " + (selected ? "is-selected " : "") + (hovered ? "is-hovered" : "")}
            key={cell.cell_id}
            onClick={() => onSelect(cell.cell_id)}
            onFocus={() => onHover(cell.cell_id)}
            onBlur={() => onHover(null)}
            onMouseEnter={() => onHover(cell.cell_id)}
            onMouseLeave={() => onHover(null)}
            style={{ clipPath: "polygon(" + polygonFor(region, page) + ")" }}
          >
            <span>Table {tableIndex + 1}, row {cell.row_index + 1}, column {cell.column_index + 1}</span>
          </button>
        );
      })}
      {hoveredCell?.region ? (
        <TableCellTooltip
          cell={hoveredCell.cell}
          page={page}
          region={hoveredCell.region}
          tableIndex={hoveredCell.tableIndex}
        />
      ) : null}
    </>
  );
}
function DemoPage({
  page,
  selectedId,
  hoveredId,
  overlays,
  onSelect,
  onHover,
}: {
  page: PageResult;
  selectedId: string | null;
  hoveredId: string | null;
  overlays: boolean;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}) {
  const hoveredBlock = page.blocks.find((block) => block.block_id === hoveredId);
  const hoveredRegion = hoveredBlock ? regionFor(hoveredBlock, page.page.page_number) : undefined;

  return (
    <div className="demo-sheet" aria-label={"Demo document page " + page.page.page_number}>
      <div className="demo-brand-line">
        <span className="demo-brand-mark">YC</span>
        <span>Youth Care Services</span>
        <span className="demo-confidential">CONFIDENTIAL</span>
      </div>
      <div className="demo-rule" />
      {page.blocks.map((block) => {
        const region = regionFor(block, page.page.page_number);
        if (!region) return null;
        const bounds = boundsFor(region, page);
        return (
          <div
            className={"demo-source-text " + (block.role === "title" ? "demo-title" : "")}
            dir="auto"
            key={"text-" + block.block_id}
            style={bounds}
          >
            {block.source_text}
          </div>
        );
      })}
      {page.tables.map((table) => {
        const region = table.bounding_regions.find(
          (candidate) => candidate.page_number === page.page.page_number,
        );
        if (!region) return null;
        const bounds = boundsFor(region, page);
        return (
          <div
            aria-label={`Source table ${table.row_count} by ${table.column_count}`}
            className="demo-source-table"
            key={table.table_id}
            role="table"
            style={{
              ...bounds,
              gridTemplateColumns: `repeat(${table.column_count}, minmax(0, 1fr))`,
              gridTemplateRows: `repeat(${table.row_count}, minmax(0, 1fr))`,
            }}
          >
            {table.cells.map((cell) => (
              <div
                className={"demo-source-table-cell " + (cell.kind === "columnHeader" ? "is-header" : "")}
                dir="auto"
                key={cell.cell_id}
                role={cell.kind === "columnHeader" ? "columnheader" : "cell"}
                style={{
                  gridColumn: `${cell.column_index + 1} / span ${cell.column_span}`,
                  gridRow: `${cell.row_index + 1} / span ${cell.row_span}`,
                }}
              >
                {cell.content}
              </div>
            ))}
          </div>
        );
      })}
      <div className="demo-footer">
        <span>Secure multilingual intake</span>
        <span>{page.page.page_number} / {page.page.page_count}</span>
      </div>
      {overlays
        ? page.blocks.map((block) => {
            const region = regionFor(block, page.page.page_number);
            if (!region) return null;
            const selected = selectedId === block.block_id;
            const hovered = hoveredId === block.block_id;
            return (
              <button
                aria-describedby={hovered ? tooltipIdFor(block, page) : undefined}
                aria-label={"Select extracted region " + block.reading_order}
                className={"region-overlay " + (selected ? "is-selected " : "") + (hovered ? "is-hovered" : "")}
                key={block.block_id}
                onClick={() => onSelect(block.block_id)}
                onFocus={() => onHover(block.block_id)}
                onBlur={() => onHover(null)}
                onMouseEnter={() => onHover(block.block_id)}
                onMouseLeave={() => onHover(null)}
                style={{ clipPath: "polygon(" + polygonFor(region, page) + ")" }}
              >
                <span>{block.reading_order}</span>
              </button>
            );
          })
        : null}
      {overlays && hoveredBlock && hoveredRegion ? (
        <RegionTooltip block={hoveredBlock} page={page} region={hoveredRegion} />
      ) : null}
      {overlays ? (
        <TableCellOverlays
          hoveredId={hoveredId}
          onHover={onHover}
          onSelect={onSelect}
          page={page}
          selectedId={selectedId}
        />
      ) : null}
    </div>
  );
}

function OverlayLayer({
  page,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
}: {
  page: PageResult;
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}) {
  const hoveredBlock = page.blocks.find((block) => block.block_id === hoveredId);
  const hoveredRegion = hoveredBlock ? regionFor(hoveredBlock, page.page.page_number) : undefined;

  return (
    <div className="overlay-layer">
      {page.blocks.map((block) => {
        const region = regionFor(block, page.page.page_number);
        if (!region) return null;
        return (
          <button
            aria-describedby={hoveredId === block.block_id ? tooltipIdFor(block, page) : undefined}
            aria-label={"Select extracted region " + block.reading_order}
            className={
              "region-overlay " +
              (selectedId === block.block_id ? "is-selected " : "") +
              (hoveredId === block.block_id ? "is-hovered" : "")
            }
            key={block.block_id}
            onClick={() => onSelect(block.block_id)}
            onFocus={() => onHover(block.block_id)}
            onBlur={() => onHover(null)}
            onMouseEnter={() => onHover(block.block_id)}
            onMouseLeave={() => onHover(null)}
            style={{ clipPath: "polygon(" + polygonFor(region, page) + ")" }}
          >
            <span>{block.reading_order}</span>
          </button>
        );
      })}
      {hoveredBlock && hoveredRegion ? (
        <RegionTooltip block={hoveredBlock} page={page} region={hoveredRegion} />
      ) : null}
      <TableCellOverlays
        hoveredId={hoveredId}
        onHover={onHover}
        onSelect={onSelect}
        page={page}
        selectedId={selectedId}
      />
    </div>
  );
}

function DocumentListPanel({
  open,
  items,
  loading,
  error,
  currentDocumentId,
  backendConnected,
  deletingDocumentId,
  onClose,
  onOpen,
  onDelete,
}: {
  open: boolean;
  items: DocumentSummary[];
  loading: boolean;
  error: string | null;
  currentDocumentId: string | null;
  backendConnected: boolean;
  deletingDocumentId: string | null;
  onClose: () => void;
  onOpen: (documentId: string) => void;
  onDelete: (item: DocumentSummary) => void;
}) {
  if (!open) return null;

  return (
    <div className="doc-panel-overlay" onClick={onClose}>
      <aside
        aria-label="Recent documents"
        className="doc-panel"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="doc-panel-heading">
          <h2>Recent documents</h2>
          <button aria-label="Close recent documents" onClick={onClose} type="button">
            <Icon name="close" />
          </button>
        </div>
        {!backendConnected ? (
          <p className="doc-panel-status is-error">Backend not connected</p>
        ) : null}
        {backendConnected && loading ? <p className="doc-panel-status">Loading…</p> : null}
        {backendConnected && error ? <p className="doc-panel-status is-error">{error}</p> : null}
        {backendConnected && !loading && !error && !items.length ? (
          <p className="doc-panel-status">No documents uploaded yet.</p>
        ) : null}
        <ul className="doc-panel-list">
          {items.map((item) => (
            <li className={item.id === currentDocumentId ? "is-current" : ""} key={item.id}>
              <button
                className="doc-panel-row"
                onClick={() => onOpen(item.id)}
                type="button"
              >
                <span className="doc-panel-name">{item.original_filename}</span>
                <span className={"status-badge status-" + item.status}>
                  <span className="status-dot" />
                  {statusLabels[item.status] ?? item.status}
                </span>
                <span className="doc-panel-date">{new Date(item.updated_at).toLocaleString()}</span>
              </button>
              <button
                aria-label={"Delete " + item.original_filename}
                className="doc-panel-delete"
                // handleDeleteDocument's guard is global (one delete in flight blocks
                // all), so every row's button must reflect that - not just the one
                // being deleted, or the others look clickable but silently no-op.
                disabled={Boolean(deletingDocumentId)}
                onClick={() => onDelete(item)}
                type="button"
              >
                <Icon name="trash" />
              </button>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

export function DocumentStudio() {
  const [document, setDocument] = useState<DocumentDetail>(demoDocument);
  const [pages, setPages] = useState<PageResult[]>(demoPages);
  const [pageSummaries, setPageSummaries] = useState<PageSummary[]>([]);
  const [financialResult, setFinancialResult] = useState<FinancialResult | null>(null);
  const [financialReviews, setFinancialReviews] = useState<FinancialReviewRecord[]>([]);
  const [financialCorrections, setFinancialCorrections] = useState<Record<string, string>>({});
  const [financialCorrectionCurrencies, setFinancialCorrectionCurrencies] = useState<
    Record<string, string>
  >({});
  const [financialStructureDecisions, setFinancialStructureDecisions] = useState<
    Record<string, "accepted" | "rejected">
  >({});
  const [financialReviewNote, setFinancialReviewNote] = useState("");
  const [financialReviewSubmitting, setFinancialReviewSubmitting] = useState(false);
  const [translationReviews, setTranslationReviews] = useState<TranslationReviewRecord[]>([]);
  const [translationCorrections, setTranslationCorrections] = useState<Record<string, string>>({});
  const [translationReviewNote, setTranslationReviewNote] = useState("");
  const [translationReviewSubmitting, setTranslationReviewSubmitting] = useState(false);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const [downloadingArtifact, setDownloadingArtifact] = useState<string | null>(null);
  const [session, setSession] = useState<SessionStatus | null>(null);
  const { error, errorRetry, sessionError, setActionError, reportApiError, clearSessionError } =
    useActionError(setSession);
  const [pageView, setPageView] = useState<PageView>("financial");
  const [contentLanguageView, setContentLanguageView] =
    useState<ContentLanguageView>("source");
  const [pageCache, setPageCache] = useState<Record<number, PageResult>>({});
  const [pageLoadError, setPageLoadError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [activeTab, setActiveTab] = useState<InspectorTab>("financial");
  const [selectedId, setSelectedId] = useState<string | null>(demoPages[0].blocks[0].block_id);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(0.82);
  const [rotation, setRotation] = useState(0);
  const [overlays, setOverlays] = useState(true);
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [sourceViewport, setSourceViewport] = useState<{ width: number; height: number } | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sourceBlobUrl, setSourceBlobUrl] = useState<string | null>(null);
  const [isDocumentListOpen, setIsDocumentListOpen] = useState(false);
  const [documentList, setDocumentList] = useState<DocumentSummary[]>([]);
  const [documentListLoading, setDocumentListLoading] = useState(false);
  const [documentListError, setDocumentListError] = useState<string | null>(null);
  const [inspectorWidth, setInspectorWidth] = useState<number | null>(null);
  const [isResizingPanels, setIsResizingPanels] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const inspectorContentRef = useRef<HTMLDivElement>(null);
  const studioBodyRef = useRef<HTMLDivElement>(null);
  const hoverScrollFrameRef = useRef<number | null>(null);
  const activeRunRef = useRef<AbortController | null>(null);

  const measuredInspectorWidth = useCallback(() => {
    if (inspectorWidth !== null) return inspectorWidth;
    const panel = studioBodyRef.current?.querySelector<HTMLElement>(".inspector-panel");
    return panel?.getBoundingClientRect().width ?? 460;
  }, [inspectorWidth]);

  const MIN_INSPECTOR_WIDTH = 340;
  const MIN_MAIN_WIDTH = 360;

  const handleResizerPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const container = studioBodyRef.current;
      if (!container) return;
      event.preventDefault();
      const containerWidth = container.getBoundingClientRect().width;
      const startX = event.clientX;
      const startWidth = measuredInspectorWidth();
      const handle = event.currentTarget;
      const pointerId = event.pointerId;
      handle.setPointerCapture(pointerId);
      setIsResizingPanels(true);

      const endResize = () => {
        setIsResizingPanels(false);
        window.removeEventListener("pointermove", handleMove);
        window.removeEventListener("pointerup", endResize);
        window.removeEventListener("pointercancel", endResize);
        try {
          if (handle.hasPointerCapture(pointerId)) {
            handle.releasePointerCapture(pointerId);
          }
        } catch {
          // Capture may already be released by the browser.
        }
      };
      const handleMove = (moveEvent: PointerEvent) => {
        const delta = startX - moveEvent.clientX;
        const next = Math.min(
          containerWidth - MIN_MAIN_WIDTH,
          Math.max(MIN_INSPECTOR_WIDTH, startWidth + delta),
        );
        setInspectorWidth(next);
      };
      window.addEventListener("pointermove", handleMove);
      window.addEventListener("pointerup", endResize);
      window.addEventListener("pointercancel", endResize);
    },
    [measuredInspectorWidth],
  );

  const handleResizerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const container = studioBodyRef.current;
      if (!container) return;
      const step = 32;
      const containerWidth = container.getBoundingClientRect().width;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setInspectorWidth(
          Math.min(containerWidth - MIN_MAIN_WIDTH, measuredInspectorWidth() + step),
        );
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setInspectorWidth(Math.max(MIN_INSPECTOR_WIDTH, measuredInspectorWidth() - step));
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setInspectorWidth(null);
      }
    },
    [measuredInspectorWidth],
  );

  useEffect(() => {
    const onResize = () => {
      setInspectorWidth((previous) => {
        if (previous === null) return previous;
        const container = studioBodyRef.current;
        if (!container) return previous;
        const max = container.getBoundingClientRect().width - MIN_MAIN_WIDTH;
        if (max < MIN_INSPECTOR_WIDTH) return previous;
        return Math.min(max, Math.max(MIN_INSPECTOR_WIDTH, previous));
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    return () => {
      activeRunRef.current?.abort();
    };
  }, []);

  // Last-resort net for a promise rejection that slipped past every try/catch in this
  // file - guarantees it's never silently swallowed. Intentionally log-only, not a UI
  // banner: for an error class that by definition wasn't anticipated, a banner here
  // risks contradicting or duplicating whatever state-specific error the app already
  // knows how to show.
  useEffect(() => {
    function onUnhandledRejection(event: PromiseRejectionEvent) {
      console.error("Unhandled promise rejection:", event.reason);
    }
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => window.removeEventListener("unhandledrejection", onUnhandledRejection);
  }, []);

  // Pre-flight check: without this, a document only reveals that translation isn't
  // configured after a full upload + extraction cycle. Best-effort - upload still works
  // if this fails or is slow, it's just an early heads-up.
  useEffect(() => {
    if (!API_BASE) return;
    const controller = new AbortController();
    checkHealth({ signal: controller.signal })
      .then((result) => setHealth(result))
      .catch(() => undefined);
    checkSession({ signal: controller.signal })
      .then((result) => setSession(result))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  // Resume a document from ?documentId= after refresh or shared links.
  useEffect(() => {
    if (!API_BASE || typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const resumeId = params.get("documentId")?.trim();
    if (!resumeId || resumeId === demoDocument.id) return;
    void openDocument(resumeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot deep link on mount
  }, []);

  // PDF/image previews cannot set Authorization headers. Fetch once with auth and use
  // an object URL for pdf.js / <img>.
  useEffect(() => {
    if (document.demo || !API_BASE || !document.id) {
      return;
    }
    let revoked = false;
    let objectUrl: string | null = null;
    const controller = new AbortController();
    fetchSourceBlobUrl(document.id, { signal: controller.signal })
      .then((url) => {
        if (revoked) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setSourceBlobUrl(url);
      })
      .catch(() => {
        if (!revoked) setSourceBlobUrl(null);
      });
    return () => {
      revoked = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setSourceBlobUrl(null);
    };
  }, [document.demo, document.id]);

  const page = document.demo
    ? pages.find((item) => item.page.page_number === currentPage) ?? pages[0]
    : pageCache[currentPage];
  const pageCount = document.page_count ?? (document.demo ? pages.length : pageSummaries.length);
  const realSource = !document.demo && API_BASE ? sourceBlobUrl : null;
  const canPreviewPdf = Boolean(realSource && isPdfContentType(document.content_type));
  const canPreviewImage = Boolean(realSource && isImageContentType(document.content_type));
  const canPreviewSource = canPreviewPdf || canPreviewImage;
  const viewerPageCount = pageCount || (canPreviewSource ? 1 : 0);
  const pageUnit = page?.page.unit ?? "inch";
  const canvasWidth = page
    ? dimensionToCssPixels(page.page.width, pageUnit, zoom)
    : sourceViewport?.width ?? dimensionToCssPixels(8.5, "inch", zoom);
  const canvasHeight = page
    ? dimensionToCssPixels(page.page.height, pageUnit, zoom)
    : sourceViewport?.height ?? dimensionToCssPixels(11, "inch", zoom);

  const diConfigured = Boolean(health?.azure_configured.document_intelligence);
  const openaiConfigured = Boolean(
    health?.azure_configured.openai && (health.openai_deployment_configured ?? true),
  );

  const handleSourceReady = useCallback((width: number, height: number) => {
    setSourceViewport({ width, height });
  }, []);

  const standaloneBlocks = useMemo(
    () => (page ? standaloneBlocksForPage(page) : []),
    [page],
  );
  const pageContent = useMemo(
    () => (page ? orderedPageContent(page, standaloneBlocks) : []),
    [page, standaloneBlocks],
  );
  const displayPage = useMemo(
    () => (page ? { ...page, blocks: standaloneBlocks } : undefined),
    [page, standaloneBlocks],
  );
  const selectedBlock = useMemo(
    () => standaloneBlocks.find((block) => block.block_id === selectedId) ?? null,
    [standaloneBlocks, selectedId],
  );
  const selectedCell = useMemo(() => findSelectedCell(page, selectedId), [page, selectedId]);

  // Unified shape for the thumbnail rail. Demo pages are fully preloaded (only 3
  // pages); real documents use page_count for slots and summaries for dimensions so
  // the rail can grow as page-range extraction completes.
  const railItems: RailItem[] = useMemo(() => {
    if (document.demo) {
      return pages.map((item) => ({
        pageNumber: item.page.page_number,
        width: item.page.width,
        height: item.page.height,
        unit: item.page.unit,
        reviewRequired: item.warnings.length > 0,
        ready: true,
        // The bundled multilingual demo is not a financial document. Keep its
        // classification unset so the UI never presents synthetic care-form
        // tables as financially classified data.
        financialSelected: false,
        financialDisposition: null,
        financialLabel: null,
        financialConfidence: null,
        validationIssueCount: 0,
      }));
    }
    const count = Math.max(document.page_count ?? 0, pageSummaries.length);
    if (!count) return [];
    const byNumber = new Map(pageSummaries.map((item) => [item.page_number, item]));
    return Array.from({ length: count }, (_, index) => {
      const pageNumber = index + 1;
      const summary = byNumber.get(pageNumber);
      return {
        pageNumber,
        width: summary?.width ?? 8.5,
        height: summary?.height ?? 11,
        unit: summary?.unit ?? "inch",
        reviewRequired: summary?.review_required ?? false,
        ready: Boolean(
          summary &&
            (summary.width > 0 || summary.block_count > 0 || summary.table_count > 0),
        ),
        financialSelected: summary?.financial_selected ?? false,
        financialDisposition: summary?.financial_disposition ?? null,
        financialLabel: summary?.financial_label ?? null,
        financialConfidence: summary?.financial_confidence ?? null,
        validationIssueCount: summary?.validation_issue_count ?? 0,
      };
    });
  }, [document.demo, document.page_count, pages, pageSummaries]);
  const hasFinancialClassification = railItems.some(
    (item) => item.financialDisposition != null,
  );
  const visibleRailItems = useMemo(() => {
    if (document.demo || !hasFinancialClassification || pageView === "all") return railItems;
    if (pageView === "review") {
      return railItems.filter((item) => item.reviewRequired);
    }
    return railItems.filter((item) => item.financialDisposition === "financial");
  }, [document.demo, hasFinancialClassification, pageView, railItems]);
  const visiblePageNumbers = useMemo(
    () => visibleRailItems.map((item) => item.pageNumber),
    [visibleRailItems],
  );
  const currentVisibleIndex = visiblePageNumbers.indexOf(currentPage);
  const currentPageSummary = useMemo(
    () => pageSummaries.find((item) => item.page_number === currentPage) ?? null,
    [currentPage, pageSummaries],
  );
  const financialTableById = useMemo(
    () => new Map(financialResult?.tables.map((table) => [table.table_id, table]) ?? []),
    [financialResult],
  );
  const financialContentItems = useMemo<FinancialContentItem[]>(() => {
    if (!financialResult) return [];
    if (financialResult.content_items?.length)
      return financialResult.content_items;
    // Compatibility for stored financial-result-1.1 artifacts. Reprocessing creates
    // the full format-preserving content stream.
    return financialResult.tables.map((table, index) => ({
      item_id: `table:${table.table_id}`,
      item_type: "table",
      reading_order: index + 1,
      source_pages: table.source_pages,
      source_language: "mixed",
      table_id: table.table_id,
      relevance: "uncertain",
      bounding_regions: [],
      review_required: table.review_required,
      warnings: ["Reprocess this document to rebuild surrounding financial text."],
    }));
  }, [financialResult]);
  const financialIssues = financialResult?.validation.issues ?? [];
  const currentFinancialContentItems = useMemo(
    () =>
      financialContentItems.filter((item) => item.source_pages.includes(currentPage)),
    [currentPage, financialContentItems],
  );
  const currentFinancialTableCount = useMemo(
    () =>
      financialResult?.tables.filter((table) =>
        table.source_pages.includes(currentPage),
      ).length ?? 0,
    [currentPage, financialResult],
  );
  const financialCorrectionCells = useMemo(
    () =>
      financialResult?.tables.flatMap((table) =>
        table.cells.filter(
          (cell) =>
            cell.value.requires_normalized_correction ||
            cell.value.requires_currency_correction,
        ),
      ) ?? [],
    [financialResult],
  );
  const flaggedPageNumbers = useMemo(
    () => railItems.filter((item) => item.reviewRequired).map((item) => item.pageNumber),
    [railItems],
  );
  const currentPageReady = document.demo || Boolean(
    currentPageSummary &&
      (currentPageSummary.width > 0 ||
        currentPageSummary.block_count > 0 ||
        currentPageSummary.table_count > 0),
  );

  // Fetch the currently viewed page's full content on demand. The thumbnail rail and
  // the source PDF preview never depend on this - only the inspector/overlay panels do
  // - so navigating a 70-page document stays instant even while this is in flight.
  useEffect(() => {
    if (document.demo || !document.id || pageCache[currentPage]) return;
    if (!currentPageReady) return;
    const controller = new AbortController();
    const documentId = document.id;
    const pageNumber = currentPage;
    getPage(documentId, pageNumber, { signal: controller.signal })
      .then((loaded) => {
        setPageCache((previous) => ({ ...previous, [pageNumber]: loaded }));
        setSelectedId((previous) => {
          const ids = new Set([
            ...standaloneBlocksForPage(loaded).map((block) => block.block_id),
            ...loaded.tables.flatMap((table) => table.cells.map((cell) => cell.cell_id)),
          ]);
          if (previous && ids.has(previous)) return previous;
          return standaloneBlocksForPage(loaded)[0]?.block_id ?? null;
        });
        setPageLoadError(null);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setPageLoadError(describeError(caught, "This page could not be loaded."));
      });
    return () => controller.abort();
  }, [document.demo, document.id, currentPage, pageCache, currentPageReady]);

  // Quietly prefetch the next page so "Next" feels instant most of the time, without
  // ever eagerly loading the whole document up front. Best-effort: a prefetch failure
  // is silently dropped, since the effect above will retry (and surface a real error)
  // once the user actually navigates there.
  useEffect(() => {
    if (document.demo || !document.id) return;
    const currentIndex = visiblePageNumbers.indexOf(currentPage);
    const nextPageNumber = visiblePageNumbers[currentIndex + 1];
    const nextSummary = pageSummaries.find((item) => item.page_number === nextPageNumber);
    const nextReady = Boolean(
      nextSummary &&
        (nextSummary.width > 0 || nextSummary.block_count > 0 || nextSummary.table_count > 0),
    );
    if (nextPageNumber == null) return;
    if (!nextReady || nextPageNumber > pageCount || pageCache[nextPageNumber]) return;
    const controller = new AbortController();
    getPage(document.id, nextPageNumber, { signal: controller.signal })
      .then((loaded) => {
        setPageCache((previous) => ({ ...previous, [nextPageNumber]: loaded }));
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [
    document.demo,
    document.id,
    currentPage,
    pageCount,
    pageCache,
    pageSummaries,
    visiblePageNumbers,
  ]);

  useEffect(() => {
    if (!selectedId) return;
    window.document.getElementById("result-" + selectedId)?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, [currentPage, selectedId]);

  useEffect(() => {
    if (!hoveredId) return;

    const inspector = inspectorContentRef.current;
    const result = window.document.getElementById("result-" + hoveredId);
    if (!inspector || !result) return;

    if (hoverScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(hoverScrollFrameRef.current);
    }

    hoverScrollFrameRef.current = window.requestAnimationFrame(() => {
      const inspectorBounds = inspector.getBoundingClientRect();
      const resultBounds = result.getBoundingClientRect();
      const safeTop = inspectorBounds.top + 20;
      const safeBottom = inspectorBounds.bottom - 20;

      if (resultBounds.top < safeTop || resultBounds.bottom > safeBottom) {
        const visibleResultHeight = Math.min(resultBounds.height, inspector.clientHeight - 40);
        const centeredOffset = (inspector.clientHeight - visibleResultHeight) / 2;
        const nextScrollTop = inspector.scrollTop + resultBounds.top - inspectorBounds.top - centeredOffset;

        inspector.scrollTo({
          behavior: "smooth",
          top: Math.max(0, nextScrollTop),
        });
      }

      hoverScrollFrameRef.current = null;
    });

    return () => {
      if (hoverScrollFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverScrollFrameRef.current);
        hoverScrollFrameRef.current = null;
      }
    };
  }, [currentPage, hoveredId]);

  const viewIsDefault = Math.abs(zoom - 0.82) < 0.001 && rotation === 0 && overlays;

  function fitViewer(mode: "width" | "page") {
    const viewer = viewerRef.current;
    if (!viewer) return;

    const baseWidth = page
      ? dimensionToCssPixels(page.page.width, page.page.unit, 1)
      : sourceViewport
        ? sourceViewport.width / zoom
        : dimensionToCssPixels(8.5, "inch", 1);
    const baseHeight = page
      ? dimensionToCssPixels(page.page.height, page.page.unit, 1)
      : sourceViewport
        ? sourceViewport.height / zoom
        : dimensionToCssPixels(11, "inch", 1);
    const rotated = rotation % 180 !== 0;
    const visualWidth = rotated ? baseHeight : baseWidth;
    const visualHeight = rotated ? baseWidth : baseHeight;
    const styles = window.getComputedStyle(viewer);
    const availableWidth =
      viewer.clientWidth - parseFloat(styles.paddingLeft) - parseFloat(styles.paddingRight) - 16;
    const availableHeight =
      viewer.clientHeight - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom) - 16;
    const nextZoom = mode === "width"
      ? availableWidth / visualWidth
      : Math.min(availableWidth / visualWidth, availableHeight / visualHeight);

    setZoom(Math.min(1.5, Math.max(0.5, nextZoom)));
  }

  function resetViewer() {
    setZoom(0.82);
    setRotation(0);
    setOverlays(true);
  }

  const selectPage = useCallback((number: number) => {
    setCurrentPage(number);
    setPageLoadError(null);
    if (document.demo) {
      const target = pages.find((item) => item.page.page_number === number);
      setSelectedId(target ? standaloneBlocksForPage(target)[0]?.block_id ?? null : null);
      return;
    }
    const cached = pageCache[number];
    // If not cached, leave selectedId null - the load-effect above resolves it once
    // the page's content arrives, instead of blocking navigation on the fetch.
    setSelectedId(cached ? standaloneBlocksForPage(cached)[0]?.block_id ?? null : null);
  }, [document.demo, pages, pageCache]);

  function jumpToNextFlagged() {
    if (!flaggedPageNumbers.length) return;
    const next = flaggedPageNumbers.find((number) => number > currentPage) ?? flaggedPageNumbers[0];
    selectPage(next);
  }

  const navigateVisible = useCallback((direction: -1 | 1) => {
    if (!visiblePageNumbers.length) return;
    const currentIndex = visiblePageNumbers.indexOf(currentPage);
    const fallbackIndex = direction > 0 ? 0 : visiblePageNumbers.length - 1;
    const nextIndex = currentIndex < 0 ? fallbackIndex : currentIndex + direction;
    const nextPage = visiblePageNumbers[nextIndex];
    if (nextPage != null) selectPage(nextPage);
  }, [currentPage, selectPage, visiblePageNumbers]);

  function resetPageState() {
    setPageSummaries([]);
    setFinancialResult(null);
    setFinancialReviews([]);
    setFinancialCorrections({});
    setFinancialCorrectionCurrencies({});
    setFinancialStructureDecisions({});
    setFinancialReviewNote("");
    setTranslationReviews([]);
    setTranslationCorrections({});
    setTranslationReviewNote("");
    setPageCache({});
    setPageLoadError(null);
    setCurrentPage(1);
    setSelectedId(null);
    setSourceViewport(null);
  }

  async function loadPageSummaries(
    nextDocument: DocumentDetail,
    signal?: AbortSignal,
    options?: { preservePage?: boolean; keepCache?: boolean },
    requestedView: PageView = pageView,
  ) {
    const count = nextDocument.page_count ?? nextDocument.pages_ready ?? 0;
    if (!count) return;
    const summaries = await listPageSummaries(
      nextDocument.id,
      { signal },
      requestedView,
    );
    if (signal?.aborted) return;
    setPageSummaries(summaries);
    setActiveTab("financial");
    if (isTerminal(nextDocument.status)) {
      try {
        const result = await getFinancialResult(nextDocument.id, { signal });
        if (!signal?.aborted) setFinancialResult(result);
      } catch {
        if (!signal?.aborted) setFinancialResult(null);
      }
      try {
        const history = await getFinancialReviews(nextDocument.id, { signal });
        if (!signal?.aborted) setFinancialReviews(history.items);
      } catch {
        if (!signal?.aborted) setFinancialReviews([]);
      }
      try {
        const translationHistory = await getTranslationReviews(nextDocument.id, { signal });
        if (!signal?.aborted) setTranslationReviews(translationHistory.items);
      } catch {
        if (!signal?.aborted) setTranslationReviews([]);
      }
    }
    if (!options?.keepCache) {
      setPageCache({});
    }
    if (!options?.preservePage) {
      const firstPage =
        requestedView === "financial"
          ? summaries.find((item) => item.financial_selected)?.page_number
          : summaries[0]?.page_number;
      setCurrentPage(firstPage ?? 1);
    }
  }

  async function followJob(documentId: string, signal: AbortSignal) {
    const pollMinutes = health?.limits?.job_poll_timeout_minutes ?? 90;
    const pollDeadline = Date.now() + pollMinutes * 60 * 1000;
    let delayMs = 1500;
    let latest = await getDocument(documentId, { signal });
    if (signal.aborted) return;
    setDocument(latest);

    let lastPagesReady = -1;
    let lastBatchesDone = -1;

    const refreshPagesIfNeeded = async (doc: DocumentDetail, force = false) => {
      const ready = doc.pages_ready ?? 0;
      const batchesDone = doc.translation_batches_done ?? -1;
      const readyGrew = ready > lastPagesReady;
      const batchesChanged = batchesDone !== lastBatchesDone;
      const shouldLoad =
        force ||
        readyGrew ||
        batchesChanged ||
        ((doc.page_count ?? 0) > 0 && lastPagesReady < 0);
      if (!shouldLoad) return;
      lastPagesReady = ready;
      lastBatchesDone = batchesDone;
      try {
        await loadPageSummaries(doc, signal, {
          preservePage: true,
          // Keep cached pages while extraction adds thumbnails; refresh when
          // translation batches change so inspector text stays current.
          keepCache: readyGrew && !batchesChanged && !force,
        });
      } catch {
        // Keep polling; page list may still be catching up mid-extract.
      }
    };

    await refreshPagesIfNeeded(latest, true);

    const maxConsecutivePollFailures = 5;
    let consecutivePollFailures = 0;

    while (!isTerminal(latest.status) && Date.now() < pollDeadline) {
      await wait(delayMs, signal);
      try {
        latest = await getDocument(documentId, { signal });
        consecutivePollFailures = 0;
      } catch (pollError) {
        if (signal.aborted) return;
        consecutivePollFailures += 1;
        // A single dropped connection or backend restart mid-poll shouldn't freeze the
        // UI on a stale "still processing" state - keep polling through transient
        // blips, and only surface the failure once it's clearly not transient.
        if (consecutivePollFailures >= maxConsecutivePollFailures) throw pollError;
        continue;
      }
      if (signal.aborted) return;
      setDocument(latest);
      await refreshPagesIfNeeded(latest);
      delayMs = Math.min(Math.round(delayMs * 1.2), 5000);
    }

    if ((latest.page_count ?? 0) > 0 || (latest.pages_ready ?? 0) > 0) {
      await loadPageSummaries(latest, signal, { preservePage: true });
    }
    if (signal.aborted) return;
    if (latest.status === "failed") {
      throw new Error(latest.safe_error_message ?? "Document processing failed.");
    }
    if (latest.status === "cancelled") {
      return;
    }
    if (!isTerminal(latest.status)) {
      setInfo(
        "Processing is still running in the background. Open the document again to continue monitoring progress."
      );
      return;
    }
  }

  async function processFile(file: File) {
    // Also guards drag-and-drop, which isn't covered by the upload button's
    // `disabled={busy}` - without this, dropping a second file mid-upload starts a
    // second poll loop that interleaves state updates with the first.
    if (busy) return;
    setActionError(null);
    setInfo(null);
    const maxUploadBytes =
      (health?.limits?.max_upload_size_mb ?? 150) * 1024 * 1024;
    const validationError = validateUploadFile(file, maxUploadBytes);
    if (validationError) {
      setActionError(validationError);
      return;
    }
    if (!API_BASE) {
      setActionError("Backend not connected. Copy .env.local.example to .env.local and run the Python API before uploading.");
      return;
    }
    activeRunRef.current?.abort();
    const controller = new AbortController();
    activeRunRef.current = controller;
    setBusy(true);
    try {
      const created = await uploadDocument(file, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setDocument({
        id: created.document_id,
        original_filename: file.name,
        content_type: file.type || "",
        status: created.status,
        page_count: null,
        current_stage: "Upload accepted",
        progress_percent: 5,
        safe_error_message: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        processing_profile: created.processing_profile ?? null,
        data_class: created.data_class ?? null,
      });
      resetPageState();
      await followJob(created.document_id, controller.signal);
    } catch (caught) {
      if (controller.signal.aborted) return;
      await reportApiError(caught, "The document could not be processed.", {
        retry: () => void processFile(file),
      });
    } finally {
      if (activeRunRef.current === controller) {
        activeRunRef.current = null;
        setBusy(false);
      }
    }
  }

  async function handleCancel() {
    if (document.demo) {
      activeRunRef.current?.abort();
      activeRunRef.current = null;
      setBusy(false);
      setInfo("Cancelled.");
      setActionError(null);
      return;
    }
    if (!API_BASE || !document.id) {
      setActionError("Backend not connected. Cancel could not be sent to the server.");
      return;
    }
    const documentId = document.id;
    setActionError(null);
    setInfo(null);
    setBusy(true);
    try {
      await cancelDocument(documentId);
      activeRunRef.current?.abort();
      activeRunRef.current = null;
      const latest = await getDocument(documentId);
      setDocument(latest);
      setInfo(latest.safe_error_message ?? "Processing was cancelled. You can retry when ready.");
    } catch (caught) {
      await reportApiError(caught, "Cancel failed.");
      // Keep polling if cancel failed and work is still running.
      if (!isTerminal(document.status) && !activeRunRef.current) {
        const controller = new AbortController();
        activeRunRef.current = controller;
        void followJob(documentId, controller.signal)
          .catch(() => undefined)
          .finally(() => {
            if (activeRunRef.current === controller) {
              activeRunRef.current = null;
              setBusy(false);
            }
          });
        return;
      }
    } finally {
      if (!activeRunRef.current) {
        setBusy(false);
      }
    }
  }

  async function openDocument(documentId: string) {
    if (busy) return;
    setIsDocumentListOpen(false);
    setActionError(null);
    activeRunRef.current?.abort();
    const controller = new AbortController();
    activeRunRef.current = controller;
    setBusy(true);
    try {
      const detail = await getDocument(documentId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setDocument(detail);
      if (typeof window !== "undefined") {
        const url = new URL(window.location.href);
        url.searchParams.set("documentId", documentId);
        window.history.replaceState({}, "", url.toString());
      }
      resetPageState();
      if (!isTerminal(detail.status)) {
        await followJob(documentId, controller.signal);
      } else if ((detail.page_count ?? 0) > 0) {
        await loadPageSummaries(detail, controller.signal);
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
      await reportApiError(caught, "The document could not be opened.");
    } finally {
      if (activeRunRef.current === controller) {
        activeRunRef.current = null;
        setBusy(false);
      }
    }
  }

  async function openDocumentListPanel() {
    setIsDocumentListOpen(true);
    if (!API_BASE) {
      setDocumentList([]);
      setDocumentListError(null);
      setDocumentListLoading(false);
      return;
    }
    setDocumentListLoading(true);
    setDocumentListError(null);
    try {
      const response = await listDocuments(1, 50);
      setDocumentList(response.items);
    } catch (caught) {
      setDocumentListError(describeError(caught, "Documents could not be loaded."));
    } finally {
      setDocumentListLoading(false);
    }
  }

  async function handleDeleteDocument(item: DocumentSummary) {
    if (deletingDocumentId) return;
    if (!window.confirm(`Delete "${item.original_filename}"? This cannot be undone.`)) return;
    setDeletingDocumentId(item.id);
    // A stale error/Retry banner from an earlier action could otherwise point at the
    // document we're about to delete.
    setActionError(null);
    try {
      await deleteDocument(item.id);
      setDocumentList((items) => items.filter((candidate) => candidate.id !== item.id));
      if (document.id === item.id) {
        activeRunRef.current?.abort();
        // Falling back to the demo document must clear every piece of the deleted
        // document's state, not just the page-viewer bits - otherwise its financial
        // extraction/review data keeps rendering on top of the demo doc.
        resetPageState();
        setDocument(demoDocument);
        setPages(demoPages);
        setSelectedId(demoPages[0].blocks[0].block_id);
      }
    } catch (caught) {
      setDocumentListError(describeError(caught, "The document could not be deleted."));
    } finally {
      setDeletingDocumentId(null);
    }
  }

  function handleFileInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void processFile(file);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    if (busy) return;
    const file = event.dataTransfer.files?.[0];
    if (file) void processFile(file);
  }

  async function handleRetry() {
    if (document.demo || busy) return;
    activeRunRef.current?.abort();
    const controller = new AbortController();
    activeRunRef.current = controller;
    setBusy(true);
    setActionError(null);
    try {
      await retryDocument(document.id, "resume", { signal: controller.signal });
      if (controller.signal.aborted) return;
      setPageSummaries([]);
      setPageCache({});
      setPageLoadError(null);
      await followJob(document.id, controller.signal);
    } catch (caught) {
      if (controller.signal.aborted) return;
      await reportApiError(caught, "Retry failed.", { retry: () => void handleRetry() });
    } finally {
      if (activeRunRef.current === controller) {
        activeRunRef.current = null;
        setBusy(false);
      }
    }
  }

  async function handleDownload(
    artifact: "reviewed-bilingual" | "financial" | "financial-xlsx",
  ) {
    if (downloadingArtifact) return;
    setActionError(null);
    if (document.demo) {
      const payload =
        artifact === "financial"
          ? financialResult ?? { document_id: document.id, tables: [] }
          : { ...document, pages };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = "demo-" + artifact + ".json";
      link.click();
      URL.revokeObjectURL(url);
      return;
    }
    setDownloadingArtifact(artifact);
    try {
      await downloadArtifact(document.id, artifact, currentPage);
    } catch (caught) {
      await reportApiError(caught, "Download failed.", {
        retry: () => void handleDownload(artifact),
      });
    } finally {
      setDownloadingArtifact(null);
    }
  }

  async function handleFinancialReview(decision: "approved" | "rejected") {
    if (document.demo || !financialResult || financialReviewSubmitting) return;
    const corrections = financialCorrectionCells
      .map((cell) => ({
        cell_id: cell.cell_id,
        normalized_value: financialCorrections[cell.cell_id]?.trim() || null,
        currency:
          financialCorrectionCurrencies[cell.cell_id]?.trim() ||
          cell.value.currency ||
          null,
        reason: "Reviewer-entered normalized correction",
      }))
      .filter(
        (correction) =>
          correction.normalized_value != null || correction.currency != null,
      );
    const unresolvedCells = financialCorrectionCells.filter(
      (cell) =>
        (cell.value.requires_normalized_correction &&
          !financialCorrections[cell.cell_id]?.trim()) ||
        (cell.value.requires_currency_correction &&
          !financialCorrectionCurrencies[cell.cell_id]?.trim()),
    );
    const structureDecisions = financialResult.reconciliation_candidate_ids.flatMap(
      (candidateId) => {
        const structureDecision = financialStructureDecisions[candidateId];
        return structureDecision
          ? [
              {
                candidate_id: candidateId,
                decision: structureDecision,
                reason: "Reviewer decision recorded in the financial workspace",
              },
            ]
          : [];
      },
    );
    const unresolvedStructures = financialResult.reconciliation_candidate_ids.filter(
      (candidateId) => financialStructureDecisions[candidateId] !== "accepted",
    );
    if (decision === "approved" && unresolvedCells.length) {
      setActionError("Resolve every required monetary amount and currency before approval.");
      return;
    }
    if (decision === "approved" && unresolvedStructures.length) {
      setActionError("Accept every reconstructed table structure before approval.");
      return;
    }
    setFinancialReviewSubmitting(true);
    setActionError(null);
    try {
      const persisted = await createFinancialReview(document.id, {
        decision,
        note: financialReviewNote.trim() || null,
        corrections,
        structure_decisions: structureDecisions,
      });
      setFinancialReviews((current) => [persisted, ...current]);
      setDocument((current) => ({
        ...current,
        ...(decision === "rejected"
          ? { status: "needs_review" as const, current_stage: "needs_review" }
          : {}),
        financial_review_status: decision,
        financial_reviewed_by: persisted.reviewer_subject,
        financial_reviewed_at: persisted.created_at,
      }));
      setInfo(
        decision === "approved"
          ? "Financial result approved and audit record saved."
          : "Financial result rejected and audit record saved.",
      );
    } catch (caught) {
      await reportApiError(caught, "Financial review could not be saved.");
    } finally {
      setFinancialReviewSubmitting(false);
    }
  }

  async function handleTranslationReview(decision: "approved" | "rejected") {
    if (document.demo || translationReviewSubmitting) return;
    setTranslationReviewSubmitting(true);
    setActionError(null);
    try {
      let corrections = Object.entries(translationCorrections)
        .filter(([, text]) => text.trim())
        .map(([key, text]) => {
          const [kind, ...idParts] = key.split(":");
          const targetId = idParts.join(":");
          return {
            target_kind: (kind === "cell" ? "cell" : "block") as "block" | "cell",
            target_id: targetId,
            page_number: currentPage,
            corrected_translated_text: text.trim(),
            reason: "Reviewer correction from translation workspace",
          };
        });

      if (decision === "approved") {
        const bilingual = await getBilingualDocument(document.id);
        const required: Array<{
          target_kind: "block" | "cell";
          target_id: string;
          page_number: number;
          defaultText: string;
        }> = [];
        const blocks = Array.isArray(bilingual.blocks) ? bilingual.blocks : [];
        for (const block of blocks) {
          if (!block || typeof block !== "object") continue;
          const item = block as Record<string, unknown>;
          if (!item.review_required || typeof item.block_id !== "string") continue;
          const regions = Array.isArray(item.bounding_regions) ? item.bounding_regions : [];
          const pageNumber =
            regions[0] &&
            typeof regions[0] === "object" &&
            typeof (regions[0] as { page_number?: unknown }).page_number === "number"
              ? ((regions[0] as { page_number: number }).page_number)
              : 1;
          required.push({
            target_kind: "block",
            target_id: item.block_id,
            page_number: pageNumber,
            defaultText: typeof item.translated_text === "string" ? item.translated_text : "",
          });
        }
        const tables = Array.isArray(bilingual.tables) ? bilingual.tables : [];
        for (const table of tables) {
          if (!table || typeof table !== "object") continue;
          const cells = Array.isArray((table as { cells?: unknown }).cells)
            ? ((table as { cells: unknown[] }).cells)
            : [];
          for (const cell of cells) {
            if (!cell || typeof cell !== "object") continue;
            const item = cell as Record<string, unknown>;
            if (!item.review_required || typeof item.cell_id !== "string") continue;
            const regions = Array.isArray(item.bounding_regions) ? item.bounding_regions : [];
            const pageNumber =
              regions[0] &&
              typeof regions[0] === "object" &&
              typeof (regions[0] as { page_number?: unknown }).page_number === "number"
                ? ((regions[0] as { page_number: number }).page_number)
                : 1;
            required.push({
              target_kind: "cell",
              target_id: item.cell_id,
              page_number: pageNumber,
              defaultText:
                typeof item.translated_content === "string" ? item.translated_content : "",
            });
          }
        }
        const byKey = new Map(
          corrections.map((item) => [`${item.target_kind}:${item.target_id}`, item]),
        );
        for (const target of required) {
          const key = `${target.target_kind}:${target.target_id}`;
          if (!byKey.has(key)) {
            byKey.set(key, {
              target_kind: target.target_kind,
              target_id: target.target_id,
              page_number: target.page_number,
              corrected_translated_text:
                translationCorrections[key]?.trim() || target.defaultText,
              reason: "Reviewer confirmed machine translation",
            });
          }
        }
        corrections = Array.from(byKey.values()).filter(
          (item) => item.corrected_translated_text.trim().length >= 0,
        );
        const stillMissing = required.filter((target) => {
          const entry = byKey.get(`${target.target_kind}:${target.target_id}`);
          return !entry;
        });
        if (stillMissing.length) {
          setActionError("Resolve every review-flagged translation before approval.");
          return;
        }
      }

      const persisted = await createTranslationReview(document.id, {
        decision,
        note: translationReviewNote.trim() || null,
        corrections,
      });
      setTranslationReviews((current) => [persisted, ...current]);
      setDocument((current) => ({
        ...current,
        ...(decision === "rejected"
          ? { status: "needs_review" as const, current_stage: "needs_review" }
          : { status: "completed" as const, current_stage: "completed" }),
        document_review_status: decision === "approved" ? "approved" : "rejected",
        translation_review_status: decision,
        translation_reviewed_by: persisted.reviewer_subject,
        translation_reviewed_at: persisted.created_at,
      }));
      setInfo(
        decision === "approved"
          ? "Translation approved. Reviewed bilingual export is now available."
          : "Translation rejected and audit record saved.",
      );
    } catch (caught) {
      await reportApiError(caught, "Translation review could not be saved.");
    } finally {
      setTranslationReviewSubmitting(false);
    }
  }

  async function handleCopyPageJson() {
    if (!page) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(page, null, 2));
    } catch {
      setActionError("Clipboard copy failed. Check browser permissions and try again.");
    }
  }

  const sourceLanguages = page
    ? Array.from(new Set([
        ...standaloneBlocks.map((block) => displayLanguage(block.source_language)),
        ...page.tables.flatMap((table) =>
          table.cells.map((cell) => displayLanguage(cell.source_language)),
        ),
      ]))
    : [];

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && /^(input|textarea|select)$/i.test(target.tagName)) return;
      if (event.key === "ArrowRight") {
        navigateVisible(1);
      } else if (event.key === "ArrowLeft") {
        navigateVisible(-1);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [navigateVisible]);

  return (
    <main
      aria-label="Care intelligence workspace"
      className="studio-shell"
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
    >
      <input
        accept="application/pdf,image/png,image/jpeg,image/tiff,image/bmp"
        className="visually-hidden"
        onChange={handleFileInput}
        ref={inputRef}
        type="file"
      />

      <header className="global-header">
        <div className="product-lockup">
          <span className="product-mark" aria-hidden="true">
            <span className="product-mark-letter">C</span>
            <span className="product-mark-spark" />
          </span>
          <div className="file-summary">
            <div className="filename-row">
              <h1 title={document.original_filename}>{document.original_filename}</h1>
              <StatusBadge document={document} />
            </div>
            <p className="document-meta">
              <span>{document.demo ? "Interactive demo" : document.current_stage}</span>
              <i aria-hidden="true" />
              <span>{document.demo ? "Multilingual source" : "Source document"}</span>
              <i aria-hidden="true" />
              <span>{pageCount || "—"} pages</span>
              <i aria-hidden="true" />
              <span>English output</span>
              {document.processing_profile ? (
                <>
                  <i aria-hidden="true" />
                  <span>{document.processing_profile}</span>
                </>
              ) : null}
              {document.data_class ? (
                <>
                  <i aria-hidden="true" />
                  <span>{document.data_class}</span>
                </>
              ) : null}
            </p>
          </div>
        </div>
        <div className="service-pills" aria-label="Service configuration">
          <span className="service-node">
            <span className="service-monogram" aria-hidden="true">DI</span>
            <span className="service-copy"><small>Extract &amp; structure</small><strong>Document Intelligence</strong></span>
            <i
              className={diConfigured ? "service-online" : "service-offline"}
              aria-label={diConfigured ? "Configured" : "Not configured"}
            />
          </span>
          <span className="service-connector" aria-hidden="true"><i /></span>
          <span className="service-node">
            <span className="service-monogram" aria-hidden="true">AI</span>
            <span className="service-copy"><small>Translate to English</small><strong>Azure OpenAI</strong></span>
            <i
              className={openaiConfigured ? "service-online" : "service-offline"}
              aria-label={
                openaiConfigured ? "Configured" : health ? "Not configured" : "Not checked"
              }
            />
          </span>
        </div>
        <div className="header-actions">
          {!document.demo &&
          document.financial_review_status !== "approved" &&
          (document.status === "failed" ||
            document.status === "needs_review" ||
            document.status === "cancelled") ? (
            <button className="secondary-button" disabled={busy} onClick={() => void handleRetry()}><Icon name="refresh" /> Retry</button>
          ) : null}
          <button className="secondary-button" disabled={!financialResult || !!downloadingArtifact} onClick={() => void handleDownload("financial")}><Icon name="download" /> Financial JSON</button>
          <button className="secondary-button" disabled={!financialResult || !!downloadingArtifact} onClick={() => void handleDownload("financial-xlsx")}><Icon name="download" /> XLSX</button>
          <button
            className="secondary-button export-button"
            disabled={document.demo || document.document_review_status !== "approved" || !!downloadingArtifact}
            onClick={() => void handleDownload("reviewed-bilingual")}
          >
            <Icon name="download" /> Approved bilingual
          </button>
          <button className="secondary-button" onClick={() => void openDocumentListPanel()}>
            <Icon name="folder" /> Recent
          </button>
          {!document.demo && !isTerminal(document.status) ? (
            <button className="secondary-button" disabled={busy} onClick={() => void handleCancel()}><Icon name="close" /> Cancel</button>
          ) : null}
          <button className="primary-button" disabled={busy} onClick={() => inputRef.current?.click()}>
            <span className="button-icon" aria-hidden="true"><Icon name="plus" /></span> Upload document
          </button>
        </div>
      </header>

      <DocumentListPanel
        backendConnected={Boolean(API_BASE)}
        currentDocumentId={document.demo ? null : document.id}
        deletingDocumentId={deletingDocumentId}
        error={documentListError}
        items={documentList}
        loading={documentListLoading}
        onClose={() => setIsDocumentListOpen(false)}
        onDelete={(item) => void handleDeleteDocument(item)}
        onOpen={(documentId) => void openDocument(documentId)}
        open={isDocumentListOpen}
      />

      <div
        className="studio-body"
        ref={studioBodyRef}
        style={inspectorWidth !== null ? { gridTemplateColumns: `minmax(0, 1fr) 6px ${inspectorWidth}px` } : undefined}
      >
      <div className="studio-main-column">
      {!document.demo && health && (!health.azure_configured.document_intelligence || !health.azure_configured.openai) ? (
        <div className="notice-bar" role="status">
          <span className="notice-icon">!</span>
          <span className="notice-copy">
            <strong>Service not fully configured</strong>
            <span>
              {!health.azure_configured.document_intelligence
                ? "Document extraction is not configured. "
                : ""}
              {!health.azure_configured.openai
                ? "Translation is not configured - documents will extract but fail at the translation step."
                : ""}
            </span>
          </span>
        </div>
      ) : null}

      {info ? (
        <div className="info-bar" role="status">
          <strong>Status</strong><p>{info}</p><button onClick={() => setInfo(null)}>Dismiss</button>
        </div>
      ) : null}

      {sessionError ? (
        <div className="error-bar session-error-bar" role="alert">
          <span>!</span><strong>Authentication problem</strong><p>{sessionError}</p>
          <button onClick={() => clearSessionError()}>Dismiss</button>
        </div>
      ) : null}

      {error ? (
        <div className="error-bar" role="alert">
          <span>!</span><strong>Action needed</strong><p>{error}</p>
          {errorRetry ? (
            <button
              onClick={() => {
                const retry = errorRetry;
                setActionError(null);
                retry();
              }}
            >
              Retry
            </button>
          ) : null}
          <button onClick={() => setActionError(null)}>Dismiss</button>
        </div>
      ) : null}

      {!isTerminal(document.status) && !document.demo ? (
        <div className="progress-strip" aria-label={document.progress_percent + "% complete"}>
          <span style={{ width: document.progress_percent + "%" }} />
          <p>{progressLabel(document)}</p>
        </div>
      ) : null}

      <section className="workspace-grid workspace-grid--main">
        <aside className="thumbnail-rail" aria-label="Document pages">
          <div className="rail-heading">
            <span>Relevant pages</span>
            {flaggedPageNumbers.length ? (
              <button
                className="rail-flag-jump"
                onClick={jumpToNextFlagged}
                title="Jump to next page needing review"
                type="button"
              >
                <Icon name="flag" /> {flaggedPageNumbers.length}
              </button>
            ) : (
              <span>{pageCount || 0}</span>
            )}
          </div>
          {!document.demo && hasFinancialClassification ? (
            <div className="page-view-switcher" aria-label="Page filter" role="group">
              {(
                [
                  { view: "financial", label: "Financial pages", title: "Show financially selected pages" },
                  { view: "review", label: "Needs review", title: "Show pages flagged for review" },
                  { view: "all", label: "All pages", title: "Show every page" },
                ] as const
              ).map(({ view, label, title }) => (
                <button
                  aria-pressed={pageView === view}
                  className={pageView === view ? "is-active" : ""}
                  key={view}
                  onClick={() => {
                    setPageView(view);
                    void loadPageSummaries(
                      document,
                      undefined,
                      { keepCache: true },
                      view,
                    );
                  }}
                  title={title}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}
          <div className="thumbnail-scroll">
            {visibleRailItems.map((item) => (
              <button
                aria-current={currentPage === item.pageNumber ? "page" : undefined}
                className={"page-thumbnail" + (item.ready ? "" : " is-pending")}
                key={item.pageNumber}
                onClick={() => selectPage(item.pageNumber)}
              >
                {document.demo ? (
                  <span className="thumbnail-paper">
                    <DemoThumbnail
                      page={pages.find((candidate) => candidate.page.page_number === item.pageNumber)!}
                    />
                  </span>
                ) : realSource && canPreviewPdf ? (
                  <VirtualPdfThumb
                    authSrc={realSource}
                    height={item.height}
                    pageNumber={item.pageNumber}
                    rotation={0}
                    src={realSource}
                    unit={item.unit}
                    width={item.width}
                    zoom={thumbnailZoom(item)}
                  />
                ) : realSource && canPreviewImage ? (
                  <span
                    className="thumbnail-paper"
                    style={{
                      aspectRatio: `${item.width} / ${item.height}`,
                      height: "auto",
                    }}
                  >
                    <img
                      alt=""
                      aria-hidden="true"
                      src={realSource}
                      style={{ display: "block", height: "100%", objectFit: "contain", width: "100%" }}
                    />
                  </span>
                ) : (
                  <span
                    className="thumbnail-paper"
                    style={{
                      aspectRatio: `${item.width} / ${item.height}`,
                      height: "auto",
                    }}
                  >
                    <span className="thumb-placeholder" aria-hidden="true" />
                  </span>
                )}
                <span>Page {item.pageNumber}</span>
                {item.financialDisposition ? (
                  <span
                    className={"financial-page-badge is-" + item.financialDisposition}
                    title={
                      item.financialLabel && item.financialConfidence != null
                        ? `${item.financialLabel} · ${Math.round(item.financialConfidence * 100)}%`
                        : undefined
                    }
                  >
                    {item.financialDisposition === "financial"
                      ? "Financial"
                      : item.financialDisposition === "uncertain"
                        ? "Check"
                        : "Other"}
                  </span>
                ) : null}
                {item.reviewRequired ? <span className="thumb-warning" title="Review suggested">!</span> : null}
              </button>
            ))}
            {!visibleRailItems.length ? (
              <div className="rail-empty">No pages match this filter.</div>
            ) : null}
          </div>
        </aside>

        <section className="viewer-panel">
          <div className="viewer-toolbar" aria-label="Document viewer controls" role="toolbar">
            <div className="toolbar-group">
              <button
                aria-label="Previous page"
                className="toolbar-text-button"
                disabled={currentVisibleIndex <= 0}
                onClick={() => navigateVisible(-1)}
              >
                <Icon name="arrowLeft" /> Prev
              </button>
              <span className="page-counter">Page <strong>{currentPage}</strong> of {viewerPageCount}</span>
              <button
                aria-label="Next page"
                className="toolbar-text-button"
                disabled={
                  currentVisibleIndex < 0 || currentVisibleIndex >= visiblePageNumbers.length - 1
                }
                onClick={() => navigateVisible(1)}
              >
                Next <Icon name="arrowRight" />
              </button>
            </div>
            <div className="toolbar-group">
              <button
                aria-label="Zoom out"
                disabled={zoom <= 0.5}
                onClick={() => setZoom((value) => Math.max(0.5, value - 0.1))}
              >
                <Icon name="minus" />
              </button>
              <span className="zoom-value">{Math.round(zoom * 100)}%</span>
              <button
                aria-label="Zoom in"
                disabled={zoom >= 1.5}
                onClick={() => setZoom((value) => Math.min(1.5, value + 0.1))}
              >
                <Icon name="plus" />
              </button>
              <span className="toolbar-divider" />
              <button className="toolbar-text-button" onClick={() => fitViewer("width")}>Fit width</button>
              <button className="toolbar-text-button" onClick={() => fitViewer("page")}>Fit page</button>
              <span className="toolbar-divider" />
              <button aria-label="Rotate page left" onClick={() => setRotation((value) => (value + 270) % 360)}><Icon name="rotateLeft" /></button>
              <button aria-label="Rotate page right" onClick={() => setRotation((value) => (value + 90) % 360)}><Icon name="rotateRight" /></button>
              <button className="toolbar-text-button" disabled={viewIsDefault} onClick={resetViewer}>Reset</button>
              <span className="toolbar-divider" />
              <button
                aria-pressed={overlays}
                className={"toolbar-text-button " + (overlays ? "tool-active" : "")}
                onClick={() => setOverlays((value) => !value)}
                title="Toggle extraction overlays"
              >
                {overlays ? "Overlays on hover" : "Enable overlays"}
              </button>
            </div>
          </div>
          <div ref={viewerRef} className="viewer-canvas" onDoubleClick={() => setZoom((value) => (value < 1 ? 1 : 0.82))}>
            {page || canPreviewSource ? (
              <div
                className="page-rotation-frame"
                style={{
                  height: canvasHeight,
                  transform: "rotate(" + rotation + "deg)",
                  width: canvasWidth,
                }}
              >
                {document.demo && page ? (
                  <DemoPage
                    hoveredId={hoveredId}
                    onHover={setHoveredId}
                    onSelect={setSelectedId}
                    overlays={overlays}
                    page={displayPage ?? page}
                    selectedId={selectedId}
                  />
                ) : canPreviewPdf && realSource ? (
                  <div className="real-page-frame">
                    <PdfPage
                      authSrc={realSource}
                      onReady={handleSourceReady}
                      pageNumber={currentPage}
                      rotation={0}
                      src={realSource}
                      zoom={zoom * (96 / 72)}
                    />
                    {overlays && page ? (
                      <OverlayLayer
                        hoveredId={hoveredId}
                        onHover={setHoveredId}
                        onSelect={setSelectedId}
                        page={displayPage ?? page}
                        selectedId={selectedId}
                      />
                    ) : null}
                  </div>
                ) : canPreviewImage && realSource ? (
                  <div className="real-page-frame">
                    <img
                      alt={"Source preview for " + document.original_filename}
                      className="source-image-preview"
                      onLoad={(event) => {
                        const image = event.currentTarget;
                        handleSourceReady(image.naturalWidth * zoom, image.naturalHeight * zoom);
                      }}
                      src={realSource}
                      style={{
                        display: "block",
                        height: "auto",
                        maxWidth: "100%",
                        transform: "scale(" + zoom + ")",
                        transformOrigin: "top left",
                        width: "auto",
                      }}
                    />
                    {overlays && page ? (
                      <OverlayLayer
                        hoveredId={hoveredId}
                        onHover={setHoveredId}
                        onSelect={setSelectedId}
                        page={displayPage ?? page}
                        selectedId={selectedId}
                      />
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="empty-viewer">
                <span className="empty-upload-icon"><Icon name="arrowUp" /></span>
                <h2>{busy ? "Processing your document" : "Upload a document to begin"}</h2>
                <p>PDF, PNG, JPEG, TIFF, or BMP · detected source languages → English</p>
              </div>
            )}
          </div>
          <div className="viewer-footer">
            <span><i className="legend-box selected" /> Selected</span>
            <span><i className="legend-box review" /> Review suggested</span>
            <span className="viewer-tip">Hover a text region or result card to highlight it</span>
          </div>
        </section>
      </section>
      </div>

        <div
          aria-label="Resize document and translation panels"
          aria-orientation="vertical"
          className={"panel-resizer" + (isResizingPanels ? " is-resizing" : "")}
          onDoubleClick={() => setInspectorWidth(null)}
          onKeyDown={handleResizerKeyDown}
          onPointerDown={handleResizerPointerDown}
          role="separator"
          tabIndex={0}
        />

        <aside className="inspector-panel">
          <div className="inspector-content" ref={inspectorContentRef}>
            {(() => {
              const inspectorBanner = selectInspectorBanner({
                activeTab,
                hasFinancialContent: Boolean(currentFinancialContentItems.length),
                isDemo: Boolean(document.demo),
                hasPage: Boolean(page),
                pageLoadError,
                hasActionError: Boolean(error),
                documentStatus: document.status,
                pageCount: document.page_count ?? null,
                currentPageReady,
                financialExcluded: currentPageSummary?.financial_selected === false,
                safeErrorMessage: document.safe_error_message ?? null,
              });

              if (inspectorBanner === "unavailable") {
                return (
                  <div className="translation-status-message" role="status">
                    <strong>{page ? "Translation unavailable" : "Extraction unavailable"}</strong>
                    <span>{document.safe_error_message}</span>
                  </div>
                );
              }
              if (inspectorBanner === "excluded") {
                return (
                  <div className="page-loading-message financial-page-excluded" role="status">
                    <strong>Detailed extraction was not run for page {currentPage}</strong>
                    <span>
                      Classified as {currentPageSummary?.financial_label ?? "non-financial"}
                      {currentPageSummary?.financial_confidence != null
                        ? ` · ${Math.round(currentPageSummary.financial_confidence * 100)}% confidence`
                        : ""}.
                    </span>
                  </div>
                );
              }
              if (inspectorBanner === "extracting") {
                return (
                  <div className="page-loading-message" role="status">
                    <strong>Page {currentPage} is still extracting…</strong>
                    <span>Source preview is available now. Extracted text appears when this page finishes OCR.</span>
                  </div>
                );
              }
              if (inspectorBanner === "loading") {
                return (
                  <div className="page-loading-message" role="status">
                    <strong>Loading page {currentPage}…</strong>
                    <span>Fetching extracted and translated content for this page.</span>
                  </div>
                );
              }
              if (inspectorBanner === "empty") {
                return (
                  <div className="page-loading-message" role="status">
                    <strong>No page content is available for page {currentPage}</strong>
                    <span>
                      {document.safe_error_message ??
                        "Processing finished without producing extracted content for this page."}
                    </span>
                  </div>
                );
              }
              return null;
            })()}

            {!document.demo &&
            pageLoadError &&
            // A whole-document failure banner ("unavailable") already covers this
            // state and takes priority - don't stack a second, page-scoped banner on
            // top of it.
            selectInspectorBanner({
              activeTab,
              hasFinancialContent: Boolean(currentFinancialContentItems.length),
              isDemo: Boolean(document.demo),
              hasPage: Boolean(page),
              pageLoadError,
              hasActionError: Boolean(error),
              documentStatus: document.status,
              pageCount: document.page_count ?? null,
              currentPageReady,
              financialExcluded: currentPageSummary?.financial_selected === false,
              safeErrorMessage: document.safe_error_message ?? null,
            }) !== "unavailable" ? (
              <div className="translation-status-message" role="alert">
                <strong>Page {currentPage} could not be loaded</strong>
                <span>{pageLoadError}</span>
              </div>
            ) : null}

            {activeTab === "financial" ? (
              <div className="financial-inspector">
                <div className="financial-summary-card">
                  <div>
                    <span className="eyebrow">Format-preserving financial extraction</span>
                    <strong>Financial document</strong>
                    <span className="financial-summary-meta">
                      Page {currentPage}: {currentFinancialContentItems.length} structured{" "}
                      {currentFinancialContentItems.length === 1 ? "item" : "items"}
                      {" · "}
                      {currentFinancialTableCount}{" "}
                      {currentFinancialTableCount === 1 ? "table" : "tables"}
                      {financialIssues.length
                        ? ` · ${financialIssues.length} validation issues`
                        : " · no validation issues"}
                    </span>
                  </div>
                  <div
                    aria-label="Financial content language"
                    className="financial-language-switcher"
                    role="group"
                  >
                    <button
                      aria-pressed={contentLanguageView === "source"}
                      className={contentLanguageView === "source" ? "is-active" : ""}
                      onClick={() => setContentLanguageView("source")}
                      type="button"
                    >
                      Source
                    </button>
                    <button
                      aria-pressed={contentLanguageView === "english"}
                      className={contentLanguageView === "english" ? "is-active" : ""}
                      onClick={() => setContentLanguageView("english")}
                      type="button"
                    >
                      English
                    </button>
                  </div>
                </div>
                {financialResult &&
                financialResult.schema_version !== CURRENT_FINANCIAL_RESULT_SCHEMA ? (
                  <div className="translation-status-message" role="status">
                    <strong>Legacy financial normalization</strong>
                    <span>
                      Reprocess this document to apply semantic value typing. Normalized
                      values from the older result are withheld because their meaning was
                      not classified before normalization.
                    </span>
                  </div>
                ) : null}
                <div
                  aria-label="Financial document content"
                  className="financial-document-flow"
                >
                  {currentFinancialContentItems.map((item) => {
                    const pageNumber = item.source_pages[0];
                    const table = item.table_id
                      ? financialTableById.get(item.table_id)
                      : undefined;
                    const translatedText = item.translated_text?.trim();
                    const sourceText = item.source_text?.trim() ?? "";
                    const displayText =
                      contentLanguageView === "english" && translatedText
                        ? translatedText
                        : sourceText;

                    return (
                      <section
                        className={`financial-content-item is-${item.item_type}`}
                        id={`result-${item.item_id}`}
                        key={item.item_id}
                      >
                        <div className="financial-content-meta">
                          <button
                            className="financial-content-page"
                            onClick={() => {
                              selectPage(pageNumber);
                              setSelectedId(table?.cells[0]?.cell_id ?? item.item_id);
                            }}
                            type="button"
                          >
                            Page {item.source_pages.join(", ")}
                          </button>
                          <span>{item.item_type.replace("_", " ")}</span>
                          <span>{item.relevance}</span>
                          <span>{displayLanguage(item.source_language)}</span>
                          {item.review_required ? (
                            <span className="needs-review-badge">Review required</span>
                          ) : null}
                        </div>

                        {item.item_type === "table" && table ? (
                          <div className="financial-table">
                            <div className="table-result-heading">
                              <span>
                                <Icon name="table" /> Table
                              </span>
                              <span>
                                {table.row_count} × {table.column_count}
                                {table.currencies.length
                                  ? ` · ${table.currencies.join(", ")}`
                                  : ""}
                                {!table.complete ? " · incomplete" : ""}
                                {table.classification_override_pages.length
                                  ? ` · retained across pages ${table.classification_override_pages.join(", ")}`
                                  : ""}
                              </span>
                            </div>
                            {table.integrity_status === "reconciled" &&
                            table.reconciliation_candidate_id ? (
                              <div className="table-reconciliation-review" role="group">
                                <div>
                                  <strong>Reconstructed table structure</strong>
                                  <span>
                                    Provider: {table.provider_row_count ?? table.row_count} ×{" "}
                                    {table.provider_column_count ?? table.column_count}; effective:{" "}
                                    {table.row_count} × {table.column_count}. Reconstructed cells are
                                    highlighted below.
                                  </span>
                                </div>
                                <button
                                  aria-pressed={
                                    financialStructureDecisions[
                                      table.reconciliation_candidate_id
                                    ] === "accepted"
                                  }
                                  className={
                                    financialStructureDecisions[
                                      table.reconciliation_candidate_id
                                    ] === "accepted"
                                      ? "is-active"
                                      : ""
                                  }
                                  onClick={() =>
                                    setFinancialStructureDecisions((current) => ({
                                      ...current,
                                      [table.reconciliation_candidate_id!]: "accepted",
                                    }))
                                  }
                                  type="button"
                                >
                                  {financialStructureDecisions[
                                    table.reconciliation_candidate_id
                                  ] === "accepted"
                                    ? "Accepted for review"
                                    : "Accept structure"}
                                </button>
                                <button
                                  aria-pressed={
                                    financialStructureDecisions[
                                      table.reconciliation_candidate_id
                                    ] === "rejected"
                                  }
                                  className={
                                    financialStructureDecisions[
                                      table.reconciliation_candidate_id
                                    ] === "rejected"
                                      ? "is-rejected"
                                      : ""
                                  }
                                  onClick={() =>
                                    setFinancialStructureDecisions((current) => ({
                                      ...current,
                                      [table.reconciliation_candidate_id!]: "rejected",
                                    }))
                                  }
                                  type="button"
                                >
                                  {financialStructureDecisions[
                                    table.reconciliation_candidate_id
                                  ] === "rejected"
                                    ? "Rejected for review"
                                    : "Reject structure"}
                                </button>
                                <span aria-live="polite" className="structure-decision-help">
                                  {financialStructureDecisions[
                                    table.reconciliation_candidate_id
                                  ]
                                    ? "Selection ready. Use Approve or Reject below to save the audit record."
                                    : "Choose the effective table structure, then save it with the reviewer decision below."}
                                </span>
                              </div>
                            ) : null}
                            <div
                              className="table-result-grid"
                              style={{
                                gridTemplateColumns:
                                  "repeat(" +
                                  Math.max(table.column_count, 1) +
                                  ", minmax(0, 1fr))",
                              }}
                            >
                              {table.cells.map((cell) => {
                                const translatedCellText = cell.translated_text?.trim();
                                const cellText =
                                  contentLanguageView === "english" && translatedCellText
                                    ? translatedCellText
                                    : cell.value.raw_text;

                                return (
                                  <button
                                    className={
                                      "table-cell-result financial-cell " +
                                      (cell.review_required ||
                                      cell.value.requires_normalized_correction ||
                                      cell.value.requires_currency_correction
                                        ? "needs-review "
                                        : "") +
                                      (cell.origin === "reconstructed"
                                        ? "is-reconstructed "
                                        : "") +
                                      (selectedId === cell.cell_id ? "is-selected" : "")
                                    }
                                    dir="auto"
                                    id={"result-" + cell.cell_id}
                                    key={cell.cell_id}
                                    onClick={() => {
                                      selectPage(cell.source_page);
                                      setSelectedId(cell.cell_id);
                                    }}
                                    style={{
                                      gridColumn: `${cell.column_index + 1} / span ${cell.column_span}`,
                                      gridRow: `${cell.row_index + 1} / span ${cell.row_span}`,
                                    }}
                                    type="button"
                                  >
                                    <span>{cellText || "—"}</span>
                                    {contentLanguageView === "english" &&
                                    translatedCellText &&
                                    translatedCellText !== cell.value.raw_text ? (
                                      <small>{cell.value.raw_text}</small>
                                    ) : null}
                                    {cell.value.normalized_value != null &&
                                    (cell.value.semantic_type === "monetary_amount" ||
                                      cell.value.semantic_type === "percentage") ? (
                                      <small className="financial-normalized-value">
                                        Normalized: {cell.value.normalized_value}
                                      </small>
                                    ) : null}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        ) : null}

                        {item.item_type === "heading" ? (
                          <h3 dir="auto">{displayText || "Untitled financial section"}</h3>
                        ) : null}

                        {item.item_type === "key_value" ? (
                          contentLanguageView === "english" &&
                          translatedText &&
                          !item.translated_key ? (
                            <p dir="auto">{translatedText}</p>
                          ) : (
                            <dl className="financial-key-value" dir="auto">
                              <dt>
                                {contentLanguageView === "english"
                                  ? item.translated_key ?? item.key
                                  : item.key}
                              </dt>
                              <dd>
                                {contentLanguageView === "english"
                                  ? item.translated_value ?? item.value
                                  : item.value}
                              </dd>
                            </dl>
                          )
                        ) : null}

                        {item.item_type === "list_item" ? (
                          <div className="financial-list-item" dir="auto">
                            <span aria-hidden="true">•</span>
                            <p>{stripListMarker(displayText)}</p>
                          </div>
                        ) : null}

                        {item.item_type === "paragraph" ? (
                          <p dir="auto">{displayText}</p>
                        ) : null}

                        {contentLanguageView === "english" &&
                        translatedText &&
                        sourceText &&
                        translatedText !== sourceText &&
                        item.item_type !== "table" ? (
                          <p className="financial-source-original" dir="auto">
                            Source: {sourceText}
                          </p>
                        ) : null}

                        {item.warnings.length ? (
                          <ul className="financial-content-warnings">
                            {item.warnings.map((warning) => (
                              <li key={warning}>{warning}</li>
                            ))}
                          </ul>
                        ) : null}
                      </section>
                    );
                  })}
                </div>
                {financialIssues.length ? (
                  <section className="financial-validation-list" aria-label="Financial validation">
                    <strong>Validation</strong>
                    {financialIssues.map((issue) => (
                      <div className={"validation-issue is-" + issue.severity} key={issue.issue_id}>
                        <span>{issue.severity}</span>
                        <p>{issue.message}</p>
                      </div>
                    ))}
                  </section>
                ) : null}
                {financialCorrectionCells.length ? (
                  <section className="financial-correction-list" aria-label="Financial corrections">
                    <strong>Required monetary corrections</strong>
                    <p>
                      Only monetary values that cannot be normalized safely appear here.
                      Measurements, dates, phone numbers, account numbers, identifiers, and
                      percentage ranges remain unchanged.
                    </p>
                    {financialCorrectionCells.map((cell) => (
                      <label key={cell.cell_id}>
                        <span>{cell.value.raw_text} · page {cell.source_page}</span>
                        {cell.value.requires_normalized_correction ? (
                          <input
                            aria-label={`Normalized correction for ${cell.value.raw_text}`}
                            inputMode="decimal"
                            onChange={(event) =>
                              setFinancialCorrections((current) => ({
                                ...current,
                                [cell.cell_id]: event.target.value,
                              }))
                            }
                            placeholder="Normalized decimal value"
                            value={financialCorrections[cell.cell_id] ?? ""}
                          />
                        ) : null}
                        {cell.value.requires_currency_correction ? (
                          <select
                            aria-label={`Currency correction for ${cell.value.raw_text}`}
                            onChange={(event) =>
                              setFinancialCorrectionCurrencies((current) => ({
                                ...current,
                                [cell.cell_id]: event.target.value,
                              }))
                            }
                            value={financialCorrectionCurrencies[cell.cell_id] ?? ""}
                          >
                            <option value="">Select currency</option>
                            {cell.value.currency_candidates.map((currency) => (
                              <option key={currency} value={currency}>
                                {currency}
                              </option>
                            ))}
                          </select>
                        ) : null}
                      </label>
                    ))}
                  </section>
                ) : null}
                {financialResult ? (
                  <section className="financial-review-panel" aria-label="Financial review decision">
                    <strong>Reviewer decision</strong>
                    <textarea
                      aria-label="Financial review note"
                      maxLength={4000}
                      onChange={(event) => setFinancialReviewNote(event.target.value)}
                      placeholder="Decision note (recommended; required by your operating policy)"
                      value={financialReviewNote}
                    />
                    <div className="financial-review-actions">
                      <button
                        disabled={
                          financialReviewSubmitting ||
                          financialResult.validation.error_count > 0 ||
                          financialCorrectionCells.some(
                            (cell) =>
                              (cell.value.requires_normalized_correction &&
                                !financialCorrections[cell.cell_id]?.trim()) ||
                              (cell.value.requires_currency_correction &&
                                !financialCorrectionCurrencies[cell.cell_id]?.trim()),
                          ) ||
                          financialResult.reconciliation_candidate_ids.some(
                            (candidateId) =>
                              financialStructureDecisions[candidateId] !== "accepted",
                          )
                        }
                        onClick={() => void handleFinancialReview("approved")}
                        type="button"
                      >
                        Approve
                      </button>
                      <button
                        disabled={financialReviewSubmitting}
                        onClick={() => void handleFinancialReview("rejected")}
                        type="button"
                      >
                        Reject
                      </button>
                    </div>
                    {financialReviews.length ? (
                      <ul className="financial-review-history">
                        {financialReviews.map((review) => (
                          <li key={review.id}>
                            <strong>
                              {review.decision} · {review.active_result ? "current result" : "prior result"}
                            </strong>
                            <span>{new Date(review.created_at).toLocaleString()}</span>
                            <span>{review.corrections.length} corrections</span>
                            <span>
                              {review.structure_decisions.length} structure decisions
                            </span>
                            {review.note ? <p>{review.note}</p> : null}
                            {review.corrections.length ? (
                              <details>
                                <summary>Show corrections</summary>
                                <ul>
                                  {review.corrections.map((correction) => (
                                    <li key={correction.cell_id}>
                                      <code>{correction.cell_id}</code>
                                      <span>
                                        {correction.normalized_value ?? "not normalized"}
                                        {correction.currency ? ` ${correction.currency}` : ""}
                                      </span>
                                      <span>{correction.reason}</span>
                                    </li>
                                  ))}
                                </ul>
                              </details>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>No reviewer decision has been recorded.</p>
                    )}
                  </section>
                ) : null}
                {!currentFinancialContentItems.length && financialResult ? (
                  <div className="page-loading-message" role="status">
                    <strong>No financial content was resolved for page {currentPage}</strong>
                    <span>
                      Open the Page tab for full OCR on this page, or review selected source pages
                      and reprocess after correcting classification.
                    </span>
                  </div>
                ) : null}
              </div>
            ) : null}

            {activeTab === "json" && page ? (
              <div className="json-panel">
                <div className="json-meta"><span>page-{String(currentPage).padStart(4, "0")}.json</span><span>Schema v{page.schema_version}</span></div>
                <pre>{JSON.stringify(page, null, 2)}</pre>
              </div>
            ) : null}

            {activeTab === "page" && page ? (
              <>
                <div className="financial-summary-card page-ocr-summary">
                  <div>
                    <span className="eyebrow">Full page OCR</span>
                    <strong>
                      {contentLanguageView === "english" ? "Page English" : "Page source"}
                    </strong>
                    <span className="financial-summary-meta">
                      {standaloneBlocks.length} text regions · {page.tables.length} structured{" "}
                      {page.tables.length === 1 ? "table" : "tables"}
                      {" · "}Financial stream stays on the Financial tab
                    </span>
                  </div>
                  <div
                    aria-label="Page content language"
                    className="financial-language-switcher"
                    role="group"
                  >
                    <button
                      aria-pressed={contentLanguageView === "source"}
                      className={contentLanguageView === "source" ? "is-active" : ""}
                      onClick={() => setContentLanguageView("source")}
                      type="button"
                    >
                      Source
                    </button>
                    <button
                      aria-pressed={contentLanguageView === "english"}
                      className={contentLanguageView === "english" ? "is-active" : ""}
                      onClick={() => setContentLanguageView("english")}
                      type="button"
                    >
                      English
                    </button>
                  </div>
                </div>
                {page.tables.length ? (
                  <p className="table-grouping-note">
                    Table cell values stay grouped and appear at their original position in the page reading order.
                  </p>
                ) : null}
                <div className="block-list content-sequence">
                  {pageContent.map((item) => {
                    if (item.kind === "table") {
                      const { table, tableIndex } = item;
                      return (
                        <section
                          aria-label={"Structured table " + (tableIndex + 1)}
                          className={"table-result " + (selectedCell?.table.table_id === table.table_id ? "is-selected" : "")}
                          key={table.table_id}
                        >
                          <div className="table-result-heading">
                            <span><Icon name="table" /> Table {tableIndex + 1}</span>
                            <span>{table.row_count} rows × {table.column_count} columns</span>
                          </div>
                          <div
                            className="table-result-grid"
                            style={{ gridTemplateColumns: "repeat(" + Math.max(table.column_count, 1) + ", minmax(0, 1fr))" }}
                          >
                            {table.cells.map((cell) => {
                              const selected = selectedId === cell.cell_id;
                              const hovered = hoveredId === cell.cell_id;
                              return (
                                <button
                                  aria-pressed={selected}
                                  className={
                                    "table-cell-result " +
                                    (cell.review_required ? "needs-review " : "") +
                                    (selected ? "is-selected " : "") +
                                    (hovered ? "is-hovered" : "")
                                  }
                                  id={"result-" + cell.cell_id}
                                  key={cell.cell_id}
                                  onClick={() => setSelectedId(cell.cell_id)}
                                  onFocus={() => setHoveredId(cell.cell_id)}
                                  onBlur={() => setHoveredId(null)}
                                  onMouseEnter={() => setHoveredId(cell.cell_id)}
                                  onMouseLeave={() => setHoveredId(null)}
                                  style={{
                                    gridColumn: String(cell.column_index + 1) + " / span " + cell.column_span,
                                    gridRow: String(cell.row_index + 1) + " / span " + cell.row_span,
                                  }}
                                  type="button"
                                >
                                  <span>
                                    {contentLanguageView === "english"
                                      ? cell.translated_content || "Translation pending"
                                      : cell.content}
                                  </span>
                                  {contentLanguageView === "english" ? (
                                    <small dir="auto">{cell.content}</small>
                                  ) : null}
                                  {cell.review_required && contentLanguageView === "english" ? (
                                    <label
                                      className="translation-correction-field"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      <span>Reviewer correction</span>
                                      <textarea
                                        aria-label={`Correction for table cell ${cell.cell_id}`}
                                        maxLength={20000}
                                        onChange={(event) =>
                                          setTranslationCorrections((current) => ({
                                            ...current,
                                            [`cell:${cell.cell_id}`]: event.target.value,
                                          }))
                                        }
                                        placeholder={cell.translated_content || "Enter corrected English"}
                                        rows={2}
                                        value={
                                          translationCorrections[`cell:${cell.cell_id}`] ??
                                          cell.translated_content ??
                                          ""
                                        }
                                      />
                                    </label>
                                  ) : null}
                                </button>
                              );
                            })}
                          </div>
                        </section>
                      );
                    }

                    const { block } = item;
                    const selected = block.block_id === selectedId;
                    const hovered = block.block_id === hoveredId;
                    return (
                      <button
                        className={"result-card " + (selected ? "is-selected " : "") + (hovered ? "is-hovered" : "")}
                        id={"result-" + block.block_id}
                        key={block.block_id}
                        onClick={() => setSelectedId(block.block_id)}
                        onFocus={() => setHoveredId(block.block_id)}
                        onBlur={() => setHoveredId(null)}
                        onMouseEnter={() => setHoveredId(block.block_id)}
                        onMouseLeave={() => setHoveredId(null)}
                        type="button"
                      >
                        <span className="result-card-topline">
                          <span className="region-number">{block.reading_order}</span>
                          <span className="role-chip">{block.role ?? "Body"}</span>
                          <span className="language-chip">{displayLanguage(block.source_language)}</span>
                          {block.ocr_confidence != null ? <span className="confidence-chip">{Math.round(block.ocr_confidence * 100)}% OCR</span> : null}
                          {block.review_required ? <span className="review-chip">Review</span> : null}
                        </span>
                        {contentLanguageView === "english" ? (
                          <>
                            <span className="translation-text">{block.translated_text || "Translation pending"}</span>
                            <span className="source-preview" dir="auto">{block.source_text}</span>
                            {block.review_required ? (
                              <label
                                className="translation-correction-field"
                                onClick={(event) => event.stopPropagation()}
                              >
                                <span>Reviewer correction</span>
                                <textarea
                                  aria-label={`Correction for region ${block.reading_order}`}
                                  maxLength={20000}
                                  onChange={(event) =>
                                    setTranslationCorrections((current) => ({
                                      ...current,
                                      [`block:${block.block_id}`]: event.target.value,
                                    }))
                                  }
                                  placeholder={block.translated_text || "Enter corrected English"}
                                  rows={2}
                                  value={
                                    translationCorrections[`block:${block.block_id}`] ??
                                    block.translated_text ??
                                    ""
                                  }
                                />
                              </label>
                            ) : null}
                          </>
                        ) : (
                          <span className="extracted-text" dir="auto">{block.source_text}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
                {!document.demo && isTerminal(document.status) ? (
                  <section className="financial-review-panel" aria-label="Translation review decision">
                    <strong>Translation reviewer decision</strong>
                    <span className="financial-summary-meta">
                      {document.translation_review_status
                        ? `Current status: ${document.translation_review_status}`
                        : "Approve after resolving review chips, or reject for rework."}
                      {session?.roles?.length
                        ? ` · Signed in as ${session.subject ?? "token"} (${session.roles.join(", ")})`
                        : ""}
                    </span>
                    <textarea
                      aria-label="Translation review note"
                      maxLength={2000}
                      onChange={(event) => setTranslationReviewNote(event.target.value)}
                      placeholder="Decision note (optional)"
                      value={translationReviewNote}
                    />
                    <div className="financial-review-actions">
                      <button
                        disabled={translationReviewSubmitting || document.translation_review_status === "approved"}
                        onClick={() => void handleTranslationReview("approved")}
                        type="button"
                      >
                        Approve translation
                      </button>
                      <button
                        disabled={translationReviewSubmitting}
                        onClick={() => void handleTranslationReview("rejected")}
                        type="button"
                      >
                        Reject
                      </button>
                    </div>
                    {translationReviews.length ? (
                      <ul className="financial-review-history">
                        {translationReviews.map((review) => (
                          <li key={review.id}>
                            <strong>
                              {review.decision} · {review.active_result ? "current result" : "prior result"}
                            </strong>
                            <span>{new Date(review.created_at).toLocaleString()}</span>
                            <span>{review.corrections.length} corrections</span>
                            {review.note ? <p>{review.note}</p> : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>No translation reviewer decision has been recorded.</p>
                    )}
                  </section>
                ) : null}
              </>
            ) : null}
          </div>

          <div className="inspector-dock" aria-label="Page analysis controls">
            <div className="inspector-dock-meta">
              <span className="eyebrow">Page intelligence</span>
              <strong>Page {currentPage} <span>of {viewerPageCount}</span></strong>
              <span className="page-structure">
                {page ? `${standaloneBlocks.length} regions · ${page.tables.length} ${page.tables.length === 1 ? "table" : "tables"}` : "Awaiting analysis"}
              </span>
            </div>
            <div className="language-summary">
              <span className="language-summary-label">Route</span>
              <strong className="language-token">{sourceLanguages.join(" + ") || "—"}</strong>
              <span className="language-arrow"><Icon name="arrowRight" /></span>
              <strong className="language-token is-target">English</strong>
            </div>
            <div className="inspector-dock-actions">
              <div className="tab-list" role="tablist" aria-label="Inspector results">
                {(["financial", "page", "json"] as InspectorTab[]).map((tab) => (
                  <button
                    aria-selected={activeTab === tab}
                    className={activeTab === tab ? "active" : ""}
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    role="tab"
                    type="button"
                  >
                    {tab === "financial" ? "Financial" : tab === "page" ? "Page" : "JSON"}
                  </button>
                ))}
              </div>
              <button aria-label="Copy page JSON" disabled={!page} onClick={() => void handleCopyPageJson()} type="button">
                <Icon name="copy" />
              </button>
            </div>
          </div>

          {selectedBlock || selectedCell ? (
            <div className="selection-footer">
              <span>
                {selectedBlock
                  ? `Region ${selectedBlock.reading_order} selected`
                  : `Table ${selectedCell!.tableIndex + 1} · Row ${selectedCell!.cell.row_index + 1} · Column ${selectedCell!.cell.column_index + 1} selected`}
              </span>
              <button onClick={() => setSelectedId(null)} type="button">Clear</button>
            </div>
          ) : null}
        </aside>
      </div>
    </main>
  );
}
