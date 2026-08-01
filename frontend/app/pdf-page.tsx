"use client";

import { useEffect, useRef, useState } from "react";

type PdfPageProps = {
  src: string;
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

function loadPdfJs() {
  pdfJsPromise ??= import("pdfjs-dist/webpack.mjs");
  return pdfJsPromise.catch((error) => {
    pdfJsPromise = null;
    throw error;
  });
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

export function PdfPage({ src, pageNumber, zoom, rotation, compact = false, onReady }: PdfPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderTaskRef = useRef<{ cancel: () => void } | null>(null);
  const [preview, setPreview] = useState<PreviewState>({
    status: "loading",
    message: "Loading PDF preview...",
  });
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    let disposed = false;
    let loadingTask: { destroy?: () => Promise<void> } | null = null;
    let pdfDocument: { destroy?: () => Promise<void> } | null = null;

    async function disposeAttempt() {
      if (typeof pdfDocument?.destroy === "function") {
        await pdfDocument.destroy().catch(() => undefined);
        pdfDocument = null;
      } else if (typeof loadingTask?.destroy === "function") {
        await loadingTask.destroy().catch(() => undefined);
      }
      loadingTask = null;
    }

    async function renderPage() {
      setPreview({ status: "loading", message: "Loading PDF preview..." });
      const retryDelays = [0, 400, 1200];
      let lastError: unknown;

      for (let attempt = 0; attempt < retryDelays.length; attempt += 1) {
        if (retryDelays[attempt]) await pause(retryDelays[attempt]);
        if (disposed) return;

        try {
          const pdfjs = await loadPdfJs();

          const task = pdfjs.getDocument({
            url: src,
            cMapUrl: "/cmaps/",
            cMapPacked: true,
            standardFontDataUrl: "/standard_fonts/",
            wasmUrl: "/wasm/",
          });
          loadingTask = task;
          const loadedPdf = await task.promise;
          pdfDocument = loadedPdf;
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
          if (!isRetryablePreviewError(error) || attempt === retryDelays.length - 1) break;
          await disposeAttempt();
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
      void disposeAttempt();
    };
  }, [src, pageNumber, zoom, rotation, onReady, retryVersion]);

  return (
    <div className="pdf-page">
      <canvas ref={canvasRef} aria-label={"Rendered PDF page " + pageNumber} />
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