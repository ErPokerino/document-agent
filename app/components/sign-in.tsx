"use client";

import { LogIn } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { api, SIGNED_OUT_EVENT } from "../../lib/api";

type GateState = "checking" | "open" | "signed-in" | "signed-out";

/**
 * The app, or the sign-in screen when the deployment requires an account.
 *
 * While the session is being checked the app renders as usual, so the server
 * render and a machine without sign-in look exactly as before. A refusal from
 * any request later — an expired cookie — brings the screen back.
 */
export function SignInGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>("checking");

  useEffect(() => {
    let alive = true;
    const signedOut = () => setState((current) => (current === "open" ? current : "signed-out"));
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    api
      .session()
      .then((session) => {
        if (alive) setState(!session.required ? "open" : session.user ? "signed-in" : "signed-out");
      })
      // No API to ask is the app's own error to show, not a sign-in question.
      .catch(() => alive && setState("open"));
    return () => {
      alive = false;
      window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
    };
  }, []);

  if (state === "signed-out") return <SignIn />;
  return <>{children}</>;
}

function SignIn() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.signIn(username, password);
      // A fresh start: whatever the app tried while signed out failed.
      window.location.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      setBusy(false);
    }
  }

  return (
    <main className="sign-in-shell">
      <form className="sign-in-card" onSubmit={submit}>
        <p className="eyebrow">DocuFlow</p>
        <h1>Sign in</h1>
        <label className="input-label" htmlFor="sign-in-user">Username</label>
        <input id="sign-in-user" className="text-input" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
        <label className="input-label" htmlFor="sign-in-password">Password</label>
        <input id="sign-in-password" className="text-input" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
        {error && <p className="sign-in-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={busy || !username || !password}>
          <LogIn size={14} /> {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
