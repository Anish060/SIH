"use client";

// Admin console: data feeds and alerts, job runner with logs, users, system health.
import React, { useEffect, useState } from "react";
import { api, Shell, Tabs, Field, Banner, Stat, ErrorBox, card, inputCls, btn, ghost, fmt } from "../lib/ui";

export default function Admin() {
  const [tab, setTab] = useState("feeds");
  return (
    <Shell title="Admin console" subtitle="Data feed status and alerts, re-processing jobs with logs, user accounts and roles, and system health." need="admin">
      <Tabs value={tab} onChange={setTab} tabs={[["feeds", "Feeds & alerts"], ["jobs", "Jobs"], ["users", "Users"], ["health", "System health"]]} />
      {tab === "feeds" && <Feeds />}
      {tab === "jobs" && <Jobs />}
      {tab === "users" && <Users />}
      {tab === "health" && <Health />}
    </Shell>
  );
}

const tone = { error: "rose", warning: "amber", info: "slate" };

function Feeds() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const load = () => api("/api/admin/feeds").then(setD).catch(setErr);
  useEffect(() => { load(); }, []);
  if (err) return <ErrorBox err={err} />;
  if (!d) return <p className="text-body-md text-on-surface-variant">Loading…</p>;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3"><button className={ghost} onClick={load}>Refresh</button>
        <span className="text-body-sm text-on-surface-variant">Near-real-time: {d.near_real_time.latest_date ? `latest ${d.near_real_time.latest_date} (${d.near_real_time.lag_days} days behind)` : d.near_real_time.note}</span></div>
      <div className="flex flex-col gap-2">
        {d.alerts.length === 0 ? <Banner tone="emerald">No alerts.</Banner> : d.alerts.map((a, i) => <Banner key={i} tone={tone[a.level]}><strong className="uppercase text-body-sm mr-2">{a.level}</strong>{a.message}</Banner>)}
      </div>
      <h3 className="font-headline-sm text-headline-sm text-primary">Input files</h3>
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-sm">
          <thead><tr className="border-b border-surface-container-high text-on-surface-variant"><th className="px-4 py-2">File</th><th className="px-4 py-2">Folder</th><th className="px-4 py-2">Coverage</th><th className="px-4 py-2">Downloaded</th><th className="px-4 py-2">Level</th><th className="px-4 py-2">Status</th></tr></thead>
          <tbody className="divide-y divide-surface-container-high">{d.inputs.map((f, i) => (
            <tr key={i}><td className="px-4 py-2 font-mono">{f.file}</td><td className="px-4 py-2 font-mono text-on-surface-variant">{f.folder.split("/").slice(-1)[0]}</td>
              <td className="px-4 py-2 font-mono">{f.time_coverage ? `${f.time_coverage[0].slice(0, 10)} → ${f.time_coverage[1].slice(0, 10)}` : "—"}</td>
              <td className="px-4 py-2 font-mono">{f.downloaded_utc?.slice(0, 16) || "—"}</td><td className="px-4 py-2 text-on-surface-variant">{f.processing_level || "—"}</td>
              <td className={`px-4 py-2 ${f.readable ? "text-emerald-700" : "text-rose-700"}`}>{f.readable ? (f.synthetic ? "readable · synthetic" : "readable") : "unreadable"}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <h3 className="font-headline-sm text-headline-sm text-primary">Inference files</h3>
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-sm">
          <thead><tr className="border-b border-surface-container-high text-on-surface-variant"><th className="px-4 py-2">File</th><th className="px-4 py-2">Dates</th><th className="px-4 py-2">Splits</th><th className="px-4 py-2">Reference</th><th className="px-4 py-2">Inputs</th><th className="px-4 py-2">Checkpoint</th></tr></thead>
          <tbody className="divide-y divide-surface-container-high">{d.basin_files.map((b) => (
            <tr key={b.file}><td className="px-4 py-2 font-mono">{b.file}</td><td className="px-4 py-2 font-mono">{b.range[0]} → {b.range[1]}</td><td className="px-4 py-2">{Object.entries(b.splits).map(([k, v]) => `${k} ${v}`).join(", ")}</td>
              <td className="px-4 py-2">{b.reference_name}</td><td className="px-4 py-2">{b.input_data}</td><td className={`px-4 py-2 ${b.checkpoint_matches_server ? "text-emerald-700" : "text-rose-700"}`}>{b.checkpoint_matches_server ? "matches" : "different"}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <p className="text-body-sm text-on-surface-variant">Artefacts: {Object.entries(d.artefacts).map(([k, v]) => `${k} ${v.present ? "✓" : "missing"}`).join(" · ")}. Set OCEANEMBED_ALERT_WEBHOOK to receive failed-job alerts as JSON POSTs.</p>
    </div>
  );
}

const KINDS = {
  fetch_period: { label: "Download inputs for a period", fields: [["mode", "reanalysis"], ["start", ""], ["end", ""], ["out_dir", "data_<start>_<end>"]] },
  basin_inference: { label: "Run inference on downloaded inputs", fields: [["data_dir", ""], ["start", ""], ["end", ""], ["reference_file", "GLORYS12V1.nc"], ["reference_name", "GLORYS12 reanalysis"]] },
  realtime_update: { label: "Near-real-time update (latest week)", fields: [] },
  evaluate: { label: "Evaluate checkpoints (writes eval_results.json)", fields: [["data_dir", ""], ["start", "2023-01-01"], ["end", "2023-01-30"]] },
  cyclone_tracks: { label: "Fetch IBTrACS tracks", fields: [["storms", "MOCHA:2023,MICHAUNG:2023"]] },
  argo_profiles: { label: "Fetch Argo float profiles", fields: [["start", ""], ["end", ""]] },
  xgb_baseline: { label: "Train XGBoost baseline", fields: [["basin_file", "basin_output/basin_2023-01-01_2023-01-30.nc"]] }
};

function Jobs() {
  const [kind, setKind] = useState("fetch_period");
  const [args, setArgs] = useState({});
  const [jobs, setJobs] = useState([]);
  const [log, setLog] = useState(null);
  const [err, setErr] = useState(null);
  const load = () => api("/api/admin/jobs").then(setJobs).catch(setErr);
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);
  const submit = () => {
    setErr(null);
    const a = {};
    KINDS[kind].fields.forEach(([k, def]) => { const v = args[`${kind}.${k}`] ?? def; if (v !== "") a[k] = v; });
    if (kind === "cyclone_tracks") a.storms = String(a.storms || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (kind === "basin_inference") a.frozen_stats = true;
    api("/api/admin/jobs", { method: "POST", body: { kind, args: a } }).then(load).catch(setErr);
  };
  const showLog = (id) => api(`/api/admin/jobs/${id}/log?tail=400`).then(setLog).catch(setErr);
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 flex flex-col gap-4`}>
        <Field label="Job"><select className={inputCls} value={kind} onChange={(e) => setKind(e.target.value)}>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></Field>
        <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          {KINDS[kind].fields.map(([k, def]) => <Field key={k} label={k}><input className={inputCls} placeholder={def} value={args[`${kind}.${k}`] ?? def} onChange={(e) => setArgs({ ...args, [`${kind}.${k}`]: e.target.value })} /></Field>)}
        </div>
        <div><button className={btn} onClick={submit}>Start job</button></div>
        <p className="text-body-sm text-on-surface-variant">Only these job types can run. Dates are validated and every path must stay inside the data root. At most two jobs run at once.</p>
      </div>
      <ErrorBox err={err} />
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-sm">
          <thead><tr className="border-b border-surface-container-high text-on-surface-variant"><th className="px-4 py-2">#</th><th className="px-4 py-2">Job</th><th className="px-4 py-2">By</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Started</th><th className="px-4 py-2">Duration</th><th className="px-4 py-2"></th></tr></thead>
          <tbody className="divide-y divide-surface-container-high">{jobs.map((j) => (
            <tr key={j.id}><td className="px-4 py-2 font-mono">{j.id}</td><td className="px-4 py-2">{j.kind} <span className="font-mono text-on-surface-variant">{j.args}</span></td><td className="px-4 py-2">{j.user}</td>
              <td className={`px-4 py-2 ${j.status === "failed" ? "text-rose-700" : j.status === "succeeded" ? "text-emerald-700" : "text-amber-700"}`}>{j.status}{j.rc !== null && j.rc !== undefined ? ` (rc ${j.rc})` : ""}</td>
              <td className="px-4 py-2 font-mono">{j.started ? new Date(j.started * 1000).toISOString().slice(0, 19).replace("T", " ") : "—"}</td>
              <td className="px-4 py-2 font-mono">{j.finished && j.started ? `${fmt(j.finished - j.started, 1)} s` : "—"}</td>
              <td className="px-4 py-2"><button className="text-secondary" onClick={() => showLog(j.id)}>Log</button></td></tr>
          ))}</tbody>
        </table>
      </div>
      {log && <pre className={`${card} p-4 text-body-sm font-mono whitespace-pre-wrap max-h-[420px] overflow-auto`}>{`Job ${log.id}\n` + log.lines.join("\n")}</pre>}
    </div>
  );
}

function Users() {
  const [users, setUsers] = useState([]);
  const [f, setF] = useState({ username: "", password: "", role: "scientist" });
  const [err, setErr] = useState(null);
  const load = () => api("/api/admin/users").then(setUsers).catch(setErr);
  useEffect(() => { load(); }, []);
  const add = () => { setErr(null); api("/api/admin/users", { method: "POST", body: f }).then(() => { setF({ ...f, username: "", password: "" }); load(); }).catch(setErr); };
  const del = (u) => api(`/api/admin/users/${encodeURIComponent(u)}`, { method: "DELETE" }).then(load).catch(setErr);
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 grid grid-cols-1 sm:grid-cols-4 gap-4 items-end`}>
        <Field label="Username"><input className={inputCls} value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field>
        <Field label="Password (8+ characters)"><input className={inputCls} type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Field label="Role"><select className={inputCls} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{["end_user", "decision_maker", "scientist", "admin"].map((r) => <option key={r}>{r}</option>)}</select></Field>
        <button className={btn} onClick={add}>Add or update user</button>
      </div>
      <ErrorBox err={err} />
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-md">
          <thead><tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant"><th className="px-5 py-2">User</th><th className="px-5 py-2">Role</th><th className="px-5 py-2">Created</th><th></th></tr></thead>
          <tbody className="divide-y divide-surface-container-high">{users.map((u) => <tr key={u.username}><td className="px-5 py-2 font-mono">{u.username}</td><td className="px-5 py-2">{u.role}</td><td className="px-5 py-2 font-mono text-body-sm">{new Date(u.created * 1000).toISOString().slice(0, 10)}</td><td className="px-5 py-2"><button className="text-rose-700 text-body-sm" onClick={() => del(u.username)}>Delete</button></td></tr>)}</tbody>
        </table>
      </div>
      <p className="text-body-sm text-on-surface-variant">Roles: end users need no account (public dashboard); decision makers see the brief; scientists also get Science and the Data Explorer; admins get everything. Role changes apply on the user&apos;s next request.</p>
    </div>
  );
}

function Health() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { const load = () => api("/api/admin/health").then(setD).catch(setErr); load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, []);
  if (err) return <ErrorBox err={err} />;
  if (!d) return <p className="text-body-md text-on-surface-variant">Loading…</p>;
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-5`}>
        <Stat label="CPU" value={fmt(d.cpu_percent, 0)} unit={`% of ${d.cpu_count} cores`} />
        <Stat label="Memory used" value={fmt(d.memory.used_percent, 0)} unit={`% of ${d.memory.total_gb} GB`} />
        <Stat label="API process" value={fmt(d.memory.process_rss_mb, 0)} unit="MB" />
        <Stat label="Disk used" value={fmt(d.disk.used_percent, 0)} unit="%" note={d.disk.path} />
        <Stat label="Uptime" value={fmt(d.uptime_s / 3600, 1)} unit="h" />
        <Stat label="Requests / 5xx" value={`${d.requests.total} / ${d.requests.server_errors}`} />
      </div>
      <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-3 gap-5`}>
        <Stat label="File cache hits / misses" value={`${d.cache.hits} / ${d.cache.misses}`} note={`hit ratio ${d.cache.hits + d.cache.misses ? fmt((100 * d.cache.hits) / (d.cache.hits + d.cache.misses), 1) : "—"}%`} />
        <Stat label="Files in memory" value={d.cache.files.length} note={d.cache.files.map((f) => `${f.file} ${f.mb_in_memory} MB`).join(" · ")} />
        <Stat label="Model" value={d.model.device.toUpperCase()} note={`checkpoint ${d.model.checkpoint_sha256.slice(0, 12)}…`} />
      </div>
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-sm">
          <thead><tr className="border-b border-surface-container-high text-on-surface-variant"><th className="px-4 py-2">Route (last {d.requests.window} requests)</th><th className="px-4 py-2">Count</th><th className="px-4 py-2">p50</th><th className="px-4 py-2">p95</th></tr></thead>
          <tbody className="divide-y divide-surface-container-high">{d.requests.routes.map((r) => <tr key={r.route}><td className="px-4 py-2 font-mono">{r.route}</td><td className="px-4 py-2">{r.n}</td><td className="px-4 py-2 font-mono">{r.p50_ms} ms</td><td className="px-4 py-2 font-mono">{r.p95_ms} ms</td></tr>)}</tbody>
        </table>
      </div>
      <p className="text-body-sm text-on-surface-variant">The map uses the stored grid directly rather than map tiles, so the relevant cache is the in-memory file cache shown above.</p>
    </div>
  );
}
