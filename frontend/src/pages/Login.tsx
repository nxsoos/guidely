import { useState, type FormEvent } from "react";
import { api, body, errorText, type User } from "../api";
import { Brand, Notice } from "../components/shared";

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(
        await api<User>("/api/auth/login", {
          method: "POST",
          body: body({ username, password }),
        }),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-story">
        <Brand />
        <div>
          <span className="eyebrow">LESS SEARCHING. MORE KNOWING.</span>
          <h1>
            Your team's knowledge.
            <br />
            <em>A little closer.</em>
          </h1>
          <p>
            Turn scattered documents into clear answers.
            <br />
            Always with a source. Always in context.
          </p>
          <div className="story-card">
            <span>↗</span>
            <div>
              From “where is that policy?”
              <br />
              <strong>to “here’s what you need.”</strong>
            </div>
          </div>
        </div>
        <small>Built for curious teams.</small>
      </div>
      <main className="login-form">
        <form onSubmit={submit}>
          <span className="eyebrow">YOUR KNOWLEDGE WORKSPACE</span>
          <h2>Welcome to Guidely</h2>
          <p>Sign in to find your next answer.</p>
          <Notice error={error} />
          <label>
            Username
            <input
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in →"}
          </button>
          <p className="muted small">
            Need an account or password reset? Ask your workspace administrator.
          </p>
        </form>
      </main>
    </div>
  );
}
