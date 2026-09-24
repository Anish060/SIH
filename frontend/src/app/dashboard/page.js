"use client";

import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import dynamic from "next/dynamic";

// Dynamic import of Plotly for 3D Digital Twin Rendering (ssr: false prevents SSR hydration mismatch)
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

// =============================================================================
// THE 15 STANDARD OCEANOGRAPHIC DEPTH LEVELS (GLORYS12 & SIH PS 26066)
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
    context: "Warm-core anticyclonic eddy where tropical cyclones undergo rapid intensification.",
    pillar: "cyclone"
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
    context: "Steep thermocline density gradient creating active sonar shadow zones for submarine concealment.",
    pillar: "asw"
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
    context: "Cold thermocline upwelling bringing nutrient-rich waters for commercial pelagic fish shoals.",
    pillar: "fisheries"
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
    context: "River runoff creating shallow barrier layer salinity anomalies affecting acoustic propagation.",
    pillar: "volume"
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
    context: "Deep bathymetric water mass extending through all 15 hydrographic standard depth strata.",
    pillar: "volume"
  }
];

// =============================================================================
// HISTORICAL CYCLONE SIMULATOR TRACKS (Super Cyclone Amphan & Cyclone Fani)
// =============================================================================
const CYCLONE_SIMULATION_TRACKS = {
  amphan: {
    id: "amphan",
    name: "Super Cyclone Amphan (May 2020)",
    maxCategory: "Category 5 Super Cyclone",
    peakWinds: "140 knots (260 km/h)",
    minPressure: "920 hPa",
    steps: [
      { step: 1, date: "16 May 2020", lat: 10.8, lon: 86.3, cat: "Depression / Cat 1", tchp: 78.5, sst: 30.2, coldWake: -0.4, narrative: "Tropical depression forms over warm South-East Bay of Bengal with TCHP = 78.5 kJ/cm²." },
      { step: 2, date: "17 May 2020", lat: 13.2, lon: 86.1, cat: "Severe Cyclonic Storm (Cat 2)", tchp: 96.4, sst: 30.5, coldWake: -1.2, narrative: "Crosses anticyclonic warm-core eddy with deep D26 (65m), initiating explosive rapid intensification." },
      { step: 3, date: "18 May 2020", lat: 15.6, lon: 86.5, cat: "Super Cyclone (Cat 5 Peak)", tchp: 112.0, sst: 31.0, coldWake: -2.8, narrative: "Reaches Category 5 peak intensity (140 kts winds). Extracts massive heat energy, leaving a 2.8°C cold wake." },
      { step: 4, date: "19 May 2020", lat: 18.8, lon: 87.2, cat: "Extremely Severe Cyclone (Cat 4)", tchp: 82.1, sst: 29.2, coldWake: -2.1, narrative: "Track moves north towards Bengal coast over upper thermocline upwelling region." },
      { step: 5, date: "20 May 2020", lat: 21.6, lon: 88.3, cat: "Landfall (West Bengal & Delta)", tchp: 45.0, sst: 27.8, coldWake: -1.5, narrative: "Makes destructive landfall near Sundarbans / Ganges Delta with high storm surge." }
    ]
  },
  fani: {
    id: "fani",
    name: "Extremely Severe Cyclone Fani (May 2019)",
    maxCategory: "Category 4 Extremely Severe Cyclone",
    peakWinds: "115 knots (215 km/h)",
    minPressure: "932 hPa",
    steps: [
      { step: 1, date: "27 Apr 2019", lat: 5.2, lon: 88.5, cat: "Tropical Depression", tchp: 65.0, sst: 29.5, coldWake: -0.3, narrative: "Formed near equator in Indian Ocean, tracking North-West towards Sri Lanka." },
      { step: 2, date: "30 Apr 2019", lat: 10.5, lon: 84.8, cat: "Severe Cyclonic Storm (Cat 2)", tchp: 88.0, sst: 30.0, coldWake: -1.1, narrative: "Recurves North-North-East over Central Bay TCHP heat reservoir." },
      { step: 3, date: "02 May 2019", lat: 16.8, lon: 84.5, cat: "Extremely Severe Cyclone (Cat 4 Peak)", tchp: 102.5, sst: 30.8, coldWake: -2.4, narrative: "Reaches peak strength parallel to Andhra coast prior to Odisha landfall." },
      { step: 4, date: "03 May 2019", lat: 19.8, lon: 85.8, cat: "Landfall (Puri, Odisha)", tchp: 52.0, sst: 28.5, coldWake: -1.8, narrative: "Landfall at Puri, Odisha with 175 km/h winds and coastal inundation." }
    ]
  }
};

// =============================================================================
// DETERMINISTIC INITIAL STATE (Guarantees zero SSR/client hydration mismatch)
// =============================================================================
const DETERMINISTIC_INITIAL_PREDICTION = {
  profile_celsius: [29.25, 29.20, 29.12, 28.85, 27.80, 24.50, 20.10, 16.30, 13.50, 11.80, 9.70, 7.20, 5.10, 4.20, 3.40],
  latent_embedding: {
    vector_norm: 12.4582,
    mean: 0.0124,
    std: 0.8942,
    min: -2.145,
    max: 2.381,
    preview_dims: [0.42, -0.18, 0.85, -0.62, 0.31, 0.74, -0.91, 0.15, -0.45, 0.58, 0.22, -0.73, 0.67, -0.34, 0.19, 0.82],
    full_latent_vector: [
      0.42, -0.18, 0.85, -0.62, 0.31, 0.74, -0.91, 0.15, -0.45, 0.58, 0.22, -0.73, 0.67, -0.34, 0.19, 0.82,
      -0.55, 0.39, 0.71, -0.28, 0.64, -0.83, 0.12, 0.47, -0.33, 0.91, -0.16, 0.25, -0.78, 0.52, -0.41, 0.63,
      0.35, -0.68, 0.29, 0.88, -0.49, 0.17, -0.75, 0.54, -0.21, 0.66, 0.38, -0.87, 0.14, -0.59, 0.43, -0.31,
      0.76, -0.24, 0.59, -0.67, 0.33, 0.81, -0.44, 0.26, -0.89, 0.18, 0.51, -0.37, 0.72, -0.15, 0.61, -0.48,
      0.42, -0.18, 0.85, -0.62, 0.31, 0.74, -0.91, 0.15, -0.45, 0.58, 0.22, -0.73, 0.67, -0.34, 0.19, 0.82,
      -0.55, 0.39, 0.71, -0.28, 0.64, -0.83, 0.12, 0.47, -0.33, 0.91, -0.16, 0.25, -0.78, 0.52, -0.41, 0.63,
      0.35, -0.68, 0.29, 0.88, -0.49, 0.17, -0.75, 0.54, -0.21, 0.66, 0.38, -0.87, 0.14, -0.59, 0.43, -0.31,
      0.76, -0.24, 0.59, -0.67, 0.33, 0.81, -0.44, 0.26, -0.89, 0.18, 0.51, -0.37, 0.72, -0.15, 0.61, -0.48
    ]
  },
  derived_pillars: {
    cyclone: {
      d26_depth_m: 58.4,
      tchp_kj_cm2: 94.2,
      risk_category: "Category 4-5 Super Cyclone Risk (TCHP > 80 kJ/cm²)",
      rapid_intensification_threat: true
    },
    asw_defense: {
      thermocline_core_depth_m: 75,
      max_thermal_gradient_c_per_m: -0.176,
      sonic_shadow_zone: {
        start_depth_m: 75,
        end_depth_m: 150,
        thickness_m: 75,
        description: "Active surface sonar waves refract sharply downward at 75m, creating an acoustic shadow corridor for submarine concealment."
      }
    },
    fisheries: {
      upwelling_index_c: 4.75,
      pfz_status: "High Potential Fishing Zone (Strong Nutrient Upwelling)",
      nutrient_score: "High (Optimal Pelagic Shoal Environment)",
      distance_to_border_km: 32.5,
      border_alert: "Alert: Fishing shoal within 32.5 km of International Maritime Boundary Line!"
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
  const [activePillarTab, setActivePillarTab] = useState("cyclone");
  const [similarMatches, setSimilarMatches] = useState([]);
  const [volumeSliceGrid, setVolumeSliceGrid] = useState(null);
  const [customCoord, setCustomCoord] = useState({ lat: 14.5, lon: 88.0 });

  // 3D OCEAN DIGITAL TWIN & INTERACTIVE CYCLONE TRACK STATES
  const [digitalTwinMode, setDigitalTwinMode] = useState("3d_volume"); // "3d_volume" | "horizontal_slice" | "vertical_transect"
  const [activeCycloneTrackId, setActiveCycloneTrackId] = useState("amphan"); // "amphan" | "fani"
  const [cycloneStepIdx, setCycloneStepIdx] = useState(2); // Current step index along track
  const [isPlayingCyclone, setIsPlayingCyclone] = useState(false);
  const [showScatterModal, setShowScatterModal] = useState(false);
  const [stratumRotation, setStratumRotation] = useState(0);
  const [threatSimMode, setThreatSimMode] = useState(false);

  // Trigger live prediction from PyTorch FastAPI backend
  const runPrediction = useCallback(async (currentParams = params, currentLat = customCoord.lat, currentLon = customCoord.lon) => {
    setLoading(true);
    try {
      const res = await fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sst: Number(currentParams.sst),
          ssh: Number(currentParams.ssh),
          sss: Number(currentParams.sss),
          uo: Number(currentParams.uo),
          vo: Number(currentParams.vo),
          u10: Number(currentParams.u10),
          v10: Number(currentParams.v10),
          lat: Number(currentLat),
          lon: Number(currentLon)
        })
      });

      if (res.ok) {
        const data = await res.json();
        setPrediction(data);
        setBackendStatus((prev) => ({ ...prev, connected: true }));

        // Trigger Vector DB similarity search with returned 128-D embedding
        if (data.latent_embedding?.full_latent_vector) {
          fetch("/api/similar_embeddings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              latent_vector: data.latent_embedding.full_latent_vector,
              lat: currentLat,
              lon: currentLon
            })
          })
            .then((r) => r.json())
            .then((sData) => {
              if (sData.matches) setSimilarMatches(sData.matches);
            })
            .catch(() => {});
        }
      }
    } catch (err) {
      console.warn("FastAPI backend call failed:", err);
    } finally {
      setLoading(false);
    }
  }, [params, customCoord]);

  // Fetch 3D Volume Slice & Vertical Cross-Section
  const fetchVolumeSlice = useCallback((depthIdx, lat, lon, sst) => {
    fetch(`/api/volume_slice?depth_idx=${depthIdx}&lat=${lat}&lon=${lon}&sst=${sst}`)
      .then((r) => r.json())
      .then((vData) => {
        if (vData.temperature_grid_c) setVolumeSliceGrid(vData);
      })
      .catch(() => {});
  }, []);

  // Dynamic Threat Simulation Toggle (Triggers PyTorch inference with severe ocean thermal anomaly)
  const handleThreatSimToggle = useCallback(() => {
    const nextMode = !threatSimMode;
    setThreatSimMode(nextMode);
    if (nextMode) {
      const threatParams = {
        sst: 31.8,
        ssh: 0.45,
        sss: -0.30,
        uo: 1.25,
        vo: -0.85,
        u10: 28.5,
        v10: -18.2
      };
      setParams(threatParams);
      runPrediction(threatParams, customCoord.lat, customCoord.lon);
    } else {
      const defaultParams = REGIONAL_PRESETS[0].params;
      setParams(defaultParams);
      runPrediction(defaultParams, customCoord.lat, customCoord.lon);
    }
  }, [threatSimMode, customCoord, runPrediction]);

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

  // When depth slider or coordinate changes
  useEffect(() => {
    fetchVolumeSlice(selectedDepthIdx, customCoord.lat, customCoord.lon, params.sst);
  }, [selectedDepthIdx, customCoord, params.sst, fetchVolumeSlice]);

  // Cyclone Storm Simulation Step Controller
  const activeCyclone = CYCLONE_SIMULATION_TRACKS[activeCycloneTrackId];
  const currentCycloneStep = activeCyclone.steps[cycloneStepIdx] || activeCyclone.steps[0];

  // Auto-play timer for cyclone track simulation
  useEffect(() => {
    let interval = null;
    if (isPlayingCyclone) {
      interval = setInterval(() => {
        setCycloneStepIdx((prev) => {
          const next = prev + 1;
          if (next >= activeCyclone.steps.length) {
            setIsPlayingCyclone(false);
            return prev;
          }
          return next;
        });
      }, 2200);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isPlayingCyclone, activeCyclone]);

  // Update probe position when cyclone step changes during simulation
  useEffect(() => {
    if (currentCycloneStep) {
      setCustomCoord({ lat: currentCycloneStep.lat, lon: currentCycloneStep.lon });
      const updatedSst = Math.max(24.0, currentCycloneStep.sst + currentCycloneStep.coldWake);
      setParams((prev) => ({ ...prev, sst: updatedSst }));
    }
  }, [cycloneStepIdx, activeCycloneTrackId]);

  // Change preset station
  const handleSelectPreset = (preset) => {
    setActivePreset(preset);
    setParams(preset.params);
    setCustomCoord({ lat: preset.lat, lon: preset.lon });
    if (preset.pillar) setActivePillarTab(preset.pillar);
    runPrediction(preset.params, preset.lat, preset.lon);
  };

  // Change individual satellite parameter
  const handleParamChange = (key, val) => {
    const updated = { ...params, [key]: parseFloat(val) || 0 };
    setParams(updated);
    runPrediction(updated, customCoord.lat, customCoord.lon);
  };

  // Estimate location-aware physical ocean parameters based on GIS coordinates
  const getParamsForLocation = (lat, lon) => {
    const dEddy = Math.hypot(lat - 14.5, lon - 88.0);
    const dUpwelling = Math.hypot(lat - 17.5, lon - 83.5);
    const dDelta = Math.hypot(lat - 21.0, lon - 89.0);
    const dASW = Math.hypot(lat - 10.0, lon - 84.0);

    if (dEddy < 2.5) {
      return { sst: 29.8, ssh: 0.22, sss: 0.01, uo: -0.18, vo: 0.12, u10: -4.5, v10: -6.2 };
    }
    if (dUpwelling < 2.5) {
      return { sst: 26.5, ssh: -0.12, sss: 0.08, uo: 0.22, vo: 0.35, u10: 3.2, v10: 4.8 };
    }
    if (dDelta < 2.5) {
      return { sst: 27.8, ssh: 0.15, sss: -0.35, uo: -0.08, vo: -0.15, u10: -1.5, v10: -2.2 };
    }
    if (dASW < 2.5) {
      return { sst: 28.2, ssh: 0.04, sss: 0.03, uo: -0.25, vo: -0.05, u10: -2.1, v10: -3.4 };
    }

    const latFactor = (lat - 5.0) / 25.0;
    const lonFactor = (lon - 45.0) / 60.0;
    const baseSst = Math.round((28.5 + 1.2 * Math.sin(latFactor * Math.PI) - 1.0 * (1 - lonFactor)) * 10) / 10;
    const baseSsh = Math.round((0.05 + 0.12 * Math.cos(latFactor * Math.PI * 1.5)) * 100) / 100;
    const baseSss = lat > 18.0 ? -0.20 : 0.02;

    return {
      sst: Math.min(31.0, Math.max(25.0, baseSst)),
      ssh: Math.min(0.30, Math.max(-0.20, baseSsh)),
      sss: baseSss,
      uo: Math.round((-0.10 + 0.15 * Math.sin(lat)) * 100) / 100,
      vo: Math.round((0.05 - 0.10 * Math.cos(lon)) * 100) / 100,
      u10: -2.5,
      v10: -4.0
    };
  };

  // Click anywhere on SVG GIS Map to probe coordinates (Fetches Live Satellite Telemetry)
  const handleMapClick = async (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    
    const normX = Math.max(0, Math.min(1, clickX / rect.width));
    const normY = Math.max(0, Math.min(1, clickY / rect.height));
    
    const clickLon = Math.round((45.0 + normX * (105.0 - 45.0)) * 100) / 100;
    const clickLat = Math.round((30.0 - normY * (30.0 - 5.0)) * 100) / 100;
    
    setCustomCoord({ lat: clickLat, lon: clickLon });

    if (threatSimMode) {
      const threatParams = {
        sst: 31.8,
        ssh: 0.45,
        sss: -0.30,
        uo: 1.25,
        vo: -0.85,
        u10: 28.5,
        v10: -18.2
      };
      setParams(threatParams);
      runPrediction(threatParams, clickLat, clickLon);
      return;
    }

    // Immediate reticle positioning & baseline parameter estimation
    const fallbackParams = getParamsForLocation(clickLat, clickLon);
    setParams(fallbackParams);
    runPrediction(fallbackParams, clickLat, clickLon);

    // Fetch real-time live ocean satellite telemetry (OSTIA SST & ERA5 Winds)
    try {
      const liveRes = await fetch(`/api/live_telemetry?lat=${clickLat}&lon=${clickLon}`);
      if (liveRes.ok) {
        const liveData = await liveRes.json();
        if (liveData.params) {
          setParams(liveData.params);
          runPrediction(liveData.params, clickLat, clickLon);
        }
      }
    } catch (err) {
      console.warn("Live satellite fetch fallback:", err);
    }
  };

  // Copy 128-D Latent Vector
  const handleCopyVector = () => {
    const vec = prediction?.latent_embedding?.full_latent_vector || [];
    navigator.clipboard.writeText(JSON.stringify(vec));
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  // Current depth and temperature
  const currentDepth = DEPTH_LEVELS[selectedDepthIdx];
  const currentTemp = prediction?.profile_celsius?.[selectedDepthIdx] ?? 21.82;
  const surfaceTemp = prediction?.profile_celsius?.[0] ?? 25.56;
  const thermoclineTemp = prediction?.profile_celsius?.[7] ?? 21.82;
  const abyssalTemp = prediction?.profile_celsius?.[14] ?? 6.68;

  // Temperature Sounding Curve Points
  const curvePoints = useMemo(() => {
    const temps = prediction?.profile_celsius || DETERMINISTIC_INITIAL_PREDICTION.profile_celsius;
    const minT = 3.0;
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

  // Construct 3D Digital Twin Plotly Mesh Data
  const plotly3DData = useMemo(() => {
    if (!volumeSliceGrid?.temperature_grid_c) return [];

    const lats = volumeSliceGrid.lats || [13.5, 14.0, 14.5, 15.0, 15.5];
    const lons = volumeSliceGrid.lons || [87.0, 87.5, 88.0, 88.5, 89.0];
    const depths = DEPTH_LEVELS;

    if (digitalTwinMode === "3d_volume") {
      // 3D Volume Mesh Surface render
      const xVals = [], yVals = [], zVals = [], tVals = [];
      depths.forEach((d, dIdx) => {
        lats.forEach((latVal, rIdx) => {
          lons.forEach((lonVal, cIdx) => {
            xVals.push(lonVal);
            yVals.push(latVal);
            zVals.push(-d);
            const baseT = (prediction?.profile_celsius?.[dIdx] ?? 20) + 0.3 * Math.sin(rIdx + cIdx);
            tVals.push(Number(baseT.toFixed(2)));
          });
        });
      });
      return [
        {
          type: "volume",
          x: xVals,
          y: yVals,
          z: zVals,
          value: tVals,
          isomin: 4,
          isomax: 31,
          opacity: 0.35,
          surface: { count: 6 },
          colorscale: [
            [0, "#003E47"],
            [0.3, "#00B1C9"],
            [0.6, "#FFF7ED"],
            [0.85, "#EA580C"],
            [1.0, "#BA1A1A"]
          ],
          colorbar: { title: "Temp (°C)", len: 0.8 }
        }
      ];
    } else if (digitalTwinMode === "horizontal_slice") {
      // Horizontal Surface Slice at current depth
      return [
        {
          type: "surface",
          x: lons,
          y: lats,
          z: lats.map(() => lons.map(() => -currentDepth)),
          surfacecolor: volumeSliceGrid.temperature_grid_c,
          colorscale: [
            [0, "#003E47"],
            [0.4, "#00B1C9"],
            [0.7, "#FFF7ED"],
            [1.0, "#BA1A1A"]
          ],
          colorbar: { title: `${currentDepth}m Temp (°C)` }
        }
      ];
    } else {
      // Vertical Cross-Section Slice along Transect
      const vertData = volumeSliceGrid.vertical_transect_c || lats.map(() => lons.map(() => 20));
      return [
        {
          type: "surface",
          x: lons,
          y: depths.map((d) => -d),
          z: vertData,
          colorscale: "YlGnBu",
          colorbar: { title: "Transect (°C)" }
        }
      ];
    }
  }, [volumeSliceGrid, digitalTwinMode, currentDepth, prediction]);


  // Derived values used across the insight panels
  const cyclone = prediction?.derived_pillars?.cyclone || {};
  const asw = prediction?.derived_pillars?.asw_defense || {};
  const fisheries = prediction?.derived_pillars?.fisheries || {};
  const tchp = cyclone.tchp_kj_cm2 ?? 3.82;
  const d26 = cyclone.d26_depth_m ?? 34.6;
  const shadowStart = asw.sonic_shadow_zone?.start_depth_m ?? 75;
  const shadowEnd = asw.sonic_shadow_zone?.end_depth_m ?? 150;
  const thermoclineCore = asw.thermocline_core_depth_m ?? 75;
  const maxGradient = asw.max_thermal_gradient_c_per_m ?? -0.176;
  const upwelling = fisheries.upwelling_index_c ?? 4.75;
  const borderDistance = fisheries.distance_to_border_km ?? 32.5;
  const layerName = currentDepth <= 50 ? "Mixed layer" : currentDepth <= 200 ? "Thermocline" : "Deep water";
  const latent = prediction?.latent_embedding || {};

  const insightTabs = [
    { id: "cyclone", icon: "air", accent: "text-rose-600", name: "Cyclone potential", metric: `${tchp.toFixed(1)} kJ/cm²`, caption: "Heat stored above the 26 °C isotherm" },
    { id: "asw", icon: "sensors", accent: "text-purple-600", name: "Sonar shadow", metric: `${shadowStart}–${shadowEnd} m`, caption: "Depth band hidden from surface sonar" },
    { id: "fisheries", icon: "sailing", accent: "text-emerald-600", name: "Fishing zones", metric: `+${upwelling.toFixed(2)} °C`, caption: "Upwelling index, surface to 50 m" },
    { id: "volume", icon: "layers", accent: "text-cyan-600", name: "Water column", metric: `${thermoclineCore} m`, caption: "Thermocline core depth" }
  ];

  const inputFields = [
    { key: "sst", label: "Sea surface temp", unit: "°C", step: "0.1" },
    { key: "ssh", label: "Surface height", unit: "m", step: "0.01" },
    { key: "sss", label: "Salinity anomaly", unit: "PSU", step: "0.01" },
    { key: "uo", label: "Current, east", unit: "m/s", step: "0.01" },
    { key: "vo", label: "Current, north", unit: "m/s", step: "0.01" },
    { key: "u10", label: "Wind, east", unit: "m/s", step: "0.1" },
    { key: "v10", label: "Wind, north", unit: "m/s", step: "0.1" }
  ];

  const card = "bg-surface-container-lowest rounded-xl border border-surface-container-high";
  const ghostButton = "inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-body-sm font-medium text-primary bg-surface-container-lowest border border-surface-container-high hover:bg-surface-container-low transition disabled:opacity-40";

  return (
    <div className="min-h-screen bg-surface text-on-surface flex flex-col selection:bg-secondary-container selection:text-on-secondary-container">
      <header className="fixed top-0 inset-x-0 z-50 bg-surface/90 backdrop-blur-xl border-b border-surface-container-high/60">
        <div className="h-16 max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop flex items-center justify-between gap-6">
          <div className="flex items-center gap-10">
            <a href="/" className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-primary flex items-center justify-center">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path d="M2 15C5 12 8 18 12 15C16 12 19 18 22 15" stroke="#FFFFFF" strokeLinecap="round" strokeWidth="2.2"></path>
                  <ellipse cx="12" cy="12" rx="9" ry="4.5" stroke="#00B1C9" strokeDasharray="2 2" strokeWidth="1.6" transform="rotate(-25 12 12)"></ellipse>
                </svg>
              </div>
              <span className="font-headline-sm text-headline-sm text-primary">OceanEmbed</span>
            </a>

            <nav className="hidden lg:flex items-center gap-6 text-body-md text-on-surface-variant">
              <a href="#twin" className="hover:text-primary transition">3D view</a>
              <a href="#replay" className="hover:text-primary transition">Cyclone replay</a>
              <a href="#probe" className="hover:text-primary transition">Probe</a>
              <a href="#insights" className="hover:text-primary transition">Insights</a>
              <a href="#validation" className="hover:text-primary transition">Validation</a>
            </nav>
          </div>

          <div className="flex items-center gap-4">
            <span
              className="hidden sm:inline-flex items-center gap-2 text-body-sm text-on-surface-variant"
              title={`${backendStatus.params.toLocaleString()} parameters`}
            >
              <span className={`w-2 h-2 rounded-full ${backendStatus.connected ? "bg-emerald-500" : "bg-amber-500"}`}></span>
              {backendStatus.connected ? `Model online · ${backendStatus.device.toUpperCase()}` : "Connecting…"}
            </span>
            <button
              onClick={() => runPrediction(params, customCoord.lat, customCoord.lon)}
              disabled={loading}
              className="inline-flex items-center gap-1.5 bg-primary hover:bg-secondary text-on-primary text-body-sm font-medium px-4 py-2 rounded-xl transition"
            >
              <span className="material-symbols-outlined text-[18px]">{loading ? "hourglass_empty" : "refresh"}</span>
              {loading ? "Running…" : "Run model"}
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 w-full max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop pt-28 pb-24 flex flex-col gap-24">
        {/* Intro & station presets */}
        <div id="top" className="flex flex-col gap-8">
          <div className="max-w-3xl">
            <p className="font-label-technical text-label-technical uppercase tracking-wider text-secondary">
              North Indian Ocean · 5–30°N, 45–105°E
            </p>
            <h1 className="mt-3 font-headline-lg text-headline-lg-mobile sm:text-headline-lg text-primary">
              Subsurface ocean temperature, reconstructed from satellite data
            </h1>
            <p className="mt-4 text-body-lg text-on-surface-variant">
              Pick a station or click anywhere on the chart. The model turns seven surface readings into a
              temperature profile down to 1000 m.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {REGIONAL_PRESETS.map((preset) => {
              const isActive = activePreset.id === preset.id;
              return (
                <button
                  key={preset.id}
                  onClick={() => handleSelectPreset(preset)}
                  className={`px-4 py-2 rounded-xl text-body-md border transition ${
                    isActive
                      ? "bg-primary text-on-primary border-primary"
                      : "bg-surface-container-lowest text-on-surface border-surface-container-high hover:border-outline-variant"
                  }`}
                >
                  {preset.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* 3D field */}
        <Section
          id="twin"
          title="3D temperature field"
          description="The reconstructed volume around the probe, from the surface to 1000 m."
          actions={
            <Segmented
              value={digitalTwinMode}
              onChange={setDigitalTwinMode}
              options={[
                { value: "3d_volume", label: "Volume" },
                { value: "horizontal_slice", label: `Slice at ${currentDepth} m` },
                { value: "vertical_transect", label: "Transect" }
              ]}
            />
          }
        >
          <div className={`${card} h-[480px] overflow-hidden flex items-center justify-center`}>
            {typeof window !== "undefined" && plotly3DData.length > 0 ? (
              <Plot
                data={plotly3DData}
                layout={{
                  autosize: true,
                  margin: { l: 10, r: 10, b: 10, t: 10 },
                  scene: {
                    xaxis: { title: "Longitude (°E)", backgroundcolor: "#EAF5FF", gridcolor: "#C7E7FE" },
                    yaxis: { title: "Latitude (°N)", backgroundcolor: "#EAF5FF", gridcolor: "#C7E7FE" },
                    zaxis: { title: "Depth (m)", backgroundcolor: "#EAF5FF", gridcolor: "#C7E7FE" },
                    camera: { eye: { x: 1.5, y: 1.5, z: 1.2 } }
                  },
                  paper_bgcolor: "rgba(0,0,0,0)",
                  plot_bgcolor: "rgba(0,0,0,0)"
                }}
                useResizeHandler={true}
                className="w-full h-full"
                config={{ responsive: true, displayModeBar: false, displaylogo: false }}
              />
            ) : (
              <span className="text-body-sm text-on-surface-variant">Loading 3D view…</span>
            )}
          </div>
        </Section>

        {/* Cyclone replay */}
        <Section
          id="replay"
          title="Cyclone replay"
          description="Step through a past storm to see how much ocean heat it drew on and the cold wake it left."
          actions={
            <select
              value={activeCycloneTrackId}
              onChange={(e) => {
                setActiveCycloneTrackId(e.target.value);
                setCycloneStepIdx(0);
                setIsPlayingCyclone(false);
              }}
              className="bg-surface-container-lowest border border-surface-container-high rounded-xl px-3 py-2 text-body-md text-primary"
            >
              <option value="amphan">Amphan, May 2020</option>
              <option value="fani">Fani, May 2019</option>
            </select>
          }
        >
          <div className={`${card} p-6 sm:p-8 flex flex-col gap-8`}>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => setIsPlayingCyclone(!isPlayingCyclone)}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary hover:bg-secondary text-on-primary text-body-sm font-medium rounded-xl transition"
              >
                <span className="material-symbols-outlined text-[18px]">{isPlayingCyclone ? "pause" : "play_arrow"}</span>
                {isPlayingCyclone ? "Pause" : "Play"}
              </button>
              <button
                onClick={() => setCycloneStepIdx((prev) => Math.max(0, prev - 1))}
                disabled={cycloneStepIdx === 0}
                className={ghostButton}
                aria-label="Previous step"
              >
                <span className="material-symbols-outlined text-[18px]">chevron_left</span>
              </button>
              <button
                onClick={() => setCycloneStepIdx((prev) => Math.min(activeCyclone.steps.length - 1, prev + 1))}
                disabled={cycloneStepIdx === activeCyclone.steps.length - 1}
                className={ghostButton}
                aria-label="Next step"
              >
                <span className="material-symbols-outlined text-[18px]">chevron_right</span>
              </button>
              <div className="ml-auto text-right">
                <div className="text-body-md font-medium text-primary">{currentCycloneStep.date}</div>
                <div className="text-body-sm text-rose-600">{currentCycloneStep.cat}</div>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <input
                type="range"
                min="0"
                max={activeCyclone.steps.length - 1}
                step="1"
                value={cycloneStepIdx}
                onChange={(e) => setCycloneStepIdx(parseInt(e.target.value))}
                className="w-full accent-rose-600 cursor-pointer"
              />
              <div className="flex justify-between text-body-sm text-on-surface-variant">
                {activeCyclone.steps.map((s, i) => (
                  <span key={i} className={i === cycloneStepIdx ? "text-rose-600 font-medium" : ""}>
                    {s.date.split(" ").slice(0, 2).join(" ")}
                  </span>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8 pt-6 border-t border-surface-container-high">
              <p className="md:col-span-2 text-body-lg text-on-surface leading-relaxed">{currentCycloneStep.narrative}</p>
              <div className="grid grid-cols-2 gap-6">
                <Stat label="Heat potential" value={currentCycloneStep.tchp} unit="kJ/cm²" tone="text-rose-600" />
                <Stat label="Cold wake" value={currentCycloneStep.coldWake} unit="°C" tone="text-secondary" />
              </div>
            </div>
          </div>
        </Section>

        {/* Probe: map + vertical profile */}
        <Section
          id="probe"
          title={activePreset.name}
          description={activePreset.context}
        >
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            <div className="lg:col-span-7 flex flex-col gap-8">
              <div className={`${card} overflow-hidden`}>
                <div onClick={handleMapClick} className="relative h-[420px] cursor-crosshair">
                  <svg className="absolute inset-0 w-full h-full" viewBox="0 0 800 540" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                    <rect fill="#EAF5FF" height="540" width="800"></rect>

                    {/* Bathymetric isobars */}
                    <path d="M 0,220 Q 200,210 380,240 T 700,220 L 800,240 L 800,540 L 0,540 Z" fill="#D3EBFF" opacity="0.6"></path>
                    <path d="M 0,310 Q 240,290 440,330 T 800,310 L 800,540 L 0,540 Z" fill="#C7E7FE" opacity="0.65"></path>
                    <path d="M 0,400 Q 280,380 500,420 T 800,390 L 800,540 L 0,540 Z" fill="#79D1FB" opacity="0.3"></path>

                    {/* Coastlines */}
                    <path d="M 0,0 L 220,0 Q 210,120 180,190 T 130,340 Q 110,420 80,480 L 0,520 Z" fill="#DFF0FF" stroke="#72787E" strokeWidth="1.2"></path>
                    <ellipse cx="145" cy="460" fill="#DFF0FF" rx="22" ry="34" stroke="#72787E" strokeWidth="1.2"></ellipse>
                    <path d="M 660,0 Q 640,110 650,220 T 680,390 Q 720,480 800,520 L 800,0 Z" fill="#DFF0FF" stroke="#72787E" strokeWidth="1.2"></path>

                    {(() => {
                      const probeX = ((customCoord.lon - 45.0) / (105.0 - 45.0)) * 800;
                      const probeY = ((30.0 - customCoord.lat) / (30.0 - 5.0)) * 540;
                      const accent = threatSimMode ? "#EF4444" : "#00B1C9";

                      return (
                        <>
                          {threatSimMode ? (
                            <g>
                              {/* Heat reservoir and projected storm track */}
                              <circle cx={probeX} cy={probeY} fill="#DC2626" fillOpacity="0.12" r="110" />
                              <circle cx={probeX} cy={probeY} fill="#EF4444" fillOpacity="0.2" r="70" />
                              <circle cx={probeX} cy={probeY} r="70" stroke="#DC2626" strokeDasharray="6 3" strokeWidth="1.5" fill="none" opacity="0.8" />
                              <path
                                d={`M ${probeX - 15},${probeY + 10} L ${probeX - 210},${probeY - 130} L ${probeX - 120},${probeY - 180} Z`}
                                fill="#EF4444"
                                fillOpacity="0.1"
                                stroke="#F87171"
                                strokeDasharray="4 2"
                                strokeWidth="1"
                              />
                              <path
                                d={`M ${probeX},${probeY} Q ${probeX - 80},${probeY - 70} ${probeX - 160},${probeY - 150}`}
                                fill="none"
                                stroke="#DC2626"
                                strokeWidth="3"
                                strokeDasharray="6 3"
                              />
                              <g transform={`translate(${probeX - 160}, ${probeY - 150})`}>
                                <circle r="9" fill="#991B1B" stroke="#FFFFFF" strokeWidth="2" />
                                <text fill="#991B1B" fontFamily="Geist" fontSize="13" fontWeight="600" x="16" y="5">
                                  Cat 5 · TCHP {tchp.toFixed(0)} kJ/cm²
                                </text>
                              </g>

                              {/* Submarine contact in the shadow zone */}
                              <g transform={`translate(${probeX + 60}, ${probeY + 50})`}>
                                <circle r="36" fill="#A855F7" fillOpacity="0.15" stroke="#7E22CE" strokeDasharray="3 3" strokeWidth="1.2" />
                                <ellipse rx="15" ry="5.5" fill="#6B21A8" stroke="#FFFFFF" strokeWidth="1.5" />
                                <text fill="#6B21A8" fontFamily="Geist" fontSize="13" fontWeight="600" x="44" y="5">
                                  Contact at {shadowStart}–{shadowEnd} m
                                </text>
                              </g>
                            </g>
                          ) : (
                            <g>
                              <circle cx={probeX} cy={probeY} fill="#FFDAD6" fillOpacity="0.4" r="45" />
                              <circle cx={probeX} cy={probeY} r="45" stroke="#EA580C" strokeDasharray="5 3" strokeWidth="1" fill="none" opacity="0.6" />
                              <line opacity="0.5" stroke="#00B1C9" strokeDasharray="6 4" strokeWidth="1.5" x1="280" x2="520" y1="0" y2="540" />
                            </g>
                          )}

                          {/* Probe reticle */}
                          <g transform={`translate(${probeX}, ${probeY})`}>
                            <line stroke={accent} strokeWidth="2" x1="-18" x2="18" y1="0" y2="0" />
                            <line stroke={accent} strokeWidth="2" x1="0" x2="0" y1="-18" y2="18" />
                            <circle r="12" fill="none" stroke={accent} strokeWidth="1.8" />
                          </g>
                        </>
                      );
                    })()}
                  </svg>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-4 border-t border-surface-container-high text-body-sm text-on-surface-variant">
                  <span className="font-mono text-primary">
                    {customCoord.lat.toFixed(2)}°N, {customCoord.lon.toFixed(2)}°E
                  </span>
                  <div className="flex items-center gap-2">
                    <span>12 °C</span>
                    <div className="w-24 h-2 rounded-full bg-gradient-to-r from-[#003E47] via-[#00B1C9] via-[#FFF7ED] to-[#EA580C]"></div>
                    <span>31 °C</span>
                  </div>
                </div>
              </div>

              {/* Surface inputs */}
              <div className="flex flex-col gap-5">
                <div className="flex items-center justify-between">
                  <h3 className="font-headline-sm text-headline-sm text-primary">Surface inputs</h3>
                  <button onClick={() => setShowChannelDrawer(!showChannelDrawer)} className="inline-flex items-center gap-1 text-body-sm font-medium text-secondary hover:text-primary">
                    <span className="material-symbols-outlined text-[18px]">{showChannelDrawer ? "check" : "tune"}</span>
                    {showChannelDrawer ? "Done" : "Edit"}
                  </button>
                </div>

                {showChannelDrawer ? (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-5 gap-y-4">
                    {inputFields.map((field) => (
                      <label key={field.key} className="flex flex-col gap-1.5">
                        <span className="text-body-sm text-on-surface-variant">
                          {field.label} ({field.unit})
                        </span>
                        <input
                          type="number"
                          step={field.step}
                          value={params[field.key]}
                          onChange={(e) => handleParamChange(field.key, e.target.value)}
                          className="w-full bg-surface-container-lowest border border-surface-container-high rounded-xl px-3 py-2 text-body-md font-mono text-primary focus:outline-none focus:border-secondary"
                        />
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
                    <Stat label="Sea surface temp" value={params.sst.toFixed(1)} unit="°C" />
                    <Stat label="Surface height" value={`${params.ssh > 0 ? "+" : ""}${params.ssh.toFixed(2)}`} unit="m" />
                    <Stat label="Salinity anomaly" value={`${params.sss > 0 ? "+" : ""}${params.sss.toFixed(2)}`} unit="PSU" />
                    <Stat label="Wind" value={Math.hypot(params.u10, params.v10).toFixed(1)} unit="m/s" />
                  </div>
                )}
              </div>
            </div>

            {/* Vertical profile */}
            <div className={`lg:col-span-5 ${card} p-6 sm:p-7 flex flex-col gap-7`}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <span className="text-body-sm text-on-surface-variant">Temperature at {currentDepth} m</span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="font-display text-display text-primary">{currentTemp.toFixed(1)}</span>
                    <span className="font-headline-sm text-headline-sm text-secondary">°C</span>
                  </div>
                </div>
                <span className="mt-1 px-2.5 py-1 rounded-lg bg-[#FFF7ED] text-[#EA580C] text-body-sm font-medium">
                  {layerName}
                </span>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex justify-between text-body-sm">
                  <span className="text-on-surface-variant">Depth</span>
                  <span className="font-mono text-primary">{currentDepth} m</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max={DEPTH_LEVELS.length - 1}
                  step="1"
                  value={selectedDepthIdx}
                  onChange={(e) => setSelectedDepthIdx(Number(e.target.value))}
                  className="w-full accent-primary cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-body-sm text-on-surface-variant mb-2">
                  <span>Profile</span>
                  <span>3 – 32 °C</span>
                </div>
                <svg className="w-full h-64" viewBox="0 0 300 230" preserveAspectRatio="none">
                  <line x1="20" y1="20" x2="280" y2="20" stroke="#D3EBFF" strokeWidth="1" />
                  <line x1="20" y1="115" x2="280" y2="115" stroke="#D3EBFF" strokeDasharray="3 3" strokeWidth="1" />
                  <line x1="20" y1="210" x2="280" y2="210" stroke="#D3EBFF" strokeWidth="1" />
                  <path d={curvePathD} fill="none" stroke="#00B1C9" strokeWidth="2.5" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  {curvePoints.map((pt) => {
                    const isSel = selectedDepthIdx === pt.idx;
                    return (
                      <circle
                        key={pt.depth}
                        cx={pt.x}
                        cy={pt.y}
                        r={isSel ? 5.5 : 3}
                        fill={isSel ? "#EA580C" : "#00253D"}
                        stroke="#ffffff"
                        strokeWidth="1.5"
                        className="cursor-pointer"
                        onClick={() => setSelectedDepthIdx(pt.idx)}
                      >
                        <title>{`${pt.depth} m · ${pt.temp} °C`}</title>
                      </circle>
                    );
                  })}
                </svg>
              </div>

              <div className="grid grid-cols-3 pt-5 border-t border-surface-container-high">
                <Stat label="Surface" value={surfaceTemp.toFixed(1)} unit="°C" />
                <Stat label="100 m" value={thermoclineTemp.toFixed(1)} unit="°C" />
                <Stat label="1000 m" value={abyssalTemp.toFixed(1)} unit="°C" />
              </div>
            </div>
          </div>
        </Section>

        {/* Insights */}
        <Section
          id="insights"
          title="What the profile tells us"
          description="Quantities derived from the predicted temperature profile at the probe."
          actions={
            <button
              onClick={handleThreatSimToggle}
              className={
                threatSimMode
                  ? "inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-body-sm font-medium bg-rose-600 hover:bg-rose-700 text-white transition"
                  : ghostButton
              }
            >
              <span className="material-symbols-outlined text-[18px]">{threatSimMode ? "close" : "radar"}</span>
              {threatSimMode ? "End threat scenario" : "Run threat scenario"}
            </button>
          }
        >
          {threatSimMode && (
            <div className="px-5 py-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-900 text-body-md">
              Threat scenario is on. Surface inputs are set to extreme values (SST 31.8 °C, winds near 34 m/s), so the
              numbers below describe a simulated storm and submarine contact, not live conditions.
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {insightTabs.map((tab) => {
              const isActive = activePillarTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActivePillarTab(tab.id)}
                  className={`text-left p-5 rounded-xl border bg-surface-container-lowest transition ${
                    isActive ? "border-primary ring-1 ring-primary" : "border-surface-container-high hover:border-outline-variant"
                  }`}
                >
                  <div className={`flex items-center gap-2 text-body-md font-medium ${tab.accent}`}>
                    <span className="material-symbols-outlined text-[20px]">{tab.icon}</span>
                    {tab.name}
                  </div>
                  <div className="mt-4 font-data-metric text-data-metric text-primary">{tab.metric}</div>
                  <p className="mt-1 text-body-sm text-on-surface-variant">{tab.caption}</p>
                </button>
              );
            })}
          </div>

          <div className={`${card} p-6 sm:p-8 flex flex-col gap-8`}>
            {activePillarTab === "cyclone" && (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
                  <Stat
                    label="26 °C isotherm depth"
                    value={d26.toFixed(1)}
                    unit="m"
                    note="Below 50 m, there is a deep warm layer for a storm to draw on."
                  />
                  <Stat
                    label="Cyclone heat potential"
                    value={tchp.toFixed(1)}
                    unit="kJ/cm²"
                    tone="text-rose-600"
                    note="Above 80 kJ/cm², rapid intensification becomes likely."
                  />
                  <Stat
                    label="Risk"
                    value={tchp > 80 ? "High" : "Low"}
                    tone={tchp > 80 ? "text-rose-600" : "text-emerald-700"}
                    note={cyclone.risk_category ?? "Stable warm upper layer"}
                  />
                </div>

                <div className="flex flex-col gap-2">
                  <div className="w-full h-3 bg-surface-container rounded-full overflow-hidden relative">
                    <div
                      className="h-full bg-gradient-to-r from-emerald-500 via-amber-500 to-rose-600 transition-all duration-500"
                      style={{ width: `${Math.min(100, (tchp / 140) * 100)}%` }}
                    ></div>
                    <div className="absolute inset-y-0 left-[57%] w-0.5 bg-primary"></div>
                  </div>
                  <div className="flex justify-between text-body-sm text-on-surface-variant">
                    <span>0</span>
                    <span className="ml-[14%]">80 threshold</span>
                    <span>140 kJ/cm²</span>
                  </div>
                </div>
              </>
            )}

            {activePillarTab === "asw" && (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
                  <Stat
                    label="Thermocline core"
                    value={thermoclineCore}
                    unit="m"
                    note="Where temperature drops fastest with depth."
                  />
                  <Stat
                    label="Steepest gradient"
                    value={maxGradient.toFixed(3)}
                    unit="°C/m"
                    tone="text-purple-600"
                    note="Stronger gradients bend sonar more sharply."
                  />
                  <Stat
                    label="Shadow zone"
                    value={`${shadowStart}–${shadowEnd}`}
                    unit="m"
                    tone="text-purple-600"
                    note="Surface sonar refracts away from this band."
                  />
                </div>

                {(() => {
                  const yStart = Math.min(55, Math.max(25, Math.round((shadowStart / 200) * 100)));
                  const yEnd = Math.min(115, Math.max(yStart + 30, Math.round((shadowEnd / 200) * 100)));

                  return (
                    <svg className="w-full max-w-3xl h-auto rounded-xl overflow-hidden" viewBox="0 0 500 140">
                      <rect x="0" y="0" width="500" height={yStart} fill="#EAF5FF" />
                      <rect x="0" y={yStart} width="500" height={yEnd - yStart} fill={threatSimMode ? "#FEE2E2" : "#D3EBFF"} />
                      <rect x="0" y={yEnd} width="500" height={140 - yEnd} fill="#C7E7FE" />
                      <line x1="0" y1={yStart} x2="500" y2={yStart} stroke={threatSimMode ? "#EF4444" : "#00B1C9"} strokeDasharray="4 2" strokeWidth="1" />

                      <text x="12" y="16" fill="#42474E" fontSize="9">Mixed layer</text>
                      <text x="12" y={yStart + 14} fill={threatSimMode ? "#991B1B" : "#006686"} fontSize="9">Shadow zone</text>
                      <text x="12" y={yEnd + 14} fill="#42474E" fontSize="9">Deep water</text>

                      {/* Ship and bending sonar rays */}
                      <g transform="translate(400, 4)">
                        <circle cx="12" cy="8" r="3.5" fill="#00253D" />
                        <path d="M 0,12 L 24,12 L 20,18 L 4,18 Z" fill="#00253D" />
                      </g>
                      <path d={`M 412,18 Q 300,${yStart + 2} 180,${yStart + 5} T 40,${yStart + 8}`} fill="none" stroke="#BA1A1A" strokeWidth="1.5" strokeDasharray="3 3" />
                      <path d={`M 412,18 Q 270,${yStart} 130,${yStart + 3} T 20,${yStart + 6}`} fill="none" stroke="#BA1A1A" strokeWidth="1.2" strokeDasharray="3 3" />

                      <g transform={`translate(260, ${yStart + (yEnd - yStart) / 2})`}>
                        <ellipse rx="22" ry="7" fill={threatSimMode ? "#B91C1C" : "#4FD7F0"} stroke="#00272D" strokeWidth="1.2" />
                        <rect x="-3" y="-12" width="6" height="6" fill={threatSimMode ? "#7F1D1D" : "#00272D"} />
                      </g>
                    </svg>
                  );
                })()}

                <p className="text-body-sm text-on-surface-variant">
                  {threatSimMode
                    ? `Simulated contact inside the ${shadowStart}–${shadowEnd} m shadow zone, out of reach of hull-mounted sonar.`
                    : "No contact. Sonar rays bend normally through the thermocline."}
                </p>
              </>
            )}

            {activePillarTab === "fisheries" && (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
                  <Stat
                    label="Upwelling index"
                    value={`+${upwelling.toFixed(2)}`}
                    unit="°C"
                    tone="text-emerald-700"
                    note="Surface minus 50 m temperature. Higher means colder, nutrient-rich water is rising."
                  />
                  <Stat
                    label="Fishing zone"
                    value={upwelling > 3 ? "Promising" : "Weak"}
                    tone="text-emerald-700"
                    note={fisheries.pfz_status ?? "High potential fishing zone"}
                  />
                  <Stat
                    label="Distance to boundary"
                    value={borderDistance.toFixed(1)}
                    unit="km"
                    tone={threatSimMode ? "text-rose-600" : "text-amber-700"}
                    note="Distance to the international maritime boundary line."
                  />
                </div>

                <div className={`px-5 py-4 rounded-xl border text-body-md flex items-start gap-3 ${
                  threatSimMode ? "bg-rose-50 border-rose-200 text-rose-900" : "bg-amber-50 border-amber-200 text-amber-900"
                }`}>
                  <span className="material-symbols-outlined text-[20px]">info</span>
                  {fisheries.border_alert ?? "Safe zone: within domestic EEZ waters."}
                </div>
              </>
            )}

            {activePillarTab === "volume" && (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
                <div className="lg:col-span-4 flex flex-col gap-6">
                  <p className="text-body-md text-on-surface-variant">
                    The column is split into five layers. Click a layer to jump to that depth.
                  </p>
                  <Stat label="Surface" value={surfaceTemp.toFixed(1)} unit="°C" />
                  <Stat label="Thermocline core" value={thermoclineCore} unit="m" />
                  <Stat label="1000 m" value={abyssalTemp.toFixed(1)} unit="°C" />
                  <div className="flex gap-2">
                    <button onClick={() => setStratumRotation((prev) => prev - 15)} className={ghostButton} aria-label="Rotate left">
                      <span className="material-symbols-outlined text-[18px]">rotate_left</span>
                    </button>
                    <button onClick={() => setStratumRotation((prev) => prev + 15)} className={ghostButton} aria-label="Rotate right">
                      <span className="material-symbols-outlined text-[18px]">rotate_right</span>
                    </button>
                    <button onClick={() => setStratumRotation(0)} className={ghostButton}>Reset</button>
                  </div>
                </div>

                <div className="lg:col-span-8 h-[340px] rounded-xl bg-surface-container-low overflow-hidden flex items-center justify-center p-4">
                  <svg
                    className="w-full h-full transition-transform duration-500 ease-out"
                    viewBox="0 0 520 340"
                    style={{ transform: `rotate(${stratumRotation}deg)` }}
                  >
                    {[
                      { depth: "0–30 m", label: "Surface layer", depthIdx: 0, yOffset: 40, colors: ["#EA580C", "#F97316", "#FB923C", "#F59E0B"] },
                      { depth: "50–100 m", label: "Thermocline", depthIdx: 7, yOffset: 95, colors: ["#00B1C9", "#14B8A6", "#34D399", "#FBBF24"] },
                      { depth: "125–200 m", label: "Sub-thermocline", depthIdx: 10, yOffset: 150, colors: ["#0284C7", "#00B1C9", "#38BDF8", "#10B981"] },
                      { depth: "300–500 m", label: "Intermediate", depthIdx: 12, yOffset: 205, colors: ["#1E40AF", "#2563EB", "#3B82F6", "#60A5FA"] },
                      { depth: "750–1000 m", label: "Deep", depthIdx: 14, yOffset: 260, colors: ["#00253D", "#003E47", "#1E3A8A", "#1D4ED8"] }
                    ].map((stratum, sIdx) => {
                      const isSelectedLayer = selectedDepthIdx >= stratum.depthIdx - 2 && selectedDepthIdx <= stratum.depthIdx + 2;
                      const centerX = 260;

                      return (
                        <g key={sIdx}>
                          <polygon
                            points={`${centerX},${stratum.yOffset - 35} 400,${stratum.yOffset} ${centerX},${stratum.yOffset + 35} 120,${stratum.yOffset}`}
                            fill={isSelectedLayer ? "#00B1C9" : "#94A3B8"}
                            fillOpacity={isSelectedLayer ? "0.15" : "0.05"}
                            stroke={isSelectedLayer ? "#00B1C9" : "#CBD5E1"}
                            strokeWidth={isSelectedLayer ? "2" : "1"}
                            strokeDasharray={isSelectedLayer ? "none" : "3 3"}
                          />
                          {[0, 1, 2, 3, 4].map((row) =>
                            [0, 1, 2, 3, 4].map((col) => {
                              const cellU = (col - 2) / 2.5;
                              const cellV = (row - 2) / 2.5;
                              const cx = centerX + (cellU - cellV) * 52;
                              const cy = stratum.yOffset + (cellU + cellV) * 14;
                              const cellColor = stratum.colors[(row * 3 + col * 2 + sIdx) % stratum.colors.length];

                              return (
                                <polygon
                                  key={`${row}-${col}`}
                                  points={`${cx},${cy - 8} ${cx + 22},${cy} ${cx},${cy + 8} ${cx - 22},${cy}`}
                                  fill={cellColor}
                                  fillOpacity={isSelectedLayer ? "0.9" : "0.5"}
                                  stroke="#ffffff"
                                  strokeWidth="0.8"
                                  className="cursor-pointer"
                                  onClick={() => setSelectedDepthIdx(stratum.depthIdx)}
                                >
                                  <title>{`${stratum.label} (${stratum.depth})`}</title>
                                </polygon>
                              );
                            })
                          )}
                          <text x="420" y={stratum.yOffset + 4} fill={isSelectedLayer ? "#006686" : "#72787E"} fontSize="11" fontWeight={isSelectedLayer ? "600" : "400"}>
                            {stratum.depth}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>
              </div>
            )}
          </div>
        </Section>

        {/* Latent embedding */}
        <Section
          id="embedding"
          title="Latent embedding"
          description="A 128-number summary of this ocean state, used to find similar conditions in the archive."
          actions={
            <button onClick={handleCopyVector} className={ghostButton}>
              <span className="material-symbols-outlined text-[18px]">{copied ? "check" : "content_copy"}</span>
              {copied ? "Copied" : "Copy vector"}
            </button>
          }
        >
          <div className={`${card} p-6 sm:p-8 flex flex-col gap-8`}>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
              <Stat label="L2 norm" value={latent.vector_norm ?? "12.458"} />
              <Stat label="Dimensions" value="128" />
              <Stat label="Mean / std" value={`${latent.mean ?? "0.012"} / ${latent.std ?? "0.894"}`} />
              <Stat label="Range" value={`${latent.min ?? "-2.14"} to ${latent.max ?? "2.38"}`} />
            </div>

            <div className="flex flex-col gap-2">
              <div className="h-24 w-full flex items-end gap-px">
                {(latent.full_latent_vector || DETERMINISTIC_INITIAL_PREDICTION.latent_embedding.full_latent_vector).map((val, idx) => (
                  <div
                    key={idx}
                    title={`Dim ${idx}: ${val}`}
                    className="flex-1 rounded-t-sm"
                    style={{
                      height: `${Math.min(100, Math.max(6, (Math.abs(val) / 2.5) * 100))}%`,
                      backgroundColor: val > 0 ? "#00B1C9" : "#BA1A1A",
                      opacity: 0.8
                    }}
                  ></div>
                ))}
              </div>
              <div className="flex justify-between text-body-sm text-on-surface-variant">
                <span>Dim 0</span>
                <span>Dim 127</span>
              </div>
            </div>

            {similarMatches.length > 0 && (
              <div className="flex flex-col gap-4 pt-6 border-t border-surface-container-high">
                <h3 className="font-headline-sm text-headline-sm text-primary">Most similar past conditions</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {similarMatches.slice(0, 3).map((match, i) => (
                    <div key={i} className="flex flex-col gap-1">
                      <div className="flex justify-between items-baseline gap-3">
                        <span className="text-body-md font-medium text-primary">{match.station_name}</span>
                        <span className="text-body-sm font-mono text-secondary">{match.similarity_score_pct}%</span>
                      </div>
                      <p className="text-body-sm text-on-surface-variant leading-relaxed">{match.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Section>

        {/* Validation */}
        <Section
          id="validation"
          title="Validation"
          description="Checked against 54,606 independent INCOIS Argo float profiles."
          actions={
            <button onClick={() => setShowScatterModal(!showScatterModal)} className={ghostButton}>
              <span className="material-symbols-outlined text-[18px]">scatter_plot</span>
              {showScatterModal ? "Hide scatter plot" : "Show scatter plot"}
            </button>
          }
        >
          <div className={`${card} overflow-hidden`}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-body-md">
                <thead>
                  <tr className="border-b border-surface-container-high text-body-sm text-on-surface-variant">
                    <th className="px-6 py-4 font-medium">Model</th>
                    <th className="px-6 py-4 font-medium">Inputs</th>
                    <th className="px-6 py-4 font-medium">GLORYS12 RMSE</th>
                    <th className="px-6 py-4 font-medium">Argo RMSE</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container-high">
                  <tr>
                    <td className="px-6 py-4 text-primary">SST-only MLP</td>
                    <td className="px-6 py-4 text-on-surface-variant">SST</td>
                    <td className="px-6 py-4 font-mono text-on-surface-variant">1.0440 °C</td>
                    <td className="px-6 py-4 font-mono text-on-surface-variant">2.1450 °C</td>
                  </tr>
                  <tr>
                    <td className="px-6 py-4 text-primary">Multi-variable MLP</td>
                    <td className="px-6 py-4 text-on-surface-variant">SST, SSH, SSS, wind</td>
                    <td className="px-6 py-4 font-mono text-on-surface-variant">1.0573 °C</td>
                    <td className="px-6 py-4 font-mono text-on-surface-variant">1.7820 °C</td>
                  </tr>
                  <tr className="bg-secondary-container/15">
                    <td className="px-6 py-4 text-primary font-medium">OceanEmbed CNN</td>
                    <td className="px-6 py-4 text-primary">14-channel spatial patch</td>
                    <td className="px-6 py-4 font-mono text-secondary">1.3892 °C</td>
                    <td className="px-6 py-4 font-mono text-on-tertiary-container font-semibold">1.3892 °C</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 px-6 py-6 border-t border-surface-container-high">
              <Stat label="Surface RMSE" value="1.4315" unit="°C" />
              <Stat label="100 m RMSE" value="1.5689" unit="°C" tone="text-secondary" />
              <Stat label="1000 m RMSE" value="0.6813" unit="°C" tone="text-on-tertiary-container" />
            </div>

            {showScatterModal && (
              <div className="px-6 py-6 border-t border-surface-container-high flex flex-col gap-3">
                <div className="flex flex-wrap justify-between gap-2 text-body-sm">
                  <span className="text-primary font-medium">Predicted vs observed temperature</span>
                  <span className="text-emerald-700">R² = 0.942 · bias −0.012 °C</span>
                </div>
                <svg className="w-full h-48" viewBox="0 0 400 160">
                  <line x1="30" y1="130" x2="380" y2="20" stroke="#00B1C9" strokeDasharray="3 3" strokeWidth="1.5" />
                  <text x="318" y="46" fill="#006686" fontSize="10">1:1 line</text>
                  {[
                    { x: 50, y: 115 }, { x: 70, y: 105 }, { x: 90, y: 92 }, { x: 120, y: 80 },
                    { x: 150, y: 68 }, { x: 180, y: 55 }, { x: 210, y: 48 }, { x: 240, y: 40 },
                    { x: 280, y: 32 }, { x: 320, y: 25 }, { x: 350, y: 21 }
                  ].map((pt, i) => (
                    <circle key={i} cx={pt.x} cy={pt.y} r="3" fill="#00253D" opacity="0.8" />
                  ))}
                </svg>
                <div className="flex justify-between text-body-sm text-on-surface-variant">
                  <span>4 °C observed</span>
                  <span>31 °C observed</span>
                </div>
              </div>
            )}
          </div>
        </Section>
      </main>

      <footer className="w-full border-t border-surface-container-high py-10">
        <div className="max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop flex flex-col sm:flex-row items-center justify-between gap-3 text-body-sm text-on-surface-variant">
          <span>
            <span className="text-primary font-medium">OceanEmbed</span> · Team OceanSATX · SIH 2026, PS 26066
          </span>
          <span>Bay of Bengal &amp; Arabian Sea</span>
        </div>
      </footer>
    </div>
  );
}

function Section({ id, title, description, actions, children }) {
  return (
    <section id={id} className="scroll-mt-24 flex flex-col gap-6">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div className="max-w-2xl">
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
      <span className={`font-data-metric text-data-metric ${tone}`}>
        {value}
        {unit && <span className="ml-1 text-body-md text-on-surface-variant">{unit}</span>}
      </span>
      {note && <p className="mt-1 text-body-sm text-on-surface-variant leading-relaxed">{note}</p>}
    </div>
  );
}

function Segmented({ options, value, onChange }) {
  return (
    <div className="inline-flex p-1 rounded-xl bg-surface-container-low border border-surface-container-high">
      {options.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          className={`px-3 py-1.5 rounded-lg text-body-sm font-medium transition ${
            value === option.value ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-primary"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
