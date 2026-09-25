"""
===============================================================================
OceanEmbed — science, data-explorer, admin and decision-brief endpoints
===============================================================================
Registered by server.py (register(app, S) with S = the server module).
Access is enforced here, server-side, from the signed token (auth.py):
  /api/science/*   scientist, admin
  /api/explorer/*  scientist, admin
  /api/brief       decision_maker, scientist, admin
  /api/admin/*     admin
All values come from the stored real fields or from physics computed on them.
===============================================================================
"""
import datetime as dt
import glob
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

import auth
import physics as ph

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.realpath(os.environ.get("OCEANEMBED_DATA_ROOT", HERE))
LOG_DIR = os.path.join(auth.STATE_DIR, "logs")
STARTED = time.time()
REQ = {"total": 0, "errors": 0, "recent": deque(maxlen=1000)}
LOGIN_FAILS = defaultdict(deque)


# =============================================================================
# ACCESS CONTROL
# =============================================================================
def current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return auth.read_token(authorization.split(" ", 1)[1])


def require(capability):
    def dep(user=Depends(current_user)):
        if user is None:
            raise HTTPException(401, detail="Sign in required.")
        if user["role"] not in auth.ACCESS[capability]:
            raise HTTPException(403, detail=f"Role '{user['role']}' cannot use {capability}.")
        return user
    return dep


def _date_ok(s):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s or ""):
        raise HTTPException(400, detail=f"bad date {s!r}")
    return s


def _path_ok(p, must_exist=False):
    rp = os.path.realpath(os.path.join(DATA_ROOT, p)) if not os.path.isabs(p) else os.path.realpath(p)
    if not (rp == DATA_ROOT or rp.startswith(DATA_ROOT + os.sep)):
        raise HTTPException(400, detail=f"path must be inside {DATA_ROOT}")
    if must_exist and not os.path.exists(rp):
        raise HTTPException(400, detail=f"{p} does not exist")
    return rp


def register(app, S):
    store = S.store

    @app.middleware("http")
    async def _stats(request: Request, call_next):
        t0 = time.perf_counter()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            REQ["total"] += 1
            if status >= 500:
                REQ["errors"] += 1
            REQ["recent"].append((request.url.path, status, (time.perf_counter() - t0) * 1000.0, time.time()))

    def day_of(date):
        p, t, ds = store.day(_date_ok(date))
        return p, t, ds

    def cell_series(dates, r, c, var):
        idx = store.index()
        out = []
        for d in dates:
            if d not in idx:
                return None
            p, t = idx[d]
            out.append(store.open(p)[var].values[t])
        return np.stack(out)

    # -------------------------------------------------------------------- auth
    class Login(BaseModel):
        username: str
        password: str

    @app.post("/api/auth/login")
    def login(body: Login, request: Request):
        ip = request.client.host if request.client else "?"
        q = LOGIN_FAILS[ip]
        while q and q[0] < time.time() - 300:
            q.popleft()
        if len(q) >= 5:
            raise HTTPException(429, detail="Too many failed sign-ins; try again in 5 minutes.")
        role = auth.verify(body.username, body.password)
        if not role:
            q.append(time.time())
            raise HTTPException(401, detail="Wrong username or password.")
        return {"token": auth.make_token(body.username, role), "username": body.username, "role": role,
                "access": sorted(k for k, v in auth.ACCESS.items() if role in v)}

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        if not user:
            return {"signed_in": False, "role": "end_user", "access": []}
        return {"signed_in": True, "username": user["sub"], "role": user["role"],
                "access": sorted(k for k, v in auth.ACCESS.items() if user["role"] in v)}

    # ================================================================= SCIENCE
    @app.get("/api/science/currents")
    def currents(date: str, drag_scheme: str = "large_pond", cd: float = 1.3e-3, stride: int = 6, user=Depends(require("science"))):
        if not 5e-4 <= cd <= 3e-3:
            raise HTTPException(400, detail="cd must be between 0.5e-3 and 3e-3")
        p, t, ds = day_of(date)
        lat, lon = ds.latitude.values.astype(float), ds.longitude.values.astype(float)
        day = ds.isel(time=t)
        ssh, uo, vo = (day[v].values.astype(float) for v in ("in_ssh_m", "in_uo_ms", "in_vo_ms"))
        u10, v10 = day["in_u10_ms"].values.astype(float), day["in_v10_ms"].values.astype(float)
        ug, vg = ph.geostrophic_currents(ssh, lat, lon)
        ek = ph.ekman(u10, v10, lat, lon, drag_scheme, cd)
        ok = np.isfinite(ug) & np.isfinite(vg) & np.isfinite(uo) & np.isfinite(vo)
        stats = None
        if ok.sum() > 10:
            stats = {"n_cells": int(ok.sum()),
                     "corr_u": float(np.corrcoef(ug[ok], uo[ok])[0, 1]), "corr_v": float(np.corrcoef(vg[ok], vo[ok])[0, 1]),
                     "rms_obs_speed_ms": float(np.sqrt(np.mean(uo[ok] ** 2 + vo[ok] ** 2))),
                     "rms_geo_speed_ms": float(np.sqrt(np.mean(ug[ok] ** 2 + vg[ok] ** 2))),
                     "rms_vector_diff_ms": float(np.sqrt(np.mean((ug[ok] - uo[ok]) ** 2 + (vg[ok] - vo[ok]) ** 2)))}
        sl = (slice(None, None, stride), slice(None, None, stride))

        def arrows(u, v):
            LA, LO = np.meshgrid(lat[sl[0]], lon[sl[1]], indexing="ij")
            uu, vv = u[sl], v[sl]
            m = np.isfinite(uu) & np.isfinite(vv)
            return {"lat": LA[m].round(3).tolist(), "lon": LO[m].round(3).tolist(), "u": uu[m].round(4).tolist(), "v": vv[m].round(4).tolist()}
        return {"date": date, **S._file_meta(ds), "lats": lat.round(3).tolist(), "lons": lon.round(3).tolist(),
                "geostrophic_speed_ms": S._grid(np.hypot(ug, vg), 3), "observed_speed_ms": S._grid(np.hypot(uo, vo), 3),
                "ekman_pumping_m_per_day": S._grid(ek["w_ekman_m_per_day"], 3), "wind_stress_n_m2": S._grid(np.hypot(ek["taux"], ek["tauy"]), 4),
                "arrows": {"geostrophic": arrows(ug, vg), "observed": arrows(uo, vo), "ekman_transport": arrows(ek["mx"], ek["my"])},
                "comparison": stats,
                "method": {"geostrophic": "u=-(g/f)∂η/∂y, v=(g/f)∂η/∂x from CMEMS zos on the 0.25° grid (central differences)",
                           "observed": "CMEMS GLO12 surface current (model input)",
                           "ekman": f"τ=ρa·Cd·|U|U (ρa={ph.RHO_AIR}, Cd={'Large & Pond 1981' if drag_scheme == 'large_pond' else cd}); "
                                    "M=τ×k/(ρ0 f); w_E=curl(τ/f)/ρ0, positive = upwelling. Daily ERA5 12:00 UTC winds.",
                           "note": "Geostrophy excludes wind-driven (Ekman) and ageostrophic flow, so it differs from the total surface current."}}

    class DriftReq(BaseModel):
        date: str
        lat: float
        lon: float
        days: float = Field(3, ge=0.25, le=10)
        n_particles: int = Field(100, ge=1, le=1000)
        spread_km: float = Field(5, ge=0, le=100)
        diffusivity_m2s: float = Field(10, ge=0, le=1000)
        windage: float = Field(0.0, ge=0, le=0.05)
        dt_hours: float = Field(1.0, ge=0.25, le=6)
        seed: int = 0

    @app.post("/api/science/drift")
    def drift(req: DriftReq, user=Depends(require("science"))):
        start = pd.Timestamp(_date_ok(req.date))
        n_fields = int(np.ceil(req.days)) + 1
        dates = [str((start + pd.Timedelta(days=k)).date()) for k in range(n_fields)]
        idx = store.index()
        missing = [d for d in dates if d not in idx]
        if missing:
            raise HTTPException(404, detail={"message": f"Drift over {req.days} days needs daily currents for {dates[0]}..{dates[-1]}; missing {missing}."})
        ds0 = store.open(idx[dates[0]][0])
        lat, lon = ds0.latitude.values.astype(float), ds0.longitude.values.astype(float)
        g = lambda v: np.stack([store.open(idx[d][0])[v].values[idx[d][1]] for d in dates]).astype(float)  # noqa: E731
        u, v = g("in_uo_ms"), g("in_vo_ms")
        u10, v10 = (g("in_u10_ms"), g("in_v10_ms")) if req.windage > 0 else (None, None)
        hours = 12.0 + 24.0 * np.arange(n_fields)          # daily means, valid at mid-day
        out = ph.drift(u, v, hours, lat, lon, req.lat, req.lon, 12.0, req.days * 24.0, req.dt_hours, req.n_particles,
                       req.spread_km, req.diffusivity_m2s, req.windage, u10, v10, req.seed)
        stride = max(1, int(round(3 / req.dt_hours)))
        la, lo = out["lat"][::stride], out["lon"][::stride]
        fin_la, fin_lo = out["lat"][-1], out["lon"][-1]
        disp = ph.haversine_km(out["lat"][0], out["lon"][0], fin_la, fin_lo)
        cla, clo = float(np.mean(fin_la)), float(np.mean(fin_lo))
        spread = ph.haversine_km(cla, clo, fin_la, fin_lo)
        return {"start": {"date": req.date, "lat": req.lat, "lon": req.lon}, "hours": out["hours"][::stride].tolist(),
                "lat": np.round(la, 4).tolist(), "lon": np.round(lo, 4).tolist(), "status": out["status"],
                "summary": {"mean_displacement_km": round(float(np.mean(disp)), 2), "centroid": [round(cla, 3), round(clo, 3)],
                            "rms_spread_km": round(float(np.sqrt(np.mean(spread ** 2))), 2),
                            "stopped_fraction": round(float(np.mean([s != "active" for s in out["status"]])), 3)},
                "method": "RK4 on CMEMS GLO12 daily-mean surface currents (bilinear in space, linear in time), "
                          f"windage {req.windage:.3f}×U10 (ERA5), random walk K={req.diffusivity_m2s} m²/s, seed {req.seed}. "
                          "Surface currents only; no Stokes drift or tides."}

    class PWPReq(BaseModel):
        date: str
        lat: float
        lon: float
        days: int = Field(3, ge=1, le=10)
        forcing: str = "era5"            # era5 | constant
        wind_speed_ms: float = Field(20.0, ge=0, le=70)
        wind_toward_deg: float = 0.0
        heat_flux_wm2: float = Field(0.0, ge=-1500, le=1500)
        initial: str = "model"           # model | reference
        rb_crit: float = Field(0.65, ge=0.1, le=2.0)
        rg_crit: float = Field(0.25, ge=0.05, le=1.0)
        drag_scheme: str = "large_pond"
        cd: float = Field(1.3e-3, ge=5e-4, le=3e-3)

    @app.post("/api/science/pwp")
    def pwp_run(req: PWPReq, user=Depends(require("science"))):
        p, t, ds = day_of(req.date)
        r, c, dist = S._nearest_cell(ds, t, req.lat, req.lon)
        clat, clon = float(ds.latitude.values[r]), float(ds.longitude.values[c])
        T0 = ds["pred_temp_c" if req.initial == "model" else "ref_temp_c"].values[t, :, r, c].astype(float)
        if "ref_so_psu" in ds:
            S0, s_note = ds["ref_so_psu"].values[t, :, r, c].astype(float), f"{ds.attrs.get('reference_name')} salinity profile"
        else:
            S0, s_note = float(ds["in_sss"].values[t, r, c]), "uniform, equal to the surface salinity input"
        start = pd.Timestamp(req.date)
        dates = [str((start + pd.Timedelta(days=k)).date()) for k in range(req.days + 1)]
        idx = store.index()
        if req.forcing == "era5":
            miss = [d for d in dates if d not in idx]
            if miss:
                raise HTTPException(404, detail={"message": f"ERA5 forcing needs inference files for {dates[0]}..{dates[-1]}; missing {miss}."})
            uw = [float(store.open(idx[d][0])["in_u10_ms"].values[idx[d][1], r, c]) for d in dates]
            vw = [float(store.open(idx[d][0])["in_v10_ms"].values[idx[d][1], r, c]) for d in dates]
            fh = 24.0 * np.arange(len(dates))
            f_note = "ERA5 10 m wind at 12:00 UTC each day at this cell, linearly interpolated in time (daily snapshots under-resolve storm peaks)"
        else:
            th = np.radians(req.wind_toward_deg)
            uw, vw = [req.wind_speed_ms * np.sin(th)] * 2, [req.wind_speed_ms * np.cos(th)] * 2
            fh = np.array([0.0, 24.0 * req.days])
            f_note = f"constant {req.wind_speed_ms} m/s toward {req.wind_toward_deg}° (what-if)"
        t0 = time.perf_counter()
        out = ph.pwp(T0, S0, S.core.DEPTH_LEVELS, clat, clon, fh, uw, vw, req.heat_flux_wm2, rb_crit=req.rb_crit,
                     rg_crit=req.rg_crit, drag_scheme=req.drag_scheme, cd=req.cd)
        obs = None
        if dates[0] in idx and dates[-1] in idx:
            s0 = store.open(idx[dates[0]][0])["in_sst_c"].values[idx[dates[0]][1], r, c]
            s1 = store.open(idx[dates[-1]][0])["in_sst_c"].values[idx[dates[-1]][1], r, c]
            obs = {"observed_dsst_c": S._f(s1 - s0, 3), "from": dates[0], "to": dates[-1], "source": "OSTIA SST (model input)"}
        k = slice(None, None, 2)
        return {"cell": {"lat": clat, "lon": clon, "distance_km": round(dist, 1)},
                "series": {"hours": out["hours"].round(2).tolist(), "sst_c": out["sst_c"].round(4).tolist(),
                           "mld_m": out["mld_m"].round(1).tolist(), "wind_stress_n_m2": out["tau_n_m2"].round(4).tolist()},
                "profile": {"z_m": out["z_m"][k].round(1).tolist(), "initial_c": np.round(out["T_initial_c"][k], 3).tolist(),
                            "final_c": np.round(out["T_final_c"][k], 3).tolist()},
                "simulated_dsst_c": round(float(out["sst_c"][-1] - out["sst_c"][0]), 3), "observed": obs,
                "runtime_s": round(time.perf_counter() - t0, 2),
                "settings": req.model_dump(),
                "method": {"model": "PWP (Price, Weller & Pinkel 1986): static, bulk-Ri and gradient-Ri mixing with inertial rotation; TEOS-10 density",
                           "initial_temperature": f"{'OceanEmbed prediction' if req.initial == 'model' else ds.attrs.get('reference_name')} at this cell",
                           "salinity": s_note, "forcing": f_note, "heat_flux": f"{req.heat_flux_wm2} W/m² into the ocean (user setting)",
                           "limits": "1-D: no horizontal advection or Ekman upwelling, which add to cooling under real cyclones."}}

    @app.get("/api/science/stratification")
    def strat(date: str, lat: float, lon: float, source: str = "reference", user=Depends(require("science"))):
        p, t, ds = day_of(date)
        r, c, dist = S._nearest_cell(ds, t, lat, lon)
        clat, clon = float(ds.latitude.values[r]), float(ds.longitude.values[c])
        pt = ds["ref_temp_c" if source == "reference" else "pred_temp_c"].values[t, :, r, c].astype(float)
        has_s = "ref_so_psu" in ds
        sp = ds["ref_so_psu"].values[t, :, r, c].astype(float) if has_s else np.full(15, float(ds["in_sss"].values[t, r, c]))
        u = v = None
        if "ref_uo_ms" in ds and source == "reference":
            u, v = ds["ref_uo_ms"].values[t, :, r, c].astype(float), ds["ref_vo_ms"].values[t, :, r, c].astype(float)
        s = ph.stratification(pt, sp, S.core.DEPTH_LEVELS, clat, clon, u, v)
        J = lambda a, d=4: [None if not np.isfinite(x) else round(float(x), d) for x in a]  # noqa: E731
        return {"cell": {"lat": clat, "lon": clon, "distance_km": round(dist, 1)}, "source": source,
                "depth_m": S.core.DEPTH_LEVELS.tolist(), "pt_c": J(pt, 3), "sp_psu": J(sp, 3),
                "rho_kg_m3": J(s["rho_kg_m3"], 3), "sigma0_kg_m3": J(s["sigma0_kg_m3"], 3), "sound_speed_ms": J(s["sound_speed_ms"], 2),
                "z_mid_m": J(s["z_mid_m"], 1), "n2_s2": [None if not np.isfinite(x) else float(f"{x:.4e}") for x in s["n2_s2"]],
                "ri": None if "ri" not in s else [None if not np.isfinite(x) else round(float(x), 3) for x in s["ri"]],
                "u_ms": J(u) if u is not None else None, "v_ms": J(v) if v is not None else None,
                "notes": {"salinity": "reference salinity profile" if has_s else "no salinity profile in this file: uniform surface salinity used",
                          "ri": "Ri = N²/(∂u/∂z²+∂v/∂z²) from reference currents on the standard levels; Ri < 0.25 marks shear instability"
                                if u is not None else "no velocity profile for this source, so Ri is not computed",
                          "equation_of_state": "TEOS-10 (gsw): SA from SP, CT from potential temperature"}}

    class OIReq(BaseModel):
        date: str
        depth_m: float = 100
        window_days: int = Field(5, ge=0, le=15)
        length_km: float = Field(150, ge=10, le=1000)
        sigma_b: float = Field(0.8, ge=0.01, le=10)
        sigma_o: float = Field(0.3, ge=0.01, le=10)

    @app.post("/api/science/assimilate")
    def assimilate(req: OIReq, user=Depends(require("science"))):
        files = sorted(glob.glob(os.path.join(S.BASIN_DIR, "argo_profiles_*.nc")))
        if not files:
            S._missing("Argo profile files", "pip install argopy && python fetch_argo_profiles.py --start <YYYY-MM-DD> --end <YYYY-MM-DD>")
        levels = S.core.DEPTH_LEVELS
        if req.depth_m not in levels:
            raise HTTPException(400, detail=f"depth must be one of {levels.tolist()}")
        k = int(np.where(levels == req.depth_m)[0][0])
        p, t, ds = day_of(req.date)
        import xarray as xr
        d0 = pd.Timestamp(req.date)
        rows = []
        for f in files:
            with xr.open_dataset(f) as a:
                tt = pd.to_datetime(a["time"].values)
                sel = np.abs((tt - d0) / pd.Timedelta(days=1)) <= req.window_days + 0.5
                for i in np.nonzero(sel)[0]:
                    val = float(a["pt_c"].values[i, k])
                    if np.isfinite(val):
                        rows.append((float(a.latitude.values[i]), float(a.longitude.values[i]), val, int(a.platform.values[i]), str(tt[i].date()),
                                     str(a.attrs.get("fixture", ""))))
        if not rows:
            raise HTTPException(404, detail={"message": f"No Argo values at {req.depth_m} m within ±{req.window_days} days of {req.date}."})
        bg = ds["pred_temp_c"].values[t, k].astype(float)
        lat, lon = ds.latitude.values.astype(float), ds.longitude.values.astype(float)
        res = ph.optimal_interpolation(bg, lat, lon, [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows],
                                       req.length_km, req.sigma_b, req.sigma_o)
        obs_tbl = [{"lat": round(a, 3), "lon": round(b, 3), "value_c": round(v, 3), "background_c": round(float(h), 3),
                    "innovation_c": round(float(dd), 3), "loo_residual_c": round(float(l), 3)}
                   for a, b, v, h, dd, l in zip(res["obs_lat"], res["obs_lon"], res["obs_val"], res["bg_at_obs"], res["innovation"], res["loo_residual"])]
        return {"date": req.date, "depth_m": req.depth_m, "lats": lat.round(3).tolist(), "lons": lon.round(3).tolist(),
                "analysis_c": S._grid(res["analysis"], 2), "increment_c": S._grid(res["increment"], 3), "observations": obs_tbl,
                "stats": {"n_obs": res["n_obs"], "rmse_background_c": round(res["rmse_background_c"], 4),
                          "bias_background_c": round(res["bias_background_c"], 4), "rmse_loo_analysis_c": round(res["rmse_loo_analysis_c"], 4)},
                "synthetic_obs": any(r[5] == "synthetic" for r in rows),
                "method": f"Optimal interpolation, Gaussian background covariance (L={req.length_km} km, σb={req.sigma_b} °C), "
                          f"observation error σo={req.sigma_o} °C, Argo potential temperature within ±{req.window_days} days. "
                          "Skill = exact leave-one-out: each float predicted by the analysis built without it."}

    @app.get("/api/science/xgb")
    def xgb_metrics(user=Depends(require("science"))):
        f = os.path.join(S.BASIN_DIR, "xgb_baseline.json")
        if not os.path.exists(f):
            S._missing("xgb_baseline.json", "python train_xgb_baseline.py --basin basin_output/basin_<training range>.nc")
        return json.load(open(f))

    # ================================================================ EXPLORER
    SHA = {}

    def sha256(path):
        key = (path, os.path.getmtime(path))
        if key not in SHA:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            SHA[key] = h.hexdigest()
        return SHA[key]

    def data_files():
        dirs = {os.path.realpath(S.BASIN_DIR)}
        for d in os.environ.get("OCEANEMBED_DATA_DIRS", "").split(os.pathsep):
            if d:
                dirs.add(os.path.realpath(d))
        for d in glob.glob(os.path.join(DATA_ROOT, "*")):
            if os.path.isdir(d) and glob.glob(os.path.join(d, "OSTIA_SST.nc")):
                dirs.add(os.path.realpath(d))
            for sub in glob.glob(os.path.join(d, "*")):
                if os.path.isdir(sub) and glob.glob(os.path.join(sub, "OSTIA_SST.nc")):
                    dirs.add(os.path.realpath(sub))
        files = []
        for d in sorted(dirs):
            files += sorted(glob.glob(os.path.join(d, "*.nc")) + glob.glob(os.path.join(d, "*.json")))
        return files

    def describe(path, with_hash=True):
        import xarray as xr
        st = os.stat(path)
        info = {"path": path, "name": os.path.basename(path), "folder": os.path.dirname(path), "size_mb": round(st.st_size / 1e6, 2),
                "modified_utc": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(timespec="seconds")}
        if with_hash:
            info["sha256"] = sha256(path)
        if path.endswith(".json"):
            info["kind"] = "json"
            return info
        try:
            with store._lock, xr.open_dataset(path) as d:
                info["kind"] = "netcdf"
                info["dims"] = {k: int(v) for k, v in d.sizes.items()}
                info["variables"] = [{"name": n, "dims": list(v.dims), "units": v.attrs.get("units"), "long_name": v.attrs.get("long_name")} for n, v in d.data_vars.items()]
                info["attrs"] = {k: (str(v)[:500]) for k, v in d.attrs.items() if not k.endswith("_json")}
                for tn in ("time", "valid_time"):
                    if tn in d.coords or tn in d.variables:
                        tv = pd.to_datetime(d[tn].values)
                        info["time_coverage"] = [str(tv.min()), str(tv.max()), int(tv.size)]
                        break
                info["readable"] = True
        except Exception as e:
            info["readable"] = False
            info["error"] = str(e)[:300]
        return info

    @app.get("/api/explorer/files")
    def files(with_hash: bool = False, user=Depends(require("explorer"))):
        return {"data_root": DATA_ROOT, "files": [describe(f, with_hash) for f in data_files()]}

    @app.get("/api/explorer/file")
    def one_file(path: str, user=Depends(require("explorer"))):
        rp = _path_ok(path, must_exist=True)
        if rp not in [os.path.realpath(f) for f in data_files()]:
            raise HTTPException(404, detail="not a listed data file")
        return describe(rp, True)

    SERIES_VARS = {"pred_temp_c": True, "ref_temp_c": True, "ref_so_psu": True, "ref_uo_ms": True, "ref_vo_ms": True}

    @app.get("/api/explorer/series")
    def series(lat: float, lon: float, var: str, depth_m: float = 0, fmt: str = "json", user=Depends(require("explorer"))):
        idx = store.index()
        if not idx:
            S._missing("No basin inference files", "python basin_inference.py ...")
        rows = []
        for d in sorted(idx):
            p, t = idx[d]
            ds = store.open(p)
            if var not in ds:
                continue
            try:
                r, c, dist = S._nearest_cell(ds, t, lat, lon)
            except HTTPException:
                continue
            if SERIES_VARS.get(var):
                levels = list(ds.depth.values.astype(float))
                if depth_m not in levels:
                    raise HTTPException(400, detail=f"depth_m must be one of {levels}")
                val = ds[var].values[t, levels.index(depth_m), r, c]
            else:
                val = ds[var].values[t, r, c]
            rows.append({"date": d, "value": S._f(val, 4), "cell_lat": float(ds.latitude.values[r]), "cell_lon": float(ds.longitude.values[c]),
                         "distance_km": round(dist, 1), "split": str(ds["split"].values[t]), "file": os.path.basename(p)})
        if not rows:
            raise HTTPException(404, detail=f"variable {var} not found near {lat},{lon}")
        units = store.open(store.index()[rows[0]["date"]][0])[var].attrs.get("units", "")
        if fmt == "csv":
            df = pd.DataFrame(rows)
            return PlainTextResponse(f"# variable={var} units={units} depth_m={depth_m if SERIES_VARS.get(var) else 'n/a'}\n" + df.to_csv(index=False),
                                     media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{var}_{lat}_{lon}.csv"'})
        return {"variable": var, "units": units, "depth_m": depth_m if SERIES_VARS.get(var) else None, "rows": rows}

    @app.get("/api/explorer/variables")
    def variables(user=Depends(require("explorer"))):
        idx = store.index()
        if not idx:
            return []
        ds = store.open(store.index()[sorted(idx)[0]][0])
        return [{"name": n, "units": v.attrs.get("units"), "long_name": v.attrs.get("long_name"), "has_depth": "depth" in v.dims}
                for n, v in ds.data_vars.items() if "time" in v.dims and ("latitude" in v.dims)]

    @app.get("/api/explorer/profile")
    def profile(date: str, lat: float, lon: float, fmt: str = "json", user=Depends(require("explorer"))):
        p, t, ds = day_of(date)
        r, c, dist = S._nearest_cell(ds, t, lat, lon)
        clat, clon = float(ds.latitude.values[r]), float(ds.longitude.values[c])
        cols = {"depth_m": S.core.DEPTH_LEVELS}
        for v in ("pred_temp_c", "ref_temp_c", "ref_so_psu", "ref_uo_ms", "ref_vo_ms"):
            if v in ds:
                cols[v] = ds[v].values[t, :, r, c].astype(float)
        sp = cols.get("ref_so_psu", np.full(15, float(ds["in_sss"].values[t, r, c])))
        st = ph.stratification(cols["ref_temp_c"], sp, S.core.DEPTH_LEVELS, clat, clon)
        cols["ref_sigma0_kg_m3"] = st["sigma0_kg_m3"]
        cols["ref_sound_speed_ms"] = st["sound_speed_ms"]
        df = pd.DataFrame(cols)
        meta = {"date": date, "cell_lat": clat, "cell_lon": clon, "source_file": os.path.basename(p),
                "reference": ds.attrs.get("reference_name"), "input_data": ds.attrs.get("input_data"),
                "salinity_for_density": "reference profile" if "ref_so_psu" in ds else "uniform surface salinity"}
        if fmt == "csv":
            head = "".join(f"# {k}={v}\n" for k, v in meta.items())
            return PlainTextResponse(head + df.to_csv(index=False), media_type="text/csv",
                                     headers={"Content-Disposition": f'attachment; filename="profile_{date}_{clat}_{clon}.csv"'})
        if fmt == "nc":
            import xarray as xr
            x = xr.Dataset({k: (("depth",), v) for k, v in cols.items() if k != "depth_m"}, coords={"depth": cols["depth_m"]}, attrs=meta)
            return Response(x.to_netcdf(), media_type="application/x-netcdf",
                            headers={"Content-Disposition": f'attachment; filename="profile_{date}_{clat}_{clon}.nc"'})
        return {**meta, "columns": {k: [None if not np.isfinite(x) else round(float(x), 4) for x in v] for k, v in cols.items()}}

    # =================================================================== ADMIN
    def jobs_db():
        con = sqlite3.connect(os.path.join(auth.STATE_DIR, "oceanembed.db"))
        con.execute("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, args TEXT, user TEXT, status TEXT, "
                    "rc INTEGER, created REAL, started REAL, finished REAL, log TEXT)")
        return con

    def build_argv(kind, a):
        py = [sys.executable]
        if kind == "fetch_period":
            if a.get("mode") not in ("reanalysis", "nrt"):
                raise HTTPException(400, detail="mode must be reanalysis or nrt")
            return py + ["fetch_period.py", "--mode", a["mode"], "--start", _date_ok(a.get("start")), "--end", _date_ok(a.get("end")),
                         "--out-dir", _path_ok(a.get("out_dir", f"data_{a.get('start')}_{a.get('end')}"))]
        if kind == "basin_inference":
            argv = py + ["basin_inference.py", "--data-dir", _path_ok(a.get("data_dir", ""), True), "--start", _date_ok(a.get("start")),
                         "--end", _date_ok(a.get("end"))]
            if a.get("frozen_stats", True):
                argv += ["--stats-json", os.path.join(S.BASIN_DIR, "normalisation_stats.json")]
            if a.get("reference_file"):
                if not re.fullmatch(r"[A-Za-z0-9_.-]+\.nc", a["reference_file"]):
                    raise HTTPException(400, detail="bad reference_file")
                argv += ["--reference-file", a["reference_file"], "--reference-name", str(a.get("reference_name", "reference"))[:80]]
            return argv + ["--out", os.path.join(S.BASIN_DIR, f"basin_{a['start']}_{a['end']}.nc")]
        if kind == "realtime_update":
            return py + ["realtime_update.py"]
        if kind == "evaluate":
            return py + ["kaggle_oceanembed_eval.py", "--data-dir", _path_ok(a.get("data_dir", ""), True), "--start", _date_ok(a.get("start")),
                         "--end", _date_ok(a.get("end")), "--ckpt-dir", os.path.join(HERE, "trained"), "--out", os.path.join(S.BASIN_DIR, "eval_results.json")]
        if kind == "cyclone_tracks":
            storms = a.get("storms") or []
            if not storms or not all(re.fullmatch(r"[A-Za-z]+:\d{4}", s) for s in storms):
                raise HTTPException(400, detail="storms must look like NAME:YYYY")
            return py + ["fetch_cyclone_tracks.py"] + sum((["--storm", s] for s in storms), []) + ["--out", os.path.join(S.BASIN_DIR, "cyclone_tracks.json")]
        if kind == "argo_profiles":
            return py + ["fetch_argo_profiles.py", "--start", _date_ok(a.get("start")), "--end", _date_ok(a.get("end"))]
        if kind == "xgb_baseline":
            return py + ["train_xgb_baseline.py", "--basin", _path_ok(a.get("basin_file", ""), True), "--out", os.path.join(S.BASIN_DIR, "xgb_baseline.json")]
        raise HTTPException(400, detail=f"unknown job kind {kind}")

    def alert(payload):
        url = os.environ.get("OCEANEMBED_ALERT_WEBHOOK")
        if not url:
            return
        import urllib.request
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=10)
        except Exception:
            pass

    def run_job(job_id, argv, log_path):
        with jobs_db() as con:
            con.execute("UPDATE jobs SET status='running', started=? WHERE id=?", (time.time(), job_id))
        with open(log_path, "w") as lf:
            lf.write("$ " + " ".join(argv) + "\n")
            lf.flush()
            try:
                rc = subprocess.call(argv, cwd=HERE, stdout=lf, stderr=subprocess.STDOUT)
            except Exception as e:
                lf.write(f"\n[launcher error] {e}\n")
                rc = -1
        status = "succeeded" if rc == 0 else "failed"
        with jobs_db() as con:
            con.execute("UPDATE jobs SET status=?, rc=?, finished=? WHERE id=?", (status, rc, time.time(), job_id))
        if rc != 0:
            alert({"event": "job_failed", "job_id": job_id, "argv": argv, "rc": rc})

    class JobReq(BaseModel):
        kind: str
        args: dict = Field(default_factory=dict)

    @app.post("/api/admin/jobs")
    def submit(req: JobReq, user=Depends(require("admin"))):
        argv = build_argv(req.kind, req.args)
        with jobs_db() as con:
            running = con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if running >= 2:
                raise HTTPException(429, detail="Two jobs are already running; wait for one to finish.")
            cur = con.execute("INSERT INTO jobs (kind,args,user,status,created) VALUES (?,?,?,?,?)",
                              (req.kind, json.dumps(req.args), user["sub"], "queued", time.time()))
            job_id = cur.lastrowid
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, f"job_{job_id}.log")
        with jobs_db() as con:
            con.execute("UPDATE jobs SET log=? WHERE id=?", (log_path, job_id))
        threading.Thread(target=run_job, args=(job_id, argv, log_path), daemon=True).start()
        return {"id": job_id, "argv": argv}

    @app.get("/api/admin/jobs")
    def jobs(user=Depends(require("admin"))):
        with jobs_db() as con:
            rows = con.execute("SELECT id,kind,args,user,status,rc,created,started,finished FROM jobs ORDER BY id DESC LIMIT 100").fetchall()
        return [dict(zip(["id", "kind", "args", "user", "status", "rc", "created", "started", "finished"], r)) for r in rows]

    @app.get("/api/admin/jobs/{job_id}/log")
    def job_log(job_id: int, tail: int = 200, user=Depends(require("admin"))):
        with jobs_db() as con:
            row = con.execute("SELECT log FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or not row[0] or not os.path.exists(row[0]):
            raise HTTPException(404, detail="no log")
        lines = open(row[0], errors="replace").read().splitlines()
        return {"id": job_id, "lines": lines[-max(1, min(tail, 5000)):]}

    class UserReq(BaseModel):
        username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
        password: str = Field(min_length=8)
        role: str

    @app.get("/api/admin/users")
    def users(user=Depends(require("admin"))):
        return auth.list_users()

    @app.post("/api/admin/users")
    def add_user(req: UserReq, user=Depends(require("admin"))):
        try:
            auth.add_user(req.username, req.password, req.role)
        except ValueError as e:
            raise HTTPException(400, detail=str(e))
        return {"ok": True}

    @app.delete("/api/admin/users/{username}")
    def del_user(username: str, user=Depends(require("admin"))):
        if username == user["sub"]:
            raise HTTPException(400, detail="You cannot delete your own account.")
        auth.delete_user(username)
        return {"ok": True}

    @app.get("/api/admin/feeds")
    def feeds(user=Depends(require("admin"))):
        alerts = []
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        inputs = []
        for f in data_files():
            if not f.endswith(".nc") or os.path.basename(f).startswith(("basin_", "argo_profiles", "_")):
                continue
            info = describe(f, with_hash=False)
            a = info.get("attrs", {})
            inputs.append({"file": info["name"], "folder": info["folder"], "readable": info.get("readable"), "error": info.get("error"),
                           "time_coverage": info.get("time_coverage"), "processing_level": a.get("processing_level"),
                           "source": a.get("oceanembed_source") or a.get("title"), "downloaded_utc": a.get("oceanembed_downloaded_utc"),
                           "synthetic": a.get("fixture") == "synthetic", "size_mb": info["size_mb"]})
            if not info.get("readable"):
                alerts.append({"level": "error", "message": f"{f} is unreadable or corrupted: {info.get('error')}"})
        basins = []
        for pth in store.files():
            ds = store.open(pth)
            meta = S._file_meta(ds)
            sp = pd.Series(ds["split"].values).value_counts().to_dict()
            tv = pd.to_datetime(ds["time"].values)
            basins.append({"file": os.path.basename(pth), "range": [str(tv.min().date()), str(tv.max().date())], "days": int(tv.size),
                           "splits": {k: int(v) for k, v in sp.items()}, **meta})
            if not meta["checkpoint_matches_server"]:
                alerts.append({"level": "warning", "message": f"{os.path.basename(pth)} was made with a different checkpoint; re-run basin_inference.py"})
            if "SYNTHETIC" in str(meta["input_data"]).upper():
                alerts.append({"level": "warning", "message": f"{os.path.basename(pth)} is a synthetic test fixture"})
        nrt = [b for b in basins if b["file"].startswith("basin_nrt_")]
        if nrt:
            latest = max(pd.Timestamp(b["range"][1]) for b in nrt)
            lag = int((today - latest).days)
            if lag > 9:
                alerts.append({"level": "error", "message": f"Near-real-time data is {lag} days old (expected about 6). Check realtime_update.py."})
            nrt_status = {"latest_date": str(latest.date()), "lag_days": lag}
        else:
            nrt_status = {"latest_date": None, "lag_days": None, "note": "realtime_update.py has not produced any file yet"}
        artefacts = {}
        for name in ("eval_results.json", "cyclone_tracks.json", "xgb_baseline.json", "normalisation_stats.json"):
            fp = os.path.join(S.BASIN_DIR, name)
            artefacts[name] = {"present": os.path.exists(fp),
                               "modified_utc": dt.datetime.fromtimestamp(os.path.getmtime(fp), dt.timezone.utc).isoformat(timespec="seconds") if os.path.exists(fp) else None}
            if not os.path.exists(fp):
                alerts.append({"level": "info", "message": f"{name} is missing"})
        with jobs_db() as con:
            failed = con.execute("SELECT id, kind, finished FROM jobs WHERE status='failed' AND finished > ?", (time.time() - 7 * 86400,)).fetchall()
        for jid, kind, fin in failed:
            alerts.append({"level": "error", "message": f"Job {jid} ({kind}) failed; see its log"})
        return {"inputs": inputs, "basin_files": basins, "near_real_time": nrt_status, "artefacts": artefacts, "alerts": alerts}

    @app.get("/api/admin/health")
    def health(user=Depends(require("admin"))):
        import psutil
        proc = psutil.Process()
        recent = list(REQ["recent"])
        by = defaultdict(list)
        for path, status, ms, _ in recent:
            key = "/".join(path.split("/")[:4])
            by[key].append(ms)
        routes = [{"route": k, "n": len(v), "p50_ms": round(float(np.percentile(v, 50)), 1), "p95_ms": round(float(np.percentile(v, 95)), 1)}
                  for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))]
        cached = [{"file": os.path.basename(p), "mb_in_memory": round(ds.nbytes / 1e6, 1)} for p, (_, ds) in store._cache.items()]
        du = psutil.disk_usage(S.BASIN_DIR if os.path.exists(S.BASIN_DIR) else HERE)
        vm = psutil.virtual_memory()
        return {"uptime_s": int(time.time() - STARTED), "cpu_percent": psutil.cpu_percent(interval=0.2), "cpu_count": psutil.cpu_count(),
                "memory": {"total_gb": round(vm.total / 1e9, 2), "used_percent": vm.percent, "process_rss_mb": round(proc.memory_info().rss / 1e6, 1)},
                "disk": {"total_gb": round(du.total / 1e9, 1), "used_percent": du.percent, "path": S.BASIN_DIR},
                "requests": {"total": REQ["total"], "server_errors": REQ["errors"], "window": len(recent), "routes": routes},
                "cache": {"hits": store.hits, "misses": store.misses, "files": cached},
                "model": {"device": str(S.device), "checkpoint_sha256": S.CHECKPOINT_SHA}}

    # =================================================================== BRIEF
    @app.get("/api/brief")
    def brief(date: Optional[str] = None, user=Depends(require("brief"))):
        idx = store.index()
        if not idx:
            S._missing("No basin inference files", "python basin_inference.py ...")
        date = date or sorted(idx)[-1]
        p, t, ds = day_of(date)
        lat, lon = ds.latitude.values.astype(float), ds.longitude.values.astype(float)
        dphi, dlam = np.radians(abs(lat[1] - lat[0])), np.radians(abs(lon[1] - lon[0]))
        area = ((ph.R_EARTH / 1e3) ** 2 * dphi * dlam * np.cos(np.radians(lat)))[:, None] * np.ones((1, lon.size))
        tm = ds["model_tchp_kj_cm2"].values[t].astype(float)
        tr = ds["ref_tchp_kj_cm2"].values[t].astype(float)
        valid = np.isfinite(tm)

        def area_ge(a, th):
            return float(np.nansum(np.where(a >= th, area, 0.0)))
        hi_m, hi_r = tm >= 50, tr >= 50
        inter = float(np.sum(area[hi_m & hi_r]))
        union = float(np.sum(area[hi_m | hi_r]))
        # hotspots: greedy top cells at least 300 km apart
        order = np.argsort(np.where(valid, -tm, np.inf), axis=None)
        spots = []
        for flat in order:
            i, j = np.unravel_index(flat, tm.shape)
            if not valid[i, j] or len(spots) >= 5:
                break
            if all(ph.haversine_km(lat[i], lon[j], s["lat"], s["lon"]) >= 300 for s in spots):
                spots.append({"lat": float(lat[i]), "lon": float(lon[j]), "model_tchp_kj_cm2": round(float(tm[i, j]), 1),
                              "ref_tchp_kj_cm2": S._f(tr[i, j], 1), "model_d26_m": S._f(ds["model_d26_m"].values[t, i, j], 1)})
        # anomaly relative to the mean of the days in this file (not a climatology)
        all_t = ds["model_tchp_kj_cm2"].values.astype(float)
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                mean_t = np.nanmean(all_t, axis=0)
        anom = tm - mean_t
        z = ds["in_max_abs_z"].values[t]
        frac_ood = float(np.mean(z[valid] > 4)) if valid.any() else None
        tracks_near = []
        tf = os.path.join(S.BASIN_DIR, "cyclone_tracks.json")
        if os.path.exists(tf):
            d0 = pd.Timestamp(date)
            for tr_ in json.load(open(tf))["tracks"]:
                pts = [q for q in tr_["points"] if abs((pd.Timestamp(q["time"]) - d0).total_seconds()) <= 86400]
                if pts:
                    last = pts[-1]
                    tracks_near.append({"name": tr_["name"], "season": tr_["season"], "time": last["time"], "lat": last["lat"], "lon": last["lon"],
                                        "wmo_wind_kt": last["wmo_wind_kt"], "imd_grade": last["imd_grade"]})
        skill = json.loads(ds.attrs.get("skill_json", "{}"))
        split = str(ds["split"].values[t])
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        a50, a80 = area_ge(tm, 50), area_ge(tm, 80)
        lines = [f"Ocean heat able to support rapid cyclone intensification (TCHP ≥ 50 kJ/cm²) covers about {a50:,.0f} km² in the model on {date}"
                 f" ({area_ge(tr, 50):,.0f} km² in {ds.attrs.get('reference_name')}; overlap {inter / union * 100 if union else 0:.0f}%).",
                 f"TCHP ≥ 80 kJ/cm² covers about {a80:,.0f} km².",
                 f"Highest model TCHP: {spots[0]['model_tchp_kj_cm2']} kJ/cm² at {spots[0]['lat']:.2f}°N {spots[0]['lon']:.2f}°E." if spots else "No valid cells.",
                 (f"{frac_ood * 100:.0f}% of cells have inputs outside the training range (|z| > 4); treat those values with caution." if frac_ood is not None else "")]
        if tracks_near:
            lines.append("Active storms within a day: " + ", ".join(f"{s['name']} ({s['imd_grade'] or 'grade n/a'}, {s['wmo_wind_kt'] or '?'} kt) at {s['lat']:.1f}°N {s['lon']:.1f}°E" for s in tracks_near) + ".")
        return {"date": date, "split": split, **S._file_meta(ds), "data_age_days": int((today - pd.Timestamp(date)).days),
                "summary_lines": [l for l in lines if l],
                "cyclone_heat": {"area_tchp_ge50_km2": round(a50), "area_tchp_ge80_km2": round(a80), "ref_area_tchp_ge50_km2": round(area_ge(tr, 50)),
                                 "overlap_iou": round(inter / union, 3) if union else None, "hotspots": spots,
                                 "d26_median_m": S._f(np.nanmedian(ds["model_d26_m"].values[t]), 1)},
                "anomaly": {"definition": f"model TCHP minus its mean over the {all_t.shape[0]} days in {os.path.basename(p)} (not a climatology)",
                            "max_kj_cm2": S._f(np.nanmax(anom), 1), "lats": lat.round(3).tolist(), "lons": lon.round(3).tolist(),
                            "grid": S._grid(anom, 1)},
                "tchp_grid": S._grid(tm, 1),
                "input_quality": {"fraction_cells_outside_training_range": None if frac_ood is None else round(frac_ood, 3)},
                "storms_near_date": tracks_near, "model_skill_in_file": skill}
