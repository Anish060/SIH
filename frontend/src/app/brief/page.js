"use client";

// Decision brief: one-page summary computed by /api/brief, printable to PDF.
import React, { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { api, Shell, Field, Banner, Stat, ErrorBox, useDates, card, inputCls, btn, fmt, PLOT_CFG } from "../lib/ui";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const MAP = { autosize: true, margin: { l: 45, r: 10, t: 30, b: 35 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#E2E8F0", showlegend: false,
  xaxis: { range: [45, 105] }, yaxis: { range: [5, 30], scaleanchor: "x" } };

export default function Brief() {
  const [dates, dErr] = useDates();
  const [date, setDate] = useState(null);
  const [b, setB] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { if (dates?.length && !date) setDate(dates[dates.length - 1].date); }, [dates, date]);
  useEffect(() => { if (!date) return; setB(null); setErr(null); api(`/api/brief?date=${date}`).then(setB).catch(setErr); }, [date]);
  return (
    <Shell title="Ocean heat brief" subtitle="Summary for decision makers: where the upper ocean holds enough heat to fuel cyclone intensification, how the model compares with the reference, data freshness and quality, and storms nearby. Every figure is computed from the stored fields." need="brief">
      <ErrorBox err={dErr} />
      <div className="flex flex-wrap items-end gap-4 print:hidden">
        {dates && <Field label="Date"><select className={inputCls} value={date || ""} onChange={(e) => setDate(e.target.value)}>{dates.map((d) => <option key={d.date} value={d.date}>{d.date} · {d.split}</option>)}</select></Field>}
        <button className={btn} onClick={() => window.print()} disabled={!b}>Export PDF</button>
      </div>
      <ErrorBox err={err} />
      {b && (
        <>
          {String(b.input_data).includes("SYNTHETIC") && <Banner tone="rose">Synthetic test fixture: not observations. Do not use for decisions.</Banner>}
          {b.split === "train" && <Banner tone="amber">This date was in the model&apos;s training period.</Banner>}
          <div className={`${card} p-6 flex flex-col gap-2`}>
            <p className="text-body-sm text-on-surface-variant">{b.date} · data {b.data_age_days} days old · comparison: {b.reference_name}</p>
            <ul className="list-disc pl-5 text-body-lg text-on-surface leading-relaxed">{b.summary_lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
          <div className={`${card} p-5 grid grid-cols-2 sm:grid-cols-5 gap-5`}>
            <Stat label="Area TCHP ≥ 50 kJ/cm²" value={b.cyclone_heat.area_tchp_ge50_km2.toLocaleString()} unit="km²" tone="text-rose-600" />
            <Stat label="Area TCHP ≥ 80 kJ/cm²" value={b.cyclone_heat.area_tchp_ge80_km2.toLocaleString()} unit="km²" />
            <Stat label={`Reference area ≥ 50`} value={b.cyclone_heat.ref_area_tchp_ge50_km2.toLocaleString()} unit="km²" />
            <Stat label="Model–reference overlap" value={b.cyclone_heat.overlap_iou === null ? "—" : `${fmt(b.cyclone_heat.overlap_iou * 100, 0)}%`} note="intersection over union of the ≥ 50 areas" />
            <Stat label="Inputs outside training range" value={b.input_quality.fraction_cells_outside_training_range === null ? "—" : `${fmt(b.input_quality.fraction_cells_outside_training_range * 100, 0)}%`} note="cells with |z| > 4" />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className={`${card} h-[380px] p-2`}>
              <Plot data={[{ type: "heatmap", x: b.anomaly.lons, y: b.anomaly.lats, z: b.tchp_grid, colorscale: "YlOrRd", zmin: 0, colorbar: { title: { text: "kJ/cm²" } } },
                { type: "scatter", mode: "markers+text", x: b.cyclone_heat.hotspots.map((h) => h.lon), y: b.cyclone_heat.hotspots.map((h) => h.lat), text: b.cyclone_heat.hotspots.map((h, i) => `${i + 1}`), textposition: "top center", marker: { size: 9, color: "#0F172A", symbol: "circle-open" } },
                ...b.storms_near_date.map((s) => ({ type: "scatter", mode: "markers+text", x: [s.lon], y: [s.lat], text: [s.name], textposition: "bottom center", marker: { size: 14, symbol: "star", color: "#7C3AED" } }))]}
                layout={{ ...MAP, title: { text: "Model TCHP", font: { size: 12 } } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
            </div>
            <div className={`${card} h-[380px] p-2`}>
              <Plot data={[{ type: "heatmap", x: b.anomaly.lons, y: b.anomaly.lats, z: b.anomaly.grid, colorscale: "RdBu", reversescale: true, zmid: 0, colorbar: { title: { text: "Δ kJ/cm²" } } }]}
                layout={{ ...MAP, title: { text: "TCHP relative to the period mean", font: { size: 12 } } }} useResizeHandler className="w-full h-full" config={PLOT_CFG} />
            </div>
          </div>
          <p className="text-body-sm text-on-surface-variant">Anomaly: {b.anomaly.definition}.</p>
          <div className={`${card} overflow-x-auto`}>
            <table className="w-full text-left text-body-md">
              <thead><tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant"><th className="px-5 py-2">#</th><th className="px-5 py-2">Location</th><th className="px-5 py-2">Model TCHP</th><th className="px-5 py-2">Reference TCHP</th><th className="px-5 py-2">D26</th></tr></thead>
              <tbody className="divide-y divide-surface-container-high">{b.cyclone_heat.hotspots.map((h, i) => <tr key={i}><td className="px-5 py-2">{i + 1}</td><td className="px-5 py-2 font-mono">{h.lat.toFixed(2)}°N {h.lon.toFixed(2)}°E</td><td className="px-5 py-2 font-mono">{fmt(h.model_tchp_kj_cm2)} kJ/cm²</td><td className="px-5 py-2 font-mono">{fmt(h.ref_tchp_kj_cm2)} kJ/cm²</td><td className="px-5 py-2 font-mono">{fmt(h.model_d26_m)} m</td></tr>)}</tbody>
            </table>
          </div>
          <p className="text-body-sm text-on-surface-variant leading-relaxed">
            Hotspots: highest model TCHP cells at least 300 km apart. TCHP is one ingredient of intensification, alongside vertical wind shear and mid-level humidity; this brief is not a cyclone forecast.
            Model skill in this file: {Object.entries(b.model_skill_in_file).filter(([, v]) => v?.rmse_c != null).map(([k, v]) => `${k} RMSE ${fmt(v.rmse_c, 2)} °C`).join(", ") || "n/a"}.
          </p>
        </>
      )}
    </Shell>
  );
}
