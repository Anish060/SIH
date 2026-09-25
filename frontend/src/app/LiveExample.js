"use client";

// Landing-page example drawn from the API: the newest held-out or independent day,
// at the Central Bay of Bengal. Shows nothing but a note if the backend has no data.

import { useEffect, useState } from "react";

const DEPTHS = [0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000];
const LABELS = { sst: "Sea surface temperature", ssh: "Sea surface height", sss: "Surface salinity", uo: "Eastward current", vo: "Northward current", u10: "Eastward wind", v10: "Northward wind" };
const SOURCES = { sst: "OSTIA", ssh: "CMEMS", sss: "CMEMS", uo: "CMEMS", vo: "CMEMS", u10: "ERA5", v10: "ERA5" };
const fmt = (v, d = 2) => (v === null || v === undefined || !Number.isFinite(Number(v)) ? "—" : Number(v).toFixed(d));

async function j(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

export function useLiveExample() {
  const [state, setState] = useState({ status: "loading" });
  useEffect(() => {
    (async () => {
      try {
        const meta = await j("/api/basin/meta");
        const order = ["independent", "heldout"];
        const pool = order.map((s) => meta.dates.filter((d) => d.split === s)).find((a) => a.length);
        if (!pool) return setState({ status: "none" });
        const day = pool[pool.length - 1];
        const point = await j(`/api/point?date=${day.date}&lat=14.5&lon=88.0`);
        let bench = null;
        try { bench = await j("/api/benchmarks"); } catch { /* optional */ }
        setState({ status: "ok", day, point, bench });
      } catch {
        setState({ status: "none" });
      }
    })();
  }, []);
  return state;
}

export function LiveInputs({ state }) {
  if (state.status !== "ok") {
    return <p className="text-body-md text-on-surface-variant">{state.status === "loading" ? "Loading a real example…" : "Start the backend with inference files to see a real example here."}</p>;
  }
  const { point, day } = state;
  return (
    <>
      <dl className="divide-y divide-surface-container-high border-y border-surface-container-high">
        {Object.entries(point.inputs).map(([k, v]) => (
          <div key={k} className="flex items-baseline gap-4 py-3">
            <dt className="flex-1 text-body-md text-on-surface">{LABELS[k]}</dt>
            <dd className="font-mono text-body-md text-primary tabular-nums">{fmt(v.value, k === "ssh" ? 3 : 2)} {v.units}</dd>
            <dd className="w-14 text-right text-body-sm text-on-surface-variant">{SOURCES[k]}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-body-sm text-on-surface-variant">
        {point.cell.lat.toFixed(2)}°N {point.cell.lon.toFixed(2)}°E on {day.date} ({day.split === "heldout" ? "held-out day" : "outside the training period"}).
        {String(day.input_data).includes("SYNTHETIC") && " Synthetic test fixture, not observations."}
      </p>
    </>
  );
}

export function LiveProfile({ state }) {
  if (state.status !== "ok") return null;
  const P = state.point.model.profile_c;
  const R = state.point.reference.profile_c;
  const all = [...P, ...R].filter((v) => Number.isFinite(v));
  const lo = Math.floor(Math.min(...all)) - 1;
  const hi = Math.ceil(Math.max(...all)) + 1;
  const px = (t) => 16 + ((t - lo) / (hi - lo)) * 268;
  const py = (d) => 12 + Math.sqrt(d / 1000) * 296;
  const path = (arr) => arr.map((t, i) => `${i ? "L" : "M"}${px(t).toFixed(1)},${py(DEPTHS[i]).toFixed(1)}`).join(" ");
  return (
    <>
      <svg viewBox="0 0 300 330" className="w-full h-auto" role="img" aria-label="Predicted and reference temperature profiles">
        {[0, 100, 500, 1000].map((d) => (
          <g key={d}>
            <line x1="16" x2="284" y1={py(d)} y2={py(d)} stroke="#D3EBFF" strokeWidth="1" />
            <text x="284" y={py(d) - 5} textAnchor="end" fontSize="10" fill="#42474E">{d === 0 ? "surface" : `${d} m`}</text>
          </g>
        ))}
        <path d={path(R)} fill="none" stroke="#EA580C" strokeWidth="1.8" strokeDasharray="4 3" />
        <path d={path(P)} fill="none" stroke="#00B1C9" strokeWidth="2.5" strokeLinejoin="round" />
        {P.map((t, i) => <circle key={i} cx={px(t)} cy={py(DEPTHS[i])} r="2.6" fill="#00253D" />)}
        <text x={px(P[0]) - 6} y={py(0) + 16} textAnchor="end" fontSize="11" fontWeight="600" fill="#00253D">{fmt(P[0], 1)} °C</text>
        <text x={px(P[14]) + 8} y={py(1000) - 6} fontSize="11" fontWeight="600" fill="#00253D">{fmt(P[14], 1)} °C</text>
      </svg>
      <p className="mt-3 text-body-sm text-on-surface-variant">
        Solid: OceanEmbed. Dashed: {state.point.reference_name}. Profile RMSE {fmt(state.point.profile_rmse_c, 2)} °C. Depth on a square-root scale.
      </p>
    </>
  );
}

export function LiveValidation({ state }) {
  const oe = state.bench?.models?.find((m) => m.model === "OceanEmbed CNN");
  if (!oe?.evaluated) return <>Validation numbers appear here once <span className="font-mono">eval_results.json</span> exists.</>;
  return (
    <>
      On held-out days it is within <span className="text-secondary">{fmt(oe.glorys_heldout_rmse_c, 2)} °C</span> (RMSE) of GLORYS12
      {oe.argo && <>, and <span className="text-secondary">{fmt(oe.argo.rmse_c, 2)} °C</span> of the gridded Argo analysis</>}.
    </>
  );
}
