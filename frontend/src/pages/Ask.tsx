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

type Turn = {
  id: number;
  question: string;
  response?: Message["response"];
  category: string;
  tag: string;
  error?: string;
};

export default function Ask({
  docs,
  docsLoaded,
  docsLoading,
  selectedConversation,
  onConversation,
  onRefresh,
}: {
  docs: Doc[];
  docsLoaded: boolean;
  docsLoading: boolean;
  selectedConversation: string | null;
  onConversation: (id: string | null) => void;
  onRefresh: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Turn[]>([]);
  const [category, setCategory] = useState("");
  const [tag, setTag] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const activeConversation = useRef(selectedConversation);
  const displayedConversation = useRef(selectedConversation);
  displayedConversation.current = selectedConversation;
  const nextTurn = useRef(0);
  const generation = useRef(0);
  const adoptedConversation = useRef<string | null>(null);
  const inFlight = useRef<{ controller: AbortController; generation: number } | null>(null);
  const categories = [
    ...new Set(docs.map((d) => d.category).filter(Boolean)),
  ].sort();
  const tags = [...new Set(docs.flatMap((d) => d.tags))].sort();
  useEffect(() => {
    // A new conversation ID returned by our own send already has its complete turn.
    if (selectedConversation && adoptedConversation.current === selectedConversation) {
      adoptedConversation.current = null;
      activeConversation.current = selectedConversation;
      return;
    }
    generation.current += 1;
    inFlight.current?.controller.abort();
    inFlight.current = null;
    adoptedConversation.current = null;
    activeConversation.current = selectedConversation;
    setBusy(false);
    setError("");
    setMessages([]);
    setQuestion("");
    if (!selectedConversation) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api<Conversation>(`/api/conversations/${selectedConversation}`)
      .then((c) => {
        if (!cancelled) setMessages((c.messages || []).map((message) => ({ ...message, id: ++nextTurn.current, category: "", tag: "" })));
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
  useEffect(() => () => {
    generation.current += 1;
    inFlight.current?.controller.abort();
    inFlight.current = null;
  }, []);
  useEffect(() => {
    if (messages.length || busy)
      end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);
  async function send(turn: Turn) {
    if (inFlight.current || loading) return;
    const requestedConversation = selectedConversation;
    const request = { controller: new AbortController(), generation: generation.current };
    inFlight.current = request;
    setBusy(true);
    setError("");
    setMessages((previous) => previous.map((message) => message.id === turn.id ? { ...message, error: undefined } : message));
    try {
      const response = await api<Message["response"]>("/api/questions", {
        method: "POST",
        signal: request.controller.signal,
        body: body({
          question: turn.question,
          conversation_id: requestedConversation,
          category: turn.category,
          tags: turn.tag ? [turn.tag] : [],
        }),
      });
      if (inFlight.current !== request || generation.current !== request.generation || activeConversation.current !== requestedConversation || displayedConversation.current !== requestedConversation) return;
      setMessages((previous) => previous.map((message) => message.id === turn.id ? { ...message, response, error: undefined } : message));
      if (!requestedConversation) {
        adoptedConversation.current = response.conversation_id;
        activeConversation.current = response.conversation_id;
        onConversation(response.conversation_id);
      }
      onRefresh();
    } catch (e) {
      if (inFlight.current === request && generation.current === request.generation && displayedConversation.current === requestedConversation && !request.controller.signal.aborted)
        setMessages((previous) => previous.map((message) => message.id === turn.id ? { ...message, error: errorText(e) } : message));
    } finally {
      if (inFlight.current === request) {
        inFlight.current = null;
        setBusy(false);
      }
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || inFlight.current || busy || loading) return;
    const turn = { id: ++nextTurn.current, question: question.trim(), category, tag };
    setMessages((previous) => [...previous, turn]);
    setQuestion("");
    void send(turn);
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
          {docsLoaded ? `${docs.filter((d) => d.state === "ready").length} documents ready` : docsLoading ? "Loading documents..." : "Documents unavailable"}
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
          {messages.map((message) => (
            <article className="exchange" key={message.id}>
              <div className="question-bubble">
                <span className="eyebrow">YOU ASKED</span>
                <h2>{message.question}</h2>
              </div>
              {message.response ? <div className="answer">
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
              </div> : message.error ? <div className="answer">
                <Notice error={message.error} />
                <button type="button" disabled={busy || loading} onClick={() => void send(message)}>Retry question</button>
              </div> : <div className="thinking" role="status">
                <span><Icon name="sparkle" /></span>{" "}
                Finding passages and preparing your answer...
              </div>}
            </article>
          ))}
        </div>
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
            disabled={busy || loading}
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
                  disabled={busy || loading}
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
                <select value={tag} disabled={busy || loading} onChange={(e) => setTag(e.target.value)}>
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
