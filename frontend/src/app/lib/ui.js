"use client";

// Shared client helpers: signed-in session (token in localStorage, wrapped in try/catch), fetch with
// the token, authenticated file download, and small UI pieces used by the workspace pages.

import React, { useEffect, useState } from "react";

const KEY = "oceanembed_session";

export function getSession() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || "null");
    return s && s.token ? s : null;
  } catch {
    return null;
  }
}
export function setSession(s) {
  try { s ? localStorage.setItem(KEY, JSON.stringify(s)) : localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
}

export async function api(url, opts = {}) {
  const s = getSession();
  const headers = { ...(opts.headers || {}) };
  if (s) headers.Authorization = `Bearer ${s.token}`;
  if (opts.body && typeof opts.body !== "string") {
    headers["Content-Type"] = "application/json";
    opts = { ...opts, body: JSON.stringify(opts.body) };
  }
  const r = await fetch(url, { ...opts, headers });
  const isJson = (r.headers.get("content-type") || "").includes("json");
  const body = isJson ? await r.json().catch(() => ({})) : null;
  if (!r.ok) {
    const d = body?.detail;
    const e = new Error(typeof d === "string" ? d : d?.message || `HTTP ${r.status}`);
    e.status = r.status;
    e.detail = d;
    throw e;
  }
  return body;
}

export async function download(url, filename) {
  const s = getSession();
  const r = await fetch(url, { headers: s ? { Authorization: `Bearer ${s.token}` } : {} });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function useSession() {
  const [me, setMe] = useState(null);
  useEffect(() => {
    api("/api/auth/me").then(setMe).catch(() => setMe({ signed_in: false, role: "end_user", access: [] }));
  }, []);
  return me;
}

export const finite = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
export const fmt = (v, d = 1) => (finite(v) ? Number(v).toFixed(d) : "—");
export const card = "bg-surface-container-lowest rounded-xl border border-surface-container-high";
export const inputCls = "w-full bg-surface-container-lowest border border-surface-container-high rounded-xl px-3 py-2 text-body-md font-mono text-primary";
export const btn = "inline-flex items-center gap-1.5 bg-primary hover:bg-secondary text-on-primary text-body-sm font-medium px-4 py-2 rounded-xl transition disabled:opacity-50";
export const ghost = "inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-body-sm font-medium text-primary bg-surface-container-lowest border border-surface-container-high hover:bg-surface-container-low transition disabled:opacity-40";
export const PLOT_CFG = { responsive: true, displaylogo: false };

const LINKS = [
  ["/dashboard", "Dashboard", null],
  ["/brief", "Brief", "brief"],
  ["/science", "Science", "science"],
  ["/explorer", "Data Explorer", "explorer"],
  ["/admin", "Admin", "admin"]
];

export function AppNav({ me }) {
  const access = new Set(me?.access || []);
  return (
    <div className="flex items-center gap-4 text-body-sm">
      {LINKS.filter(([, , cap]) => !cap || access.has(cap)).map(([href, label]) => (
        <a key={href} href={href} className="text-on-surface-variant hover:text-primary transition">{label}</a>
      ))}
      {me?.signed_in ? (
        <button className="text-secondary hover:text-primary" onClick={() => { setSession(null); window.location.href = "/login"; }}>
          Sign out ({me.username}, {me.role.replace("_", " ")})
        </button>
      ) : (
        <a href="/login" className="text-secondary hover:text-primary">Sign in</a>
      )}
    </div>
  );
}

export function Shell({ title, subtitle, need, children }) {
  const me = useSession();
  const allowed = !need || (me?.access || []).includes(need);
  return (
    <div className="min-h-screen bg-surface text-on-surface">
      <header className="border-b border-surface-container-high bg-surface/90 backdrop-blur-xl sticky top-0 z-40 print:hidden">
        <div className="h-16 max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop flex items-center justify-between gap-6">
          <a href="/" className="font-headline-sm text-headline-sm text-primary">OceanEmbed</a>
          <AppNav me={me} />
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop py-10 flex flex-col gap-8">
        <div>
          <h1 className="font-headline-lg text-headline-lg-mobile sm:text-headline-lg text-primary">{title}</h1>
          {subtitle && <p className="mt-2 text-body-md text-on-surface-variant max-w-3xl">{subtitle}</p>}
        </div>
        {me === null ? <p className="text-body-md text-on-surface-variant">Checking access…</p> : allowed ? children : (
          <Banner tone="amber">
            {me.signed_in ? `Your role (${me.role.replace("_", " ")}) cannot open this page.` : "Sign in to open this page."}{" "}
            {!me.signed_in && <a className="underline" href="/login">Sign in</a>}
          </Banner>
        )}
      </main>
    </div>
  );
}

export function Banner({ tone = "slate", children }) {
  const cls = { rose: "bg-rose-50 border-rose-300 text-rose-900", amber: "bg-amber-50 border-amber-300 text-amber-900", slate: "bg-surface-container-low border-surface-container-high text-on-surface", emerald: "bg-emerald-50 border-emerald-300 text-emerald-900" }[tone];
  return <div className={`px-5 py-3 rounded-xl border text-body-md ${cls}`}>{children}</div>;
}

export function Stat({ label, value, unit, tone = "text-primary", note }) {
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-body-sm text-on-surface-variant">{label}</span>
      <span className={`font-data-metric text-data-metric ${tone}`}>{value}{unit && <span className="ml-1 text-body-md text-on-surface-variant">{unit}</span>}</span>
      {note && <p className="mt-1 text-body-sm text-on-surface-variant leading-relaxed">{note}</p>}
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="inline-flex flex-wrap p-1 rounded-xl bg-surface-container-low border border-surface-container-high print:hidden">
      {tabs.map(([v, l]) => (
        <button key={v} onClick={() => onChange(v)} className={`px-3 py-1.5 rounded-lg text-body-sm font-medium transition ${value === v ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-primary"}`}>{l}</button>
      ))}
    </div>
  );
}

export function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1.5 min-w-0">
      <span className="text-body-sm text-on-surface-variant">{label}</span>
      {children}
    </label>
  );
}

export function ErrorBox({ err }) {
  if (!err) return null;
  return (
    <Banner tone="amber">
      {err.message}
      {err.detail?.how_to_create && <pre className="mt-2 text-body-sm font-mono whitespace-pre-wrap">{err.detail.how_to_create}</pre>}
    </Banner>
  );
}

export function useDates() {
  const [dates, setDates] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api("/api/basin/meta").then((m) => setDates(m.dates)).catch(setErr); }, []);
  return [dates, err];
}
