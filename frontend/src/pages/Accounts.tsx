import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, body, errorText, type User } from "../api";
import { Notice } from "../components/shared";

export default function Accounts({
  self,
  onSelfChange,
}: {
  self: User;
  onSelfChange: () => void;
}) {
  const [users, setUsers] = useState<User[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reader");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [resetUser, setResetUser] = useState<User | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const load = useCallback(
    async () => setUsers(await api<User[]>("/api/users")),
    [],
  );
  useEffect(() => {
    void load().catch((e) => setError(errorText(e)));
  }, [load]);
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api("/api/users", {
        method: "POST",
        body: body({ username, password, role }),
      });
      setUsername("");
      setPassword("");
      await load();
      setMessage("Account created.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function update(
    user: User,
    changes: { role?: string; password?: string },
  ) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api(`/api/users/${user.id}`, {
        method: "PATCH",
        body: body(changes),
      });
      if (user.id === self.id) onSelfChange();
      else await load();
      setResetUser(null);
      setResetPassword("");
      setMessage("Account updated. Password changes sign the account out.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="management">
      <div className="page-top">
        <div>
          <span className="eyebrow">YOUR TEAM</span>
          <h1>People & access</h1>
        </div>
      </div>
      <p className="page-description">
        Readers explore knowledge. Administrators keep it organized.
      </p>
      <Notice error={error} message={message} />
      <section className="panel">
        <h2>Create an account</h2>
        <form className="account-form" onSubmit={create}>
          <label>
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              maxLength={80}
              required
              autoComplete="off"
            />
          </label>
          <label>
            Temporary password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={10}
              maxLength={128}
              required
              autoComplete="new-password"
            />
          </label>
          <label>
            Role
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="reader">Reader</option>
              <option value="admin">Administrator</option>
            </select>
          </label>
          <button className="primary" disabled={busy}>
            Create account
          </button>
        </form>
      </section>
      <section className="panel">
        <h2>Workspace members</h2>
        {users.map((user) => (
          <div className="member-row" key={user.id}>
            <span className="avatar">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <strong>
              {user.username}
              {user.id === self.id ? " (you)" : ""}
            </strong>
            <select
              aria-label={`Role for ${user.username}`}
              value={user.role}
              disabled={busy}
              onChange={(e) => void update(user, { role: e.target.value })}
            >
              <option value="reader">Reader</option>
              <option value="admin">Administrator</option>
            </select>
            <button
              disabled={busy}
              onClick={() => {
                setResetUser(user);
                setResetPassword("");
              }}
            >
              Reset password
            </button>
          </div>
        ))}
      </section>
      {resetUser && (
        <section className="panel">
          <h2>Reset password for {resetUser.username}</h2>
          <form
            className="account-form"
            onSubmit={(e) => {
              e.preventDefault();
              void update(resetUser, { password: resetPassword });
            }}
          >
            <label>
              New password
              <input
                type="password"
                autoComplete="new-password"
                minLength={10}
                maxLength={128}
                required
                value={resetPassword}
                onChange={(e) => setResetPassword(e.target.value)}
              />
            </label>
            <button className="primary" disabled={busy}>
              Save password
            </button>
            <button type="button" onClick={() => setResetUser(null)}>
              Cancel
            </button>
          </form>
        </section>
      )}
    </main>
  );
}
