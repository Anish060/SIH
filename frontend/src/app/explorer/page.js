"use client";

// Data Explorer: every input/output file with metadata, point time series and profile downloads.
import React, { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { api, download, Shell, Tabs, Field, Banner, ErrorBox, useDates, card, inputCls, btn, ghost, fmt, PLOT_CFG } from "../lib/ui";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const LAYOUT = { autosize: true, margin: { l: 55, r: 15, t: 30, b: 45 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", legend: { orientation: "h", x: 0, y: 1.12 } };

export default function Explorer() {
  const [tab, setTab] = useState("files");
  return (
    <Shell title="Data Explorer" subtitle="Every file the system reads or writes, with its source product, processing level, coverage and checksum; plus point time series and vertical profiles you can download." need="explorer">
      <Tabs value={tab} onChange={setTab} tabs={[["files", "Files & metadata"], ["series", "Time series"], ["profile", "Profiles"]]} />
      {tab === "files" && <Files />}
      {tab === "series" && <Series />}
      {tab === "profile" && <Profile />}
    </Shell>
  );
}

function Files() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(null);
  useEffect(() => { api("/api/explorer/files").then(setD).catch(setErr); }, []);
  const show = (f) => { setOpen(f.path); setDetail(null); api(`/api/explorer/file?path=${encodeURIComponent(f.path)}`).then(setDetail).catch(setErr); };
  if (err) return <ErrorBox err={err} />;
  if (!d) return <p className="text-body-md text-on-surface-variant">Loading…</p>;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-body-sm text-on-surface-variant">Data root: <span className="font-mono">{d.data_root}</span>. Processing levels: OSTIA is L4 (gap-free analysis); CMEMS, GLORYS and Mercator are model analyses/reanalyses with data assimilation; ERA5 is an atmospheric reanalysis; Argo profiles are in-situ observations. These products carry no single instrument calibration date; the product/dataset ID and download time identify the exact version.</p>
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-sm">
          <thead><tr className="border-b border-surface-container-high text-on-surface-variant"><th className="px-4 py-2">File</th><th className="px-4 py-2">Folder</th><th className="px-4 py-2">Size</th><th className="px-4 py-2">Coverage</th><th className="px-4 py-2">Processing level / source</th><th className="px-4 py-2"></th></tr></thead>
          <tbody className="divide-y divide-surface-container-high">
            {d.files.map((f) => (
              <React.Fragment key={f.path}>
                <tr className={f.readable === false ? "bg-rose-50" : ""}>
                  <td className="px-4 py-2 font-mono text-primary">{f.name}{f.attrs?.fixture === "synthetic" && <span className="ml-2 text-rose-700">synthetic</span>}</td>
                  <td className="px-4 py-2 font-mono text-on-surface-variant">{f.folder.split("/").slice(-2).join("/")}</td>
                  <td className="px-4 py-2">{fmt(f.size_mb, 1)} MB</td>
                  <td className="px-4 py-2 font-mono">{f.time_coverage ? `${f.time_coverage[0].slice(0, 10)} → ${f.time_coverage[1].slice(0, 10)} (${f.time_coverage[2]})` : "—"}</td>
                  <td className="px-4 py-2 text-on-surface-variant">{f.readable === false ? `unreadable: ${f.error}` : f.attrs?.processing_level || f.attrs?.oceanembed_source || f.attrs?.title || f.attrs?.source || (f.kind === "json" ? "JSON artefact" : "—")}</td>
                  <td className="px-4 py-2"><button className="text-secondary" onClick={() => (open === f.path ? setOpen(null) : show(f))}>{open === f.path ? "Hide" : "Metadata"}</button></td>
                </tr>
                {open === f.path && (
                  <tr><td colSpan={6} className="px-4 py-3 bg-surface-container-low">
                    {!detail ? "Loading…" : (
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        <div>
                          <p className="font-medium text-primary">sha256</p><p className="font-mono break-all">{detail.sha256}</p>
                          <p className="mt-2 font-medium text-primary">Dimensions</p><p className="font-mono">{JSON.stringify(detail.dims || {})}</p>
                          <p className="mt-2 font-medium text-primary">Global attributes</p>
                          <dl className="font-mono text-body-sm">{Object.entries(detail.attrs || {}).map(([k, v]) => <div key={k}><dt className="inline text-on-surface-variant">{k}: </dt><dd className="inline break-all">{v}</dd></div>)}</dl>
                        </div>
                        <div>
                          <p className="font-medium text-primary">Variables</p>
                          <table className="w-full font-mono text-body-sm"><tbody>{(detail.variables || []).map((v) => <tr key={v.name}><td className="pr-3">{v.name}</td><td className="pr-3 text-on-surface-variant">({v.dims.join(", ")})</td><td className="pr-3">{v.units || ""}</td><td className="text-on-surface-variant">{v.long_name || ""}</td></tr>)}</tbody></table>
                        </div>
                      </div>
                    )}
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Series() {
  const [vars, setVars] = useState([]);
  const [q, setQ] = useState({ lat: 14.5, lon: 88.0, var: "pred_temp_c", depth_m: 100 });
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api("/api/explorer/variables").then(setVars).catch(setErr); }, []);
  const v = vars.find((x) => x.name === q.var);
  const url = (f) => `/api/explorer/series?lat=${q.lat}&lon=${q.lon}&var=${q.var}&depth_m=${q.depth_m}&fmt=${f}`;
  const run = () => { setErr(null); api(url("json")).then(setD).catch(setErr); };
  const set = (k) => (e) => setQ({ ...q, [k]: e.target.value });
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-6 gap-4 items-end`}>
        <Field label="Latitude"><input className={inputCls} type="number" step="0.25" value={q.lat} onChange={set("lat")} /></Field>
        <Field label="Longitude"><input className={inputCls} type="number" step="0.25" value={q.lon} onChange={set("lon")} /></Field>
        <Field label="Variable"><select className={inputCls} value={q.var} onChange={set("var")}>{vars.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}</select></Field>
        {v?.has_depth && <Field label="Depth (m)"><select className={inputCls} value={q.depth_m} onChange={set("depth_m")}>{[0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000].map((z) => <option key={z}>{z}</option>)}</select></Field>}
        <button className={btn} onClick={run}>Plot</button>
        <button className={ghost} onClick={() => download(url("csv"), `${q.var}_${q.lat}_${q.lon}.csv`).catch(setErr)}>Download CSV</button>
      </div>
      {v && <p className="text-body-sm text-on-surface-variant">{v.long_name} ({v.units || "no units"})</p>}
      <ErrorBox err={err} />
      {d && (
        <>
          <div className={`${card} h-[360px] p-2`}>
            <Plot data={[{ type: "scatter", mode: "lines+markers", x: d.rows.map((r) => r.date), y: d.rows.map((r) => r.value), marker: { color: d.rows.map((r) => (r.split === "train" ? "#94A3B8" : r.split === "heldout" ? "#00B1C9" : "#EA580C")) }, line: { color: "#CBD5E1" } }]}
              layout={{ ...LAYOUT, showlegend: false, yaxis: { title: { text: `${d.variable} (${d.units})` } } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
          </div>
          <p className="text-body-sm text-on-surface-variant">Grey: training days · teal: held-out · orange: independent. Nearest predicted cell: {d.rows[0].cell_lat}°N {d.rows[0].cell_lon}°E ({d.rows[0].distance_km} km).</p>
        </>
      )}
    </div>
  );
}

function Profile() {
  const [dates, dErr] = useDates();
  const [q, setQ] = useState({ date: null, lat: 14.5, lon: 88.0 });
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { if (dates?.length && !q.date) setQ((x) => ({ ...x, date: dates[dates.length - 1].date })); }, [dates, q.date]);
  const url = (f) => `/api/explorer/profile?date=${q.date}&lat=${q.lat}&lon=${q.lon}&fmt=${f}`;
  const run = () => { setErr(null); api(url("json")).then(setD).catch(setErr); };
  const set = (k) => (e) => setQ({ ...q, [k]: e.target.value });
  const col = d?.columns || {};
  const P = (k, name, color, dash) => col[k] && { type: "scatter", mode: "lines+markers", x: col[k], y: col.depth_m, name, line: { color, dash } };
  return (
    <div className="flex flex-col gap-5">
      <ErrorBox err={dErr} />
      {dates && (
        <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-6 gap-4 items-end`}>
          <Field label="Date"><select className={inputCls} value={q.date || ""} onChange={set("date")}>{dates.map((x) => <option key={x.date}>{x.date}</option>)}</select></Field>
          <Field label="Latitude"><input className={inputCls} type="number" step="0.25" value={q.lat} onChange={set("lat")} /></Field>
          <Field label="Longitude"><input className={inputCls} type="number" step="0.25" value={q.lon} onChange={set("lon")} /></Field>
          <button className={btn} onClick={run}>Plot</button>
          <button className={ghost} onClick={() => download(url("csv"), `profile_${q.date}.csv`).catch(setErr)}>CSV</button>
          <button className={ghost} onClick={() => download(url("nc"), `profile_${q.date}.nc`).catch(setErr)}>NetCDF</button>
        </div>
      )}
      <ErrorBox err={err} />
      {d && (
        <>
          {String(d.input_data).includes("SYNTHETIC") && <Banner tone="rose">Synthetic test fixture, not observations.</Banner>}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className={`${card} h-[360px] p-2`}><Plot data={[P("pred_temp_c", "OceanEmbed θ", "#00B1C9"), P("ref_temp_c", `${d.reference} θ`, "#EA580C", "dash")].filter(Boolean)} layout={{ ...LAYOUT, xaxis: { title: { text: "°C" } }, yaxis: { autorange: "reversed", title: { text: "Depth (m)" } } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} /></div>
            <div className={`${card} h-[360px] p-2`}><Plot data={[P("ref_so_psu", "Salinity", "#0E7490")].filter(Boolean)} layout={{ ...LAYOUT, xaxis: { title: { text: "PSU" } }, yaxis: { autorange: "reversed" } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} /></div>
            <div className={`${card} h-[360px] p-2`}><Plot data={[P("ref_sigma0_kg_m3", "σ0 (TEOS-10)", "#7C3AED")].filter(Boolean)} layout={{ ...LAYOUT, xaxis: { title: { text: "kg/m³" } }, yaxis: { autorange: "reversed" } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} /></div>
          </div>
          <p className="text-body-sm text-on-surface-variant">Cell {d.cell_lat}°N {d.cell_lon}°E from {d.source_file}. Density uses the {d.salinity_for_density}.</p>
        </>
      )}
    </div>
  );
}
