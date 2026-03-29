"use client";

export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <html>
      <body style={{ padding: 40, fontFamily: "monospace", background: "#111", color: "#eee", minHeight: "100vh" }}>
        <h1 style={{ color: "#f87171", fontSize: 24 }}>Global Dashboard Error</h1>
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", color: "#fbbf24", marginTop: 16, fontSize: 14 }}>
          {error.message}
        </pre>
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", color: "#a1a1aa", marginTop: 12, fontSize: 12, maxHeight: 400, overflow: "auto" }}>
          {error.stack}
        </pre>
        {error.digest && (
          <p style={{ color: "#71717a", marginTop: 12, fontSize: 12 }}>Digest: {error.digest}</p>
        )}
        <button onClick={unstable_retry} style={{ marginTop: 24, padding: "8px 24px", background: "#7c3aed", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 14 }}>
          Try Again
        </button>
      </body>
    </html>
  );
}
