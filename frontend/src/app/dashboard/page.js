"use client";

// OceanEmbed dashboard. Every number on this page comes from the API, which reads
// files produced from real satellite/reanalysis inputs (basin_inference.py,
// kaggle_oceanembed_eval.py, fetch_cyclone_tracks.py). When a file is missing the
// section says which command creates it; nothing is filled in with example values.

import React, { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import BasinAnalysis from "./BasinAnalysis";
import { AppNav, useSession } from "../lib/ui";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const card = "bg-surface-container-lowest rounded-xl border border-surface-container-high";
const ghostButton =
  "inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-body-sm font-medium text-primary bg-surface-container-lowest border border-surface-container-high hover:bg-surface-container-low transition disabled:opacity-40";
const primaryButton =
  "inline-flex items-center gap-1.5 bg-primary hover:bg-secondary text-on-primary text-body-sm font-medium px-4 py-2 rounded-xl transition disabled:opacity-50";
const selectCls = "bg-surface-container-lowest border border-surface-container-high rounded-xl px-3 py-2 text-body-md text-primary";
const MODEL_COLOR = "#00B1C9";
const REF_COLOR = "#EA580C";
const PLOT_CFG = { responsive: true, displaylogo: false };
const SPLIT_LABEL = { train: "training day", heldout: "held-out", independent: "independent" };

const finite = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
const fmt = (v, d = 1) => (finite(v) ? Number(v).toFixed(d) : "—");
const signed = (v, d = 2) => (finite(v) ? `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(d)}` : "—");

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = body.detail;
    const err = new Error(typeof d === "string" ? d : d?.message || `HTTP ${r.status}`);
    err.detail = d;
    err.status = r.status;
    throw err;
  }
  return body;
}

// =============================================================================
export default function OceanEmbedApp() {
  const me = useSession();
  const [health, setHealth] = useState(null);
  const [meta, setMeta] = useState(null);
  const [metaErr, setMetaErr] = useState(null);
  const [places, setPlaces] = useState([]);
  const [date, setDate] = useState(null);
  const [probe, setProbe] = useState({ lat: 14.5, lon: 88.0, name: "Central Bay of Bengal" });
  const [dayModel, setDayModel] = useState(null);
  const [dayRef, setDayRef] = useState(null);
  const [point, setPoint] = useState(null);
  const [pointErr, setPointErr] = useState(null);
  const [depthIdx, setDepthIdx] = useState(7);
  const [mapField, setMapField] = useState("sst_c");
  const [tab, setTab] = useState("cyclone");

  useEffect(() => {
    getJSON("/api/health").then(setHealth).catch(() => setHealth(null));
    getJSON("/api/places").then(setPlaces).catch(() => {});
    getJSON("/api/basin/meta")
      .then((m) => {
        setMeta(m);
        const order = ["independent", "heldout", "train"];
        const pick = order.map((s) => m.dates.filter((d) => d.split === s)).find((a) => a.length);
        setDate(pick[pick.length - 1].date);
      })
      .catch((e) => setMetaErr(e));
  }, []);

  useEffect(() => {
    if (!date) return;
    setDayModel(null);
    setDayRef(null);
    getJSON(`/api/basin/day?date=${date}&source=model`).then(setDayModel).catch(() => {});
    getJSON(`/api/basin/day?date=${date}&source=reference`).then(setDayRef).catch(() => {});
  }, [date]);

  useEffect(() => {
    if (!date) return;
    setPointErr(null);
    getJSON(`/api/point?date=${date}&lat=${probe.lat}&lon=${probe.lon}`)
      .then(setPoint)
      .catch((e) => {
        setPoint(null);
        setPointErr(e.message);
      });
  }, [date, probe]);

  const dateInfo = meta?.dates.find((d) => d.date === date);
  const refName = dateInfo?.reference_name || "reference";
  const isFixture = String(dateInfo?.input_data || "").toUpperCase().includes("SYNTHETIC");

  return (
    <div className="min-h-screen bg-surface text-on-surface flex flex-col">
      <header className="fixed top-0 inset-x-0 z-50 bg-surface/90 backdrop-blur-xl border-b border-surface-container-high/60">
        <div className="h-16 max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop flex items-center justify-between gap-6">
          <div className="flex items-center gap-10">
            <a href="/" className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-primary flex items-center justify-center">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24">
                  <path d="M2 15C5 12 8 18 12 15C16 12 19 18 22 15" stroke="#FFFFFF" strokeLinecap="round" strokeWidth="2.2"></path>
                  <ellipse cx="12" cy="12" rx="9" ry="4.5" stroke="#00B1C9" strokeDasharray="2 2" strokeWidth="1.6" transform="rotate(-25 12 12)"></ellipse>
                </svg>
              </div>
              <span className="font-headline-sm text-headline-sm text-primary">OceanEmbed</span>
            </a>
            <nav className="hidden lg:flex items-center gap-6 text-body-md text-on-surface-variant">
              {[["probe", "Probe"], ["insights", "Insights"], ["sensitivity", "What-if"], ["twin", "3D"], ["basin", "Basin"], ["replay", "Cyclones"], ["embedding", "Embedding"], ["validation", "Validation"]].map(([id, l]) => (
                <a key={id} href={`#${id}`} className="hover:text-primary transition">{l}</a>
              ))}
            </nav>
          </div>
          <div className="hidden xl:block"><AppNav me={me} /></div>
          <span className="hidden sm:inline-flex items-center gap-2 text-body-sm text-on-surface-variant" title={health?.checkpoint_sha256}>
            <span className={`w-2 h-2 rounded-full ${health ? "bg-emerald-500" : "bg-amber-500"}`}></span>
            {health ? `Model online · ${health.device.toUpperCase()} · ${health.total_parameters.toLocaleString()} parameters` : "Backend not reachable"}
          </span>
        </div>
      </header>

      <main className="flex-1 w-full max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop pt-28 pb-24 flex flex-col gap-20">
        <div className="flex flex-col gap-6">
          <div className="max-w-3xl">
            <p className="font-label-technical text-label-technical uppercase tracking-wider text-secondary">North Indian Ocean · 5–30°N, 45–105°E · 0.25°</p>
            <h1 className="mt-3 font-headline-lg text-headline-lg-mobile sm:text-headline-lg text-primary">Subsurface ocean temperature, reconstructed from satellite data</h1>
          </div>

          {metaErr ? (
            <MissingData err={metaErr} />
          ) : (
            meta && (
              <div className="flex flex-wrap items-end gap-4">
                <label className="flex flex-col gap-1.5">
                  <span className="text-body-sm text-on-surface-variant">Date</span>
                  <select value={date || ""} onChange={(e) => setDate(e.target.value)} className={selectCls}>
                    {meta.dates.map((d) => (
                      <option key={d.date} value={d.date}>{d.date} · {SPLIT_LABEL[d.split] || d.split}</option>
                    ))}
                  </select>
                </label>
                <div className="flex flex-wrap gap-2">
                  {places.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => setProbe({ lat: p.lat, lon: p.lon, name: p.name })}
                      className={`px-4 py-2 rounded-xl text-body-md border transition ${probe.name === p.name ? "bg-primary text-on-primary border-primary" : "bg-surface-container-lowest text-on-surface border-surface-container-high hover:border-outline-variant"}`}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>
            )
          )}

          {isFixture && (
            <Banner tone="rose"><strong>Synthetic test fixture.</strong> These files were made from idealised test inputs to check the pipeline. They are not observations; do not present these numbers.</Banner>
          )}
          {dateInfo?.split === "train" && (
            <Banner tone="amber">This date was in the training period: the model has seen the reference for it, so agreement here is not evidence of skill.</Banner>
          )}
          {dateInfo?.split === "independent" && (
            <Banner tone="slate">This date is outside the training period ({refName} used for comparison). The network was trained on one month only, so check the input |z| values below: above about 4 the prediction is an extrapolation.</Banner>
          )}
        </div>

        {meta && (
          <>
            <ProbeSection
              date={date} dayModel={dayModel} probe={probe} setProbe={setProbe} point={point} pointErr={pointErr}
              places={places} depthIdx={depthIdx} setDepthIdx={setDepthIdx} mapField={mapField} setMapField={setMapField} refName={refName}
            />
            <InsightsSection point={point} tab={tab} setTab={setTab} refName={refName} />
            <SensitivitySection date={date} probe={probe} point={point} />
            <VolumeSection date={date} probe={probe} depthIdx={depthIdx} refName={refName} />
            <Section id="basin" title="Basin analysis" description={`Every deep-water cell on ${date}: isotherm depths, parallel coordinates and a linked map, with ${refName} for comparison.`}>
              <BasinAnalysis meta={meta} date={date} dayModel={dayModel} dayRef={dayRef} />
            </Section>
            <CycloneSection setProbe={setProbe} setDate={setDate} meta={meta} />
            <EmbeddingSection date={date} probe={probe} point={point} setProbe={setProbe} setDate={setDate} />
          </>
        )}
        <ValidationSection />
      </main>

      <footer className="w-full border-t border-surface-container-high py-10">
        <div className="max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop flex flex-col sm:flex-row items-center justify-between gap-3 text-body-sm text-on-surface-variant">
          <span><span className="text-primary font-medium">OceanEmbed</span> · Team OceanSATX · SIH 2026, PS 26066</span>
          <span>{health ? `checkpoint ${health.checkpoint_sha256.slice(0, 12)}…` : ""}</span>
        </div>
      </footer>
    </div>
  );
}

// =============================================================================
function ProbeSection({ date, dayModel, probe, setProbe, point, pointErr, places, depthIdx, setDepthIdx, mapField, setMapField, refName }) {
  const MAP_FIELDS = {
    sst_c: { label: "SST (model input)", units: "°C", scale: "RdBu", reverse: true },
    tchp_kj_cm2: { label: "TCHP (model)", units: "kJ/cm²", scale: "YlOrRd", reverse: false },
    d20_m: { label: "D20 (model)", units: "m", scale: "Viridis", reverse: true },
    mld_m: { label: "Mixed-layer depth (model)", units: "m", scale: "Viridis", reverse: true }
  };
  const mf = MAP_FIELDS[mapField];
  const depths = point?.depth_levels_m || [0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000];
  const depth = depths[depthIdx];

  const mapData = dayModel
    ? [
        {
          type: "heatmap", x: dayModel.lons, y: dayModel.lats, z: dayModel.fields[mapField],
          colorscale: mf.scale, reversescale: mf.reverse, colorbar: { title: { text: mf.units }, thickness: 12 },
          hovertemplate: `%{y:.2f}°N %{x:.2f}°E<br>%{z:.2f} ${mf.units}<extra></extra>`
        },
        {
          type: "scatter", mode: "markers+text", x: places.map((p) => p.lon), y: places.map((p) => p.lat), text: places.map((p) => p.name),
          textposition: "top center", textfont: { size: 10, color: "#00253D" }, marker: { size: 7, color: "#00253D", symbol: "circle-open" }, hoverinfo: "text"
        },
        point && {
          type: "scatter", mode: "markers", x: [point.cell.lon], y: [point.cell.lat],
          marker: { size: 14, color: "rgba(0,0,0,0)", line: { color: "#E11D48", width: 2.5 }, symbol: "circle" }, hoverinfo: "skip"
        }
      ].filter(Boolean)
    : [];

  const prof = point
    ? [
        { type: "scatter", mode: "lines+markers", name: "OceanEmbed", x: point.model.profile_c, y: depths, line: { color: MODEL_COLOR, width: 2.5 }, marker: { size: 5 } },
        { type: "scatter", mode: "lines+markers", name: refName, x: point.reference.profile_c, y: depths, line: { color: REF_COLOR, width: 2, dash: "dash" }, marker: { size: 4 } }
      ]
    : [];

  return (
    <Section
      id="probe"
      title="Probe"
      description="Click the map or pick a place. The probe snaps to the nearest deep-water cell the model predicts (it was trained only where the ocean is at least 1000 m deep)."
      actions={
        <select value={mapField} onChange={(e) => setMapField(e.target.value)} className={selectCls}>
          {Object.entries(MAP_FIELDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className={`lg:col-span-7 ${card} overflow-hidden`}>
          <div className="h-[430px]">
            {dayModel ? (
              <Plot
                data={mapData}
                layout={{
                  autosize: true, margin: { l: 50, r: 10, t: 10, b: 40 }, showlegend: false,
                  xaxis: { title: { text: "Longitude (°E)" }, range: [45, 105], gridcolor: "#D3EBFF" },
                  yaxis: { title: { text: "Latitude (°N)" }, range: [5, 30], scaleanchor: "x", scaleratio: 1, gridcolor: "#D3EBFF" },
                  plot_bgcolor: "#E2E8F0", paper_bgcolor: "rgba(0,0,0,0)"
                }}
                onClick={(ev) => {
                  const pt = ev.points?.[0];
                  if (pt && finite(pt.x) && finite(pt.y)) setProbe({ lat: Number(pt.y), lon: Number(pt.x), name: null });
                }}
                useResizeHandler className="w-full h-full" config={PLOT_CFG}
              />
            ) : (
              <div className="h-full flex items-center justify-center text-body-sm text-on-surface-variant">Loading {date}…</div>
            )}
          </div>
          <p className="px-5 py-3 border-t border-surface-container-high text-body-sm text-on-surface-variant">
            {mf.label} on {date}. Grey: land, or no value. Equirectangular, 0.25° cells.
          </p>
        </div>

        <div className={`lg:col-span-5 ${card} p-6 flex flex-col gap-5`}>
          {pointErr && <Banner tone="amber">{pointErr}</Banner>}
          {point && (
            <>
              <div className="flex justify-between gap-3 text-body-sm text-on-surface-variant">
                <span>
                  Cell <span className="font-mono text-primary">{point.cell.lat.toFixed(2)}°N {point.cell.lon.toFixed(2)}°E</span>
                  {point.cell.distance_km > 0 && ` (${point.cell.distance_km} km from the click)`}
                </span>
                <span>RMSE vs {refName} <span className="font-mono text-primary">{fmt(point.profile_rmse_c, 2)} °C</span></span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Stat label={`OceanEmbed at ${depth} m`} value={fmt(point.model.profile_c[depthIdx], 2)} unit="°C" tone="text-secondary" />
                <Stat label={`${refName} at ${depth} m`} value={fmt(point.reference.profile_c[depthIdx], 2)} unit="°C" />
              </div>
              <input type="range" min="0" max={depths.length - 1} step="1" value={depthIdx} onChange={(e) => setDepthIdx(Number(e.target.value))} className="w-full accent-primary" />
              <div className="h-[300px]">
                <Plot
                  data={prof}
                  layout={{
                    autosize: true, margin: { l: 50, r: 10, t: 30, b: 40 }, legend: { orientation: "h", x: 0, y: 1.12 },
                    xaxis: { title: { text: "Temperature (°C)" }, gridcolor: "#E2E8F0" },
                    yaxis: { title: { text: "Depth (m)" }, autorange: "reversed", gridcolor: "#E2E8F0" },
                    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: depth, y1: depth, line: { color: "#94A3B8", dash: "dot", width: 1 } }],
                    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)"
                  }}
                  useResizeHandler className="w-full h-full" config={PLOT_CFG}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {point && (
        <div className={`${card} overflow-x-auto`}>
          <table className="w-full text-left text-body-md">
            <thead>
              <tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant">
                <th className="px-5 py-3 font-medium">Model input at this cell ({point.date})</th>
                {Object.keys(point.inputs).map((k) => <th key={k} className="px-4 py-3 font-medium">{k.toUpperCase()}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="px-5 py-3 text-on-surface-variant">Value</td>
                {Object.entries(point.inputs).map(([k, v]) => <td key={k} className="px-4 py-3 font-mono text-primary">{fmt(v.value, 3)} <span className="text-on-surface-variant text-body-sm">{v.units}</span></td>)}
              </tr>
              <tr>
                <td className="px-5 py-3 text-on-surface-variant">z vs training data</td>
                {Object.entries(point.input_z_scores).map(([k, z]) => (
                  <td key={k} className={`px-4 py-3 font-mono ${finite(z) && Math.abs(z) > 4 ? "text-rose-600 font-semibold" : "text-on-surface-variant"}`}>{fmt(z, 2)}</td>
                ))}
              </tr>
            </tbody>
          </table>
          <p className="px-5 py-3 text-body-sm text-on-surface-variant border-t border-surface-container-high">
            SST: OSTIA · SSH (zos), salinity (so), currents: Copernicus GLO12 · winds: ERA5. Red |z| &gt; 4: outside the range the network was trained on.
          </p>
        </div>
      )}
    </Section>
  );
}

// =============================================================================
function InsightsSection({ point, tab, setTab, refName }) {
  if (!point) return null;
  const m = point.model.diagnostics;
  const r = point.reference.diagnostics;
  const ms = point.model.sound_speed;
  const rs = point.reference.sound_speed;
  const tabs = [
    { id: "cyclone", name: "Cyclone heat", metric: `${fmt(m.tchp_kj_cm2)} kJ/cm²`, caption: "TCHP, heat above the 26 °C isotherm" },
    { id: "sound", name: "Sound speed", metric: ms ? `${fmt(ms.sld_m, 0)} m` : "—", caption: "Sonic layer depth" },
    { id: "upwelling", name: "Upwelling context", metric: `${fmt(m.d20_m)} m`, caption: "20 °C isotherm depth (D20)" },
    { id: "column", name: "Water column", metric: `${fmt(m.thermocline_mid_m)} m`, caption: "Thermocline (steepest layer mid-point)" }
  ];
  const Pair = ({ label, a, b, unit, d = 1, note }) => (
    <div className="flex flex-col gap-1">
      <span className="text-body-sm text-on-surface-variant">{label}</span>
      <span className="font-data-metric text-data-metric text-secondary">{fmt(a, d)}<span className="ml-1 text-body-md text-on-surface-variant">{unit}</span></span>
      <span className="text-body-sm text-on-surface-variant">{refName}: <span className="font-mono">{fmt(b, d)} {unit}</span></span>
      {note && <p className="mt-1 text-body-sm text-on-surface-variant leading-relaxed">{note}</p>}
    </div>
  );
  const depths = point.depth_levels_m;
  const mp = point.model.profile_c;
  const rp = point.reference.profile_c;

  return (
    <Section id="insights" title="What the profile tells us" description={`Derived from the predicted profile at the probe cell, with the ${refName} profile alongside for comparison.`}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className={`text-left p-5 rounded-xl border bg-surface-container-lowest transition ${tab === t.id ? "border-primary ring-1 ring-primary" : "border-surface-container-high hover:border-outline-variant"}`}>
            <div className="text-body-md font-medium text-secondary">{t.name}</div>
            <div className="mt-3 font-data-metric text-data-metric text-primary">{t.metric}</div>
            <p className="mt-1 text-body-sm text-on-surface-variant">{t.caption}</p>
          </button>
        ))}
      </div>

      <div className={`${card} p-6 sm:p-8 flex flex-col gap-6`}>
        {tab === "cyclone" && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
            <Pair label="Tropical cyclone heat potential" a={m.tchp_kj_cm2} b={r.tchp_kj_cm2} unit="kJ/cm²" note="ρ·cₚ·∫(T − 26 °C) dz from the surface to D26 (ρ = 1026 kg/m³, cₚ = 4178 J/kg/K). Around 50 kJ/cm² and above is commonly cited as favourable for rapid intensification, together with low wind shear and moist air." />
            <Pair label="26 °C isotherm depth" a={m.d26_m} b={r.d26_m} unit="m" note={m.d26_note || "First depth where the profile drops below 26 °C, linear between levels."} />
            <Pair label="Temperature at 100 m" a={m.t100_c} b={r.t100_c} unit="°C" d={2} />
          </div>
        )}
        {tab === "sound" && (
          ms ? (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
              <div className="lg:col-span-5 flex flex-col gap-6">
                <div className="grid grid-cols-2 gap-6">
                  <Pair label="Sonic layer depth" a={ms.sld_m} b={rs?.sld_m} unit="m" d={0} />
                  <Pair label="Gradient below the layer" a={ms.below_layer_gradient_ms_per_m} b={rs?.below_layer_gradient_ms_per_m} unit="m/s per m" d={3} />
                  <Pair label="Surface sound speed" a={ms.c_surface_ms} b={rs?.c_surface_ms} unit="m/s" />
                  <Pair label="Minimum above 1000 m" a={ms.c_min_ms} b={rs?.c_min_ms} unit="m/s" note={`at ${fmt(ms.c_min_depth_m, 0)} m`} />
                </div>
                <p className="text-body-sm text-on-surface-variant leading-relaxed">
                  Sound speed from the Mackenzie (1981) equation using the predicted temperature and this cell&apos;s surface
                  salinity ({fmt(point.inputs.sss.value, 2)} PSU), assumed uniform with depth. The sonic layer depth is the
                  near-surface sound-speed maximum: below it sound speed decreases, so rays from a source in the layer bend
                  down and leave a shadow zone beneath the layer at range. This is a profile diagnostic, not a
                  propagation-loss model.
                  {!ms.within_mackenzie_validity && " Some values fall outside the equation's validity range (T 2–30 °C, S 25–40)."}
                </p>
              </div>
              <div className="lg:col-span-7 h-[320px]">
                <Plot
                  data={[
                    { type: "scatter", mode: "lines+markers", name: "OceanEmbed", x: ms.c_levels_ms, y: depths, line: { color: MODEL_COLOR, width: 2.5 } },
                    rs && { type: "scatter", mode: "lines+markers", name: refName, x: rs.c_levels_ms, y: depths, line: { color: REF_COLOR, dash: "dash" } }
                  ].filter(Boolean)}
                  layout={{
                    autosize: true, margin: { l: 55, r: 10, t: 30, b: 40 }, legend: { orientation: "h", x: 0, y: 1.12 },
                    xaxis: { title: { text: "Sound speed (m/s)" }, gridcolor: "#E2E8F0" },
                    yaxis: { title: { text: "Depth (m)" }, autorange: "reversed", gridcolor: "#E2E8F0" },
                    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: ms.sld_m, y1: ms.sld_m, line: { color: MODEL_COLOR, dash: "dot" } }],
                    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)"
                  }}
                  useResizeHandler className="w-full h-full" config={PLOT_CFG}
                />
              </div>
            </div>
          ) : (
            <p className="text-body-md text-on-surface-variant">No valid surface salinity at this cell, so sound speed is not computed.</p>
          )
        )}
        {tab === "upwelling" && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
              <Pair label="20 °C isotherm depth (D20)" a={m.d20_m} b={r.d20_m} unit="m" note="Upwelling lifts the thermocline, so D20 is shallower than in surrounding water. Compare cells in Basin analysis." />
              <Pair label="Mixed-layer depth" a={m.mld_m} b={r.mld_m} unit="m" note="Depth where temperature first differs from the 10 m value by 0.2 °C (de Boyer Montégut et al. 2004)." />
              <Pair label="Stratification, 0–50 m" a={m.stratification_0_50m_c} b={r.stratification_0_50m_c} unit="°C" d={2} note="Surface minus 50 m. Upwelling usually lowers this; a large value is not a fishing-zone signal." />
            </div>
            <Banner tone="slate">Potential fishing zones are not assessed here: operational advisories (e.g. INCOIS) combine satellite SST fronts with chlorophyll, which this model does not predict.</Banner>
          </>
        )}
        {tab === "column" && (
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-8">
            <Pair label="Thermocline depth" a={m.thermocline_mid_m} b={r.thermocline_mid_m} unit="m" note={`Layer ${fmt(m.thermocline_top_m, 0)}–${fmt(m.thermocline_bottom_m, 0)} m: the steepest drop between standard levels.`} />
            <Pair label="Steepest gradient" a={m.thermocline_grad_c_per_m} b={r.thermocline_grad_c_per_m} unit="°C/m" d={3} />
            <Pair label="Surface" a={mp[0]} b={rp[0]} unit="°C" d={2} />
            <Pair label="1000 m" a={mp[14]} b={rp[14]} unit="°C" d={2} />
          </div>
        )}
      </div>
    </Section>
  );
}

// =============================================================================
function SensitivitySection({ date, probe, point }) {
  const VARS = [
    ["sst", "SST", "°C", 0.1], ["ssh", "SSH", "m", 0.01], ["sss", "Salinity", "PSU", 0.1],
    ["uo", "Current east", "m/s", 0.05], ["vo", "Current north", "m/s", 0.05], ["u10", "Wind east", "m/s", 0.5], ["v10", "Wind north", "m/s", 0.5]
  ];
  const [deltas, setDeltas] = useState({});
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRes(null), [date, probe]);
  if (!point) return null;

  const run = () => {
    setBusy(true);
    setErr(null);
    const d = Object.fromEntries(Object.entries(deltas).filter(([, v]) => finite(v) && Number(v) !== 0).map(([k, v]) => [k, Number(v)]));
    getJSON("/api/sensitivity", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date, lat: probe.lat, lon: probe.lon, deltas: d }) })
      .then(setRes).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  const depths = point.depth_levels_m;
  const bigZ = res ? Object.entries(res.perturbed_input_z_scores).filter(([, z]) => finite(z) && Math.abs(z) > 4) : [];
  const rows = [["TCHP", "tchp_kj_cm2", "kJ/cm²", 1], ["D26", "d26_m", "m", 1], ["D20", "d20_m", "m", 1], ["Mixed layer", "mld_m", "m", 1], ["Thermocline", "thermocline_mid_m", "m", 1], ["T at 100 m", "t100_c", "°C", 2]];

  return (
    <Section id="sensitivity" title="What-if: change the real inputs" description="Adds a uniform change to the real 31 × 31 input patch around the probe cell for this date and re-runs the network. The unchanged run reproduces the stored prediction, so any difference comes only from your change.">
      <div className={`${card} p-6 sm:p-8 flex flex-col gap-6`}>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-4">
          {VARS.map(([k, l, u, step]) => (
            <label key={k} className="flex flex-col gap-1.5">
              <span className="text-body-sm text-on-surface-variant">Δ {l} ({u})</span>
              <input type="number" step={step} value={deltas[k] ?? 0} onChange={(e) => setDeltas({ ...deltas, [k]: e.target.value })}
                className="w-full bg-surface-container-lowest border border-surface-container-high rounded-xl px-3 py-2 text-body-md font-mono text-primary" />
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={run} disabled={busy} className={primaryButton}>{busy ? "Running…" : "Run model"}</button>
          <button onClick={() => { setDeltas({}); setRes(null); }} className={ghostButton}>Reset</button>
          {res && <span className="text-body-sm text-on-surface-variant">Reconstruction check: the unchanged run differs from the stored prediction by at most {res.reconstruction_max_abs_diff_c} °C.</span>}
        </div>
        {err && <Banner tone="amber">{err}</Banner>}
        {bigZ.length > 0 && <Banner tone="rose">Inputs used in this run are far outside the training data ({bigZ.map(([k, z]) => `${k} z = ${z}`).join(", ")}; this includes values you did not change). The network is extrapolating, so treat this result with caution.</Banner>}
        {res && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            <div className="lg:col-span-6 h-[320px]">
              <Plot
                data={[
                  { type: "scatter", mode: "lines+markers", name: "Real inputs", x: res.baseline.profile_c, y: depths, line: { color: MODEL_COLOR, width: 2.5 } },
                  { type: "scatter", mode: "lines+markers", name: "With change", x: res.perturbed.profile_c, y: depths, line: { color: "#7C3AED", width: 2, dash: "dash" } }
                ]}
                layout={{ autosize: true, margin: { l: 50, r: 10, t: 30, b: 40 }, legend: { orientation: "h", x: 0, y: 1.12 }, xaxis: { title: { text: "Temperature (°C)" } }, yaxis: { title: { text: "Depth (m)" }, autorange: "reversed" }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)" }}
                useResizeHandler className="w-full h-full" config={PLOT_CFG}
              />
            </div>
            <table className="lg:col-span-6 w-full text-left text-body-md">
              <thead><tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant"><th className="py-2 font-medium">Quantity</th><th className="py-2 font-medium">Real inputs</th><th className="py-2 font-medium">With change</th><th className="py-2 font-medium">Difference</th></tr></thead>
              <tbody className="divide-y divide-surface-container-high">
                {rows.map(([l, k, u, d]) => {
                  const a = res.baseline.diagnostics[k];
                  const b = res.perturbed.diagnostics[k];
                  return (
                    <tr key={k}>
                      <td className="py-2 text-on-surface-variant">{l} ({u})</td>
                      <td className="py-2 font-mono">{fmt(a, d)}</td>
                      <td className="py-2 font-mono">{fmt(b, d)}</td>
                      <td className="py-2 font-mono text-secondary">{finite(a) && finite(b) ? signed(b - a, d) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Section>
  );
}

// =============================================================================
function VolumeSection({ date, probe, depthIdx, refName }) {
  const [vol, setVol] = useState(null);
  const [err, setErr] = useState(null);
  const [mode, setMode] = useState("slice");
  const [src, setSrc] = useState("model_c");
  useEffect(() => {
    if (!date) return;
    setErr(null);
    getJSON(`/api/volume?date=${date}&lat=${probe.lat}&lon=${probe.lon}&half_width_deg=1.5`).then(setVol).catch((e) => { setVol(null); setErr(e.message); });
  }, [date, probe]);

  const data = useMemo(() => {
    if (!vol) return null;
    const isDiff = src === "diff";
    const cube = isDiff
      ? vol.model_c.map((lvl, d) => lvl.map((row, i) => row.map((v, j) => (finite(v) && finite(vol.reference_c[d][i][j]) ? v - vol.reference_c[d][i][j] : null))))
      : vol[src];
    const cs = isDiff ? "RdBu" : "Turbo";
    const common = { colorscale: cs, reversescale: isDiff, zmid: isDiff ? 0 : undefined, colorbar: { title: { text: isDiff ? "Δ °C" : "°C" }, thickness: 12 } };
    if (mode === "slice") {
      return { traces: [{ type: "heatmap", x: vol.lons, y: vol.lats, z: cube[depthIdx], ...common, hovertemplate: "%{y:.2f}°N %{x:.2f}°E<br>%{z:.2f}<extra></extra>" }], layout: { xaxis: { title: { text: "Longitude (°E)" } }, yaxis: { title: { text: "Latitude (°N)" }, scaleanchor: "x" } } };
    }
    if (mode === "transect") {
      const r = vol.center.row_in_subgrid;
      return { traces: [{ type: "heatmap", x: vol.lons, y: vol.depths_m, z: cube.map((lvl) => lvl[r]), ...common, hovertemplate: "%{x:.2f}°E, %{y} m<br>%{z:.2f}<extra></extra>" }], layout: { xaxis: { title: { text: `Longitude (°E) at ${vol.center.lat.toFixed(2)}°N` } }, yaxis: { title: { text: "Depth (m)" }, autorange: "reversed" } } };
    }
    const x = [], y = [], z = [], v = [];
    vol.depths_m.forEach((dep, d) => vol.lats.forEach((la, i) => vol.lons.forEach((lo, j) => {
      const val = cube[d][i][j];
      if (finite(val)) { x.push(lo); y.push(la); z.push(-dep); v.push(val); }
    })));
    return { traces: [{ type: "scatter3d", mode: "markers", x, y, z, marker: { size: 2.5, color: v, colorscale: cs, reversescale: isDiff, colorbar: { title: { text: isDiff ? "Δ °C" : "°C" } } }, hovertemplate: "%{y:.2f}°N %{x:.2f}°E %{z} m<br>%{marker.color:.2f}<extra></extra>" }], layout: { scene: { xaxis: { title: { text: "Lon" } }, yaxis: { title: { text: "Lat" } }, zaxis: { title: { text: "Depth (m)" } }, aspectratio: { x: 1.4, y: 1.4, z: 0.9 } } } };
  }, [vol, mode, src, depthIdx]);

  const depth = vol?.depths_m[depthIdx];
  return (
    <Section id="twin" title="3D temperature field" description="Stored model predictions on the 0.25° grid, ±1.5° around the probe, at all 15 levels. Each point is the network's output for its own real input patch; nothing is interpolated between cells."
      actions={
        <div className="flex flex-wrap gap-2">
          <Segmented value={mode} onChange={setMode} options={[{ value: "slice", label: `Slice at ${depth ?? "…"} m` }, { value: "transect", label: "Transect" }, { value: "points", label: "3D points" }]} />
          <Segmented value={src} onChange={setSrc} options={[{ value: "model_c", label: "OceanEmbed" }, { value: "reference_c", label: refName }, { value: "diff", label: "Difference" }]} />
        </div>
      }>
      <div className={`${card} h-[460px] overflow-hidden`}>
        {err ? <div className="p-6"><Banner tone="amber">{err}</Banner></div> : data ? (
          <Plot data={data.traces} layout={{ autosize: true, margin: { l: 55, r: 10, t: 10, b: 45 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#E2E8F0", ...data.layout }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
        ) : <div className="h-full flex items-center justify-center text-body-sm text-on-surface-variant">Loading…</div>}
      </div>
      <p className="text-body-sm text-on-surface-variant">The slice depth follows the depth slider in the Probe section. Blank cells are land, shelf water shallower than 1000 m, or cells without data.</p>
    </Section>
  );
}

// =============================================================================
function CycloneSection({ setProbe, setDate, meta }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [ti, setTi] = useState(0);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { getJSON("/api/cyclones").then(setData).catch(setErr); }, []);
  const track = data?.tracks?.[ti];
  useEffect(() => {
    if (!playing || !track) return;
    const id = setInterval(() => setStep((s) => {
      if (s + 1 >= track.points.length) { setPlaying(false); return s; }
      return s + 1;
    }), 900);
    return () => clearInterval(id);
  }, [playing, track]);

  if (err) return <Section id="replay" title="Cyclone replay" description="Real best tracks, with the model's ocean heat along them."><MissingData err={err} /></Section>;
  if (!track) return null;
  const pt = track.points[Math.min(step, track.points.length - 1)];
  const o = pt.ocean;
  const withOcean = track.points.filter((p) => p.ocean);
  const dates = new Set(meta.dates.map((d) => d.date));

  return (
    <Section id="replay" title="Cyclone replay" description={`${data.source}. Ocean heat is shown only on days that have an inference file.`}
      actions={
        <select value={ti} onChange={(e) => { setTi(Number(e.target.value)); setStep(0); setPlaying(false); }} className={selectCls}>
          {data.tracks.map((t, i) => <option key={t.sid} value={i}>{t.name} {t.season}</option>)}
        </select>
      }>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className={`lg:col-span-7 ${card} overflow-hidden h-[420px]`}>
          <Plot
            data={[
              { type: "scattergeo", mode: "lines", lon: track.points.map((p) => p.lon), lat: track.points.map((p) => p.lat), line: { color: "#94A3B8", width: 2 }, hoverinfo: "skip" },
              { type: "scattergeo", mode: "markers", lon: track.points.map((p) => p.lon), lat: track.points.map((p) => p.lat),
                marker: { size: 7, color: track.points.map((p) => p.ocean?.model_tchp_kj_cm2 ?? null), colorscale: "YlOrRd", cmin: 0, colorbar: { title: { text: "TCHP" }, thickness: 10 }, line: { color: "#00253D", width: 0.5 } },
                text: track.points.map((p) => `${p.time.replace("T", " ").slice(0, 16)} UTC<br>${fmt(p.wmo_wind_kt, 0)} kt · ${fmt(p.wmo_pres_hpa, 0)} hPa`), hoverinfo: "text" },
              { type: "scattergeo", mode: "markers", lon: [pt.lon], lat: [pt.lat], marker: { size: 16, color: "rgba(0,0,0,0)", line: { color: "#E11D48", width: 2.5 } }, hoverinfo: "skip" }
            ]}
            layout={{
              autosize: true, margin: { l: 0, r: 0, t: 0, b: 0 }, showlegend: false, paper_bgcolor: "rgba(0,0,0,0)",
              geo: { projection: { type: "equirectangular" }, lonaxis: { range: [45, 105] }, lataxis: { range: [3, 30] }, showland: true, landcolor: "#E2E8F0", showocean: true, oceancolor: "#EAF5FF", coastlinecolor: "#72787E", showcountries: true, countrycolor: "#CBD5E1", resolution: 50 }
            }}
            useResizeHandler className="w-full h-full" config={PLOT_CFG}
          />
        </div>
        <div className={`lg:col-span-5 ${card} p-6 flex flex-col gap-5`}>
          <div className="flex items-center gap-2">
            <button onClick={() => setPlaying(!playing)} className={primaryButton}>{playing ? "Pause" : "Play"}</button>
            <button onClick={() => setStep(Math.max(0, step - 1))} className={ghostButton} disabled={step === 0}>‹</button>
            <button onClick={() => setStep(Math.min(track.points.length - 1, step + 1))} className={ghostButton} disabled={step >= track.points.length - 1}>›</button>
            <span className="ml-auto text-body-sm text-on-surface-variant">{step + 1} / {track.points.length}</span>
          </div>
          <input type="range" min="0" max={track.points.length - 1} value={step} onChange={(e) => setStep(Number(e.target.value))} className="w-full accent-rose-600" />
          <div className="font-mono text-body-md text-primary">{pt.time.replace("T", " ").slice(0, 16)} UTC · {fmt(pt.lat, 1)}°N {fmt(pt.lon, 1)}°E</div>
          <div className="grid grid-cols-3 gap-4">
            <Stat label="Max wind (WMO)" value={fmt(pt.wmo_wind_kt, 0)} unit="kt" />
            <Stat label="Pressure" value={fmt(pt.wmo_pres_hpa, 0)} unit="hPa" />
            <Stat label="IMD grade" value={pt.imd_grade || "—"} />
          </div>
          {o ? (
            <div className="grid grid-cols-3 gap-4 pt-4 border-t border-surface-container-high">
              <Stat label="TCHP, model" value={fmt(o.model_tchp_kj_cm2)} unit="kJ/cm²" tone="text-secondary" />
              <Stat label={`TCHP, ${o.reference_name}`} value={fmt(o.ref_tchp_kj_cm2)} unit="kJ/cm²" />
              <Stat label="Cold wake" value={signed(o.cold_wake_c)} unit="°C" note={o.cold_wake_definition} />
            </div>
          ) : (
            <p className="pt-4 border-t border-surface-container-high text-body-sm text-on-surface-variant">{pt.ocean_note}.</p>
          )}
          {o && dates.has(pt.time.slice(0, 10)) && (
            <button className={ghostButton} onClick={() => { setDate(pt.time.slice(0, 10)); setProbe({ lat: o.cell_lat, lon: o.cell_lon, name: null }); document.getElementById("probe")?.scrollIntoView({ behavior: "smooth" }); }}>
              Open this point in the probe
            </button>
          )}
          <p className="text-body-sm text-on-surface-variant">{withOcean.length} of {track.points.length} track points have model ocean data.</p>
        </div>
      </div>
    </Section>
  );
}

// =============================================================================
function EmbeddingSection({ date, probe, point, setProbe, setDate }) {
  const [sim, setSim] = useState(null);
  const [err, setErr] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!point) return;
    setErr(null);
    getJSON("/api/similar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date, lat: probe.lat, lon: probe.lon, k: 6 }) })
      .then(setSim).catch((e) => { setSim(null); setErr(e.message); });
  }, [point, date, probe]);
  if (!point) return null;
  const L = point.latent;
  return (
    <Section id="embedding" title="Latent embedding" description="The network's 128-number summary of the input patch at the probe cell, and the most similar ocean states elsewhere in the same file (cosine similarity)."
      actions={<button className={ghostButton} onClick={() => { navigator.clipboard.writeText(JSON.stringify(L.vector)); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>{copied ? "Copied" : "Copy vector"}</button>}>
      <div className={`${card} p-6 sm:p-8 flex flex-col gap-6`}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
          <Stat label="L2 norm" value={fmt(L.l2_norm, 3)} />
          <Stat label="Mean / std" value={`${fmt(L.mean, 3)} / ${fmt(L.std, 3)}`} />
          <Stat label="Min" value={fmt(L.min, 3)} />
          <Stat label="Max" value={fmt(L.max, 3)} />
        </div>
        <div className="h-32">
          <Plot data={[{ type: "bar", x: L.vector.map((_, i) => i), y: L.vector, marker: { color: L.vector.map((v) => (v >= 0 ? MODEL_COLOR : "#BA1A1A")) }, hovertemplate: "dim %{x}: %{y:.4f}<extra></extra>" }]}
            layout={{ autosize: true, margin: { l: 40, r: 10, t: 5, b: 25 }, bargap: 0.1, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)" }} useResizeHandler className="w-full h-full" config={{ ...PLOT_CFG, displayModeBar: false }} />
        </div>
        {err && <Banner tone="amber">{err}</Banner>}
        {sim && (
          <div className="flex flex-col gap-3 pt-5 border-t border-surface-container-high">
            <p className="text-body-sm text-on-surface-variant">Searched {sim.searched}; excluded {sim.excluded}.</p>
            <table className="w-full text-left text-body-md">
              <thead><tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant"><th className="py-2 font-medium">Date</th><th className="py-2 font-medium">Cell</th><th className="py-2 font-medium">Distance</th><th className="py-2 font-medium">Cosine</th><th className="py-2 font-medium">TCHP</th><th className="py-2 font-medium">D26</th><th></th></tr></thead>
              <tbody className="divide-y divide-surface-container-high">
                {sim.matches.map((mm, i) => (
                  <tr key={i}>
                    <td className="py-2 font-mono">{mm.date}</td>
                    <td className="py-2 font-mono">{mm.lat.toFixed(2)}°N {mm.lon.toFixed(2)}°E</td>
                    <td className="py-2">{mm.distance_km} km</td>
                    <td className="py-2 font-mono text-secondary">{mm.cosine_similarity.toFixed(4)}</td>
                    <td className="py-2 font-mono">{fmt(mm.model_tchp_kj_cm2)}</td>
                    <td className="py-2 font-mono">{fmt(mm.model_d26_m)}</td>
                    <td className="py-2"><button className="text-secondary text-body-sm" onClick={() => { setDate(mm.date); setProbe({ lat: mm.lat, lon: mm.lon, name: null }); }}>Probe</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Section>
  );
}

// =============================================================================
function ValidationSection() {
  const [b, setB] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { getJSON("/api/benchmarks").then(setB).catch(setErr); }, []);
  if (err) return <Section id="validation" title="Validation" description="Scores computed by kaggle_oceanembed_eval.py."><MissingData err={err} /></Section>;
  if (!b) return null;
  const oe = b.models.find((mm) => mm.model === "OceanEmbed CNN");
  const argo = oe?.argo;
  const depths = b.depth_levels_m;
  return (
    <Section id="validation" title="Validation" description={`Held-out days ${b.heldout_days[0]} to ${b.heldout_days[b.heldout_days.length - 1]} (${b.n_validation_samples.toLocaleString()} samples). ${b.glorys_note}`}>
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full text-left text-body-md">
          <thead><tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant"><th className="px-6 py-3 font-medium">Model</th><th className="px-6 py-3 font-medium">Inputs</th><th className="px-6 py-3 font-medium">RMSE vs GLORYS12, held-out</th><th className="px-6 py-3 font-medium">RMSE vs gridded Argo</th></tr></thead>
          <tbody className="divide-y divide-surface-container-high">
            {b.models.map((mm) => (
              <tr key={mm.model}>
                <td className="px-6 py-3 text-primary">{mm.model}</td>
                <td className="px-6 py-3 text-on-surface-variant">{mm.inputs}</td>
                <td className="px-6 py-3 font-mono">{mm.evaluated ? `${fmt(mm.glorys_heldout_rmse_c, 4)} °C` : "not evaluated"}</td>
                <td className="px-6 py-3 font-mono">{mm.argo ? `${fmt(mm.argo.rmse_c, 4)} °C` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className={`${card} p-4 h-[340px]`}>
          <Plot
            data={[
              ...b.models.filter((mm) => mm.evaluated).map((mm, i) => ({ type: "scatter", mode: "lines+markers", name: `${mm.model} vs GLORYS12`, x: mm.glorys_heldout_rmse_by_depth_c, y: depths, line: { color: ["#94A3B8", "#64748B", MODEL_COLOR][i % 3] } })),
              argo && { type: "scatter", mode: "lines+markers", name: "OceanEmbed vs gridded Argo", x: argo.rmse_by_depth_c, y: depths, line: { color: REF_COLOR, dash: "dash" } }
            ].filter(Boolean)}
            layout={{ autosize: true, margin: { l: 55, r: 10, t: 60, b: 40 }, legend: { orientation: "h", x: 0, y: 1.25, font: { size: 10 } }, xaxis: { title: { text: "RMSE (°C)" } }, yaxis: { title: { text: "Depth (m)" }, autorange: "reversed" }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)" }}
            useResizeHandler className="w-full h-full" config={PLOT_CFG}
          />
        </div>
        {argo ? (
          <div className={`${card} p-4 h-[340px]`}>
            <Plot
              data={[
                { type: "scattergl", mode: "markers", x: argo.scatter_sample.observed_c, y: argo.scatter_sample.predicted_c, marker: { size: 3, color: argo.scatter_sample.depth_m, colorscale: "Viridis", reversescale: true, colorbar: { title: { text: "Depth m" }, thickness: 10 }, opacity: 0.6 }, hovertemplate: "obs %{x:.2f} · pred %{y:.2f}<extra></extra>" },
                { type: "scatter", mode: "lines", x: [0, 32], y: [0, 32], line: { color: "#94A3B8", dash: "dot" }, hoverinfo: "skip" }
              ]}
              layout={{ autosize: true, margin: { l: 55, r: 10, t: 10, b: 40 }, showlegend: false, xaxis: { title: { text: "Gridded Argo (°C)" }, range: [0, 32] }, yaxis: { title: { text: "OceanEmbed (°C)" }, range: [0, 32] }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)" }}
              useResizeHandler className="w-full h-full" config={PLOT_CFG}
            />
          </div>
        ) : <div className={`${card} p-6 text-body-md text-on-surface-variant`}>No Argo comparison in eval_results.json.</div>}
      </div>
      {argo && (
        <p className="text-body-sm text-on-surface-variant leading-relaxed">
          {argo.product}: {argo.n_grid_cell_days.toLocaleString()} {argo.unit}, {argo.n_values.toLocaleString()} level values.
          RMSE {fmt(argo.rmse_c, 3)} °C, bias {signed(argo.bias_c, 3)} °C, R² {fmt(argo.r2, 3)}. Levels outside the product&apos;s depth
          range ({argo.product_depth_range_m[0]}–{argo.product_depth_range_m[1]} m) are not extrapolated. The scatter shows a random sample of {argo.scatter_sample.n.toLocaleString()} values (seed {argo.scatter_sample.seed}).
        </p>
      )}
    </Section>
  );
}

// =============================================================================
function MissingData({ err }) {
  const d = err?.detail;
  return (
    <div className={`${card} p-6 flex flex-col gap-3`}>
      <p className="text-body-lg text-primary font-medium">{err?.message || "Data unavailable."}</p>
      {d?.how_to_create && (
        <>
          <p className="text-body-md text-on-surface-variant">This view only shows values computed from real input files. Create them with:</p>
          <pre className="text-body-sm font-mono bg-surface-container-low rounded-xl p-4 overflow-x-auto whitespace-pre-wrap">{d.how_to_create}</pre>
          {d.directory && <p className="text-body-sm text-on-surface-variant">Output folder: <span className="font-mono">{d.directory}</span> (reload the page afterwards)</p>}
        </>
      )}
    </div>
  );
}

function Banner({ tone = "slate", children }) {
  const cls = { rose: "bg-rose-50 border-rose-300 text-rose-900", amber: "bg-amber-50 border-amber-300 text-amber-900", slate: "bg-surface-container-low border-surface-container-high text-on-surface" }[tone];
  return <div className={`px-5 py-3 rounded-xl border text-body-md ${cls}`}>{children}</div>;
}

function Section({ id, title, description, actions, children }) {
  return (
    <section id={id} className="scroll-mt-24 flex flex-col gap-6">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div className="max-w-3xl">
          <h2 className="font-headline-md text-headline-md text-primary">{title}</h2>
          {description && <p className="mt-2 text-body-md text-on-surface-variant">{description}</p>}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, unit, tone = "text-primary", note }) {
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-body-sm text-on-surface-variant">{label}</span>
      <span className={`font-data-metric text-data-metric ${tone}`}>{value}{unit && <span className="ml-1 text-body-md text-on-surface-variant">{unit}</span>}</span>
      {note && <p className="mt-1 text-body-sm text-on-surface-variant leading-relaxed">{note}</p>}
    </div>
  );
}

function Segmented({ options, value, onChange }) {
  return (
    <div className="inline-flex p-1 rounded-xl bg-surface-container-low border border-surface-container-high">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)} className={`px-3 py-1.5 rounded-lg text-body-sm font-medium transition ${value === o.value ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-primary"}`}>{o.label}</button>
      ))}
    </div>
  );
}
