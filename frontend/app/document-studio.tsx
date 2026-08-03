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
  cancelDocument,
  deleteDocument,
  downloadArtifact,
  fetchSourceBlobUrl,
  getDocument,
  getPage,
  isTerminal,
  listDocuments,
  listPageSummaries,
  retryDocument,
  uploadDocument,
} from "./lib/api";
import { PdfPage } from "./pdf-page";
import type {
  BoundingRegion,
  DocumentDetail,
  DocumentSummary,
  HealthStatus,
  PageResult,
  PageSummary,
  TableCell,
  TableResult,
  TextBlock,
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
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

function fileExtension(filename: string): string {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}

function validateUploadFile(file: File): string | null {
  if (!ALLOWED_UPLOAD_EXTENSIONS.has(fileExtension(file.name))) {
    return "Unsupported file type. Upload PDF, PNG, JPEG, TIFF, or BMP.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "File exceeds the 50 MB upload limit.";
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

type InspectorTab = "extracted" | "translated" | "json";

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
    ar: "Arabic",
    "zh-Hans": "Mandarin",
    zh: "Mandarin",
    mixed: "Mixed",
    en: "English",
    und: "Unknown",
  };
  return labels[language] ?? language;
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
            dir={block.source_language === "ar" ? "rtl" : "ltr"}
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
        const isArabic = block.source_language === "ar";
        return (
          <div
            className={"demo-source-text " + (block.role === "title" ? "demo-title" : "")}
            dir={isArabic ? "rtl" : "ltr"}
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
  const [pageCache, setPageCache] = useState<Record<number, PageResult>>({});
  const [pageLoadError, setPageLoadError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [activeTab, setActiveTab] = useState<InspectorTab>("translated");
  const [selectedId, setSelectedId] = useState<string | null>(demoPages[0].blocks[0].block_id);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(0.82);
  const [rotation, setRotation] = useState(0);
  const [overlays, setOverlays] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  // Pre-flight check: without this, a document only reveals that translation isn't
  // configured after a full upload + extraction cycle. Best-effort - upload still works
  // if this fails or is slow, it's just an early heads-up.
  useEffect(() => {
    if (!API_BASE) return;
    const controller = new AbortController();
    checkHealth({ signal: controller.signal })
      .then((result) => setHealth(result))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  // PDF/image previews cannot set Authorization headers. Fetch once with auth and use
  // an object URL for pdf.js / <img>.
  useEffect(() => {
    if (document.demo || !API_BASE || !document.id) {
      setSourceBlobUrl(null);
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

  const diOnline = Boolean(health?.azure_configured.document_intelligence);
  const openaiOnline = Boolean(
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
        ready: Boolean(summary),
      };
    });
  }, [document.demo, document.page_count, pages, pageSummaries]);
  const flaggedPageNumbers = useMemo(
    () => railItems.filter((item) => item.reviewRequired).map((item) => item.pageNumber),
    [railItems],
  );
  const currentPageReady = document.demo || pageSummaries.some((item) => item.page_number === currentPage);

  // Fetch the currently viewed page's full content on demand. The thumbnail rail and
  // the source PDF preview never depend on this - only the inspector/overlay panels do
  // - so navigating a 70-page document stays instant even while this is in flight.
  useEffect(() => {
    if (document.demo || !document.id || pageCache[currentPage]) return;
    if (!currentPageReady) {
      setPageLoadError(null);
      return;
    }
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
        setPageLoadError(caught instanceof Error ? caught.message : "This page could not be loaded.");
      });
    return () => controller.abort();
  }, [document.demo, document.id, currentPage, pageCache, currentPageReady]);

  // Quietly prefetch the next page so "Next" feels instant most of the time, without
  // ever eagerly loading the whole document up front. Best-effort: a prefetch failure
  // is silently dropped, since the effect above will retry (and surface a real error)
  // once the user actually navigates there.
  useEffect(() => {
    if (document.demo || !document.id) return;
    const nextPageNumber = currentPage + 1;
    const nextReady = pageSummaries.some((item) => item.page_number === nextPageNumber);
    if (!nextReady || nextPageNumber > pageCount || pageCache[nextPageNumber]) return;
    const controller = new AbortController();
    getPage(document.id, nextPageNumber, { signal: controller.signal })
      .then((loaded) => {
        setPageCache((previous) => ({ ...previous, [nextPageNumber]: loaded }));
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [document.demo, document.id, currentPage, pageCount, pageCache, pageSummaries]);

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

  function resetPageState() {
    setPageSummaries([]);
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
  ) {
    const count = nextDocument.page_count ?? nextDocument.pages_ready ?? 0;
    if (!count) return;
    const summaries = await listPageSummaries(nextDocument.id, { signal });
    if (signal?.aborted) return;
    setPageSummaries(summaries);
    if (!options?.keepCache) {
      setPageCache({});
    }
    if (!options?.preservePage) {
      setCurrentPage(1);
    }
  }

  async function followJob(documentId: string, signal: AbortSignal) {
    const pollDeadline = Date.now() + 20 * 60 * 1000;
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

    while (!isTerminal(latest.status) && Date.now() < pollDeadline) {
      await wait(delayMs, signal);
      latest = await getDocument(documentId, { signal });
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
      throw new Error("Processing is still running. Refresh the document in a moment.");
    }
  }

  async function processFile(file: File) {
    // Also guards drag-and-drop, which isn't covered by the upload button's
    // `disabled={busy}` - without this, dropping a second file mid-upload starts a
    // second poll loop that interleaves state updates with the first.
    if (busy) return;
    setError(null);
    setInfo(null);
    const validationError = validateUploadFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    if (!API_BASE) {
      setError("Backend not connected. Copy .env.local.example to .env.local and run the Python API before uploading.");
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
      setError(caught instanceof Error ? caught.message : "The document could not be processed.");
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
      setError(null);
      return;
    }
    if (!API_BASE || !document.id) {
      setError("Backend not connected. Cancel could not be sent to the server.");
      return;
    }
    const documentId = document.id;
    setError(null);
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
      setError(caught instanceof Error ? caught.message : "Cancel failed.");
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
    setError(null);
    activeRunRef.current?.abort();
    const controller = new AbortController();
    activeRunRef.current = controller;
    setBusy(true);
    try {
      const detail = await getDocument(documentId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setDocument(detail);
      resetPageState();
      if (!isTerminal(detail.status)) {
        await followJob(documentId, controller.signal);
      } else if ((detail.page_count ?? 0) > 0) {
        await loadPageSummaries(detail, controller.signal);
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "The document could not be opened.");
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
      setDocumentListError(caught instanceof Error ? caught.message : "Documents could not be loaded.");
    } finally {
      setDocumentListLoading(false);
    }
  }

  async function handleDeleteDocument(item: DocumentSummary) {
    if (!window.confirm(`Delete "${item.original_filename}"? This cannot be undone.`)) return;
    try {
      await deleteDocument(item.id);
      setDocumentList((items) => items.filter((candidate) => candidate.id !== item.id));
      if (document.id === item.id) {
        activeRunRef.current?.abort();
        setDocument(demoDocument);
        setPages(demoPages);
        setPageSummaries([]);
        setPageCache({});
        setPageLoadError(null);
        setCurrentPage(1);
        setSelectedId(demoPages[0].blocks[0].block_id);
      }
    } catch (caught) {
      setDocumentListError(caught instanceof Error ? caught.message : "The document could not be deleted.");
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
    setError(null);
    try {
      await retryDocument(document.id, "resume", { signal: controller.signal });
      if (controller.signal.aborted) return;
      setPageSummaries([]);
      setPageCache({});
      setPageLoadError(null);
      await followJob(document.id, controller.signal);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "Retry failed.");
    } finally {
      if (activeRunRef.current === controller) {
        activeRunRef.current = null;
        setBusy(false);
      }
    }
  }

  async function handleDownload(artifact: "page" | "extracted" | "bilingual") {
    if (document.demo) {
      const payload = artifact === "page" ? page : { ...document, pages };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = artifact === "page" ? "demo-page-" + currentPage + ".json" : "demo-" + artifact + ".json";
      link.click();
      URL.revokeObjectURL(url);
      return;
    }
    try {
      await downloadArtifact(document.id, artifact, currentPage);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Download failed.");
    }
  }

  async function handleCopyPageJson() {
    if (!page) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(page, null, 2));
    } catch {
      setError("Clipboard copy failed. Check browser permissions and try again.");
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
      if (event.key === "ArrowRight" && currentPage < viewerPageCount) {
        selectPage(currentPage + 1);
      } else if (event.key === "ArrowLeft" && currentPage > 1) {
        selectPage(currentPage - 1);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentPage, viewerPageCount, selectPage]);

  return (
    <main className="studio-shell" onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}>
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
              <span>{document.demo ? "Arabic + Mandarin" : "Source document"}</span>
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
        <div className="service-pills" aria-label="Service status">
          <span className="service-node">
            <span className="service-monogram" aria-hidden="true">DI</span>
            <span className="service-copy"><small>Extract &amp; structure</small><strong>Document Intelligence</strong></span>
            <i
              className={diOnline ? "service-online" : "service-offline"}
              aria-label={diOnline ? "Available" : "Unavailable"}
            />
          </span>
          <span className="service-connector" aria-hidden="true"><i /></span>
          <span className="service-node">
            <span className="service-monogram" aria-hidden="true">AI</span>
            <span className="service-copy"><small>Translate to English</small><strong>Azure OpenAI</strong></span>
            <i
              className={openaiOnline ? "service-online" : "service-offline"}
              aria-label={openaiOnline ? "Available" : health ? "Unavailable" : "Offline"}
            />
          </span>
        </div>
        <div className="header-actions">
          {!document.demo &&
          (document.status === "failed" ||
            document.status === "needs_review" ||
            document.status === "cancelled") ? (
            <button className="secondary-button" disabled={busy} onClick={() => void handleRetry()}><Icon name="refresh" /> Retry</button>
          ) : null}
          <button className="secondary-button" disabled={!page} onClick={() => void handleDownload("page")}><Icon name="download" /> Page JSON</button>
          <button className="secondary-button export-button" disabled={!page} onClick={() => void handleDownload("bilingual")}><Icon name="download" /> Full export</button>
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

      {error ? (
        <div className="error-bar" role="alert">
          <span>!</span><strong>Action needed</strong><p>{error}</p><button onClick={() => setError(null)}>Dismiss</button>
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
            <span>Document pages</span>
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
          <div className="thumbnail-scroll">
            {railItems.map((item) => (
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
                {item.reviewRequired ? <span className="thumb-warning" title="Review suggested">!</span> : null}
              </button>
            ))}
            {!railItems.length ? <div className="rail-empty">Pages appear after extraction.</div> : null}
          </div>
        </aside>

        <section className="viewer-panel">
          <div className="viewer-toolbar" aria-label="Document viewer controls" role="toolbar">
            <div className="toolbar-group">
              <button
                aria-label="Previous page"
                className="toolbar-text-button"
                disabled={currentPage <= 1}
                onClick={() => selectPage(currentPage - 1)}
              >
                <Icon name="arrowLeft" /> Prev
              </button>
              <span className="page-counter">Page <strong>{currentPage}</strong> of {viewerPageCount}</span>
              <button
                aria-label="Next page"
                className="toolbar-text-button"
                disabled={currentPage >= viewerPageCount}
                onClick={() => selectPage(currentPage + 1)}
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
                <p>PDF, PNG, JPEG, TIFF, or BMP · Arabic and Mandarin supported</p>
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
            {activeTab === "translated" && document.status === "failed" && document.safe_error_message ? (
              <div className="translation-status-message" role="status">
                <strong>{page ? "Translation unavailable" : "Extraction unavailable"}</strong>
                <span>{document.safe_error_message}</span>
              </div>
            ) : null}

            {!document.demo && !page && !pageLoadError && document.page_count && !currentPageReady ? (
              <div className="page-loading-message" role="status">
                <strong>Page {currentPage} is still extracting…</strong>
                <span>Source preview is available now. Extracted text appears when this page finishes OCR.</span>
              </div>
            ) : null}

            {!document.demo && !page && !pageLoadError && currentPageReady && document.page_count ? (
              <div className="page-loading-message" role="status">
                <strong>Loading page {currentPage}…</strong>
                <span>Fetching extracted and translated content for this page.</span>
              </div>
            ) : null}

            {!document.demo && pageLoadError ? (
              <div className="translation-status-message" role="alert">
                <strong>Page {currentPage} could not be loaded</strong>
                <span>{pageLoadError}</span>
              </div>
            ) : null}

            {activeTab === "json" && page ? (
              <div className="json-panel">
                <div className="json-meta"><span>page-{String(currentPage).padStart(4, "0")}.json</span><span>Schema v{page.schema_version}</span></div>
                <pre>{JSON.stringify(page, null, 2)}</pre>
              </div>
            ) : null}

            {activeTab !== "json" && page ? (
              <>
                <div className="result-count">
                  <strong>{activeTab === "extracted" ? "Extracted text" : "English translation"}</strong>
                  <span>{standaloneBlocks.length} text regions · {page.tables.length} structured {page.tables.length === 1 ? "table" : "tables"}</span>
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
                                  <span>{activeTab === "translated" ? cell.translated_content || "Translation pending" : cell.content}</span>
                                  {activeTab === "translated" ? (
                                    <small dir={cell.source_language === "ar" ? "rtl" : "ltr"}>{cell.content}</small>
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
                        {activeTab === "translated" ? (
                          <>
                            <span className="translation-text">{block.translated_text || "Translation pending"}</span>
                            <span className="source-preview" dir={block.source_language === "ar" ? "rtl" : "ltr"}>{block.source_text}</span>
                          </>
                        ) : (
                          <span className="extracted-text" dir={block.source_language === "ar" ? "rtl" : "ltr"}>{block.source_text}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
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
              <div className="tab-list" role="tablist" aria-label="Page results">
                {(["extracted", "translated", "json"] as InspectorTab[]).map((tab) => (
                  <button
                    aria-selected={activeTab === tab}
                    className={activeTab === tab ? "active" : ""}
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    role="tab"
                    type="button"
                  >
                    {tab === "extracted" ? "Extracted" : tab === "translated" ? "Translated" : "JSON"}
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
