import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText, type User, type Doc, type Conversation } from "./api";
import { Brand, Notice } from "./components/shared";
import Icon from "./components/Icon";
import Login from "./pages/Login";
import Ask from "./pages/Ask";
import Documents from "./pages/Documents";
import Accounts from "./pages/Accounts";
import Activity from "./pages/Activity";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [page, setPage] = useState("ask");
  const [docs, setDocs] = useState<Doc[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [newChatKey, setNewChatKey] = useState(0);
  const [error, setError] = useState("");
  const [fake, setFake] = useState(false);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsError, setDocsError] = useState("");
  const generation = useRef(0);
  const activeUser = useRef<string | null>(null);
  const controllers = useRef(new Set<AbortController>());
  const docsRequest = useRef<{ generation: number; promise: Promise<void> } | null>(null);
  const activateUser = useCallback((next: User | null) => {
    if (activeUser.current !== (next ? `${next.id}:${next.role}` : null)) {
      generation.current += 1;
      activeUser.current = next ? `${next.id}:${next.role}` : null;
      controllers.current.forEach((controller) => controller.abort());
      controllers.current.clear();
      docsRequest.current = null;
      setDocs([]);
      setDocsLoaded(false);
      setDocsLoading(Boolean(next));
      setDocsError("");
      setConversations([]);
      setConversation(null);
      setError("");
    }
    setUser(next);
  }, []);
  const refreshDocs = useCallback((forceFresh = false): Promise<void> => {
    if (!activeUser.current) return Promise.resolve();
    const requestedGeneration = generation.current;
    if (docsRequest.current?.generation === requestedGeneration) {
      const existing = docsRequest.current.promise;
      if (!forceFresh) return existing;
      // A mutation needs a snapshot started after it committed, not an older read.
      return existing.catch(() => {}).then(() => {
        if (generation.current === requestedGeneration) return refreshDocs();
      });
    }
    const controller = new AbortController();
    controllers.current.add(controller);
    setDocsLoading(true);
    setDocsError("");
    const promise = api<Doc[]>("/api/documents", { signal: controller.signal })
      .then((loaded) => {
        if (generation.current === requestedGeneration) {
          setDocs(loaded);
          setDocsLoaded(true);
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted && generation.current === requestedGeneration) {
          setDocsError(errorText(failure));
          throw failure;
        }
      })
      .finally(() => {
        controllers.current.delete(controller);
        if (generation.current === requestedGeneration) {
          setDocsLoading(false);
          docsRequest.current = null;
        }
      });
    docsRequest.current = { generation: requestedGeneration, promise };
    return promise;
  }, []);
  const refreshConversations = useCallback(async () => {
    if (!activeUser.current) return;
    const requestedGeneration = generation.current;
    const controller = new AbortController();
    controllers.current.add(controller);
    try {
      const loaded = await api<Conversation[]>("/api/conversations", { signal: controller.signal });
      if (generation.current === requestedGeneration) setConversations(loaded);
    } catch (failure) {
      if (!controller.signal.aborted && generation.current === requestedGeneration) throw failure;
    } finally {
      controllers.current.delete(controller);
    }
  }, []);
  const refreshUser = useCallback(() => {
    const requestedGeneration = generation.current;
    void api<User>("/api/auth/me")
      .then((u) => {
        if (generation.current !== requestedGeneration) return;
        activateUser(u);
        if (u.role !== "admin") setPage("ask");
      })
      .catch(() => {
        if (generation.current === requestedGeneration) window.dispatchEvent(new Event("guidely-session-expired"));
      });
  }, [activateUser]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    api<User>("/api/auth/me", { signal: controller.signal })
      .then((loaded) => { if (active) activateUser(loaded); })
      .catch(() => {})
      .finally(() => { if (active) setBooting(false); });
    api<{ provider: string }>("/health", { signal: controller.signal })
      .then((h) => { if (active) setFake(h.provider === "fake"); })
      .catch(() => {});
    const expired = () => activateUser(null);
    window.addEventListener("guidely-session-expired", expired);
    return () => {
      active = false;
      controller.abort();
      window.removeEventListener("guidely-session-expired", expired);
    };
  }, [activateUser]);
  useEffect(() => {
    if (user) {
      void refreshDocs().catch(() => {});
      void refreshConversations().catch((e) => setError(errorText(e)));
    }
  }, [user, refreshDocs, refreshConversations]);
  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
      activateUser(null);
      setPage("ask");
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function deleteConversation(id: string) {
    try {
      await api(`/api/conversations/${id}`, { method: "DELETE" });
      if (id === conversation) setConversation(null);
      await refreshConversations();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (booting)
    return (
      <div className="boot">
        <Brand />
        <p>Opening your workspace…</p>
      </div>
    );
  if (!user)
    return (
      <Login
        onLogin={(u) => {
          activateUser(u);
          setPage("ask");
          setError("");
        }}
      />
    );
  const nav = [
    ["ask", "sparkle", "Ask Guidely"],
    ["documents", "documents", "Documents"],
    ...(user.role === "admin"
      ? [
          ["accounts", "people", "People & access"],
          ["activity", "activity", "Activity"],
        ]
      : []),
  ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <span className="workspace-label">TEAM KNOWLEDGE WORKSPACE</span>
        <button
          className="new-question"
          onClick={() => {
            setNewChatKey((previous) => previous + 1);
            setConversation(null);
            setPage("ask");
          }}
        >
          <Icon name="plus" /> New conversation
        </button>
        <nav aria-label="Main navigation">
          {nav.map(([id, icon, name]) => (
            <button
              aria-current={page === id ? "page" : undefined}
              key={id}
              className={page === id ? "active" : ""}
              onClick={() => setPage(id)}
            >
              <Icon name={icon} />
              {name}
              {id === "documents" && <small>{docsLoaded ? docs.length : docsError ? "-" : "..."}</small>}
            </button>
          ))}
        </nav>
        <div className="recent">
          <span className="eyebrow">RECENT CONVERSATIONS</span>
          {!conversations.length && (
            <p>Your questions will find a home here.</p>
          )}
          {conversations.map((c) => (
            <div className="recent-row" key={c.id}>
              <button
                className={
                  conversation === c.id && page === "ask" ? "selected" : ""
                }
                onClick={() => {
                  setConversation(c.id);
                  setPage("ask");
                }}
              >
                {c.title}
              </button>
              <button
                aria-label={`Delete conversation ${c.title}`}
                onClick={() => void deleteConversation(c.id)}
              >
                <Icon name="close" />
              </button>
            </div>
          ))}
        </div>
        <div className="sidebar-bottom">
          <div className="knowledge-note">
            <span>
              <Icon name="arrow" />
            </span>
            <strong>
              Good answers start
              <br />
              with good sources.
            </strong>
            <p>
              Keep your team's knowledge
              <br />
              up to date in Documents.
            </p>
          </div>
          <div className="user-panel">
            <span className="avatar">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{user.username}</strong>
              <small>
                {user.role === "admin" ? "Administrator" : "Reader"}
              </small>
            </div>
            <button
              onClick={() => void logout()}
              aria-label="Sign out"
              title="Sign out"
            >
              <Icon name="logout" />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <span>/</span> {nav.find((n) => n[0] === page)?.[2]}
          </span>
          <span className="private-label">
            <Icon name="lock" /> Private workspace
          </span>
        </header>
        {fake && (
          <div className="demo-banner" role="status">
            Offline test provider is active. Answers repeat document text; this
            mode does not use real AI.
          </div>
        )}
        {error && (
          <div className="global-error">
            <Notice error={error} />
            <button onClick={() => setError("")}>Dismiss</button>
          </div>
        )}
        {page === "ask" && (
          <Ask
            key={newChatKey}
            docs={docs}
            docsLoaded={docsLoaded}
            docsLoading={docsLoading}
            selectedConversation={conversation}
            onConversation={setConversation}
            onRefresh={() =>
              void refreshConversations().catch((e) => setError(errorText(e)))
            }
          />
        )}
        {page === "documents" && (
          <Documents
            docs={docs}
            refresh={refreshDocs}
            loading={docsLoading}
            loaded={docsLoaded}
            loadError={docsError}
            admin={user.role === "admin"}
          />
        )}
        {page === "accounts" && user.role === "admin" && (
          <Accounts self={user} onSelfChange={refreshUser} />
        )}
        {page === "activity" && user.role === "admin" && <Activity />}
      </div>
    </div>
  );
}
