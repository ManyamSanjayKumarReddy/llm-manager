import { useEffect, useRef, useState, type SubmitEvent } from "react";

import { BRAND } from "../../brand";
import { Deco } from "../../components/Stickers";
import { Logo } from "../../components/Logo";
import { Marquee } from "../../components/Marquee";
import { Alert, Field, type Notice } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { Link } from "../../router/Link";
import { useAuth } from "./context";

const TICKER = ["Wake on demand", "One endpoint", "Shared GPUs", "Sleep when idle", "OpenAI compatible", "Zero idle VRAM"];

export function LoginPage() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>();
  const userInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    userInput.current?.focus();
  }, []);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice(undefined);
    try {
      await signIn(username.trim(), password);
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Sign-in failed." });
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login-glow" aria-hidden="true" />
      <header className="login-top">
        <Logo to="/" />
        <Link className="back-link" to="/"><Icon name="arrow-left" size={16} /> Back to home</Link>
      </header>

      <main className="login-main">
        <section className="login-hero">
          <span className="eyebrow">
            <span className="live-dot" /> GPU control room
          </span>
          <h1>
            Models that <em>wake</em> when you call.
          </h1>
          <p className="dim lead">{BRAND.description}</p>
          <div className="login-stickers">
            <Deco name="metal" size={120} rotate={-8} />
            <Deco name="pill" size={110} delay={1.2} rotate={6} />
            <Deco name="star" size={100} delay={2.4} rotate={-4} />
          </div>
        </section>

        <form className="login-card surface glow" onSubmit={(e) => void submit(e)}>
          <h2>Sign in</h2>
          <p className="dim">Use the account an administrator created for you.</p>
          <Alert notice={notice} />
          <Field label="Username">
            <input
              ref={userInput}
              className="input"
              type="text"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              maxLength={64}
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
              }}
            />
          </Field>
          <Field label="Password">
            <input
              className="input"
              type="password"
              name="password"
              autoComplete="current-password"
              required
              maxLength={256}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
              }}
            />
          </Field>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>

      <Marquee items={TICKER} />
    </div>
  );
}
