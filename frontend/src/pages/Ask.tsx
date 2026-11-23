import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  body,
  errorText,
  type Doc,
  type Conversation,
  type Message,
} from "../api";
import { Notice, SourceCard } from "../components/shared";
import Icon from "../components/Icon";

export default function Ask({
  docs,
  selectedConversation,
  onConversation,
  onRefresh,
}: {
  docs: Doc[];
  selectedConversation: string | null;
  onConversation: (id: string | null) => void;
  onRefresh: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [category, setCategory] = useState("");
  const [tag, setTag] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const activeConversation = useRef(selectedConversation);
  const categories = [
    ...new Set(docs.map((d) => d.category).filter(Boolean)),
  ].sort();
  const tags = [...new Set(docs.flatMap((d) => d.tags))].sort();
  useEffect(() => {
    activeConversation.current = selectedConversation;
    setError("");
    setMessages([]);
    if (!selectedConversation) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api<Conversation>(`/api/conversations/${selectedConversation}`)
      .then((c) => {
        if (!cancelled) setMessages(c.messages || []);
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedConversation]);
  useEffect(() => {
    if (messages.length || busy)
      end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy || loading) return;
    const asked = question.trim();
    const requestedConversation = selectedConversation;
    setBusy(true);
    setError("");
    try {
      const response = await api<Message["response"]>("/api/questions", {
        method: "POST",
        body: body({
          question: asked,
          conversation_id: selectedConversation,
          category,
          tags: tag ? [tag] : [],
        }),
      });
      if (activeConversation.current !== requestedConversation) return;
      if (!selectedConversation) onConversation(response.conversation_id);
      setMessages((previous) => [...previous, { question: asked, response }]);
      setQuestion("");
      onRefresh();
    } catch (e) {
      if (activeConversation.current === requestedConversation)
        setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="ask-page">
      <div className="page-top">
        <div>
          <span className="eyebrow">YOUR WORKSPACE</span>
          <h1>Ask your knowledge</h1>
        </div>
        <span className="live-pill">
          <i />
          {docs.filter((d) => d.state === "ready").length} documents ready
        </span>
      </div>
      <div className="ask-content">
        {!messages.length && !loading && (
          <div className="welcome">
            <div className="welcome-icon">
              <Icon name="sparkle" />
            </div>
            <span className="eyebrow">A GOOD QUESTION STARTS HERE</span>
            <h2>What would you like to know?</h2>
            <p>
              Ask in your own words. I’ll find the relevant passages
              <br className="desktop-only" /> and bring the answer back with
              sources.
            </p>
            <div className="suggestions">
              {[
                "How do I request time off?",
                "How do I get IT support?",
                "What can I claim as an expense?",
              ].map((text) => (
                <button key={text} onClick={() => setQuestion(text)}>
                  <span>
                    <Icon name="arrow" />
                  </span>
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}
        {loading && <p role="status">Loading conversation…</p>}
        <div className="messages">
          {messages.map((message, i) => (
            <article className="exchange" key={i}>
              <div className="question-bubble">
                <span className="eyebrow">YOU ASKED</span>
                <h2>{message.question}</h2>
              </div>
              <div className="answer">
                <div className="answer-heading">
                  <span className="answer-symbol">
                    <Icon name="sparkle" />
                  </span>
                  <strong>Guidely</strong>
                  <span>ANSWER WITH SOURCES</span>
                </div>
                <p className="answer-text">{message.response.answer}</p>
                <div className="sources-heading">
                  SOURCES{" "}
                  <span>
                    {message.response.references.length} referenced ·{" "}
                    {(message.response.elapsed_ms / 1000).toFixed(2)}s
                  </span>
                </div>
                {message.response.references.map((s) => (
                  <SourceCard key={s.chunk_id} source={s} />
                ))}
                <details className="ranked">
                  <summary>
                    View all ranked search results (
                    {message.response.passages.length})
                  </summary>
                  {message.response.passages.map((s) => (
                    <SourceCard key={s.chunk_id} source={s} />
                  ))}
                </details>
              </div>
            </article>
          ))}
        </div>
        {busy && (
          <div className="thinking" role="status">
            <span>
              <Icon name="sparkle" />
            </span>{" "}
            Finding passages and preparing your answer…
          </div>
        )}
        <div ref={end} />
      </div>
      <div className="composer-wrap">
        <Notice error={error} />
        <form className="composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="question">
            Your question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Ask a question about your team's documents…"
            maxLength={2000}
            rows={2}
          />
          <div className="composer-bottom">
            <div className="filters">
              <label>
                <span className="sr-only">Category filter</span>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  <option value="">All categories</option>
                  {categories.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="sr-only">Tag filter</span>
                <select value={tag} onChange={(e) => setTag(e.target.value)}>
                  <option value="">All tags</option>
                  {tags.map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </label>
            </div>
            <button
              className="primary"
              disabled={busy || loading || !question.trim()}
            >
              {busy ? "Thinking…" : "Ask Guidely ↑"}
            </button>
          </div>
        </form>
        <p className="composer-note">
          Grounded in your documents. AI can make mistakes — check the sources.
        </p>
      </div>
    </main>
  );
}
