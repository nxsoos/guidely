import type { Source } from "../api";
import Icon from "./Icon";

export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        g<span>↗</span>
      </span>
      <span>
        guidely<span className="brand-dot">.</span>
      </span>
    </div>
  );
}

export function Notice({
  error,
  message,
}: {
  error?: string;
  message?: string;
}) {
  return (
    <>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="notice success" role="status">
          {message}
        </div>
      )}
    </>
  );
}

export function SourceCard({ source }: { source: Source }) {
  return (
    <details className="source-card">
      <summary>
        <span className="source-number">{source.source_id}</span>
        <span>
          <strong>{source.filename}</strong>
          <small>
            {source.section || "Document passage"}
            {source.page ? ` · Page ${source.page}` : ""} ·{" "}
            {Math.round(source.score * 100)}% similarity
          </small>
        </span>
        <span className="source-expand">
          <Icon name="chevron" />
        </span>
      </summary>
      <p className="snippet">{source.snippet}</p>
      <a href={`/api/documents/${source.document_id}/original`}>
        Download original ↗
      </a>
    </details>
  );
}
