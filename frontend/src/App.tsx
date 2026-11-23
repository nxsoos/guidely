import { useCallback, useEffect, useState } from "react";
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
  const [error, setError] = useState("");
  const [fake, setFake] = useState(false);
  const refreshDocs = useCallback(
    async () => setDocs(await api<Doc[]>("/api/documents")),
    [],
  );
  const refreshConversations = useCallback(
    async () =>
      setConversations(await api<Conversation[]>("/api/conversations")),
    [],
  );
  const refreshUser = useCallback(() => {
    void api<User>("/api/auth/me")
      .then((u) => {
        setUser(u);
        if (u.role !== "admin") setPage("ask");
      })
      .catch(() => window.dispatchEvent(new Event("guidely-session-expired")));
  }, []);
  useEffect(() => {
    api<User>("/api/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setBooting(false));
    api<{ provider: string }>("/health")
      .then((h) => setFake(h.provider === "fake"))
      .catch(() => {});
    const expired = () => {
      setUser(null);
      setDocs([]);
      setConversations([]);
      setConversation(null);
    };
    window.addEventListener("guidely-session-expired", expired);
    return () => window.removeEventListener("guidely-session-expired", expired);
  }, []);
  useEffect(() => {
    if (user) {
      void Promise.all([refreshDocs(), refreshConversations()]).catch((e) =>
        setError(errorText(e)),
      );
    }
  }, [user, refreshDocs, refreshConversations]);
  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
      setUser(null);
      setDocs([]);
      setConversations([]);
      setConversation(null);
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
          setUser(u);
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
              {id === "documents" && <small>{docs.length}</small>}
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
            docs={docs}
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
