"""
===============================================================================
OceanEmbed — FastAPI backend
Team OceanSATX | SIH 2026 | Problem Statement 26066
===============================================================================
Every value this API returns is read from files produced from real inputs:

  basin_output/basin_*.nc (+ .latent.npy)  basin_inference.py  model + reference fields
  basin_output/eval_results.json           kaggle_oceanembed_eval.py  validation numbers
  basin_output/cyclone_tracks.json         fetch_cyclone_tracks.py    IBTrACS best tracks

or computed on request by the trained network from input patches rebuilt out of
those files (sensitivity experiments). If a file is missing the endpoint returns
404 with instructions; nothing is invented to fill the gap.
===============================================================================
"""

import glob
import json
import os
import sys
from typing import Dict, Optional

import numpy as np
import torch
import xarray as xr
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import oceanembed_core as core  # noqa: E402

app = FastAPI(title="OceanEmbed AI Service", version="2.0.0",
              description="Subsurface temperature from satellite surface fields — file-backed, no synthetic data")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
BASIN_DIR = os.environ.get("OCEANEMBED_BASIN_DIR", os.path.join(HERE, "basin_output"))
CHECKPOINT = os.environ.get("OCEANEMBED_CHECKPOINT", os.path.join(HERE, "trained", "best_oceanembed_model.pth"))
model = core.load_trained_model(CHECKPOINT, device)      # strict=True
CHECKPOINT_SHA = core.file_sha256(CHECKPOINT)
print(f"[+] OceanEmbed loaded (strict) from {CHECKPOINT} on {device}")

EARTH_R_KM = 6371.0
MAX_SNAP_KM = 111.0   # a probe snaps to the nearest predicted cell within ~1°


def _missing(what, how):
    raise HTTPException(status_code=404, detail={"message": f"{what} not found.", "how_to_create": how, "directory": BASIN_DIR})


def _f(v, d=None):
    """float or None (JSON-safe)."""
    v = float(v)
    if not np.isfinite(v):
        return None
    return round(v, d) if d is not None else v


def _grid(a, d):
    a = np.round(np.asarray(a, dtype=np.float64), d)
    return [[None if not np.isfinite(x) else float(x) for x in row] for row in a]


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(np.asarray(lon2) - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(a))


# =============================================================================
# FILE REGISTRY
# =============================================================================
class BasinStore:
    def __init__(self, directory):
        self.dir = directory
        self._cache = {}          # path -> (mtime, in-memory dataset)
        self._lat_cache = {}
        import threading
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def files(self):
        return sorted(set(glob.glob(os.path.join(self.dir, "basin_*.nc")) + glob.glob(os.path.join(self.dir, "oceanembed_basin.nc"))))

    def open(self, path):
        # HDF5/netCDF4 is not thread-safe and FastAPI serves requests on a thread pool, so each file
        # is read fully into memory once, under a lock, and the file handle is closed straight away.
        m = os.path.getmtime(path)
        with self._lock:
            c = self._cache.get(path)
            if c and c[0] == m:
                self.hits += 1
                return c[1]
            self.misses += 1
            with xr.open_dataset(path) as src:
                ds = src.load()
            self._cache[path] = (m, ds)
            self._lat_cache.pop(path, None)
            return ds

    def index(self):
        """date -> (path, t). A date in several files is served from the most recently created file."""
        idx = {}
        for p in self.files():
            ds = self.open(p)
            created = ds.attrs.get("created_utc", "")
            for t, v in enumerate(ds["time"].values):
                d = str(np.datetime_as_string(v, unit="D"))
                if d not in idx or created > idx[d][2]:
                    idx[d] = (p, t, created)
        return {d: (p, t) for d, (p, t, _) in idx.items()}

    def day(self, date):
        idx = self.index()
        if not idx:
            _missing("No basin inference files", "python basin_inference.py --data-dir <inputs> --start <YYYY-MM-DD> --end <YYYY-MM-DD>")
        if date not in idx:
            raise HTTPException(404, detail={"message": f"No inference for {date}.", "available": sorted(idx)})
        p, t = idx[date]
        return p, t, self.open(p)

    def latents(self, path):
        if path not in self._lat_cache:
            f = path + ".latent.npy"
            if not os.path.exists(f):
                _missing(f"Embeddings for {os.path.basename(path)}", "re-run basin_inference.py (it writes <file>.latent.npy)")
            self._lat_cache[path] = np.load(f, mmap_mode="r")
        return self._lat_cache[path]


store = BasinStore(BASIN_DIR)


def _file_meta(ds):
    return {
        "input_data": ds.attrs.get("input_data", "unknown"),
        "reference_name": ds.attrs.get("reference_name", "GLORYS12 reanalysis"),
        "normalisation": ds.attrs.get("normalisation"),
        "checkpoint_matches_server": ds.attrs.get("checkpoint_sha256") == CHECKPOINT_SHA,
        "created_utc": ds.attrs.get("created_utc"),
    }


def _nearest_cell(ds, t, lat, lon):
    valid = np.isfinite(ds["pred_temp_c"].isel(time=t, depth=0).values)
    if not valid.any():
        raise HTTPException(404, detail="No predicted cells on this day.")
    LAT, LON = np.meshgrid(ds.latitude.values, ds.longitude.values, indexing="ij")
    d = np.where(valid, _haversine_km(lat, lon, LAT, LON), np.inf)
    r, c = np.unravel_index(int(np.argmin(d)), d.shape)
    if d[r, c] > MAX_SNAP_KM:
        raise HTTPException(404, detail={"message": f"No deep-water (≥1000 m) model cell within {MAX_SNAP_KM:.0f} km of "
                                                    f"{lat:.2f}°N {lon:.2f}°E. The model only predicts where it was trained.",
                                         "nearest_km": _f(d[r, c], 1)})
    return int(r), int(c), float(d[r, c])


def _stats(ds):
    s = json.loads(ds.attrs["normalisation_stats_json"])
    return {k: (float(v[0]), float(v[1])) for k, v in s.items()}, ds.attrs.get("sst_source_units", "K") == "K"


INPUT_VARS = {"sst": "in_sst_c", "ssh": "in_ssh_m", "sss": "in_sss", "uo": "in_uo_ms", "vo": "in_vo_ms", "u10": "in_u10_ms", "v10": "in_v10_ms"}
INPUT_UNITS = {"sst": "°C", "ssh": "m", "sss": "PSU", "uo": "m/s", "vo": "m/s", "u10": "m/s", "v10": "m/s"}


def _zscores(values, stats, sst_k):
    out = {}
    for k, v in values.items():
        if v is None:
            out[k] = None
            continue
        m, s = stats[k]
        x = v + 273.15 if (k == "sst" and sst_k) else v
        out[k] = round((x - m) / (s + 1e-6), 2)
    return out


def _profile_block(P, sss):
    diag = core.all_diagnostics(P)
    d = {k: _f(v[0], 3) for k, v in diag.items()}
    if d["d26_m"] is None and d["tchp_kj_cm2"] == 0.0:
        d["d26_note"] = "surface colder than 26 °C"
    sl = None
    if sss is not None and 25.0 <= sss <= 40.0:
        s = core.sonic_layer(P, sss)
        sl = {k: (_f(v, 3) if isinstance(v, float) else v) for k, v in s.items() if k != "c_levels_ms"}
        sl["c_levels_ms"] = [round(x, 2) for x in s["c_levels_ms"]]
    i50 = int(np.where(core.DEPTH_LEVELS == 50)[0][0])
    d["stratification_0_50m_c"] = _f(P[0] - P[i50], 3)
    return {"profile_c": [round(float(x), 3) for x in P], "diagnostics": d, "sound_speed": sl}


# =============================================================================
# ENDPOINTS
# =============================================================================
@app.get("/api/health")
def health():
    files = store.files()
    return {"status": "healthy", "device": str(device), "checkpoint": os.path.basename(CHECKPOINT),
            "checkpoint_sha256": CHECKPOINT_SHA, "total_parameters": int(sum(p.numel() for p in model.parameters())),
            "basin_files": [os.path.basename(f) for f in files], "depth_levels_m": core.DEPTH_LEVELS.tolist()}


@app.get("/api/basin/meta")
def basin_meta():
    idx = store.index()
    if not idx:
        _missing("No basin inference files", "python basin_inference.py --data-dir <folder with OSTIA_SST.nc, COPERNICUS_CURRENTS_SSH.nc, "
                 "ERA5_WINDS.nc, GLORYS12V1.nc> --start 2023-01-01 --end 2023-01-30")
    files = []
    for p in store.files():
        ds = store.open(p)
        files.append({"file": os.path.basename(p), "date_range": ds.attrs.get("date_range"),
                      "skill": json.loads(ds.attrs.get("skill_json", "{}")), **_file_meta(ds)})
    dates = []
    for d in sorted(idx):
        p, t = idx[d]
        ds = store.open(p)
        dates.append({"date": d, "split": str(ds["split"].values[t]), "file": os.path.basename(p),
                      "reference_name": ds.attrs.get("reference_name"), "input_data": ds.attrs.get("input_data")})
    ds0 = store.open(store.files()[0])
    return {
        "dates": dates, "files": files,
        "grid": {"lat_min": float(ds0.latitude.min()), "lat_max": float(ds0.latitude.max()),
                 "lon_min": float(ds0.longitude.min()), "lon_max": float(ds0.longitude.max()),
                 "resolution_deg": float(abs(ds0.latitude.values[1] - ds0.latitude.values[0])),
                 "n_lat": int(ds0.sizes["latitude"]), "n_lon": int(ds0.sizes["longitude"])},
        "depth_levels_m": core.DEPTH_LEVELS.tolist(),
        "diagnostics": core.DIAGNOSTIC_META,
        "valid_cell_rule": ds0.attrs.get("valid_cell_rule"),
    }


DAY_FIELDS = {
    "sst_c": ("in_sst_c", 2), "ssh_m": ("in_ssh_m", 3), "in_max_abs_z": ("in_max_abs_z", 2),
    "d26_m": ("{s}_d26_m", 1), "d20_m": ("{s}_d20_m", 1), "tchp_kj_cm2": ("{s}_tchp_kj_cm2", 1), "mld_m": ("{s}_mld_m", 1),
    "thermocline_mid_m": ("{s}_thermocline_mid_m", 1), "thermocline_grad_c_per_m": ("{s}_thermocline_grad_c_per_m", 4),
    "t100_c": ("{s}_t100_c", 2), "profile_rmse_c": ("profile_rmse_c", 2),
}


@app.get("/api/basin/day")
def basin_day(date: str, source: str = "model"):
    source = {"glorys": "ref", "reference": "ref"}.get(source, source)
    if source not in ("model", "ref"):
        raise HTTPException(400, detail="source must be 'model' or 'reference'")
    p, t, ds = store.day(date)
    day = ds.isel(time=t)
    fields = {k: _grid(day[v.format(s=source)].values, d) for k, (v, d) in DAY_FIELDS.items()}
    return {"date": date, "split": str(ds["split"].values[t]), "source": source, **_file_meta(ds),
            "lats": [round(float(v), 3) for v in ds.latitude.values], "lons": [round(float(v), 3) for v in ds.longitude.values],
            "n_valid_cells": int(np.isfinite(day["pred_temp_c"].values[0]).sum()), "fields": fields}


# Named places: coordinates and plain geography only. Values always come from the data at that point.
PLACES = [
    {"id": "central_bay", "name": "Central Bay of Bengal", "lat": 14.5, "lon": 88.0, "note": "Open ocean, central basin"},
    {"id": "southwest_bay", "name": "South-west Bay of Bengal", "lat": 10.0, "lon": 84.0, "note": "East of Sri Lanka"},
    {"id": "off_visakhapatnam", "name": "Off Visakhapatnam", "lat": 17.0, "lon": 84.5, "note": "Offshore of the Andhra coast"},
    {"id": "north_bay", "name": "Northern Bay of Bengal", "lat": 19.5, "lon": 88.5, "note": "South of the Ganges–Brahmaputra delta shelf"},
    {"id": "andaman_sea", "name": "Andaman Sea", "lat": 12.0, "lon": 95.5, "note": "East of the Andaman Islands"},
    {"id": "central_arabian", "name": "Central Arabian Sea", "lat": 15.0, "lon": 65.0, "note": "Open ocean, central basin"},
]


@app.get("/api/places")
def places():
    return PLACES


@app.get("/api/point")
def point(date: str, lat: float, lon: float):
    p, t, ds = store.day(date)
    r, c, dist = _nearest_cell(ds, t, lat, lon)
    day = ds.isel(time=t, latitude=r, longitude=c)
    stats, sst_k = _stats(ds)
    inputs = {k: _f(day[v].values, 4) for k, v in INPUT_VARS.items()}
    sss = inputs["sss"]
    lat_arr = store.latents(p)
    cell_idx = int(np.nonzero((ds["cell_row"].values == r) & (ds["cell_col"].values == c))[0][0])
    lv = np.asarray(lat_arr[t, cell_idx], dtype=np.float32)
    return {
        "date": date, "split": str(ds["split"].values[t]), **_file_meta(ds), "file": os.path.basename(p),
        "requested": {"lat": lat, "lon": lon},
        "cell": {"lat": float(ds.latitude.values[r]), "lon": float(ds.longitude.values[c]), "row": r, "col": c, "distance_km": round(dist, 1)},
        "inputs": {k: {"value": v, "units": INPUT_UNITS[k]} for k, v in inputs.items()},
        "input_z_scores": _zscores(inputs, stats, sst_k),
        "model": _profile_block(day["pred_temp_c"].values.astype(np.float64), sss),
        "reference": _profile_block(day["ref_temp_c"].values.astype(np.float64), sss),
        "profile_rmse_c": _f(day["profile_rmse_c"].values, 3),
        "depth_levels_m": core.DEPTH_LEVELS.tolist(),
        "latent": {"vector": [round(float(x), 4) for x in lv], "l2_norm": _f(np.linalg.norm(lv), 4),
                   "mean": _f(lv.mean(), 4), "std": _f(lv.std(), 4), "min": _f(lv.min(), 4), "max": _f(lv.max(), 4)},
    }


class SensitivityRequest(BaseModel):
    date: str
    lat: float
    lon: float
    deltas: Dict[str, float] = Field(default_factory=dict, description="uniform change added to the real patch, e.g. {'sst': 1.0}")


@app.post("/api/sensitivity")
def sensitivity(req: SensitivityRequest):
    bad = set(req.deltas) - set(INPUT_VARS)
    if bad:
        raise HTTPException(400, detail=f"unknown variables {sorted(bad)}; allowed {list(INPUT_VARS)}")
    p, t, ds = store.day(req.date)
    r, c, dist = _nearest_cell(ds, t, req.lat, req.lon)
    stats, sst_k = _stats(ds)
    day = ds.isel(time=t)
    raw = {k: day[v].values.astype(np.float64) for k, v in INPUT_VARS.items()}
    pert = {k: raw[k] + req.deltas.get(k, 0.0) for k in raw}          # NaN (no data) stays NaN
    with torch.no_grad():
        outs = []
        for fields in (raw, pert):
            surf = torch.from_numpy(core.normalise_surface(fields, stats, sst_k)).float()
            patch = core.extract_patches(core.reflect_pad(surf).to(device), np.array([r]), np.array([c]))
            outs.append(model(patch)[0][0].cpu().numpy().astype(np.float64))
    base, new = outs
    stored = day["pred_temp_c"].values[:, r, c].astype(np.float64)
    recon = float(np.max(np.abs(base - stored)))
    centre = {k: _f(pert[k][r, c], 4) for k in pert}
    sss = centre["sss"]
    return {
        "date": req.date, "cell": {"lat": float(ds.latitude.values[r]), "lon": float(ds.longitude.values[c]), "distance_km": round(dist, 1)},
        "deltas": req.deltas,
        "method": "the stored real 31x31 input patch with the deltas added uniformly to every valid pixel, "
                  "re-normalised with the training statistics and passed through the trained network",
        "reconstruction_max_abs_diff_c": round(recon, 6),
        "baseline": _profile_block(base, raw["sss"][r, c] if np.isfinite(raw["sss"][r, c]) else None),
        "perturbed": _profile_block(new, sss),
        "perturbed_input_z_scores": _zscores(centre, stats, sst_k),
        "note": "|z| > 4 means the perturbed inputs are far outside the training data; treat the result as extrapolation.",
    }


@app.get("/api/volume")
def volume(date: str, lat: float, lon: float, half_width_deg: float = 1.0):
    half_width_deg = float(min(3.0, max(0.25, half_width_deg)))
    p, t, ds = store.day(date)
    r, c, _ = _nearest_cell(ds, t, lat, lon)
    k = int(round(half_width_deg / abs(float(ds.latitude.values[1] - ds.latitude.values[0]))))
    r0, r1 = max(0, r - k), min(ds.sizes["latitude"], r + k + 1)
    c0, c1 = max(0, c - k), min(ds.sizes["longitude"], c + k + 1)
    sub = ds.isel(time=t, latitude=slice(r0, r1), longitude=slice(c0, c1))

    def cube(v):
        return [_grid(sub[v].values[i], 2) for i in range(core.NUM_DEPTHS)]
    return {"date": date, "center": {"lat": float(ds.latitude.values[r]), "lon": float(ds.longitude.values[c]),
                                     "row_in_subgrid": r - r0, "col_in_subgrid": c - c0},
            "lats": [float(x) for x in sub.latitude.values], "lons": [float(x) for x in sub.longitude.values],
            "depths_m": core.DEPTH_LEVELS.tolist(), "model_c": cube("pred_temp_c"), "reference_c": cube("ref_temp_c"),
            "reference_name": ds.attrs.get("reference_name")}


class SimilarRequest(BaseModel):
    date: str
    lat: float
    lon: float
    k: int = 5
    exclude_km: float = 300.0


@app.post("/api/similar")
def similar(req: SimilarRequest):
    p, t, ds = store.day(req.date)
    r, c, _ = _nearest_cell(ds, t, req.lat, req.lon)
    L = store.latents(p)
    rows, cols = ds["cell_row"].values, ds["cell_col"].values
    q_idx = int(np.nonzero((rows == r) & (cols == c))[0][0])
    q = np.asarray(L[t, q_idx], dtype=np.float32)
    q /= np.linalg.norm(q) + 1e-12
    lat_c, lon_c = ds.latitude.values[rows], ds.longitude.values[cols]
    near = _haversine_km(float(ds.latitude.values[r]), float(ds.longitude.values[c]), lat_c, lon_c) < req.exclude_km
    dates = [str(np.datetime_as_string(v, unit="D")) for v in ds["time"].values]
    best = []
    for tt in range(L.shape[0]):
        X = np.asarray(L[tt], dtype=np.float32)
        ok = np.isfinite(X).all(axis=1)
        if tt == t:
            ok &= ~near                       # the neighbourhood on the same day is trivially similar
        nrm = np.linalg.norm(X, axis=1) + 1e-12
        sim = np.where(ok, (X @ q) / nrm, -np.inf)
        top = np.argpartition(-sim, min(req.k, sim.size - 1))[: req.k]
        best += [(float(sim[i]), tt, int(i)) for i in top if np.isfinite(sim[i])]
    best = sorted(best, reverse=True)[: req.k]
    out = []
    for s, tt, i in best:
        rr, cc = int(rows[i]), int(cols[i])
        out.append({"date": dates[tt], "split": str(ds["split"].values[tt]), "lat": float(ds.latitude.values[rr]),
                    "lon": float(ds.longitude.values[cc]), "cosine_similarity": round(s, 4),
                    "distance_km": round(float(_haversine_km(float(ds.latitude.values[r]), float(ds.longitude.values[c]), ds.latitude.values[rr], ds.longitude.values[cc])), 0),
                    "model_tchp_kj_cm2": _f(ds["model_tchp_kj_cm2"].values[tt, rr, cc], 1),
                    "model_d26_m": _f(ds["model_d26_m"].values[tt, rr, cc], 1)})
    return {"query": {"date": req.date, "lat": float(ds.latitude.values[r]), "lon": float(ds.longitude.values[c])},
            "searched": f"{L.shape[0]} days × {L.shape[1]} cells in {os.path.basename(p)}",
            "excluded": f"cells within {req.exclude_km:.0f} km of the query on the same day",
            "metric": "cosine similarity of 128-D embeddings", "matches": out}


@app.get("/api/cyclones")
def cyclones():
    path = os.path.join(BASIN_DIR, "cyclone_tracks.json")
    if not os.path.exists(path):
        _missing("cyclone_tracks.json", "python fetch_cyclone_tracks.py --storm MOCHA:2023 --storm MICHAUNG:2023")
    data = json.load(open(path))
    idx = store.index()
    for tr in data["tracks"]:
        for pt in tr["points"]:
            d = pt["time"][:10]
            pt["ocean"] = None
            if d not in idx or pt["lat"] is None:
                pt["ocean_note"] = f"no inference file covers {d}"
                continue
            p, t = idx[d]
            ds = store.open(p)
            try:
                r, c, dist = _nearest_cell(ds, t, pt["lat"], pt["lon"])
            except HTTPException:
                pt["ocean_note"] = "no deep-water model cell within 111 km (shelf or land)"
                continue
            o = {"cell_lat": float(ds.latitude.values[r]), "cell_lon": float(ds.longitude.values[c]), "distance_km": round(dist, 1),
                 "model_tchp_kj_cm2": _f(ds["model_tchp_kj_cm2"].values[t, r, c], 1),
                 "ref_tchp_kj_cm2": _f(ds["ref_tchp_kj_cm2"].values[t, r, c], 1),
                 "model_d26_m": _f(ds["model_d26_m"].values[t, r, c], 1),
                 "sst_c": _f(ds["in_sst_c"].values[t, r, c], 2), "reference_name": ds.attrs.get("reference_name")}
            # Cold wake: OSTIA SST 3 days after minus 1 day before, same cell, only if both days are in the data
            import pandas as pd
            before, after = str((pd.Timestamp(d) - pd.Timedelta(days=1)).date()), str((pd.Timestamp(d) + pd.Timedelta(days=3)).date())
            if before in idx and after in idx:
                sb = store.open(idx[before][0])["in_sst_c"].values[idx[before][1], r, c]
                sa = store.open(idx[after][0])["in_sst_c"].values[idx[after][1], r, c]
                o["cold_wake_c"] = _f(sa - sb, 2)
                o["cold_wake_definition"] = f"SST {after} minus SST {before} at this cell (model input, OSTIA)"
            else:
                o["cold_wake_c"] = None
                o["cold_wake_definition"] = "needs inference files for the day before and 3 days after"
            pt["ocean"] = o
    return data


@app.get("/api/benchmarks")
def benchmarks():
    path = os.path.join(BASIN_DIR, "eval_results.json")
    if not os.path.exists(path):
        _missing("eval_results.json", "python kaggle_oceanembed_eval.py --data-dir <inputs> --ckpt-dir trained --out basin_output/eval_results.json")
    res = json.load(open(path))
    res["basin_files_skill"] = [{"file": os.path.basename(p), "reference_name": store.open(p).attrs.get("reference_name"),
                                 "input_data": store.open(p).attrs.get("input_data"),
                                 "skill": json.loads(store.open(p).attrs.get("skill_json", "{}"))} for p in store.files()]
    return res


# Science, explorer, admin and brief endpoints (role-checked)
import api_extra  # noqa: E402
api_extra.register(app, sys.modules[__name__])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
