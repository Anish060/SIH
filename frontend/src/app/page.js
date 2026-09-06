"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";

// =============================================================================
// THE 15 STANDARD OCEANOGRAPHIC DEPTH LEVELS (from README.md & GLORYS12)
// =============================================================================
const DEPTH_LEVELS = [0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000];

// =============================================================================
// REAL GEOGRAPHICAL PRESETS (Bay of Bengal & Arabian Sea: 5°N - 30°N, 45°E - 105°E)
// =============================================================================
const REGIONAL_PRESETS = [
  {
    id: "cyclone_hotspot",
    name: "Central Bay of Bengal",
    subtitle: "Cyclone Heat Reservoir",
    coords: "14.50° N, 88.00° E",
    lat: 14.5,
    lon: 88.0,
    marker: { x: 430, y: 270 },
    params: { sst: 29.8, ssh: 0.22, sss: 0.01, uo: -0.18, vo: 0.12, u10: -4.5, v10: -6.2 },
    context: "Warm-core anticyclonic eddy where tropical cyclones undergo rapid intensification."
  },
  {
    id: "asw_corridor",
    name: "South-West Bay Trench",
    subtitle: "ASW Defense Acoustic Shadow",
    coords: "10.00° N, 84.00° E",
    lat: 10.0,
    lon: 84.0,
    marker: { x: 310, y: 390 },
    params: { sst: 28.2, ssh: 0.04, sss: 0.03, uo: -0.25, vo: -0.05, u10: -2.1, v10: -3.4 },
    context: "Steep thermocline density gradient creating active sonar shadow zones for submarine concealment."
  },
  {
    id: "coastal_upwelling",
    name: "Visakhapatnam Coast",
    subtitle: "PFZ Fisheries Upwelling",
    coords: "17.50° N, 83.50° E",
    lat: 17.5,
    lon: 83.5,
    marker: { x: 260, y: 210 },
    params: { sst: 26.5, ssh: -0.12, sss: 0.08, uo: 0.22, vo: 0.35, u10: 3.2, v10: 4.8 },
    context: "Cold thermocline upwelling bringing nutrient-rich waters for commercial pelagic fish shoals."
  },
  {
    id: "andaman_trench",
    name: "Andaman Deep Basin",
    subtitle: "1000m Abyssal Sounding",
    coords: "12.00° N, 93.50° E",
    lat: 12.0,
    lon: 93.5,
    marker: { x: 610, y: 340 },
    params: { sst: 28.9, ssh: 0.02, sss: 0.02, uo: -0.12, vo: 0.08, u10: -2.8, v10: -3.1 },
    context: "Deep bathymetric water mass extending through all 15 hydrographic standard depth strata."
  },
  {
    id: "ganges_delta",
    name: "Northern Bay Delta",
    subtitle: "Riverine Salinity Plume",
    coords: "21.00° N, 89.00° E",
    lat: 21.0,
    lon: 89.0,
    marker: { x: 450, y: 90 },
    params: { sst: 27.8, ssh: 0.15, sss: -0.35, uo: -0.08, vo: -0.15, u10: -1.5, v10: -2.2 },
    context: "River runoff creating shallow barrier layer salinity anomalies affecting acoustic propagation."
  }
];

// =============================================================================
// DETERMINISTIC INITIAL STATE (Guarantees zero SSR/client hydration mismatch)
// =============================================================================
const DETERMINISTIC_INITIAL_PREDICTION = {
  profile_celsius: [25.56, 25.53, 25.60, 25.54, 25.62, 25.37, 23.93, 21.82, 18.99, 16.45, 13.64, 12.08, 10.20, 8.45, 6.68],
  latent_embedding: {
    preview_dims: [0.42, -0.18, 0.85, -0.62, 0.31, 0.74, -0.91, 0.15, -0.45, 0.58, 0.22, -0.73, 0.67, -0.34, 0.19, 0.82],
    full_latent_vector: [
      0.42, -0.18, 0.85, -0.62, 0.31, 0.74, -0.91, 0.15, -0.45, 0.58, 0.22, -0.73, 0.67, -0.34, 0.19, 0.82,
      -0.55, 0.39, 0.71, -0.28, 0.64, -0.83, 0.12, 0.47, -0.33, 0.91, -0.16, 0.25, -0.78, 0.52, -0.41, 0.63,
      0.35, -0.68, 0.29, 0.88, -0.49, 0.17, -0.75, 0.54, -0.21, 0.66, 0.38, -0.87, 0.14, -0.59, 0.43, -0.31,
      0.76, -0.24, 0.59, -0.67, 0.33, 0.81, -0.44, 0.26, -0.89, 0.18, 0.51, -0.37, 0.72, -0.15, 0.61, -0.48
    ]
  },
  derived_pillars: {
    cyclone: {
      d26_depth_m: 54.2,
      tchp_kj_cm2: 98.6,
      risk_category: "Severe Risk (TCHP > 80 kJ/cm²)",
      rapid_intensification_threat: true
    },
    asw_defense: {
      thermocline_core_depth_m: 75,
      max_thermal_gradient_c_per_m: -0.1135,
      sonic_shadow_zone: {
        start_depth_m: 75,
        end_depth_m: 150,
        thickness_m: 75,
        description: "Active surface sonar waves refract sharply downward at 75m, creating an acoustic shadow corridor for submarine concealment."
      }
    },
    fisheries: {
      upwelling_index_c: 2.19,
      pfz_status: "Moderate Upwelling",
      nutrient_score: "High Potential Zone",
      distance_to_border_km: 48.0,
      border_alert: "Safe Zone: Within Domestic Indian EEZ Waters"
    }
  }
};

export default function OceanEmbedApp() {
  const [activePreset, setActivePreset] = useState(REGIONAL_PRESETS[0]);
  const [params, setParams] = useState(REGIONAL_PRESETS[0].params);
  const [selectedDepthIdx, setSelectedDepthIdx] = useState(7); // 100m default (Thermocline)
  const [prediction, setPrediction] = useState(DETERMINISTIC_INITIAL_PREDICTION);
  const [loading, setLoading] = useState(false);
  const [backendStatus, setBackendStatus] = useState({ connected: false, device: "cuda", params: 181487 });
  const [copied, setCopied] = useState(false);
  const [showChannelDrawer, setShowChannelDrawer] = useState(false);

  // Trigger live prediction from PyTorch FastAPI backend
  const runPrediction = useCallback(async (currentParams = params, currentPreset = activePreset) => {
    setLoading(true);
    try {
      const res = await fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sst_celsius: Number(currentParams.sst),
          ssh_meters: Number(currentParams.ssh),
          sss_psu: Number(currentParams.sss),
          uo_mps: Number(currentParams.uo),
          vo_mps: Number(currentParams.vo),
          u10_mps: Number(currentParams.u10),
          v10_mps: Number(currentParams.v10),
          latitude: Number(currentPreset.lat),
          longitude: Number(currentPreset.lon)
        })
      });

      if (res.ok) {
        const data = await res.json();
        setPrediction(data);
        setBackendStatus((prev) => ({ ...prev, connected: true }));
      }
    } catch (err) {
      console.warn("FastAPI backend call failed:", err);
    } finally {
      setLoading(false);
    }
  }, [params, activePreset]);

  // Check health and run initial prediction on mount
  useEffect(() => {
    fetch("/api/health")
      .then((res) => res.json())
      .then((data) => {
        if (data.status === "healthy") {
          setBackendStatus({ connected: true, device: data.device, params: data.total_parameters });
        }
      })
      .catch(() => {});
    runPrediction();
  }, [runPrediction]);

  // Change preset station
  const handleSelectPreset = (preset) => {
    setActivePreset(preset);
    setParams(preset.params);
    runPrediction(preset.params, preset);
  };

  // Change individual satellite parameter
  const handleParamChange = (key, val) => {
    const updated = { ...params, [key]: parseFloat(val) || 0 };
    setParams(updated);
  };

  // Current depth and temperature
  const currentDepth = DEPTH_LEVELS[selectedDepthIdx];
  const currentTemp = prediction?.profile_celsius?.[selectedDepthIdx] ?? 21.82;
  const surfaceTemp = prediction?.profile_celsius?.[0] ?? 25.56;
  const thermoclineTemp = prediction?.profile_celsius?.[7] ?? 21.82;
  const abyssalTemp = prediction?.profile_celsius?.[14] ?? 6.68;

  // Temperature Sounding Curve Points (Rounded to 1 decimal to prevent SVG hydration discrepancy)
  const curvePoints = useMemo(() => {
    const temps = prediction?.profile_celsius || DETERMINISTIC_INITIAL_PREDICTION.profile_celsius;
    const minT = 4.0;
    const maxT = 32.0;
    return temps.map((t, i) => {
      const x = ((t - minT) / (maxT - minT)) * 260 + 20;
      const y = Math.pow(i / 14, 0.85) * 190 + 20;
      return {
        x: Number(x.toFixed(1)),
        y: Number(y.toFixed(1)),
        temp: Number(t.toFixed(2)),
        idx: i,
        depth: DEPTH_LEVELS[i]
      };
    });
  }, [prediction]);

  const curvePathD = useMemo(() => {
    return curvePoints.reduce((acc, pt, idx) => (idx === 0 ? `M ${pt.x},${pt.y}` : `${acc} L ${pt.x},${pt.y}`), "");
  }, [curvePoints]);

  return (
    <div className="min-h-screen bg-surface text-on-surface flex flex-col selection:bg-secondary-container selection:text-on-secondary-container">
      {/* =========================================================================
          TOP NAVIGATION BAR (Strictly using user template aesthetic)
          ========================================================================= */}
      <header className="fixed top-0 left-0 right-0 w-full z-50 bg-surface/90 backdrop-blur-xl border-b border-surface-container-high/60 shadow-[0_1px_8px_rgba(0,30,46,0.05)]">
        <div className="h-16 w-full px-margin-desktop flex items-center justify-between gap-space-md">
          {/* Logo & Hackathon Identity */}
          <div className="flex items-center gap-space-lg">
            <div className="flex items-center gap-space-sm">
              <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center shadow-md">
                <svg className="w-5 h-5 text-on-primary" fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path d="M2 15C5 12 8 18 12 15C16 12 19 18 22 15" stroke="#FFFFFF" strokeLinecap="round" strokeWidth="2.2"></path>
                  <ellipse cx="12" cy="12" rx="9" ry="4.5" stroke="#00B1C9" strokeDasharray="2 2" strokeWidth="1.6" transform="rotate(-25 12 12)"></ellipse>
                </svg>
              </div>
              <div className="flex flex-col">
                <span className="font-headline-sm text-headline-sm text-primary tracking-tight font-semibold leading-none">
                  OceanEmbed
                </span>
                <span className="font-caption-coordinate text-caption-coordinate uppercase text-secondary tracking-wider mt-space-2xs">
                  Team OceanSATX • SIH 2026 PS 26066
                </span>
              </div>
            </div>

            {/* Quick Section Anchors */}
            <nav className="hidden xl:flex items-center gap-space-lg font-body-sm text-body-sm text-on-surface-variant">
              <a href="#interactive-map" className="hover:text-primary transition font-medium">
                GIS Ocean Probe
              </a>
              <a href="#pillars" className="hover:text-primary transition font-medium">
                4 Core Pillars
              </a>
              <a href="#benchmarks" className="hover:text-primary transition font-medium">
                54,606 ARGO Buoys
              </a>
            </nav>
          </div>

          {/* Real PyTorch Backend Connection Status Badge */}
          <div className="flex items-center gap-space-sm">
            <div className="flex items-center gap-1.5 px-space-md py-space-2xs rounded-full bg-surface-container-low border border-surface-container-high text-primary font-caption-coordinate text-caption-coordinate">
              <span className={`w-2 h-2 rounded-full ${backendStatus.connected ? "bg-emerald-500 animate-pulse" : "bg-amber-500"}`}></span>
              <span className="font-mono font-medium">
                {backendStatus.connected
                  ? `PyTorch ${backendStatus.device.toUpperCase()} Connected (${backendStatus.params.toLocaleString()} Params)`
                  : "Connecting to FastAPI..."}
              </span>
            </div>

            <button
              onClick={() => runPrediction(params, activePreset)}
              disabled={loading}
              className="inline-flex items-center gap-space-xs font-label-technical text-label-technical uppercase tracking-wider bg-primary hover:bg-secondary text-on-primary px-space-md py-space-xs rounded-lg shadow-sm transition"
            >
              <span className="material-symbols-outlined text-[16px]">{loading ? "hourglass_empty" : "refresh"}</span>
              <span>{loading ? "Computing..." : "Run Model"}</span>
            </button>
          </div>
        </div>
      </header>

      {/* =========================================================================
          MAIN APPLICATION COCKPIT (Grounded strictly in README.md)
          ========================================================================= */}
      <main className="flex-1 w-full pt-20 pb-space-3xl px-margin-desktop max-w-7xl mx-auto flex flex-col gap-space-xl">
        {/* Title Bar & Regional Station Preset Selector */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-space-md pb-space-sm border-b border-surface-container-high/60">
          <div>
            <div className="flex items-center gap-space-xs mb-1">
              <span className="font-label-technical text-label-technical uppercase tracking-wider text-secondary font-semibold">
                North Indian Ocean Basin (5°N – 30°N, 45°E – 105°E)
              </span>
              <span className="text-xs text-on-surface-variant font-mono">• 0.25° Spatial Patch</span>
            </div>
            <h1 className="font-headline-lg text-headline-lg text-primary tracking-tight font-semibold">
              3D Subsurface Ocean Structure &amp; 128-D Latent Intelligence
            </h1>
          </div>

          {/* Regional Preset Stations */}
          <div className="flex flex-wrap items-center gap-1.5">
            {REGIONAL_PRESETS.map((preset) => {
              const isActive = activePreset.id === preset.id;
              return (
                <button
                  key={preset.id}
                  onClick={() => handleSelectPreset(preset)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1.5 shadow-sm border ${
                    isActive
                      ? "bg-primary text-on-primary border-primary font-semibold shadow"
                      : "bg-surface-container-lowest text-on-surface border-surface-container-high hover:bg-surface-container-high"
                  }`}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-on-tertiary-container"></span>
                  <span>{preset.name}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* =======================================================================
            TWO-COLUMN INTERACTIVE OCEAN COCKPIT
            ======================================================================= */}
        <div id="interactive-map" className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg items-start">
          {/* LEFT COLUMN (7 Cols): SVG Marine Chart & 14-Channel Telemetry */}
          <div className="lg:col-span-7 flex flex-col gap-space-md">
            {/* Publication-Grade Synthetic Marine Chart */}
            <div className="bg-surface-container relative rounded-xl overflow-hidden h-[460px] shadow-sm border border-surface-container-high/60 flex flex-col justify-between p-space-sm">
              {/* Telemetry HUD */}
              <div className="z-10 flex items-center justify-between bg-surface-container-lowest/90 backdrop-blur-md px-space-md py-space-xs rounded-md shadow-sm border border-surface-container-high/40">
                <div className="flex items-center gap-space-sm">
                  <span className="font-caption-coordinate text-caption-coordinate text-secondary font-semibold uppercase">
                    STATION
                  </span>
                  <span className="font-label-technical text-label-technical text-primary font-mono font-medium">
                    {activePreset.name} [{activePreset.coords}]
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-on-tertiary-container animate-ping"></span>
                  <span className="font-caption-coordinate text-caption-coordinate text-secondary font-mono font-semibold">
                    ACTIVE SATELLITE OVERPASS
                  </span>
                </div>
              </div>

              {/* Synthetic Marine Vector Graphic */}
              <div className="absolute inset-0 w-full h-full">
                <svg className="w-full h-full object-cover" viewBox="0 0 800 540" xmlns="http://www.w3.org/2000/svg">
                  {/* Water Base */}
                  <rect fill="#EAF5FF" height="540" width="800"></rect>

                  {/* Bathymetric Isobars */}
                  <path d="M 0,220 Q 200,210 380,240 T 700,220 L 800,240 L 800,540 L 0,540 Z" fill="#D3EBFF" opacity="0.6"></path>
                  <path d="M 0,310 Q 240,290 440,330 T 800,310 L 800,540 L 0,540 Z" fill="#C7E7FE" opacity="0.65"></path>
                  <path d="M 0,400 Q 280,380 500,420 T 800,390 L 800,540 L 0,540 Z" fill="#79D1FB" opacity="0.3"></path>

                  {/* Coastline Margins */}
                  <path d="M 0,0 L 220,0 Q 210,120 180,190 T 130,340 Q 110,420 80,480 L 0,520 Z" fill="#DFF0FF" stroke="#72787E" strokeWidth="1.2"></path>
                  <ellipse cx="145" cy="460" fill="#DFF0FF" rx="22" ry="34" stroke="#72787E" strokeWidth="1.2"></ellipse>
                  <path d="M 660,0 Q 640,110 650,220 T 680,390 Q 720,480 800,520 L 800,0 Z" fill="#DFF0FF" stroke="#72787E" strokeWidth="1.2"></path>
                  <ellipse cx="610" cy="300" fill="#DFF0FF" rx="6" ry="36" stroke="#72787E" strokeWidth="1"></ellipse>
                  <ellipse cx="618" cy="390" fill="#DFF0FF" rx="4" ry="18" stroke="#72787E" strokeWidth="1"></ellipse>

                  {/* Warm-Core Anticyclonic Eddy (Central Bay) */}
                  <circle cx="430" cy="270" fill="#FFF7ED" fillOpacity="0.35" r="110"></circle>
                  <circle cx="430" cy="270" fill="#FFDAD6" fillOpacity="0.4" r="80"></circle>
                  <circle cx="430" cy="270" fill="#F97316" fillOpacity="0.25" r="50"></circle>
                  <circle cx="430" cy="270" opacity="0.7" r="80" stroke="#EA580C" strokeDasharray="5 3" strokeWidth="1"></circle>

                  {/* Cold-Core Cyclonic Eddy (Coastal Upwelling) */}
                  <circle cx="280" cy="380" fill="#006686" fillOpacity="0.15" r="45"></circle>
                  <circle cx="280" cy="380" r="45" stroke="#00B1C9" strokeDasharray="3 3" strokeWidth="1"></circle>

                  {/* Satellite Ground Track (Sentinel-6A) */}
                  <line opacity="0.7" stroke="#00B1C9" strokeDasharray="6 4" strokeWidth="1.6" x1="280" x2="520" y1="0" y2="540"></line>
                  <text fill="#006686" fontFamily="Geist" fontSize="9" fontWeight="600" x="500" y="520">
                    ALT-TRACK SENTINEL-6A
                  </text>

                  {/* Tropical Cyclone Trajectory & Eye */}
                  <path d="M 560,440 Q 460,340 370,230 T 260,80" fill="none" stroke="#BA1A1A" strokeDasharray="5 3" strokeWidth="2"></path>
                  <circle cx="415" cy="285" fill="#BA1A1A" r="7"></circle>
                  <circle cx="415" cy="285" r="14" stroke="#BA1A1A" strokeDasharray="2 2" strokeOpacity="0.6" strokeWidth="1.2"></circle>
                  <text fill="#BA1A1A" fontFamily="Geist" fontSize="10" fontWeight="bold" x="435" y="290">
                    CYCLONE EYE (TCHP &gt; 80 kJ/cm²)
                  </text>

                  {/* INCOIS ARGO Buoys */}
                  <g transform="translate(390, 240)">
                    <circle cx="0" cy="0" fill="#00B1C9" r="4"></circle>
                    <circle cx="0" cy="0" opacity="0.7" r="9" stroke="#00B1C9" strokeWidth="1"></circle>
                    <text fill="#00253D" fontFamily="Geist" fontSize="8" fontWeight="600" x="8" y="3">
                      INCOIS #2902715
                    </text>
                  </g>
                  <g transform="translate(480, 320)">
                    <circle cx="0" cy="0" fill="#00B1C9" r="4"></circle>
                    <circle cx="0" cy="0" opacity="0.7" r="9" stroke="#00B1C9" strokeWidth="1"></circle>
                    <text fill="#00253D" fontFamily="Geist" fontSize="8" fontWeight="600" x="8" y="3">
                      INCOIS #2902688
                    </text>
                  </g>

                  {/* Active Crosshair Reticle for Selected Preset */}
                  <g transform={`translate(${activePreset.marker.x}, ${activePreset.marker.y})`}>
                    <line stroke="#BA1A1A" strokeWidth="1.5" x1="-18" x2="18" y1="0" y2="0"></line>
                    <line stroke="#BA1A1A" strokeWidth="1.5" x1="0" x2="0" y1="-18" y2="18"></line>
                    <circle cx="0" cy="0" fill="none" r="14" stroke="#BA1A1A" strokeWidth="1.2"></circle>
                    <circle cx="0" cy="0" fill="none" r="22" stroke="#BA1A1A" strokeDasharray="3 3" strokeWidth="0.8"></circle>
                  </g>
                </svg>
              </div>

              {/* Bottom Marine Chart Legend */}
              <div className="z-10 mt-auto flex flex-wrap items-center justify-between gap-space-sm bg-surface-container-lowest/90 backdrop-blur-md p-space-sm rounded-md shadow-sm border border-surface-container-high/40">
                <div className="flex items-center gap-space-sm">
                  <span className="font-caption-coordinate text-caption-coordinate text-on-surface-variant font-mono">12°C</span>
                  <div className="w-28 h-2.5 rounded bg-gradient-to-r from-[#003E47] via-[#00B1C9] via-[#FFF7ED] to-[#EA580C]"></div>
                  <span className="font-caption-coordinate text-caption-coordinate text-on-surface-variant font-mono">31°C</span>
                </div>
                <div className="flex items-center gap-space-md font-caption-coordinate text-caption-coordinate text-primary">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-on-tertiary-container"></span> INCOIS Argo
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-0.5 bg-error"></span> Storm Track
                  </span>
                  <span className="font-mono text-secondary">RES: 0.25°</span>
                </div>
              </div>
            </div>

            {/* 14-Channel Satellite Input Panel (Directly from README.md Table) */}
            <div className="bg-surface-container-lowest p-space-md rounded-xl shadow-sm border border-surface-container-high/60">
              <div className="flex items-center justify-between mb-space-sm">
                <div className="flex items-center gap-space-xs">
                  <span className="font-label-technical text-label-technical uppercase tracking-wider text-primary font-semibold">
                    14-Channel Satellite Telemetry Patch
                  </span>
                  <span className="text-[10px] text-on-surface-variant font-mono">(7 Physical Vars + 7 Binary Masks)</span>
                </div>
                <button
                  onClick={() => setShowChannelDrawer(!showChannelDrawer)}
                  className="text-xs text-secondary hover:text-primary font-medium flex items-center gap-1"
                >
                  <span>{showChannelDrawer ? "Collapse Controls" : "Edit Channels"}</span>
                  <span className="material-symbols-outlined text-[16px]">
                    {showChannelDrawer ? "expand_less" : "tune"}
                  </span>
                </button>
              </div>

              {/* Minimalist Channel Overview Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                <div className="bg-surface-container-low p-2 rounded border border-surface-container-high/40">
                  <span className="text-[10px] text-on-surface-variant uppercase block">Ch 0 &amp; 1: SST</span>
                  <span className="text-sm font-bold text-primary">{params.sst.toFixed(1)} °C</span>
                </div>
                <div className="bg-surface-container-low p-2 rounded border border-surface-container-high/40">
                  <span className="text-[10px] text-on-surface-variant uppercase block">Ch 2 &amp; 3: SSH</span>
                  <span className="text-sm font-bold text-primary">{params.ssh > 0 ? `+${params.ssh.toFixed(2)}` : params.ssh.toFixed(2)} m</span>
                </div>
                <div className="bg-surface-container-low p-2 rounded border border-surface-container-high/40">
                  <span className="text-[10px] text-on-surface-variant uppercase block">Ch 4 &amp; 5: SSS</span>
                  <span className="text-sm font-bold text-primary">{params.sss > 0 ? `+${params.sss.toFixed(2)}` : params.sss.toFixed(2)} PSU</span>
                </div>
                <div className="bg-surface-container-low p-2 rounded border border-surface-container-high/40">
                  <span className="text-[10px] text-on-surface-variant uppercase block">Ch 6–9: Currents</span>
                  <span className="text-sm font-bold text-primary">U:{params.uo.toFixed(2)} V:{params.vo.toFixed(2)} m/s</span>
                </div>
              </div>

              {/* Detailed Slider Inputs (When expanded) */}
              {showChannelDrawer && (
                <div className="mt-space-md pt-space-sm border-t border-surface-container-high/40 grid grid-cols-2 sm:grid-cols-4 gap-space-md">
                  <div>
                    <label className="text-[10px] font-mono text-on-surface-variant block mb-1">
                      SST (°C) [Ch 0/1]
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={params.sst}
                      onChange={(e) => handleParamChange("sst", e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high rounded px-2 py-1 text-xs font-mono text-primary"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-on-surface-variant block mb-1">
                      SSH (m) [Ch 2/3]
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={params.ssh}
                      onChange={(e) => handleParamChange("ssh", e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high rounded px-2 py-1 text-xs font-mono text-primary"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-on-surface-variant block mb-1">
                      SSS (PSU) [Ch 4/5]
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={params.sss}
                      onChange={(e) => handleParamChange("sss", e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high rounded px-2 py-1 text-xs font-mono text-primary"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-on-surface-variant block mb-1">
                      Uo Current (m/s)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={params.uo}
                      onChange={(e) => handleParamChange("uo", e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high rounded px-2 py-1 text-xs font-mono text-primary"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-on-surface-variant block mb-1">
                      Vo Current (m/s)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={params.vo}
                      onChange={(e) => handleParamChange("vo", e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high rounded px-2 py-1 text-xs font-mono text-primary"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-on-surface-variant block mb-1">
                      U10 Wind (m/s)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={params.u10}
                      onChange={(e) => handleParamChange("u10", e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high rounded px-2 py-1 text-xs font-mono text-primary"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-mono text-on-surface-variant block mb-1">
                      V10 Wind (m/s)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={params.v10}
                      onChange={(e) => handleParamChange("v10", e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high rounded px-2 py-1 text-xs font-mono text-primary"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={() => runPrediction(params, activePreset)}
                      disabled={loading}
                      className="w-full py-1.5 bg-secondary hover:bg-primary text-on-primary text-xs font-semibold rounded transition"
                    >
                      {loading ? "Computing..." : "Update Model"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* RIGHT COLUMN (5 Cols): 15-Depth Selector, Probe & Vertical Sounding */}
          <div className="lg:col-span-5 flex flex-col gap-space-md">
            {/* 15-Level Isobaric Stratum Selector */}
            <div className="bg-surface-container-lowest p-space-md rounded-xl shadow-sm border border-surface-container-high/60">
              <div className="flex items-center justify-between mb-space-sm">
                <span className="font-label-technical text-label-technical uppercase tracking-wider text-primary font-semibold">
                  15 Isobaric Stratum Depths
                </span>
                <span className="font-caption-coordinate text-caption-coordinate font-mono text-secondary font-bold">
                  {currentDepth} METERS SELECTED
                </span>
              </div>

              <div className="grid grid-cols-5 gap-1.5">
                {DEPTH_LEVELS.map((depth, idx) => {
                  const isSel = selectedDepthIdx === idx;
                  return (
                    <button
                      key={depth}
                      onClick={() => setSelectedDepthIdx(idx)}
                      className={`py-1.5 px-1 text-center font-caption-coordinate text-caption-coordinate rounded transition ${
                        isSel
                          ? "bg-primary text-on-primary font-bold shadow-sm"
                          : "bg-surface-container-low text-on-surface hover:bg-surface-container-high"
                      }`}
                    >
                      {depth}m
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Live Subsurface Temperature Readout */}
            <div className="bg-surface-container-lowest p-space-md rounded-xl shadow-sm border border-surface-container-high/60 flex flex-col gap-space-sm">
              <div className="flex items-baseline justify-between">
                <div>
                  <span className="font-caption-coordinate text-caption-coordinate text-on-surface-variant block uppercase">
                    Model Predicted Temp at {currentDepth}m
                  </span>
                  <div className="flex items-baseline gap-1">
                    <span className="font-display text-display font-bold text-primary">
                      {currentTemp.toFixed(1)}
                    </span>
                    <span className="font-headline-sm text-headline-sm text-secondary font-semibold">°C</span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="font-caption-coordinate text-caption-coordinate text-on-surface-variant block uppercase">
                    Thermocline State
                  </span>
                  <span className="inline-flex items-center px-space-sm py-space-2xs rounded bg-[#FFF7ED] text-[#EA580C] font-label-technical text-label-technical font-semibold">
                    {currentDepth <= 50 ? "Mixed Layer" : currentDepth <= 200 ? "Thermocline" : "Deep Abyssal"}
                  </span>
                </div>
              </div>

              {/* Vertical Temperature Sounding SVG Curve */}
              <div className="bg-surface-container-low/60 p-space-sm rounded-lg border border-surface-container-high/40">
                <div className="flex items-center justify-between text-[10px] text-on-surface-variant font-mono mb-1">
                  <span>VERTICAL TEMPERATURE SOUNDING</span>
                  <span>4°C — 32°C</span>
                </div>
                <svg className="w-full h-28" viewBox="0 0 300 120" preserveAspectRatio="none">
                  <path d={curvePathD} fill="none" stroke="#00B1C9" strokeWidth="2.5" strokeLinecap="round" />
                  {curvePoints.map((pt) => {
                    const isSel = selectedDepthIdx === pt.idx;
                    return (
                      <circle
                        key={pt.depth}
                        cx={pt.x}
                        cy={pt.y}
                        r={isSel ? 5 : 2.5}
                        fill={isSel ? "#00B1C9" : "#00253D"}
                        stroke="#ffffff"
                        strokeWidth="1"
                        className="cursor-pointer transition-transform hover:scale-125"
                        onClick={() => setSelectedDepthIdx(pt.idx)}
                      />
                    );
                  })}
                </svg>
                <div className="flex justify-between items-center text-[10px] text-on-surface-variant font-mono pt-1 border-t border-surface-container-high/30">
                  <span>Surface 0m: {surfaceTemp.toFixed(1)}°C</span>
                  <span>100m: {thermoclineTemp.toFixed(1)}°C</span>
                  <span>1000m: {abyssalTemp.toFixed(1)}°C</span>
                </div>
              </div>
            </div>

            {/* Preset Station Context Card */}
            <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container-high/60 text-xs">
              <span className="font-caption-coordinate text-caption-coordinate text-secondary uppercase font-semibold block mb-1">
                Regional Oceanographic Context
              </span>
              <p className="text-on-surface-variant">{activePreset.context}</p>
            </div>
          </div>
        </div>

        {/* =======================================================================
            THE 4 CORE APPLICATION PILLARS (Strictly from README.md)
            ======================================================================= */}
        <section id="pillars" className="flex flex-col gap-space-md">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-space-xs">
            <div>
              <span className="font-label-technical text-label-technical uppercase tracking-wider text-secondary font-semibold block">
                Derived Oceanographic Physics
              </span>
              <h2 className="font-headline-lg text-headline-lg text-primary tracking-tight font-semibold">
                The 4 Core Application Pillars
              </h2>
            </div>
            <span className="font-caption-coordinate text-caption-coordinate text-on-surface-variant font-mono">
              Strictly derived from 15-depth vertical soundings
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-space-md">
            {/* PILLAR 1: Cyclone TCHP & D26 */}
            <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border-t-4 border-t-rose-500 border border-surface-container-high/60 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-space-sm">
                  <div className="flex items-center gap-1.5 text-rose-600">
                    <span className="material-symbols-outlined text-[20px]">air</span>
                    <span className="font-label-technical text-label-technical uppercase font-bold">Pillar 1</span>
                  </div>
                  <span className="font-caption-coordinate text-caption-coordinate text-rose-600 font-mono font-bold">
                    D₂₆ &amp; TCHP
                  </span>
                </div>
                <h3 className="font-headline-sm text-headline-sm text-primary mb-1">Cyclone Heat Potential</h3>
                <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
                  Thermal energy stored above the 26°C isotherm fueling rapid tropical storm intensification.
                </p>
                <div className="space-y-1.5 bg-surface-container-low p-space-sm rounded font-mono text-xs mb-space-sm">
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">D₂₆ Depth:</span>
                    <span className="font-bold text-primary">
                      {prediction?.derived_pillars?.cyclone?.d26_depth_m ?? 54.2} m
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">TCHP Energy:</span>
                    <span className="font-bold text-rose-600">
                      {prediction?.derived_pillars?.cyclone?.tchp_kj_cm2 ?? 98.6} kJ/cm²
                    </span>
                  </div>
                </div>
              </div>
              <div className="text-[11px] text-rose-700 font-medium">
                {prediction?.derived_pillars?.cyclone?.risk_category ?? "Severe Risk"}
              </div>
            </div>

            {/* PILLAR 2: ASW Thermocline Sonar Shadow Zone */}
            <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border-t-4 border-t-purple-500 border border-surface-container-high/60 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-space-sm">
                  <div className="flex items-center gap-1.5 text-purple-600">
                    <span className="material-symbols-outlined text-[20px]">shield</span>
                    <span className="font-label-technical text-label-technical uppercase font-bold">Pillar 2</span>
                  </div>
                  <span className="font-caption-coordinate text-caption-coordinate text-purple-600 font-mono font-bold">
                    ASW DEFENSE
                  </span>
                </div>
                <h3 className="font-headline-sm text-headline-sm text-primary mb-1">Acoustic Sonar Shadow</h3>
                <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
                  Thermocline density gradient ∂T/∂z that refracts active sonar waves for submarine concealment.
                </p>
                <div className="space-y-1.5 bg-surface-container-low p-space-sm rounded font-mono text-xs mb-space-sm">
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">Core Depth:</span>
                    <span className="font-bold text-primary">
                      {prediction?.derived_pillars?.asw_defense?.thermocline_core_depth_m ?? 75} m
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">Max Gradient:</span>
                    <span className="font-bold text-purple-600">
                      {prediction?.derived_pillars?.asw_defense?.max_thermal_gradient_c_per_m ?? -0.1135} °C/m
                    </span>
                  </div>
                </div>
              </div>
              <div className="text-[11px] text-purple-700 font-medium">
                Corridor: {prediction?.derived_pillars?.asw_defense?.sonic_shadow_zone?.start_depth_m ?? 75}m to{" "}
                {prediction?.derived_pillars?.asw_defense?.sonic_shadow_zone?.end_depth_m ?? 150}m
              </div>
            </div>

            {/* PILLAR 3: PFZ Fisheries & EEZ Border Alert */}
            <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border-t-4 border-t-emerald-500 border border-surface-container-high/60 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-space-sm">
                  <div className="flex items-center gap-1.5 text-emerald-600">
                    <span className="material-symbols-outlined text-[20px]">sailing</span>
                    <span className="font-label-technical text-label-technical uppercase font-bold">Pillar 3</span>
                  </div>
                  <span className="font-caption-coordinate text-caption-coordinate text-emerald-600 font-mono font-bold">
                    PFZ UPWELLING
                  </span>
                </div>
                <h3 className="font-headline-sm text-headline-sm text-primary mb-1">Fisheries &amp; EEZ Alerts</h3>
                <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
                  Cold nutrient upwelling (T₀ - T₅₀ &gt; 4.0°C) triggering pelagic feeding zones near EEZ lines.
                </p>
                <div className="space-y-1.5 bg-surface-container-low p-space-sm rounded font-mono text-xs mb-space-sm">
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">Upwelling Index:</span>
                    <span className="font-bold text-emerald-600">
                      +{prediction?.derived_pillars?.fisheries?.upwelling_index_c ?? 2.19} °C
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">EEZ Border Dist:</span>
                    <span className="font-bold text-primary">
                      {prediction?.derived_pillars?.fisheries?.distance_to_border_km ?? 48.0} km
                    </span>
                  </div>
                </div>
              </div>
              <div className="text-[11px] text-emerald-700 font-medium">
                {prediction?.derived_pillars?.fisheries?.border_alert ?? "Safe Zone: Domestic EEZ Waters"}
              </div>
            </div>

            {/* PILLAR 4: 128-D Ocean Latent Embedding */}
            <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border-t-4 border-t-cyan-500 border border-surface-container-high/60 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-space-sm">
                  <div className="flex items-center gap-1.5 text-cyan-600">
                    <span className="material-symbols-outlined text-[20px]">database</span>
                    <span className="font-label-technical text-label-technical uppercase font-bold">Pillar 4</span>
                  </div>
                  <span className="font-caption-coordinate text-caption-coordinate text-cyan-600 font-mono font-bold">
                    VECTOR DB
                  </span>
                </div>
                <h3 className="font-headline-sm text-headline-sm text-primary mb-1">128-D Latent Vector</h3>
                <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
                  Compact representation for Milvus / FAISS similarity search and climate AI forecasting.
                </p>

                {/* 64-dim Micro Heatmap Matrix */}
                <div className="grid grid-cols-16 gap-0.5 bg-surface-container-low p-1.5 rounded border border-surface-container-high/40 mb-space-sm">
                  {(
                    prediction?.latent_embedding?.full_latent_vector?.slice(0, 32) ||
                    DETERMINISTIC_INITIAL_PREDICTION.latent_embedding.full_latent_vector.slice(0, 32)
                  ).map((val, idx) => {
                    const norm = Math.max(-1, Math.min(1, val));
                    const isPos = norm >= 0;
                    return (
                      <div
                        key={idx}
                        title={`Dim ${idx}: ${val.toFixed(4)}`}
                        style={{
                          backgroundColor: isPos
                            ? `rgba(0, 177, 201, ${Math.max(0.2, Math.abs(norm)).toFixed(2)})`
                            : `rgba(239, 68, 68, ${Math.max(0.2, Math.abs(norm)).toFixed(2)})`
                        }}
                        className="h-2 rounded-[1px]"
                      />
                    );
                  })}
                </div>
              </div>
              <button
                onClick={() => {
                  if (prediction?.latent_embedding?.full_latent_vector) {
                    navigator.clipboard.writeText(JSON.stringify(prediction.latent_embedding.full_latent_vector));
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }
                }}
                className="w-full py-1 bg-surface-container-high hover:bg-surface-container text-primary text-xs font-mono rounded flex items-center justify-center gap-1 transition"
              >
                <span className="material-symbols-outlined text-[14px]">content_copy</span>
                <span>{copied ? "Copied 128 Floats!" : "Copy Embedding Vector"}</span>
              </button>
            </div>
          </div>
        </section>

        {/* =======================================================================
            INDEPENDENT INCOIS ARGO BUOY BENCHMARKS (Strictly from README.md)
            ======================================================================= */}
        <section id="benchmarks" className="bg-surface-container-lowest p-space-xl rounded-xl shadow-sm border border-surface-container-high/60 flex flex-col gap-space-md">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-space-xs border-b border-surface-container-high/60 pb-space-sm">
            <div>
              <span className="font-label-technical text-label-technical uppercase tracking-wider text-secondary font-semibold block">
                In-Situ Physical Validation
              </span>
              <h2 className="font-headline-md text-headline-md text-primary font-semibold">
                Benchmarked Against 54,606 Independent INCOIS ARGO Buoy Floats
              </h2>
            </div>
            <span className="font-caption-coordinate text-caption-coordinate text-on-surface-variant font-mono">
              Bay of Bengal &amp; Arabian Sea (5°N–30°N, 45°E–105°E)
            </span>
          </div>

          {/* Results Comparison Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left font-body-sm text-body-sm">
              <thead>
                <tr className="border-b border-surface-container-high text-secondary uppercase font-label-technical text-label-technical">
                  <th className="pb-space-xs font-semibold">Model Architecture</th>
                  <th className="pb-space-xs font-semibold">Input Telemetry</th>
                  <th className="pb-space-xs font-semibold">GLORYS12 Val RMSE</th>
                  <th className="pb-space-xs font-semibold">Independent INCOIS ARGO RMSE</th>
                  <th className="pb-space-xs font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container-high/40">
                <tr>
                  <td className="py-2.5 font-medium text-primary">1. Baseline 1 (SST-Only MLP)</td>
                  <td className="py-2.5 text-on-surface-variant">SST Surface Radiance</td>
                  <td className="py-2.5 font-mono text-on-surface-variant">1.0440 °C</td>
                  <td className="py-2.5 font-mono text-on-surface-variant">2.1450 °C</td>
                  <td className="py-2.5">
                    <span className="px-2 py-0.5 rounded bg-surface-container text-xs text-on-surface-variant">
                      Baseline Safety
                    </span>
                  </td>
                </tr>
                <tr>
                  <td className="py-2.5 font-medium text-primary">2. Baseline 2 (Multi-Var MLP)</td>
                  <td className="py-2.5 text-on-surface-variant">SST + SSH + SSS + Wind</td>
                  <td className="py-2.5 font-mono text-on-surface-variant">1.0573 °C</td>
                  <td className="py-2.5 font-mono text-on-surface-variant">1.7820 °C</td>
                  <td className="py-2.5">
                    <span className="px-2 py-0.5 rounded bg-surface-container text-xs text-on-surface-variant">
                      Multi-Var Baseline
                    </span>
                  </td>
                </tr>
                <tr className="bg-secondary-container/15 font-semibold">
                  <td className="py-2.5 text-primary flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-on-tertiary-container"></span>
                    3. OceanEmbed Target CNN Architecture
                  </td>
                  <td className="py-2.5 text-primary">14-Channel Spatial Patch</td>
                  <td className="py-2.5 font-mono text-secondary">1.3892 °C</td>
                  <td className="py-2.5 font-mono text-on-tertiary-container font-bold">1.3892 °C</td>
                  <td className="py-2.5">
                    <span className="px-2 py-0.5 rounded bg-on-tertiary-container text-white text-xs font-semibold">
                      Target SIH Model
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Depth Breakdown Badges */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-space-sm pt-space-xs">
            <div className="bg-surface-container-low p-space-sm rounded border border-surface-container-high/40 flex justify-between items-center">
              <div>
                <span className="text-[10px] text-on-surface-variant uppercase font-mono block">Surface (0m) RMSE</span>
                <span className="text-base font-bold text-primary font-mono">1.4315 °C</span>
              </div>
              <span className="text-xs text-secondary font-medium">Mixed Layer</span>
            </div>
            <div className="bg-surface-container-low p-space-sm rounded border border-surface-container-high/40 flex justify-between items-center">
              <div>
                <span className="text-[10px] text-on-surface-variant uppercase font-mono block">Thermocline (100m) RMSE</span>
                <span className="text-base font-bold text-secondary font-mono">1.5689 °C</span>
              </div>
              <span className="text-xs text-secondary font-medium">Internal Waves</span>
            </div>
            <div className="bg-surface-container-low p-space-sm rounded border border-surface-container-high/40 flex justify-between items-center">
              <div>
                <span className="text-[10px] text-on-surface-variant uppercase font-mono block">Deep (1000m) RMSE</span>
                <span className="text-base font-bold text-on-tertiary-container font-mono">0.6813 °C</span>
              </div>
              <span className="text-xs text-secondary font-medium">Abyssal Stability</span>
            </div>
          </div>
        </section>
      </main>

      {/* =========================================================================
          FOOTER (Strictly Team OceanSATX / SIH 2026 PS 26066)
          ========================================================================= */}
      <footer className="w-full bg-surface-container-low border-t border-surface-container-high/60 py-space-xl">
        <div className="max-w-7xl mx-auto px-margin-desktop flex flex-col sm:flex-row items-center justify-between gap-space-md text-xs text-on-surface-variant">
          <div className="flex items-center gap-space-sm">
            <span className="font-headline-sm text-sm text-primary font-bold">OceanEmbed</span>
            <span>•</span>
            <span>Team OceanSATX</span>
            <span>•</span>
            <span>Smart India Hackathon (SIH) 2026 Problem Statement 26066</span>
          </div>
          <div className="flex items-center gap-space-md font-mono text-[11px]">
            <span>Validated on 54,606 INCOIS ARGO Buoys</span>
            <span>•</span>
            <span className="text-secondary font-semibold">Bay of Bengal &amp; Arabian Sea</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
