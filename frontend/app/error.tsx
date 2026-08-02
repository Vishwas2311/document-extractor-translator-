"use client";

import { useEffect } from "react";

// Next.js App Router error boundary. Without this file, an uncaught render-time
// exception (a malformed API response slipping past validation, a null bounding box)
// surfaces as Next.js's generic, unbranded "Application error" crash screen with no
// in-app recovery. This scopes the failure to a dismissible screen with a retry.
export default function StudioError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Avoid logging full error bodies — they can include document content from a
    // failed render. Digest is enough for correlating with server logs.
    console.error("CareTranslate Studio crashed:", error.digest ?? "no-digest");
  }, [error]);

  return (
    <div
      role="alert"
      style={{
        alignItems: "center",
        background: "#f5f8f7",
        color: "#102729",
        display: "flex",
        flexDirection: "column",
        fontFamily: "system-ui, sans-serif",
        gap: "0.75rem",
        justifyContent: "center",
        minHeight: "100vh",
        padding: "2rem",
        textAlign: "center",
      }}
    >
      <span style={{ fontSize: "2rem" }} aria-hidden="true">
        !
      </span>
      <h1 style={{ fontSize: "1.25rem", margin: 0 }}>Something went wrong</h1>
      <p style={{ color: "#617174", margin: 0, maxWidth: "32rem" }}>
        CareTranslate Studio hit an unexpected error while rendering this document. Your
        upload is unaffected - try reloading this view.
      </p>
      <button
        onClick={reset}
        style={{
          background: "#0c6964",
          border: "none",
          borderRadius: "0.5rem",
          color: "#ffffff",
          cursor: "pointer",
          fontSize: "0.95rem",
          fontWeight: 600,
          marginTop: "0.5rem",
          padding: "0.6rem 1.4rem",
        }}
        type="button"
      >
        Try again
      </button>
    </div>
  );
}
