import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, body, errorText, type Doc } from "../api";
import { Notice } from "../components/shared";
import Icon from "../components/Icon";

export default function Documents({
  docs,
  refresh,
  admin,
  loading,
  loaded,
  loadError,
}: {
  docs: Doc[];
  refresh: (forceFresh?: boolean) => Promise<void>;
  admin: boolean;
  loading: boolean;
  loaded: boolean;
  loadError: string;
}) {
  const [selected, setSelected] = useState<Doc | null>(null);
  const [text, setText] = useState("");
  const [tags, setTags] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [indexing, setIndexing] = useState<Record<string, boolean>>({});
  const pendingIndexes = useRef(new Set<string>());
  const [uploadStage, setUploadStage] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  // Fetch again after a reload while a persisted operation may still be running.
  // Chained timeouts and App's shared request prevent overlapping slow requests.
  useEffect(() => {
    if (!docs.some((d) => d.state === "indexing")) return;
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      try { await refresh(); }
      catch (e) { if (!cancelled) setError(errorText(e)); }
      if (!cancelled) timer = window.setTimeout(poll, 3000);
    };
    timer = window.setTimeout(poll, 3000);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [docs, refresh]);
  async function upload(file: File) {
    setBusy(true);
    setError("");
    setMessage("");
    setUploadStage("Preparing upload...");
    try {
      if (file.size > 1024 * 1024) throw new Error("Files must be 1 MB or smaller.");
      const intent = await api<{ id: string; upload_url: string }>("/api/uploads", {
        method: "POST", body: body({ filename: file.name, size: file.size }),
      });
      setUploadStage("Uploading file...");
      const uploaded = await fetch(intent.upload_url, {
        method: "PUT", body: file, headers: { "Content-Type": file.type || "application/octet-stream", ...(intent.upload_url.startsWith("/") ? { "X-Guidely": "1" } : {}) },
      });
      if (!uploaded.ok) throw new Error("Storage upload failed. Please try again.");
      setUploadStage("Validating document...");
      await api<Doc>(`/api/uploads/${intent.id}/complete`, { method: "POST" });
      await refresh(true);
      setMessage("Document uploaded. Select Index to make it searchable.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      setUploadStage("");
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function open(doc: Doc) {
    setError("");
    setBusy(true);
    try {
      const full = await api<Doc>(`/api/documents/${doc.id}`);
      setSelected(full);
      setText(full.text || "");
      setTags(full.tags.join(", "));
      setCategory(full.category);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/documents/${selected.id}`, {
        method: "PATCH",
        body: body({
          text,
          tags: tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
          category,
        }),
      });
      setSelected(null);
      await refresh(true);
      setMessage(
        "Saved. Re-index changed text before asking questions about it.",
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function index(doc: Doc) {
    if (pendingIndexes.current.has(doc.id)) return;
    pendingIndexes.current.add(doc.id);
    setIndexing((previous) => ({ ...previous, [doc.id]: true }));
    setError("");
    setMessage("Indexing your document. You can keep this page open while it finishes.");
    try {
      const job = await api<{ id: string; state: string; error?: string }>(`/api/documents/${doc.id}/index`, {
        method: "POST",
      });
      if (job.state === "failed") setError(job.error || "Indexing failed. You can retry.");
      setMessage(job.state === "complete" ? "Indexing complete. Your document is ready for questions." : "");
      await refresh(true);
    } catch (e) {
      setMessage("");
      setError(errorText(e));
    } finally {
      pendingIndexes.current.delete(doc.id);
      setIndexing((previous) => { const next = { ...previous }; delete next[doc.id]; return next; });
    }
  }
  return (
    <main className="management">
      <div className="page-top">
        <div>
          <span className="eyebrow">THE SOURCE OF YOUR ANSWERS</span>
          <h1>Document library</h1>
        </div>
        <span className="count-pill">{loaded ? `${docs.length} ${docs.length === 1 ? "document" : "documents"}` : !loadError ? "Loading..." : "Unavailable"}</span>
      </div>
      <p className="page-description">
        A shared home for your team's policies, guides, and everyday know-how.
      </p>
      <Notice error={error || loadError} message={message} />
      {loadError && <button disabled={loading} onClick={() => void refresh().catch(() => {})}>Retry loading documents</button>}
      {uploadStage && <p role="status">{uploadStage}</p>}
      {(loading || (!loaded && !loadError)) && <p role="status">{loaded ? "Refreshing documents..." : "Loading documents..."}</p>}
      {admin && (
        <div className="upload-card">
          <span className="upload-icon">
            <Icon name="upload" />
          </span>
          <div>
            <h2>Add to your team's knowledge</h2>
            <p>TXT, Markdown, or text-based PDF · Up to 1 MB; 10 PDF pages; 24,000 characters</p>
          </div>
          <label className={`button primary ${busy ? "disabled" : ""}`}>
            {busy ? uploadStage || "Working..." : "Upload document +"}
            <input
              ref={fileInput}
              type="file"
              aria-label="Upload document"
              accept=".txt,.md,.pdf"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void upload(file);
              }}
            />
          </label>
        </div>
      )}
      {admin && <button disabled={busy} onClick={async () => {
        setBusy(true); setError("");
        try {
          const result = await api<{ removed: number }>("/api/uploads/cleanup", { method: "POST" });
          setMessage(`Removed ${result.removed} expired uploads.`);
        } catch (e) { setError(errorText(e)); }
        finally { setBusy(false); }
      }}>Clean up expired uploads</button>}
      <div className="document-list">
        {loaded && !loading && !loadError && !docs.length && (
          <div className="empty-state">
            No documents yet.{" "}
            {admin
              ? "Upload your first guide to get started."
              : "Ask an administrator to add documents."}
          </div>
        )}
        {docs.map((doc) => (
          <article className="document-row" key={doc.id}>
            <span className="file-icon">
              {doc.filename.split(".").pop()?.toUpperCase()}
            </span>
            <div className="document-info">
              <h2>{doc.filename}</h2>
              <div className="doc-meta">
                <span>{doc.category || "Uncategorized"}</span>
                {doc.tags.map((t) => (
                  <span className="tag" key={t}>
                    {t}
                  </span>
                ))}
              </div>
              {doc.error && <p className="inline-error">{doc.error}</p>}
            </div>
            <span className={`status ${indexing[doc.id] ? "indexing" : doc.state}`}>
              {indexing[doc.id] ? "indexing" : doc.state}
            </span>
            <div className="row-actions">
              <button
                disabled={busy || doc.state === "deleting" || (!admin && doc.state !== "ready")}
                onClick={() => void open(doc)}
              >
                {admin ? "Edit" : "View"}
              </button>
              {admin && <button disabled={busy} onClick={async () => {
                if (!window.confirm(`Delete ${doc.filename}?`)) return;
                setBusy(true);
                try { await api(`/api/documents/${doc.id}`, { method: "DELETE" }); await refresh(true); }
                catch (e) { setError(errorText(e)); }
                finally { setBusy(false); }
              }}>{doc.state === "deleting" ? "Retry delete" : "Delete"}</button>}
              {admin && (
                <button
                  disabled={!!indexing[doc.id] || doc.state === "deleting"}
                  onClick={() => void index(doc)}
                >
                  {indexing[doc.id] ? "Indexing..." : doc.state === "ready" ? "Re-index" : "Index"}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
      {selected && (
        <section className="editor" aria-label="Document editor">
          <div className="section-heading">
            <h2>{selected.filename}</h2>
            <button onClick={() => setSelected(null)}>Close ×</button>
          </div>
          <form onSubmit={save}>
            <div className="form-row">
              <label>
                Category
                <input
                  value={category}
                  readOnly={!admin}
                  maxLength={80}
                  onChange={(e) => setCategory(e.target.value)}
                />
              </label>
              <label>
                Tags (comma separated)
                <input
                  value={tags}
                  readOnly={!admin}
                  onChange={(e) => setTags(e.target.value)}
                />
              </label>
            </div>
            <label>
              Extracted document text
              <textarea
                className="document-text"
                rows={16}
                value={text}
                readOnly={!admin}
                onChange={(e) => setText(e.target.value)}
                required
              />
            </label>
            <div className="editor-footer">
              <a href={`/api/documents/${selected.id}/original`}>
                Download original ↗
              </a>
              {admin && (
                <button className="primary" disabled={busy}>
                  Save changes
                </button>
              )}
            </div>
          </form>
        </section>
      )}
    </main>
  );
}
