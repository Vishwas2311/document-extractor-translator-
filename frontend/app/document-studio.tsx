"use client";

import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { demoDocument, demoPages } from "./demo-data";
import {
  API_BASE,
  downloadUrl,
  getDocument,
  getPage,
  isTerminal,
  retryDocument,
  sourceUrl,
  uploadDocument,
} from "./lib/api";
import { PdfPage } from "./pdf-page";
import type { BoundingRegion, DocumentDetail, PageResult, TableCell, TableResult, TextBlock } from "./types";

type InspectorTab = "extracted" | "translated" | "json";

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
};

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
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

function thumbnailZoom(page: PageResult) {
  const widthInPdfPoints = page.page.unit.toLowerCase() === "inch"
    ? page.page.width * 72
    : page.page.width;
  return 78 / Math.max(widthInPdfPoints, 1);
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

export function DocumentStudio() {
  const [document, setDocument] = useState<DocumentDetail>(demoDocument);
  const [pages, setPages] = useState<PageResult[]>(demoPages);
  const [currentPage, setCurrentPage] = useState(1);
  const [activeTab, setActiveTab] = useState<InspectorTab>("translated");
  const [selectedId, setSelectedId] = useState<string | null>(demoPages[0].blocks[0].block_id);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(0.82);
  const [rotation, setRotation] = useState(0);
  const [overlays, setOverlays] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceViewport, setSourceViewport] = useState<{ width: number; height: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const inspectorContentRef = useRef<HTMLDivElement>(null);
  const hoverScrollFrameRef = useRef<number | null>(null);

  const page = pages.find((item) => item.page.page_number === currentPage) ?? pages[0];
  const pageCount = document.page_count ?? pages.length;
  const realSource = !document.demo && API_BASE ? sourceUrl(document.id) : null;
  const canPreviewSource = Boolean(realSource && document.content_type === "application/pdf");
  const viewerPageCount = pageCount || (canPreviewSource ? 1 : 0);
  const canvasWidth = page
    ? page.page.width * 96 * zoom
    : sourceViewport?.width ?? 8.5 * 96 * zoom;
  const canvasHeight = page
    ? page.page.height * 96 * zoom
    : sourceViewport?.height ?? 11 * 96 * zoom;

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
  const selectedCell = useMemo(() => {
    if (!page || !selectedId) return null;
    for (let tableIndex = 0; tableIndex < page.tables.length; tableIndex += 1) {
      const table = page.tables[tableIndex];
      const cell = table.cells.find((candidate) => candidate.cell_id === selectedId);
      if (cell) return { cell, table, tableIndex };
    }
    return null;
  }, [page, selectedId]);

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
      ? page.page.width * 96
      : sourceViewport
        ? sourceViewport.width / zoom
        : 8.5 * 96;
    const baseHeight = page
      ? page.page.height * 96
      : sourceViewport
        ? sourceViewport.height / zoom
        : 11 * 96;
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
    const target = pages.find((item) => item.page.page_number === number);
    setSelectedId(target ? standaloneBlocksForPage(target)[0]?.block_id ?? null : null);
  }, [pages]);

  async function loadPages(nextDocument: DocumentDetail) {
    const count = nextDocument.page_count ?? 0;
    if (!count) return [];
    const loaded = await Promise.all(
      Array.from({ length: count }, (_, index) => getPage(nextDocument.id, index + 1)),
    );
    setPages(loaded);
    setCurrentPage(1);
    setSelectedId(loaded[0] ? standaloneBlocksForPage(loaded[0])[0]?.block_id ?? null : null);
    return loaded;
  }

  async function followJob(documentId: string) {
    let latest = await getDocument(documentId);
    setDocument(latest);
    for (let attempt = 0; attempt < 240 && !isTerminal(latest.status); attempt += 1) {
      await wait(1500);
      latest = await getDocument(documentId);
      setDocument(latest);
    }
    if ((latest.page_count ?? 0) > 0) {
      await loadPages(latest);
    }
    if (latest.status === "failed") {
      throw new Error(latest.safe_error_message ?? "Document processing failed.");
    }
    if (!isTerminal(latest.status)) {
      throw new Error("Processing is still running. Refresh the document in a moment.");
    }
  }

  async function processFile(file: File) {
    setError(null);
    if (!API_BASE) {
      setError("Backend not connected. Copy .env.local.example to .env.local and run the Python API before uploading.");
      return;
    }
    setBusy(true);
    try {
      const created = await uploadDocument(file);
      setDocument({
        id: created.document_id,
        original_filename: file.name,
        content_type: file.type || "application/pdf",
        status: created.status,
        page_count: null,
        current_stage: "Upload accepted",
        progress_percent: 5,
        safe_error_message: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      setPages([]);
      setCurrentPage(1);
      setSelectedId(null);
      setSourceViewport(null);
      await followJob(created.document_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The document could not be processed.");
    } finally {
      setBusy(false);
    }
  }

  function handleFileInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void processFile(file);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) void processFile(file);
  }

  async function handleRetry() {
    if (document.demo) return;
    setBusy(true);
    setError(null);
    try {
      await retryDocument(document.id);
      await followJob(document.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Retry failed.");
    } finally {
      setBusy(false);
    }
  }

  function handleDownload(artifact: "page" | "extracted" | "bilingual") {
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
    window.open(downloadUrl(document.id, artifact, currentPage), "_blank", "noopener,noreferrer");
  }

  const sourceLanguages = page
    ? Array.from(new Set([
        ...standaloneBlocks.map((block) => displayLanguage(block.source_language)),
        ...page.tables.flatMap((table) =>
          table.cells.map((cell) => displayLanguage(cell.source_language)),
        ),
      ]))
    : [];

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
          <div className="product-name">
            <span className="eyebrow">Care intelligence workspace</span>
            <strong>CareTranslate <em>Studio</em></strong>
          </div>
        </div>
        <div className="service-pills" aria-label="Connected service architecture">
          <span className="service-node">
            <span className="service-monogram" aria-hidden="true">DI</span>
            <span className="service-copy"><small>Extract &amp; structure</small><strong>Document Intelligence</strong></span>
            <i className="service-online" aria-label="Connected" />
          </span>
          <span className="service-connector" aria-hidden="true"><i /></span>
          <span className="service-node">
            <span className="service-monogram" aria-hidden="true">AI</span>
            <span className="service-copy"><small>Translate to English</small><strong>Azure OpenAI · GPT-5-mini</strong></span>
            <i className="service-online" aria-label="Connected" />
          </span>
        </div>
        <div className="header-actions">
          <span className="secure-workspace"><i aria-hidden="true" /> Secure workspace</span>
          <button className="primary-button" disabled={busy} onClick={() => inputRef.current?.click()}>
            <span className="button-icon" aria-hidden="true">＋</span> Upload document
          </button>
        </div>
      </header>

      <section className="document-header">
        <div className="filename-group">
          <span className="file-glyph" aria-hidden="true"><i />PDF</span>
          <div className="file-summary">
            <div className="filename-row">
              <h1>{document.original_filename}</h1>
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
            </p>
          </div>
        </div>
        <div className="document-actions">
          {document.status === "failed" ? (
            <button className="secondary-button" disabled={busy} onClick={handleRetry}>↻ Retry</button>
          ) : null}
          <button className="secondary-button" disabled={!page} onClick={() => handleDownload("page")}>↓ Page JSON</button>
          <button className="secondary-button export-button" disabled={!page} onClick={() => handleDownload("bilingual")}>↓ Full export</button>
        </div>
      </section>

      {document.demo ? (
        <div className="notice-bar">
          <span className="notice-icon">i</span>
          <span className="notice-copy"><strong>Interactive preview</strong><span>Explore extraction, page-level translation, structured tables, and JSON review.</span></span>
          <button onClick={() => inputRef.current?.click()}>Connect a document</button>
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
          <p>{document.current_stage} · {document.progress_percent}%</p>
        </div>
      ) : null}

      <section className="workspace-grid">
        <aside className="thumbnail-rail" aria-label="Document pages">
          <div className="rail-heading">
            <span>Document pages</span>
            <span>{pageCount || 0}</span>
          </div>
          <div className="thumbnail-scroll">
            {pages.map((item) => (
              <button
                aria-current={currentPage === item.page.page_number ? "page" : undefined}
                className="page-thumbnail"
                key={item.page.page_number}
                onClick={() => selectPage(item.page.page_number)}
              >
                <span
                  className={"thumbnail-paper " + (!document.demo ? "is-pdf" : "")}
                  style={!document.demo ? {
                    aspectRatio: `${item.page.width} / ${item.page.height}`,
                    height: "auto",
                  } : undefined}
                >
                  {document.demo ? (
                    <DemoThumbnail page={item} />
                  ) : realSource ? (
                    <PdfPage
                      compact
                      pageNumber={item.page.page_number}
                      rotation={0}
                      src={realSource}
                      zoom={thumbnailZoom(item)}
                    />
                  ) : null}
                </span>
                <span>Page {item.page.page_number}</span>
                {item.warnings.length ? <span className="thumb-warning" title="Review suggested">!</span> : null}
              </button>
            ))}
            {!pages.length ? <div className="rail-empty">Pages appear after extraction.</div> : null}
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
                &larr; Prev
              </button>
              <span className="page-counter">Page <strong>{currentPage}</strong> of {viewerPageCount}</span>
              <button
                aria-label="Next page"
                className="toolbar-text-button"
                disabled={currentPage >= viewerPageCount || !page}
                onClick={() => selectPage(currentPage + 1)}
              >
                Next &rarr;
              </button>
            </div>
            <div className="toolbar-group">
              <button
                aria-label="Zoom out"
                disabled={zoom <= 0.5}
                onClick={() => setZoom((value) => Math.max(0.5, value - 0.1))}
              >
                &minus;
              </button>
              <span className="zoom-value">{Math.round(zoom * 100)}%</span>
              <button
                aria-label="Zoom in"
                disabled={zoom >= 1.5}
                onClick={() => setZoom((value) => Math.min(1.5, value + 0.1))}
              >
                +
              </button>
              <span className="toolbar-divider" />
              <button className="toolbar-text-button" onClick={() => fitViewer("width")}>Fit width</button>
              <button className="toolbar-text-button" onClick={() => fitViewer("page")}>Fit page</button>
              <span className="toolbar-divider" />
              <button aria-label="Rotate page left" onClick={() => setRotation((value) => (value + 270) % 360)}>&#10226;</button>
              <button aria-label="Rotate page right" onClick={() => setRotation((value) => (value + 90) % 360)}>&#10227;</button>
              <button className="toolbar-text-button" disabled={viewIsDefault} onClick={resetViewer}>Reset</button>
              <span className="toolbar-divider" />
              <button
                aria-pressed={overlays}
                className={"toolbar-text-button " + (overlays ? "tool-active" : "")}
                onClick={() => setOverlays((value) => !value)}
                title="Toggle extraction overlays"
              >
                {overlays ? "Hide overlays" : "Show overlays"}
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
                ) : realSource ? (
                  <div className="real-page-frame">
                    <PdfPage
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
                ) : null}
              </div>
            ) : (
              <div className="empty-viewer">
                <span className="empty-upload-icon">↑</span>
                <h2>{busy ? "Processing your document" : "Upload a document to begin"}</h2>
                <p>PDF, PNG, JPEG, TIFF, or BMP · Arabic and Mandarin supported</p>
              </div>
            )}
          </div>
          <div className="viewer-footer">
            <span><i className="legend-box selected" /> Selected</span>
            <span><i className="legend-box review" /> Review suggested</span>
            <span className="viewer-tip">Hover an overlay to follow it in the analysis panel</span>
          </div>
        </section>

        <aside className="inspector-panel">
          <div className="inspector-heading">
            <div className="inspector-heading-copy">
              <div className="inspector-title-line">
                <span className="eyebrow">Page intelligence</span>
                <span className="sync-badge"><i aria-hidden="true" /> Synced</span>
              </div>
              <div className="inspector-page-line">
                <h2>Page {currentPage} <span>of {viewerPageCount}</span></h2>
                <span className="page-structure">
                  {page ? `${standaloneBlocks.length} regions · ${page.tables.length} ${page.tables.length === 1 ? "table" : "tables"}` : "Awaiting analysis"}
                </span>
              </div>
            </div>
            <button aria-label="Copy page JSON" disabled={!page} onClick={() => page && navigator.clipboard.writeText(JSON.stringify(page, null, 2))}>▣</button>
          </div>
          <div className="language-summary">
            <span className="language-summary-label">Translation route</span>
            <strong className="language-token">{sourceLanguages.join(" + ") || "—"}</strong>
            <span className="language-arrow">→</span>
            <strong className="language-token is-target">English</strong>
          </div>
          <div className="tab-list" role="tablist" aria-label="Page results">
            {(["extracted", "translated", "json"] as InspectorTab[]).map((tab) => (
              <button
                aria-selected={activeTab === tab}
                className={activeTab === tab ? "active" : ""}
                key={tab}
                onClick={() => setActiveTab(tab)}
                role="tab"
              >
                {tab === "extracted" ? "Extracted" : tab === "translated" ? "Translated" : "JSON"}
              </button>
            ))}
          </div>

          <div className="inspector-content" ref={inspectorContentRef}>
            {activeTab === "translated" && document.status === "failed" && document.safe_error_message ? (
              <div className="translation-status-message" role="status">
                <strong>{page ? "Translation unavailable" : "Extraction unavailable"}</strong>
                <span>{document.safe_error_message}</span>
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
                            <span>▦ Table {tableIndex + 1}</span>
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
                                  {activeTab === "translated" && cell.translated_content ? (
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
                      >
                        <span className="result-card-topline">
                          <span className="region-number">{block.reading_order}</span>
                          <span className="role-chip">{block.role ?? "Body"}</span>
                          <span className="language-chip">{displayLanguage(block.source_language)}</span>
                          {block.ocr_confidence ? <span className="confidence-chip">{Math.round(block.ocr_confidence * 100)}% OCR</span> : null}
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
          {selectedBlock || selectedCell ? (
            <div className="selection-footer">
              <span>
                {selectedBlock
                  ? `Region ${selectedBlock.reading_order} selected`
                  : `Table ${selectedCell!.tableIndex + 1} · Row ${selectedCell!.cell.row_index + 1} · Column ${selectedCell!.cell.column_index + 1} selected`}
              </span>
              <button onClick={() => setSelectedId(null)}>Clear</button>
            </div>
          ) : null}
        </aside>
      </section>
    </main>
  );
}
