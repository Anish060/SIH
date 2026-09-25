"use client";

// Science workspace: physics computed on the stored real fields (see physics.py).
import React, { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { api, Shell, Tabs, Field, Banner, Stat, ErrorBox, useDates, card, inputCls, btn, fmt, PLOT_CFG } from "../lib/ui";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const LAYOUT = { autosize: true, margin: { l: 55, r: 15, t: 30, b: 45 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", legend: { orientation: "h", x: 0, y: 1.12 } };
const MAPAX = { xaxis: { title: { text: "Longitude (°E)" }, range: [45, 105] }, yaxis: { title: { text: "Latitude (°N)" }, range: [5, 30], scaleanchor: "x" }, plot_bgcolor: "#E2E8F0" };

function arrowsTrace(a, scaleDeg, color, name) {
  const x = [], y = [];
  a.u.forEach((u, i) => {
    const v = a.v[i];
    x.push(a.lon[i], a.lon[i] + u * scaleDeg, null);
    y.push(a.lat[i], a.lat[i] + v * scaleDeg, null);
  });
  return { type: "scatter", mode: "lines", x, y, line: { color, width: 1.2 }, name, hoverinfo: "skip" };
}

export default function Science() {
  const [dates, dErr] = useDates();
  const [date, setDate] = useState(null);
  const [lat, setLat] = useState(14.5);
  const [lon, setLon] = useState(88.0);
  const [tab, setTab] = useState("currents");
  // default a few days before the end of the data so forward tools (drift, PWP) have days to run over
  useEffect(() => { if (dates?.length && !date) setDate(dates[Math.max(0, dates.length - 6)].date); }, [dates, date]);
  const common = { date, lat: Number(lat), lon: Number(lon) };
  return (
    <Shell title="Science" subtitle="Physics computed on the stored real fields: geostrophic and Ekman currents, particle drift, a 1-D storm-mixing model, TEOS-10 stratification, optimal interpolation with Argo floats, and an ML baseline. Constants are fixed at their physical values; only genuinely free parameters are adjustable." need="science">
      <ErrorBox err={dErr} />
      {dates && (
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Date">
            <select className={inputCls} value={date || ""} onChange={(e) => setDate(e.target.value)}>
              {dates.map((d) => <option key={d.date} value={d.date}>{d.date} · {d.split}</option>)}
            </select>
          </Field>
          <Field label="Latitude (°N)"><input className={inputCls} type="number" step="0.25" value={lat} onChange={(e) => setLat(e.target.value)} /></Field>
          <Field label="Longitude (°E)"><input className={inputCls} type="number" step="0.25" value={lon} onChange={(e) => setLon(e.target.value)} /></Field>
          <Tabs value={tab} onChange={setTab} tabs={[["currents", "Currents"], ["drift", "Particle drift"], ["pwp", "Storm mixing (PWP)"], ["strat", "Stratification"], ["oi", "Assimilation"], ["ml", "ML baseline"]]} />
        </div>
      )}
      {date && tab === "currents" && <Currents date={date} />}
      {date && tab === "drift" && <Drift {...common} />}
      {date && tab === "pwp" && <PWP {...common} />}
      {date && tab === "strat" && <Strat {...common} />}
      {date && tab === "oi" && <OI date={date} />}
      {tab === "ml" && <ML />}
    </Shell>
  );
}

function Currents({ date }) {
  const [scheme, setScheme] = useState("large_pond");
  const [cd, setCd] = useState(1.3);
  const [field, setField] = useState("geostrophic_speed_ms");
  const [arrows, setArrows] = useState("geostrophic");
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const run = () => { setErr(null); api(`/api/science/currents?date=${date}&drag_scheme=${scheme}&cd=${Number(cd) / 1000}`).then(setD).catch(setErr); };
  useEffect(run, [date]); // eslint-disable-line react-hooks/exhaustive-deps
  const F = { geostrophic_speed_ms: ["Geostrophic speed", "m/s", "Viridis"], observed_speed_ms: ["CMEMS surface current speed", "m/s", "Viridis"], ekman_pumping_m_per_day: ["Ekman pumping (+ up)", "m/day", "RdBu"], wind_stress_n_m2: ["Wind stress", "N/m²", "YlOrRd"] };
  const cmp = d?.comparison;
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 flex flex-wrap items-end gap-4`}>
        <Field label="Map"><select className={inputCls} value={field} onChange={(e) => setField(e.target.value)}>{Object.entries(F).map(([k, v]) => <option key={k} value={k}>{v[0]}</option>)}</select></Field>
        <Field label="Arrows"><select className={inputCls} value={arrows} onChange={(e) => setArrows(e.target.value)}><option value="geostrophic">Geostrophic</option><option value="observed">CMEMS surface current</option><option value="ekman_transport">Ekman transport</option></select></Field>
        <Field label="Drag coefficient"><select className={inputCls} value={scheme} onChange={(e) => setScheme(e.target.value)}><option value="large_pond">Large & Pond (1981)</option><option value="constant">Constant</option></select></Field>
        {scheme === "constant" && <Field label={`Cd × 10³ (${cd})`}><input type="range" min="0.8" max="2.5" step="0.1" value={cd} onChange={(e) => setCd(e.target.value)} /></Field>}
        <button className={btn} onClick={run}>Recompute</button>
      </div>
      <ErrorBox err={err} />
      {d && (
        <>
          <div className={`${card} h-[520px] p-2`}>
            <Plot data={[
              { type: "heatmap", x: d.lons, y: d.lats, z: d[field], colorscale: F[field][2], reversescale: field === "ekman_pumping_m_per_day", zmid: field === "ekman_pumping_m_per_day" ? 0 : undefined, colorbar: { title: { text: F[field][1] } }, hovertemplate: `%{y:.2f}°N %{x:.2f}°E<br>%{z:.3f} ${F[field][1]}<extra></extra>` },
              arrowsTrace(d.arrows[arrows], arrows === "ekman_transport" ? 0.4 : 4, "#0F172A", arrows)
            ]} layout={{ ...LAYOUT, ...MAPAX, showlegend: false }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
          </div>
          {cmp && (
            <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-5 gap-5`}>
              <Stat label="Cells compared" value={cmp.n_cells.toLocaleString()} />
              <Stat label="Correlation u (geo vs CMEMS)" value={fmt(cmp.corr_u, 2)} />
              <Stat label="Correlation v" value={fmt(cmp.corr_v, 2)} />
              <Stat label="RMS speed geo / CMEMS" value={`${fmt(cmp.rms_geo_speed_ms, 3)} / ${fmt(cmp.rms_obs_speed_ms, 3)}`} unit="m/s" />
              <Stat label="RMS vector difference" value={fmt(cmp.rms_vector_diff_ms, 3)} unit="m/s" />
            </div>
          )}
          <p className="text-body-sm text-on-surface-variant leading-relaxed">{d.method.geostrophic}. {d.method.ekman}. {d.method.note} Arrows: every 6th cell; geostrophic/CMEMS arrows 4° per m/s, Ekman transport 0.4° per m²/s.</p>
        </>
      )}
    </div>
  );
}

function Drift({ date, lat, lon }) {
  const [p, setP] = useState({ days: 3, n_particles: 100, spread_km: 5, diffusivity_m2s: 10, windage: 0, dt_hours: 1, seed: 0 });
  const [d, setD] = useState(null);
  const [bg, setBg] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api(`/api/basin/day?date=${date}&source=model`).then(setBg).catch(() => {}); }, [date]);
  const run = () => { setBusy(true); setErr(null); api("/api/science/drift", { method: "POST", body: { date, lat, lon, ...Object.fromEntries(Object.entries(p).map(([k, v]) => [k, Number(v)])) } }).then(setD).catch(setErr).finally(() => setBusy(false)); };
  const set = (k) => (e) => setP({ ...p, [k]: e.target.value });
  const tracks = () => {
    const x = [], y = [];
    for (let j = 0; j < d.lat[0].length; j++) { d.lat.forEach((row, i) => { x.push(d.lon[i][j]); y.push(row[j]); }); x.push(null); y.push(null); }
    return { type: "scatter", mode: "lines", x, y, line: { color: "rgba(225,29,72,0.35)", width: 1 }, hoverinfo: "skip", name: "tracks" };
  };
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-4 items-end`}>
        <Field label="Days"><input className={inputCls} type="number" step="0.5" value={p.days} onChange={set("days")} /></Field>
        <Field label="Particles"><input className={inputCls} type="number" value={p.n_particles} onChange={set("n_particles")} /></Field>
        <Field label="Release radius (km)"><input className={inputCls} type="number" value={p.spread_km} onChange={set("spread_km")} /></Field>
        <Field label="Diffusivity K (m²/s)"><input className={inputCls} type="number" value={p.diffusivity_m2s} onChange={set("diffusivity_m2s")} /></Field>
        <Field label="Windage (×U10)"><input className={inputCls} type="number" step="0.005" value={p.windage} onChange={set("windage")} /></Field>
        <Field label="Time step (h)"><input className={inputCls} type="number" step="0.25" value={p.dt_hours} onChange={set("dt_hours")} /></Field>
        <Field label="Seed"><input className={inputCls} type="number" value={p.seed} onChange={set("seed")} /></Field>
        <button className={btn} onClick={run} disabled={busy}>{busy ? "Running…" : "Release"}</button>
      </div>
      <ErrorBox err={err} />
      <div className={`${card} h-[520px] p-2`}>
        <Plot data={[
          bg && { type: "heatmap", x: bg.lons, y: bg.lats, z: bg.fields.sst_c, colorscale: "Blues", showscale: false, opacity: 0.35, hoverinfo: "skip" },
          d && tracks(),
          d && { type: "scatter", mode: "markers", x: d.lon[d.lon.length - 1], y: d.lat[d.lat.length - 1], marker: { size: 4, color: "#9F1239" }, name: "final" },
          { type: "scatter", mode: "markers", x: [lon], y: [lat], marker: { size: 12, symbol: "x", color: "#0F172A" }, name: "release" }
        ].filter(Boolean)} layout={{ ...LAYOUT, ...MAPAX, showlegend: false }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
      </div>
      {d && (
        <>
          <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-4 gap-5`}>
            <Stat label="Mean displacement" value={fmt(d.summary.mean_displacement_km, 1)} unit="km" />
            <Stat label="Centroid" value={`${fmt(d.summary.centroid[0], 2)}°N ${fmt(d.summary.centroid[1], 2)}°E`} />
            <Stat label="RMS spread" value={fmt(d.summary.rms_spread_km, 1)} unit="km" />
            <Stat label="Stopped (land / edge of data)" value={`${fmt(d.summary.stopped_fraction * 100, 0)}%`} />
          </div>
          <p className="text-body-sm text-on-surface-variant">{d.method}</p>
        </>
      )}
    </div>
  );
}

function PWP({ date, lat, lon }) {
  const [p, setP] = useState({ days: 3, forcing: "era5", wind_speed_ms: 25, wind_toward_deg: 0, heat_flux_wm2: 0, initial: "model", rb_crit: 0.65, rg_crit: 0.25, drag_scheme: "large_pond" });
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setP({ ...p, [k]: e.target.value });
  const run = () => {
    setBusy(true); setErr(null);
    const body = { date, lat, lon, ...p };
    ["days", "wind_speed_ms", "wind_toward_deg", "heat_flux_wm2", "rb_crit", "rg_crit"].forEach((k) => (body[k] = Number(body[k])));
    api("/api/science/pwp", { method: "POST", body }).then(setD).catch(setErr).finally(() => setBusy(false));
  };
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-4 items-end`}>
        <Field label="Days"><input className={inputCls} type="number" value={p.days} onChange={set("days")} /></Field>
        <Field label="Wind forcing"><select className={inputCls} value={p.forcing} onChange={set("forcing")}><option value="era5">ERA5 at this cell</option><option value="constant">Constant (what-if)</option></select></Field>
        {p.forcing === "constant" && <Field label="Wind speed (m/s)"><input className={inputCls} type="number" value={p.wind_speed_ms} onChange={set("wind_speed_ms")} /></Field>}
        {p.forcing === "constant" && <Field label="Blowing toward (°)"><input className={inputCls} type="number" value={p.wind_toward_deg} onChange={set("wind_toward_deg")} /></Field>}
        <Field label="Net heat flux (W/m², + into ocean)"><input className={inputCls} type="number" value={p.heat_flux_wm2} onChange={set("heat_flux_wm2")} /></Field>
        <Field label="Initial profile"><select className={inputCls} value={p.initial} onChange={set("initial")}><option value="model">OceanEmbed prediction</option><option value="reference">Reference</option></select></Field>
        <Field label={`Bulk Ri critical (${p.rb_crit})`}><input type="range" min="0.3" max="1.2" step="0.05" value={p.rb_crit} onChange={set("rb_crit")} /></Field>
        <Field label={`Gradient Ri critical (${p.rg_crit})`}><input type="range" min="0.1" max="0.6" step="0.05" value={p.rg_crit} onChange={set("rg_crit")} /></Field>
        <Field label="Drag coefficient"><select className={inputCls} value={p.drag_scheme} onChange={set("drag_scheme")}><option value="large_pond">Large & Pond (1981)</option><option value="constant">Constant 1.3×10⁻³</option></select></Field>
        <button className={btn} onClick={run} disabled={busy}>{busy ? "Running…" : "Run PWP"}</button>
      </div>
      <ErrorBox err={err} />
      {d && (
        <>
          <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-4 gap-5`}>
            <Stat label="Simulated SST change" value={fmt(d.simulated_dsst_c, 2)} unit="°C" tone="text-secondary" />
            <Stat label="Observed SST change (OSTIA)" value={fmt(d.observed?.observed_dsst_c, 2)} unit="°C" note={d.observed ? `${d.observed.from} → ${d.observed.to}` : "needs inference files for both days"} />
            <Stat label="Mixed layer, start → end" value={`${fmt(d.series.mld_m[0], 0)} → ${fmt(d.series.mld_m[d.series.mld_m.length - 1], 0)}`} unit="m" />
            <Stat label="Run time" value={fmt(d.runtime_s, 2)} unit="s" note={`Cell ${d.cell.lat}°N ${d.cell.lon}°E`} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className={`${card} h-[340px] p-2`}>
              <Plot data={[
                { type: "scatter", x: d.series.hours, y: d.series.sst_c, name: "SST (°C)", line: { color: "#00B1C9" } },
                { type: "scatter", x: d.series.hours, y: d.series.mld_m, name: "Mixed layer (m)", yaxis: "y2", line: { color: "#7C3AED", dash: "dash" } }
              ]} layout={{ ...LAYOUT, xaxis: { title: { text: "Hours" } }, yaxis: { title: { text: "SST (°C)" } }, yaxis2: { title: { text: "MLD (m)" }, overlaying: "y", side: "right", autorange: "reversed" } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
            </div>
            <div className={`${card} h-[340px] p-2`}>
              <Plot data={[
                { type: "scatter", x: d.profile.initial_c, y: d.profile.z_m, name: "Initial", line: { color: "#94A3B8" } },
                { type: "scatter", x: d.profile.final_c, y: d.profile.z_m, name: "After forcing", line: { color: "#E11D48" } }
              ]} layout={{ ...LAYOUT, xaxis: { title: { text: "Temperature (°C)" } }, yaxis: { title: { text: "Depth (m)" }, autorange: "reversed", range: [250, 0] } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
            </div>
          </div>
          <p className="text-body-sm text-on-surface-variant leading-relaxed">{d.method.model}. Initial temperature: {d.method.initial_temperature}; salinity: {d.method.salinity}. Forcing: {d.method.forcing}. {d.method.heat_flux}. {d.method.limits}</p>
        </>
      )}
    </div>
  );
}

function Strat({ date, lat, lon }) {
  const [source, setSource] = useState("reference");
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { setErr(null); api(`/api/science/stratification?date=${date}&lat=${lat}&lon=${lon}&source=${source}`).then(setD).catch(setErr); }, [date, lat, lon, source]);
  const P = (x, name, xt, extra = {}) => ({ type: "scatter", mode: "lines+markers", x, y: d.depth_m, name, ...extra });
  return (
    <div className="flex flex-col gap-5">
      <div className="flex gap-3 items-end">
        <Field label="Temperature from"><select className={inputCls} value={source} onChange={(e) => setSource(e.target.value)}><option value="reference">Reference (with currents → Ri)</option><option value="model">OceanEmbed prediction</option></select></Field>
      </div>
      <ErrorBox err={err} />
      {d && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              [[P(d.pt_c, "θ (°C)")], "Potential temperature (°C)"],
              [[P(d.sp_psu, "S (PSU)", null, { line: { color: "#0E7490" } })], "Salinity (PSU)"],
              [[P(d.sigma0_kg_m3, "σ0", null, { line: { color: "#7C3AED" } })], "σ0 (kg/m³)"],
              [[{ type: "scatter", mode: "lines+markers", x: d.n2_s2, y: d.z_mid_m, name: "N²", line: { color: "#EA580C" } }], "N² (s⁻²)"]
            ].map(([tr, t], i) => (
              <div key={i} className={`${card} h-[320px] p-2`}>
                <Plot data={tr} layout={{ ...LAYOUT, showlegend: false, title: { text: t, font: { size: 12 } }, yaxis: { title: { text: "Depth (m)" }, autorange: "reversed" } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
              </div>
            ))}
          </div>
          {d.ri && (
            <div className={`${card} h-[320px] p-2`}>
              <Plot data={[{ type: "scatter", mode: "lines+markers", x: d.ri.map((v) => (v === null ? null : Math.max(v, 1e-3))), y: d.z_mid_m, line: { color: "#0F172A" } }]}
                layout={{ ...LAYOUT, showlegend: false, title: { text: "Gradient Richardson number (log scale)", font: { size: 12 } }, xaxis: { type: "log" }, yaxis: { title: { text: "Depth (m)" }, autorange: "reversed" },
                  shapes: [{ type: "line", x0: 0.25, x1: 0.25, yref: "paper", y0: 0, y1: 1, line: { color: "#E11D48", dash: "dot" } }] }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
            </div>
          )}
          <p className="text-body-sm text-on-surface-variant leading-relaxed">{d.notes.equation_of_state}. Salinity: {d.notes.salinity}. {d.notes.ri}. Cell {d.cell.lat}°N {d.cell.lon}°E.</p>
        </>
      )}
    </div>
  );
}

function OI({ date }) {
  const [p, setP] = useState({ depth_m: 100, window_days: 5, length_km: 150, sigma_b: 0.8, sigma_o: 0.3 });
  const [d, setD] = useState(null);
  const [show, setShow] = useState("increment_c");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setP({ ...p, [k]: e.target.value });
  const run = () => { setBusy(true); setErr(null); api("/api/science/assimilate", { method: "POST", body: { date, ...Object.fromEntries(Object.entries(p).map(([k, v]) => [k, Number(v)])) } }).then(setD).catch(setErr).finally(() => setBusy(false)); };
  return (
    <div className="flex flex-col gap-5">
      <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 items-end`}>
        <Field label="Depth (m)"><select className={inputCls} value={p.depth_m} onChange={set("depth_m")}>{[0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000].map((z) => <option key={z}>{z}</option>)}</select></Field>
        <Field label="Time window (± days)"><input className={inputCls} type="number" value={p.window_days} onChange={set("window_days")} /></Field>
        <Field label="Correlation length L (km)"><input className={inputCls} type="number" value={p.length_km} onChange={set("length_km")} /></Field>
        <Field label="Background error σb (°C)"><input className={inputCls} type="number" step="0.1" value={p.sigma_b} onChange={set("sigma_b")} /></Field>
        <Field label="Observation error σo (°C)"><input className={inputCls} type="number" step="0.05" value={p.sigma_o} onChange={set("sigma_o")} /></Field>
        <button className={btn} onClick={run} disabled={busy}>{busy ? "Running…" : "Assimilate"}</button>
      </div>
      <ErrorBox err={err} />
      {d && (
        <>
          {d.synthetic_obs && <Banner tone="rose">These observations come from a synthetic test fixture, not real Argo floats.</Banner>}
          <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-4 gap-5`}>
            <Stat label="Argo values used" value={d.stats.n_obs} />
            <Stat label="Background RMSE at floats" value={fmt(d.stats.rmse_background_c, 3)} unit="°C" note={`bias ${fmt(d.stats.bias_background_c, 3)} °C`} />
            <Stat label="Leave-one-out analysis RMSE" value={fmt(d.stats.rmse_loo_analysis_c, 3)} unit="°C" tone="text-secondary" note="each float predicted without itself" />
            <Field label="Map"><select className={inputCls} value={show} onChange={(e) => setShow(e.target.value)}><option value="increment_c">Increment</option><option value="analysis_c">Analysis</option></select></Field>
          </div>
          <div className={`${card} h-[500px] p-2`}>
            <Plot data={[
              { type: "heatmap", x: d.lons, y: d.lats, z: d[show], colorscale: show === "increment_c" ? "RdBu" : "Turbo", reversescale: show === "increment_c", zmid: show === "increment_c" ? 0 : undefined, colorbar: { title: { text: "°C" } } },
              { type: "scatter", mode: "markers", x: d.observations.map((o) => o.lon), y: d.observations.map((o) => o.lat), marker: { size: 7, color: "#0F172A", symbol: "circle-open" }, text: d.observations.map((o) => `obs ${o.value_c} · bg ${o.background_c} · LOO ${o.loo_residual_c}`), hoverinfo: "text" }
            ]} layout={{ ...LAYOUT, ...MAPAX, showlegend: false }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
          </div>
          <p className="text-body-sm text-on-surface-variant">{d.method}</p>
        </>
      )}
    </div>
  );
}

function ML() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api("/api/science/xgb").then(setD).catch(setErr); }, []);
  if (err) return <ErrorBox err={err} />;
  if (!d) return null;
  const rows = [["XGBoost", d.xgboost], ["OceanEmbed CNN", d.oceanembed_cnn]];
  return (
    <div className="flex flex-col gap-5">
      {String(d.input_data).includes("SYNTHETIC") && <Banner tone="rose">Trained on a synthetic test fixture; these scores mean nothing for the real ocean.</Banner>}
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-md">
          <thead><tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant"><th className="px-5 py-3">Model</th><th className="px-5 py-3">RMSE (m)</th><th className="px-5 py-3">MAE (m)</th><th className="px-5 py-3">Bias (m)</th><th className="px-5 py-3">R²</th><th className="px-5 py-3">Test cells</th></tr></thead>
          <tbody>{rows.map(([n, s]) => <tr key={n} className="border-b border-surface-container-high"><td className="px-5 py-3 text-primary">{n}</td><td className="px-5 py-3 font-mono">{fmt(s.rmse_m, 2)}</td><td className="px-5 py-3 font-mono">{fmt(s.mae_m, 2)}</td><td className="px-5 py-3 font-mono">{fmt(s.bias_m, 2)}</td><td className="px-5 py-3 font-mono">{fmt(s.r2, 3)}</td><td className="px-5 py-3 font-mono">{s.n.toLocaleString()}</td></tr>)}</tbody>
        </table>
      </div>
      <div className={`${card} h-[300px] p-2`}>
        <Plot data={[{ type: "bar", x: Object.keys(d.feature_importance), y: Object.values(d.feature_importance), marker: { color: "#00B1C9" } }]} layout={{ ...LAYOUT, showlegend: false, title: { text: "XGBoost feature importance", font: { size: 12 } } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
      </div>
      <p className="text-body-sm text-on-surface-variant">Target: {d.target}. Trained on {d.train_days} training days ({d.n_train.toLocaleString()} cells), tested on {d.test_days} held-out/independent days. {d.note}</p>
    </div>
  );
}
