"use client";

import { useEffect, useRef, useState } from "react";

type PdfPageProps = {
  src: string;
  /** Optional blob URL already fetched with Authorization; preferred over `src` when set. */
  authSrc?: string | null;
  pageNumber: number;
  zoom: number;
  rotation: number;
  compact?: boolean;
  onReady?: (width: number, height: number) => void;
};

type PdfJsModule = typeof import("pdfjs-dist/webpack.mjs");
type PreviewState =
  | { status: "loading"; message: string }
  | { status: "ready"; message: "" }
  | { status: "failed"; message: string };

let pdfJsPromise: Promise<PdfJsModule> | null = null;

type CachedPdfEntry = {
  // pdfjs document proxy; package typings for webpack.mjs are incomplete in this setup.
  promise: Promise<{ destroy?: () => Promise<void>; getPage: (n: number) => Promise<{
    getViewport: (params: { scale: number; rotation: number }) => { width: number; height: number };
    render: (params: {
      canvas: HTMLCanvasElement;
      canvasContext: CanvasRenderingContext2D;
      viewport: { width: number; height: number };
      transform?: number[];
    }) => { promise: Promise<void>; cancel: () => void };
  }> }>;
  refCount: number;
};

/** Shared across thumbnail + viewer instances so the same source is not downloaded N times. */
const pdfDocumentCache = new Map<string, CachedPdfEntry>();

function loadPdfJs() {
  pdfJsPromise ??= import("pdfjs-dist/webpack.mjs");
  return pdfJsPromise.catch((error) => {
    pdfJsPromise = null;
    throw error;
  });
}

function acquirePdfDocument(pdfjs: PdfJsModule, src: string): CachedPdfEntry["promise"] {
  let entry = pdfDocumentCache.get(src);
  if (!entry) {
    const task = pdfjs.getDocument({
      url: src,
      cMapUrl: "/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/standard_fonts/",
      wasmUrl: "/wasm/",
    });
    const promise = task.promise.catch((error: unknown) => {
      pdfDocumentCache.delete(src);
      throw error;
    });
    entry = { promise, refCount: 0 };
    pdfDocumentCache.set(src, entry);
  }
  entry.refCount += 1;
  return entry.promise;
}

function releasePdfDocument(src: string) {
  const entry = pdfDocumentCache.get(src);
  if (!entry) return;
  entry.refCount -= 1;
  if (entry.refCount > 0) return;
  pdfDocumentCache.delete(src);
  void entry.promise
    .then((doc) => {
      if (typeof doc.destroy === "function") return doc.destroy();
      return undefined;
    })
    .catch(() => undefined);
}

function viewerMessageFor(error: unknown) {
  const message = error instanceof Error ? error.message : "";
  if (/dynamically imported module|module script/i.test(message)) {
    return "The PDF viewer could not start after an update.";
  }
  if (/fetch|network|missing pdf/i.test(message)) {
    return "The document preview could not be downloaded.";
  }
  return message || "Unable to render this PDF page.";
}

function isRetryablePreviewError(error: unknown) {
  const message = error instanceof Error ? error.message : "";
  return error instanceof TypeError || /fetch|network|worker|module|missing pdf/i.test(message);
}

function pause(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function PdfPage({
  src,
  authSrc,
  pageNumber,
  zoom,
  rotation,
  compact = false,
  onReady,
}: PdfPageProps) {
  const resolvedSrc = authSrc || src;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderTaskRef = useRef<{ cancel: () => void } | null>(null);
  // The document reference is held across render-effect re-runs (page/zoom/rotation
  // changes) and released only on unmount, source change, or a load error. If the
  // render effect held it instead, a sole-holder instance would drop the cache
  // refCount to 0 between re-runs, destroying the entry and re-fetching/re-parsing
  // the whole blob on every zoom step.
  const heldSrcRef = useRef<string | null>(null);
  const [preview, setPreview] = useState<PreviewState>({
    status: "loading",
    message: "Loading PDF preview...",
  });
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    return () => {
      if (heldSrcRef.current) {
        releasePdfDocument(heldSrcRef.current);
        heldSrcRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    let disposed = false;

    async function renderPage() {
      setPreview({ status: "loading", message: "Loading PDF preview..." });
      const retryDelays = [0, 400, 1200];
      let lastError: unknown;

      for (let attempt = 0; attempt < retryDelays.length; attempt += 1) {
        if (retryDelays[attempt]) await pause(retryDelays[attempt]);
        if (disposed) return;

        try {
          const pdfjs = await loadPdfJs();
          if (heldSrcRef.current !== resolvedSrc || !pdfDocumentCache.has(resolvedSrc)) {
            if (heldSrcRef.current) releasePdfDocument(heldSrcRef.current);
            heldSrcRef.current = resolvedSrc;
            await acquirePdfDocument(pdfjs, resolvedSrc);
          }
          if (disposed) return;

          const loadedPdf = await pdfDocumentCache.get(resolvedSrc)!.promise;
          const loadedPage = await loadedPdf.getPage(pageNumber);
          if (disposed || !canvasRef.current) return;

          const viewport = loadedPage.getViewport({ scale: zoom, rotation });
          const canvas = canvasRef.current;
          const context = canvas.getContext("2d");
          if (!context) throw new Error("Canvas is not available.");

          const outputScale = window.devicePixelRatio || 1;
          canvas.width = Math.floor(viewport.width * outputScale);
          canvas.height = Math.floor(viewport.height * outputScale);
          canvas.style.width = Math.floor(viewport.width) + "px";
          canvas.style.height = Math.floor(viewport.height) + "px";
          onReady?.(viewport.width, viewport.height);

          renderTaskRef.current?.cancel();
          const renderTask = loadedPage.render({
            canvas,
            canvasContext: context,
            viewport,
            transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
          });
          renderTaskRef.current = renderTask;
          await renderTask.promise;
          if (!disposed) setPreview({ status: "ready", message: "" });
          return;
        } catch (error) {
          if (error instanceof Error && error.name === "RenderingCancelledException") return;
          lastError = error;
          // A failed load must not stay held: releasing lets the (already evicted)
          // poisoned entry be fully dropped so the next attempt fetches fresh.
          if (heldSrcRef.current) {
            releasePdfDocument(heldSrcRef.current);
            heldSrcRef.current = null;
          }
          if (!isRetryablePreviewError(error) || attempt === retryDelays.length - 1) break;
        }
      }

      if (!disposed) {
        setPreview({ status: "failed", message: viewerMessageFor(lastError) });
      }
    }

    void renderPage();
    return () => {
      disposed = true;
      renderTaskRef.current?.cancel();
    };
  }, [resolvedSrc, pageNumber, zoom, rotation, onReady, retryVersion]);

  return (
    <div className="pdf-page">
      <canvas
        ref={canvasRef}
        aria-hidden={compact ? true : undefined}
        aria-label={compact ? undefined : "Rendered PDF page " + pageNumber}
      />
      {preview.status !== "ready" ? (
        <div
          className={"viewer-message is-" + preview.status + (compact ? " is-compact" : "")}
          role={preview.status === "failed" ? "alert" : "status"}
        >
          {preview.status === "loading" || compact ? (
            <span>{preview.status === "loading" ? preview.message : "Preview unavailable"}</span>
          ) : (
            <div className="viewer-message-content">
              <strong>Preview unavailable</strong>
              <span>{preview.message}</span>
              <small>Document extraction continues independently.</small>
              <button
                className="viewer-retry-button"
                onClick={() => setRetryVersion((value) => value + 1)}
                type="button"
              >
                Retry preview
              </button>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
