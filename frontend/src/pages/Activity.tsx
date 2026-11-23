import { useEffect, useState } from "react";
import { api, errorText, type Metrics } from "../api";
import { Notice } from "../components/shared";

export default function Activity() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState("");
  async function load() {
    try {
      setMetrics(await api<Metrics>("/metrics"));
      setError("");
    } catch (e) {
      setError(errorText(e));
    }
  }
  useEffect(() => {
    void load();
  }, []);
  return (
    <main className="management">
      <div className="page-top">
        <div>
          <span className="eyebrow">A LOOK UNDER THE HOOD</span>
          <h1>Workspace activity</h1>
        </div>
        <button onClick={() => void load()}>Refresh</button>
      </div>
      <p className="page-description">
        Understand usage, response times, and the health of your knowledge
        pipeline.
      </p>
      <Notice error={error} />
      {metrics && (
        <>
          <div className="metric-grid">
            {[
              ["Documents", metrics.documents],
              ["Searchable passages", metrics.chunks],
              ["Questions served", metrics.queries_served],
              [
                "Median response",
                metrics.latency_ms.median == null
                  ? "—"
                  : `${(metrics.latency_ms.median / 1000).toFixed(2)}s`,
              ],
              [
                "95th percentile",
                metrics.latency_ms.p95 == null
                  ? "—"
                  : `${(metrics.latency_ms.p95 / 1000).toFixed(2)}s`,
              ],
            ].map(([label, value]) => (
              <div className="metric" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <section className="panel">
            <h2>Embedding cache & processing</h2>
            {Object.entries(metrics.counters)
              .filter(([k]) => !k.startsWith("error:"))
              .map(([key, value]) => (
                <div className="stat-row" key={key}>
                  <span>{key.replaceAll("_", " ")}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            {!Object.keys(metrics.counters).length && (
              <p className="muted">
                Activity appears after indexing documents and asking questions.
              </p>
            )}
          </section>
          <section className="panel">
            <h2>Recorded errors</h2>
            {Object.entries(metrics.errors).map(([key, value]) => (
              <div className="stat-row" key={key}>
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{value}</strong>
              </div>
            ))}
            {!Object.keys(metrics.errors).length && (
              <p className="muted">No errors recorded.</p>
            )}
          </section>
          <a className="button primary" href="/api/query-logs/export" download>
            Export query logs (CSV) ↓
          </a>
        </>
      )}
    </main>
  );
}
