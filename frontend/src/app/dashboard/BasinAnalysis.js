"use client";

// Basin analysis: isotherm-depth surfaces, parallel coordinates and a linked map.
// Every number drawn here comes from /api/basin/*, which serves the NetCDF file
// written by basin_inference.py. Nothing is generated or filled in client-side:
// cells without a value stay blank, and the reason is shown next to the chart.

import React, { useEffect, useMemo, useState, useCallback } from "react";
import dynamic from "next/dynamic";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const card = "bg-surface-container-lowest rounded-xl border border-surface-container-high";

// Parallel-coordinate axes: key in the API payload, label, units, whether null has a defined meaning.
const PC_DIMS = [
  { key: "lat", label: "Latitude", units: "°N" },
  { key: "lon", label: "Longitude", units: "°E" },
  { key: "sst_c", label: "SST (input)", units: "°C" },
  { key: "ssh_m", label: "SSH (input)", units: "m" },
  { key: "mld_m", label: "Mixed layer", units: "m" },
  { key: "d26_m", label: "D26", units: "m", nullAsZero: true },
  { key: "d20_m", label: "D20", units: "m" },
  { key: "tchp_kj_cm2", label: "TCHP", units: "kJ/cm²" },
  { key: "thermocline_mid_m", label: "Thermocline", units: "m" },
  { key: "t100_c", label: "T at 100 m", units: "°C" },
  { key: "profile_rmse_c", label: "RMSE vs reference", units: "°C" },
  { key: "in_max_abs_z", label: "Input |z| (max)", units: "σ" }
];

const MAP_METRICS = [
  { key: "tchp_kj_cm2", label: "Cyclone heat potential (TCHP)", units: "kJ/cm²", scale: "YlOrRd", diffOk: true },
  { key: "d26_m", label: "26 °C isotherm depth (D26)", units: "m", scale: "Viridis", reverse: true, diffOk: true },
  { key: "d20_m", label: "20 °C isotherm depth (D20)", units: "m", scale: "Viridis", reverse: true, diffOk: true },
  { key: "mld_m", label: "Mixed-layer depth", units: "m", scale: "Viridis", reverse: true, diffOk: true },
  { key: "thermocline_mid_m", label: "Thermocline depth", units: "m", scale: "Viridis", reverse: true, diffOk: true },
  { key: "t100_c", label: "Temperature at 100 m", units: "°C", scale: "RdBu", reverse: true, diffOk: true },
  { key: "profile_rmse_c", label: "Profile RMSE vs reference", units: "°C", scale: "Reds", diffOk: false },
  { key: "in_max_abs_z", label: "Largest input |z| vs training", units: "σ", scale: "Reds", diffOk: false },
  { key: "sst_c", label: "SST (model input)", units: "°C", scale: "RdBu", reverse: true, diffOk: false }
];

function finite(v) {
  return v !== null && v !== undefined && Number.isFinite(v);
}

function fmt(v, d = 2) {
  return finite(v) ? Number(v).toFixed(d) : "—";
}

export default function BasinAnalysis({ meta, date, dayModel, dayRef }) {
  const [source, setSource] = useState("model");
  const [mapMetric, setMapMetric] = useState("tchp_kj_cm2");
  const [mapMode, setMapMode] = useState("value"); // value | diff
  const [constraints, setConstraints] = useState({}); // dimension index -> [[lo, hi], ...]

  useEffect(() => setConstraints({}), [date]);

  const days = { model: dayModel, glorys: dayRef };
  const day = days[source];
  const dateInfo = meta?.dates.find((d) => d.date === date);

  // ---------- rows for the parallel-coordinates plot (one per valid ocean cell)
  const pc = useMemo(() => {
    if (!day) return null;
    const f = day.fields;
    const rows = [];
    let excluded = 0;
    let d26Zero = 0;
    day.lats.forEach((lat, i) => {
      day.lons.forEach((lon, j) => {
        if (!finite(f.profile_rmse_c[i][j])) return; // outside the model domain
        const row = { i, j, lat, lon };
        let ok = true;
        for (const d of PC_DIMS) {
          if (d.key === "lat" || d.key === "lon") continue;
          let v = f[d.key][i][j];
          // TCHP is exactly 0 only when the profile's own surface is below 26 °C (oceanembed_core.tchp_kj_cm2),
          // so D26 = 0 there by the standard convention. NaN TCHP (column >= 26 °C to 1000 m) stays excluded.
          if (!finite(v) && d.nullAsZero && f.tchp_kj_cm2[i][j] === 0) {
            v = 0;
            d26Zero += 1;
          }
          if (!finite(v)) {
            ok = false;
            break;
          }
          row[d.key] = v;
        }
        if (ok) rows.push(row);
        else excluded += 1;
      });
    });
    return { rows, excluded, d26Zero };
  }, [day]);

  // ---------- which rows pass every brushed range
  const selectedMask = useMemo(() => {
    if (!pc) return null;
    const active = Object.entries(constraints).filter(([, r]) => r && r.length);
    if (!active.length) return null;
    const set = new Set();
    pc.rows.forEach((row) => {
      const pass = active.every(([idx, ranges]) => {
        const v = row[PC_DIMS[Number(idx)].key];
        return ranges.some(([lo, hi]) => v >= lo && v <= hi);
      });
      if (pass) set.add(`${row.i},${row.j}`);
    });
    return set;
  }, [pc, constraints]);

  const onParcoordsRestyle = useCallback((ev) => {
    const update = Array.isArray(ev) ? ev[0] : null;
    if (!update) return;
    setConstraints((prev) => {
      const next = { ...prev };
      Object.entries(update).forEach(([k, v]) => {
        const m = k.match(/^dimensions\[(\d+)\]\.constraintrange$/);
        if (!m) return;
        let val = Array.isArray(v) && v.length === 1 && Array.isArray(v[0]) && Array.isArray(v[0][0]) ? v[0] : v;
        if (!val || (Array.isArray(val) && val.length === 0) || val[0] === null) {
          delete next[m[1]];
          return;
        }
        if (typeof val[0] === "number") val = [val];
        next[m[1]] = val;
      });
      return next;
    });
  }, []);

  if (!meta || !dayModel || !dayRef || !pc) {
    return <div className={`${card} p-8 text-body-md text-on-surface-variant`}>Loading basin fields…</div>;
  }
  const refName = dayModel.reference_name || "reference";

  const f = day.fields;
  const lons = day.lons;
  const lats = day.lats;
  const nD26 = f.d26_m.flat().filter(finite).length;
  const nD20 = f.d20_m.flat().filter(finite).length;

  // ---------- 3D isotherm surfaces
  const toDepthZ = (grid) => grid.map((row) => row.map((v) => (finite(v) ? -v : null)));
  const maxD20 = Math.max(...f.d20_m.flat().filter(finite), 50);
  const hover = (name) =>
    `${name}<br>%{y:.2f}°N, %{x:.2f}°E<br>depth %{customdata:.1f} m<extra></extra>`;
  const isoData = [
    {
      type: "surface",
      name: "D26",
      x: lons,
      y: lats,
      z: toDepthZ(f.d26_m),
      customdata: f.d26_m,
      surfacecolor: f.d26_m.map((r) => r.map(() => 1)),
      colorscale: [[0, "#EA580C"], [1, "#EA580C"]],
      showscale: false,
      opacity: 0.95,
      hovertemplate: hover("26 °C isotherm"),
      contours: { z: { show: false } }
    },
    {
      type: "surface",
      name: "D20",
      x: lons,
      y: lats,
      z: toDepthZ(f.d20_m),
      customdata: f.d20_m,
      surfacecolor: f.d20_m.map((r) => r.map(() => 0)),
      colorscale: [[0, "#0E7490"], [1, "#0E7490"]],
      showscale: false,
      opacity: 0.85,
      hovertemplate: hover("20 °C isotherm"),
      contours: { z: { show: false } }
    }
  ];

  // ---------- parallel coordinates
  const pcDims = PC_DIMS.map((d, idx) => {
    const vals = pc.rows.map((r) => r[d.key]);
    const dim = {
      label: `${d.label} (${d.units})`,
      values: vals,
      range: [Math.min(...vals), Math.max(...vals)]
    };
    if (constraints[idx]) dim.constraintrange = constraints[idx].length === 1 ? constraints[idx][0] : constraints[idx];
    return dim;
  });
  const tchpVals = pc.rows.map((r) => r.tchp_kj_cm2);
  const pcData = [
    {
      type: "parcoords",
      line: {
        color: tchpVals,
        colorscale: "YlOrRd",
        cmin: Math.min(...tchpVals),
        cmax: Math.max(...tchpVals),
        showscale: true,
        colorbar: { title: { text: "TCHP<br>kJ/cm²" }, thickness: 12 }
      },
      dimensions: pcDims,
      labelfont: { size: 11, color: "#00253D" },
      tickfont: { size: 10, color: "#42474E" },
      rangefont: { size: 9, color: "#72787E" }
    }
  ];

  // ---------- linked map
  const metric = MAP_METRICS.find((m) => m.key === mapMetric);
  const canDiff = metric.diffOk;
  const effectiveMode = canDiff ? mapMode : "value";
  const mg = days.model.fields[mapMetric];
  const gg = days.glorys.fields[mapMetric];
  const zMap = lats.map((_, i) =>
    lons.map((__, j) => {
      if (selectedMask && !selectedMask.has(`${i},${j}`)) return null;
      if (effectiveMode === "diff") {
        const a = mg[i][j];
        const b = gg[i][j];
        return finite(a) && finite(b) ? a - b : null;
      }
      const v = f[mapMetric][i][j];
      return finite(v) ? v : null;
    })
  );
  const zFlat = zMap.flat().filter(finite);
  const absMax = zFlat.length ? Math.max(...zFlat.map(Math.abs)) : 1;
  const mapData = [
    {
      type: "heatmap",
      x: lons,
      y: lats,
      z: zMap,
      colorscale: effectiveMode === "diff" ? "RdBu" : metric.scale,
      reversescale: effectiveMode === "diff" ? true : !!metric.reverse,
      zmid: effectiveMode === "diff" ? 0 : undefined,
      zmin: effectiveMode === "diff" ? -absMax : undefined,
      zmax: effectiveMode === "diff" ? absMax : undefined,
      colorbar: { title: { text: effectiveMode === "diff" ? `Δ ${metric.units}` : metric.units }, thickness: 12 },
      hovertemplate: `%{y:.2f}°N, %{x:.2f}°E<br>%{z:.2f} ${metric.units}<extra></extra>`
    }
  ];
  const nSelected = selectedMask ? selectedMask.size : pc.rows.length;
  const diffStats = (() => {
    if (effectiveMode !== "diff" || !zFlat.length) return null;
    const n = zFlat.length;
    const bias = zFlat.reduce((s, v) => s + v, 0) / n;
    const rmse = Math.sqrt(zFlat.reduce((s, v) => s + v * v, 0) / n);
    return { n, bias, rmse };
  })();

  const fileInfo = meta.files.find((x) => x.file === dateInfo?.file) || {};
  const skill = fileInfo.skill || {};
  const isFixture = String(dayModel.input_data).toUpperCase().includes("SYNTHETIC");

  return (
    <div className="flex flex-col gap-6">
      {isFixture && (
        <div className="px-5 py-4 rounded-xl bg-rose-50 border border-rose-300 text-rose-900 text-body-md">
          <strong>Synthetic test fixture.</strong> This file was produced from idealised test inputs, not satellite or
          reanalysis data. Use it to check the pipeline only; do not present these numbers.
        </div>
      )}
      {fileInfo.checkpoint_matches_server === false && (
        <div className="px-5 py-4 rounded-xl bg-amber-50 border border-amber-300 text-amber-900 text-body-md">
          The basin file was made with a different checkpoint than the one this server loaded. Re-run basin_inference.py.
        </div>
      )}

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-body-sm text-on-surface-variant">Profiles from</span>
          <div className="inline-flex p-1 rounded-xl bg-surface-container-low border border-surface-container-high">
            {[
              { v: "model", l: "OceanEmbed" },
              { v: "glorys", l: refName }
            ].map((o) => (
              <button
                key={o.v}
                onClick={() => setSource(o.v)}
                className={`px-3 py-1.5 rounded-lg text-body-sm font-medium transition ${
                  source === o.v ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-primary"
                }`}
              >
                {o.l}
              </button>
            ))}
          </div>
        </div>
        <div className="ml-auto text-body-sm text-on-surface-variant text-right">
          <div>
            RMSE vs {refName} in this file:{" "}
            {["heldout", "independent", "train"].filter((k) => skill[k]?.rmse_c != null).map((k) => (
              <span key={k} className="ml-2">{k === "train" ? "training" : k} days <span className="font-mono text-primary">{fmt(skill[k].rmse_c, 3)} °C</span></span>
            ))}
          </div>
          <div>{day.n_valid_cells.toLocaleString()} ocean cells at {meta.grid.resolution_deg}°</div>
        </div>
      </div>

      {dateInfo?.split === "train" && (
        <div className="px-5 py-3 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-body-sm">
          This date was in the training period, so the model has seen the reference for it. Agreement here is not evidence
          of skill. Pick a held-out date to judge accuracy.
        </div>
      )}

      {/* Isotherm surfaces */}
      <div className={`${card} overflow-hidden`}>
        <div className="px-6 pt-5 flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="font-headline-sm text-headline-sm text-primary">Isotherm depth surfaces</h3>
          <div className="flex items-center gap-4 text-body-sm text-on-surface-variant">
            <span className="inline-flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-[#EA580C]"></span>26 °C ({nD26.toLocaleString()} cells)</span>
            <span className="inline-flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-[#0E7490]"></span>20 °C ({nD20.toLocaleString()} cells)</span>
          </div>
        </div>
        <div className="h-[460px]">
          <Plot
            data={isoData}
            layout={{
              autosize: true,
              margin: { l: 0, r: 0, t: 10, b: 0 },
              showlegend: false,
              scene: {
                xaxis: { title: { text: "Longitude (°E)" }, backgroundcolor: "#EAF5FF", gridcolor: "#C7E7FE" },
                yaxis: { title: { text: "Latitude (°N)" }, backgroundcolor: "#EAF5FF", gridcolor: "#C7E7FE" },
                zaxis: { title: { text: "Depth (m)" }, range: [-Math.ceil(maxD20 / 50) * 50, 0], backgroundcolor: "#EAF5FF", gridcolor: "#C7E7FE" },
                aspectmode: "manual",
                aspectratio: { x: 2.4, y: 1, z: 0.55 },
                camera: { eye: { x: 0.9, y: -1.9, z: 0.9 } }
              },
              paper_bgcolor: "rgba(0,0,0,0)"
            }}
            useResizeHandler
            className="w-full h-full"
            config={{ responsive: true, displaylogo: false }}
          />
        </div>
        <p className="px-6 pb-5 text-body-sm text-on-surface-variant leading-relaxed">
          Depth where each profile first drops below 26 °C and 20 °C, by linear interpolation between the 15 standard
          levels. Gaps mean the surface is already colder than that temperature, or the cell is land or shallower than
          1000 m (outside the model&apos;s training domain). Vertical exaggeration is large; depths are true values.
        </p>
      </div>

      {/* Parallel coordinates */}
      <div className={`${card} overflow-hidden`}>
        <div className="px-6 pt-5 flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="font-headline-sm text-headline-sm text-primary">Parallel coordinates</h3>
          <span className="text-body-sm text-on-surface-variant">
            Drag along any axis to filter · {nSelected.toLocaleString()} of {pc.rows.length.toLocaleString()} cells selected
          </span>
        </div>
        <div className="h-[420px] px-2">
          <Plot
            data={pcData}
            layout={{ autosize: true, margin: { l: 60, r: 70, t: 60, b: 20 }, paper_bgcolor: "rgba(0,0,0,0)" }}
            onRestyle={onParcoordsRestyle}
            useResizeHandler
            className="w-full h-full"
            config={{ responsive: true, displaylogo: false }}
          />
        </div>
        <p className="px-6 pb-5 text-body-sm text-on-surface-variant leading-relaxed">
          One line per ocean cell for {date}. SST and SSH are the satellite inputs; the other axes come from the
          {source === "model" ? " predicted" : ` ${refName}`} profile. D26 is 0 where no water is 26 °C or warmer
          ({pc.d26Zero.toLocaleString()} cells), matching TCHP = 0 there.
          {pc.excluded > 0 && ` ${pc.excluded.toLocaleString()} cells left out because a diagnostic is undefined (for example no 0.2 °C change below 10 m, so no mixed-layer base).`}
          {" "}RMSE vs reference is the error of the OceanEmbed profile in either view. Input |z| is how far the
          surface inputs sit from the training data, in standard deviations; above about 4 the prediction is an extrapolation.
        </p>
      </div>

      {/* Linked map */}
      <div className={`${card} overflow-hidden`}>
        <div className="px-6 pt-5 flex flex-wrap items-end justify-between gap-3">
          <h3 className="font-headline-sm text-headline-sm text-primary">Map of selected cells</h3>
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={mapMetric}
              onChange={(e) => setMapMetric(e.target.value)}
              className="bg-surface-container-lowest border border-surface-container-high rounded-xl px-3 py-2 text-body-sm text-primary"
            >
              {MAP_METRICS.map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
            <div className="inline-flex p-1 rounded-xl bg-surface-container-low border border-surface-container-high">
              {[
                { v: "value", l: source === "model" ? "OceanEmbed" : refName },
                { v: "diff", l: "OceanEmbed − reference" }
              ].map((o) => (
                <button
                  key={o.v}
                  disabled={o.v === "diff" && !canDiff}
                  onClick={() => setMapMode(o.v)}
                  className={`px-3 py-1.5 rounded-lg text-body-sm font-medium transition disabled:opacity-40 ${
                    effectiveMode === o.v ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-primary"
                  }`}
                >
                  {o.l}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="h-[440px]">
          <Plot
            data={mapData}
            layout={{
              autosize: true,
              margin: { l: 55, r: 10, t: 20, b: 45 },
              xaxis: { title: { text: "Longitude (°E)" }, range: [meta.grid.lon_min, meta.grid.lon_max], gridcolor: "#D3EBFF" },
              yaxis: { title: { text: "Latitude (°N)" }, range: [meta.grid.lat_min, meta.grid.lat_max], scaleanchor: "x", scaleratio: 1, gridcolor: "#D3EBFF" },
              plot_bgcolor: "#F1F5F9",
              paper_bgcolor: "rgba(0,0,0,0)"
            }}
            useResizeHandler
            className="w-full h-full"
            config={{ responsive: true, displaylogo: false }}
          />
        </div>
        <p className="px-6 pb-5 text-body-sm text-on-surface-variant leading-relaxed">
          {effectiveMode === "diff" && diffStats
            ? `OceanEmbed minus ${refName} over ${diffStats.n.toLocaleString()} cells: mean bias ${fmt(diffStats.bias)} ${metric.units}, RMSE ${fmt(diffStats.rmse)} ${metric.units}. Cells where either value is undefined are blank. `
            : ""}
          Grey is land, water shallower than 1000 m, cells where this quantity is undefined, or cells outside the
          parallel-coordinates filter. Plate carrée projection, 0.25° cells.
        </p>
      </div>
    </div>
  );
}
