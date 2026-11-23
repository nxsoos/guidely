import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, body, errorText, type Doc } from "../api";
import { Notice } from "../components/shared";
import Icon from "../components/Icon";

export default function Documents({
  docs,
  refresh,
  admin,
}: {
  docs: Doc[];
  refresh: () => Promise<void>;
  admin: boolean;
}) {
  const [selected, setSelected] = useState<Doc | null>(null);
  const [text, setText] = useState("");
  const [tags, setTags] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<Record<string, string>>({});
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!Object.keys(jobs).length) return;
    const interval = window.setInterval(async () => {
      for (const [docId, jobId] of Object.entries(jobs)) {
        try {
          const job = await api<{ state: string; error?: string }>(
            `/api/index-jobs/${jobId}`,
          );
          if (["complete", "failed"].includes(job.state)) {
            setJobs((previous) => {
              const next = { ...previous };
              delete next[docId];
              return next;
            });
            if (job.state === "failed")
              setError(job.error || "Indexing failed.");
            else
              setMessage(
                "Indexing complete. Your document is ready for questions.",
              );
            await refresh();
          }
        } catch (e) {
          setError(errorText(e));
        }
      }
    }, 1200);
    return () => window.clearInterval(interval);
  }, [jobs, refresh]);
  // Also refresh persisted jobs after navigation or a browser reload.
  useEffect(() => {
    if (!docs.some((d) => d.state === "indexing")) return;
    const timer = window.setInterval(() => {
      void refresh().catch((e) => setError(errorText(e)));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [docs, refresh]);
  async function upload(file: File) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", file);
      await api<Doc>("/api/documents", { method: "POST", body: form });
      await refresh();
      setMessage("Document uploaded. Select Index to make it searchable.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
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
      await refresh();
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
    setError("");
    setMessage("");
    try {
      const job = await api<{ id: string }>(`/api/documents/${doc.id}/index`, {
        method: "POST",
      });
      setJobs((previous) => ({ ...previous, [doc.id]: job.id }));
      await refresh();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <main className="management">
      <div className="page-top">
        <div>
          <span className="eyebrow">THE SOURCE OF YOUR ANSWERS</span>
          <h1>Document library</h1>
        </div>
        <span className="count-pill">{docs.length} documents</span>
      </div>
      <p className="page-description">
        A shared home for your team's policies, guides, and everyday know-how.
      </p>
      <Notice error={error} message={message} />
      {admin && (
        <div className="upload-card">
          <span className="upload-icon">
            <Icon name="upload" />
          </span>
          <div>
            <h2>Add to your team's knowledge</h2>
            <p>TXT, Markdown, or text-based PDF · Up to 10 MB</p>
          </div>
          <label className={`button primary ${busy ? "disabled" : ""}`}>
            {busy ? "Working…" : "Upload document +"}
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
      <div className="document-list">
        {!docs.length && (
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
            <span className={`status ${jobs[doc.id] ? "indexing" : doc.state}`}>
              {jobs[doc.id] ? "indexing" : doc.state}
            </span>
            <div className="row-actions">
              <button
                disabled={busy || (!admin && doc.state !== "ready")}
                onClick={() => void open(doc)}
              >
                {admin ? "Edit" : "View"}
              </button>
              {admin && (
                <button
                  disabled={!!jobs[doc.id] || doc.state === "indexing"}
                  onClick={() => void index(doc)}
                >
                  {doc.state === "ready" ? "Re-index" : "Index"}
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
