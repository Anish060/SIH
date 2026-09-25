"use client";

import { useState } from "react";
import { api, setSession, card, inputCls, btn, Banner } from "../lib/ui";

export default function Login() {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const s = await api("/api/auth/login", { method: "POST", body: { username: u, password: p } });
      setSession(s);
      const dest = s.access.includes("admin") ? "/admin" : s.access.includes("science") ? "/science" : s.access.includes("brief") ? "/brief" : "/dashboard";
      window.location.href = dest;
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="min-h-screen bg-surface flex items-center justify-center px-4">
      <form onSubmit={submit} className={`${card} w-full max-w-sm p-8 flex flex-col gap-5`}>
        <div>
          <a href="/" className="font-headline-sm text-headline-sm text-primary">OceanEmbed</a>
          <p className="mt-1 text-body-sm text-on-surface-variant">Sign in for the brief, science tools, data explorer or admin console. The dashboard is open without an account.</p>
        </div>
        <input className={inputCls} placeholder="Username" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} />
        <input className={inputCls} placeholder="Password" type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} />
        {err && <Banner tone="amber">{err}</Banner>}
        <button className={btn} disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</button>
        <a href="/dashboard" className="text-body-sm text-secondary">Continue to the public dashboard</a>
      </form>
    </div>
  );
}
