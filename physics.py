"""
===============================================================================
OceanEmbed — physics modules (all driven by the stored real fields)
===============================================================================
1. Geostrophic surface currents from sea-surface height
2. Wind stress, Ekman transport and Ekman pumping from ERA5 10 m winds
3. Lagrangian particle drift on CMEMS surface currents (RK4 + random walk)
4. PWP 1-D mixed-layer model (Price, Weller & Pinkel 1986) for storm mixing
5. TEOS-10 density, buoyancy frequency N², shear and gradient Richardson number
6. Optimal interpolation of a model field with in-situ observations, with exact
   leave-one-out cross-validation

Constants are the conventional values; tunable parameters are only those that
are genuinely free (drag coefficient, windage, diffusivity, PWP critical
Richardson numbers, OI error/length scales). Latitude sets the Coriolis
parameter; N² and Ri are computed, never set.
===============================================================================
"""
from __future__ import annotations

import numpy as np

G = 9.81                 # m s^-2
OMEGA = 7.2921e-5        # s^-1
R_EARTH = 6371.0e3       # m
RHO0 = 1025.0            # kg m^-3 reference seawater density
RHO_AIR = 1.225          # kg m^-3
CP = 3985.0              # J kg^-1 K^-1 (seawater, used for surface heat flux in PWP)


def coriolis(lat_deg):
    return 2.0 * OMEGA * np.sin(np.radians(lat_deg))


def _grad(field, lat, lon):
    """∂/∂x, ∂/∂y (per metre) on a regular lat/lon grid; NaN wherever a neighbour is NaN."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    dphi = np.radians(np.gradient(lat))                     # (H,)
    dlam = np.radians(np.gradient(lon))                     # (W,)
    dfdy = np.gradient(field, axis=0) / (R_EARTH * dphi)[:, None]
    dfdx = np.gradient(field, axis=1) / (R_EARTH * np.cos(np.radians(lat))[:, None] * dlam[None, :])
    return dfdx, dfdy


# =============================================================================
# 1. GEOSTROPHY
# =============================================================================
def geostrophic_currents(ssh_m, lat, lon):
    """u_g = -(g/f) ∂η/∂y, v_g = (g/f) ∂η/∂x (m/s). η: sea-surface height (CMEMS zos)."""
    f = coriolis(np.asarray(lat))[:, None]
    detadx, detady = _grad(np.asarray(ssh_m, float), lat, lon)
    return -(G / f) * detady, (G / f) * detadx


# =============================================================================
# 2. WIND STRESS AND EKMAN
# =============================================================================
def drag_coefficient(speed, scheme="constant", cd=1.3e-3):
    """'constant' (cd), or 'large_pond' (Large & Pond 1981: 1.2e-3 below 11 m/s, (0.49+0.065U)e-3 for 11–25 m/s)."""
    speed = np.asarray(speed, float)
    if scheme == "constant":
        return np.full_like(speed, cd)
    if scheme == "large_pond":
        return np.where(speed < 11.0, 1.2e-3, (0.49 + 0.065 * np.minimum(speed, 25.0)) * 1e-3)
    raise ValueError("scheme must be 'constant' or 'large_pond'")


def wind_stress(u10, v10, scheme="constant", cd=1.3e-3):
    spd = np.hypot(u10, v10)
    c = drag_coefficient(spd, scheme, cd)
    return RHO_AIR * c * spd * u10, RHO_AIR * c * spd * v10


def ekman(u10, v10, lat, lon, scheme="constant", cd=1.3e-3):
    """
    Ekman transport (m²/s): Mx = τy/(ρ0 f), My = -τx/(ρ0 f).
    Ekman pumping (m/day, + = upwelling): w_E = (1/ρ0) [∂(τy/f)/∂x - ∂(τx/f)/∂y].
    """
    tx, ty = wind_stress(np.asarray(u10, float), np.asarray(v10, float), scheme, cd)
    f = coriolis(np.asarray(lat))[:, None]
    mx, my = ty / (RHO0 * f), -tx / (RHO0 * f)
    dtyf_dx, _ = _grad(ty / f, lat, lon)
    _, dtxf_dy = _grad(tx / f, lat, lon)
    w = (dtyf_dx - dtxf_dy) / RHO0 * 86400.0
    return {"taux": tx, "tauy": ty, "mx": mx, "my": my, "w_ekman_m_per_day": w}


# =============================================================================
# 3. PARTICLE DRIFT
# =============================================================================
def _bilinear(field, lat, lon, plat, plon):
    """Bilinear interpolation on a regular grid; NaN if any of the 4 corners is NaN or outside."""
    H, W = field.shape
    fi = (plat - lat[0]) / (lat[1] - lat[0])
    fj = (plon - lon[0]) / (lon[1] - lon[0])
    fi = np.where(np.isfinite(fi), fi, -1.0)
    fj = np.where(np.isfinite(fj), fj, -1.0)
    i0 = np.floor(fi).astype(int)
    j0 = np.floor(fj).astype(int)
    ok = (i0 >= 0) & (j0 >= 0) & (i0 < H - 1) & (j0 < W - 1)
    i0c, j0c = np.clip(i0, 0, H - 2), np.clip(j0, 0, W - 2)
    a, b = fi - i0c, fj - j0c
    v = ((1 - a) * (1 - b) * field[i0c, j0c] + (1 - a) * b * field[i0c, j0c + 1]
         + a * (1 - b) * field[i0c + 1, j0c] + a * b * field[i0c + 1, j0c + 1])
    return np.where(ok, v, np.nan)


def drift(u_days, v_days, day_hours, lat, lon, start_lat, start_lon, t0_hours, duration_hours,
          dt_hours=1.0, n_particles=50, spread_km=5.0, diffusivity_m2s=0.0,
          windage=0.0, u10_days=None, v10_days=None, seed=0):
    """
    Advects particles with RK4 on currents interpolated bilinearly in space and linearly in time
    between daily fields (u_days: (T,H,W) m/s, valid at day_hours[k] hours). Optional windage
    (fraction of the 10 m wind) and horizontal random walk with diffusivity K (Δx = sqrt(2KΔt)·N(0,1)).
    Particles stop ('beached') where currents are undefined (land) and when outside the time range.
    Returns times (h), lat/lon tracks (n_steps+1, n_particles) and status per particle.
    """
    rng = np.random.default_rng(seed)
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    day_hours = np.asarray(day_hours, float)
    r = spread_km * 1e3 * np.sqrt(rng.uniform(size=n_particles))
    th = rng.uniform(0, 2 * np.pi, size=n_particles)
    plat = start_lat + np.degrees(r * np.sin(th) / R_EARTH)
    plon = start_lon + np.degrees(r * np.cos(th) / (R_EARTH * np.cos(np.radians(start_lat))))
    if n_particles == 1:
        plat, plon = np.array([start_lat], float), np.array([start_lon], float)

    def vel(t, la, lo):
        if t < day_hours[0] or t > day_hours[-1]:
            return np.full_like(la, np.nan), np.full_like(la, np.nan)
        k = min(int(np.searchsorted(day_hours, t, side="right") - 1), len(day_hours) - 2)
        w = (t - day_hours[k]) / (day_hours[k + 1] - day_hours[k])
        uu = (1 - w) * _bilinear(u_days[k], lat, lon, la, lo) + w * _bilinear(u_days[k + 1], lat, lon, la, lo)
        vv = (1 - w) * _bilinear(v_days[k], lat, lon, la, lo) + w * _bilinear(v_days[k + 1], lat, lon, la, lo)
        if windage and u10_days is not None:
            uu = uu + windage * ((1 - w) * _bilinear(u10_days[k], lat, lon, la, lo) + w * _bilinear(u10_days[k + 1], lat, lon, la, lo))
            vv = vv + windage * ((1 - w) * _bilinear(v10_days[k], lat, lon, la, lo) + w * _bilinear(v10_days[k + 1], lat, lon, la, lo))
        return uu, vv

    def step_deg(la, dx, dy):
        return np.degrees(dy / R_EARTH), np.degrees(dx / (R_EARTH * np.cos(np.radians(la))))

    n = int(round(duration_hours / dt_hours))
    dt = dt_hours * 3600.0
    T = [t0_hours]
    LA, LO = [plat.copy()], [plon.copy()]
    active = np.ones(n_particles, bool)
    status = np.array(["active"] * n_particles, dtype=object)
    for s in range(n):
        t = t0_hours + s * dt_hours
        la, lo = LA[-1].copy(), LO[-1].copy()
        k1u, k1v = vel(t, la, lo)
        d1a, d1o = step_deg(la, k1u * dt / 2, k1v * dt / 2)
        k2u, k2v = vel(t + dt_hours / 2, la + d1a, lo + d1o)
        d2a, d2o = step_deg(la, k2u * dt / 2, k2v * dt / 2)
        k3u, k3v = vel(t + dt_hours / 2, la + d2a, lo + d2o)
        d3a, d3o = step_deg(la, k3u * dt, k3v * dt)
        k4u, k4v = vel(t + dt_hours, la + d3a, lo + d3o)
        uu = (k1u + 2 * k2u + 2 * k3u + k4u) / 6.0
        vv = (k1v + 2 * k2v + 2 * k3v + k4v) / 6.0
        dx, dy = uu * dt, vv * dt
        if diffusivity_m2s > 0:
            sd = np.sqrt(2 * diffusivity_m2s * dt)
            dx = dx + sd * rng.standard_normal(n_particles)
            dy = dy + sd * rng.standard_normal(n_particles)
        dla, dlo = step_deg(la, dx, dy)
        bad = ~np.isfinite(dla) | ~np.isfinite(dlo)
        newly = active & bad
        status[newly] = "stopped (land or outside data)" if t + dt_hours <= day_hours[-1] else "end of data"
        active &= ~bad
        la = np.where(active, la + np.nan_to_num(dla), la)
        lo = np.where(active, lo + np.nan_to_num(dlo), lo)
        LA.append(la)
        LO.append(lo)
        T.append(t + dt_hours)
    return {"hours": np.array(T), "lat": np.array(LA), "lon": np.array(LO), "status": status.tolist()}


# =============================================================================
# 4. TEOS-10 STRATIFICATION
# =============================================================================
def stratification(pt_c, sp_psu, z_m, lat, lon, u=None, v=None):
    """
    Density (TEOS-10, in-situ), N² (s^-2) and, if u/v are given, shear² and gradient
    Richardson number Ri = N² / (∂u/∂z² + ∂v/∂z²) at mid-points.
    pt_c: potential temperature (°C); sp_psu: practical salinity; z_m: depth (positive down).
    """
    import gsw
    z = np.asarray(z_m, float)
    p = gsw.p_from_z(-z, lat)
    SA = gsw.SA_from_SP(np.asarray(sp_psu, float), p, lon, lat)
    CT = gsw.CT_from_pt(SA, np.asarray(pt_c, float))
    rho = gsw.rho(SA, CT, p)
    n2, p_mid = gsw.Nsquared(SA, CT, p, lat)
    z_mid = -gsw.z_from_p(p_mid, lat)
    out = {"rho_kg_m3": rho, "sigma0_kg_m3": gsw.sigma0(SA, CT), "n2_s2": n2, "z_mid_m": z_mid,
           "sound_speed_ms": gsw.sound_speed(SA, CT, p)}
    if u is not None and v is not None:
        dz = np.diff(z)
        s2 = (np.diff(u) / dz) ** 2 + (np.diff(v) / dz) ** 2
        with np.errstate(divide="ignore", invalid="ignore"):
            out["shear2_s2"] = s2
            out["ri"] = np.where(s2 > 0, n2 / s2, np.inf)
    return out


# =============================================================================
# 5. PWP MIXED-LAYER MODEL (Price, Weller & Pinkel 1986)
# =============================================================================
def pwp(T0, S0, z_levels, lat, lon, forcing_hours, u10, v10, heat_flux_wm2=0.0,
        dz=2.0, max_depth=500.0, dt_s=900.0, rb_crit=0.65, rg_crit=0.25,
        drag_scheme="large_pond", cd=1.3e-3):
    """
    1-D PWP model. T0/S0 on z_levels are interpolated to a uniform dz grid; velocity starts at rest.
    Each step: surface heat flux into the top cell -> remove static instability -> wind stress into
    the mixed layer with inertial rotation (half steps) -> bulk Richardson (Rb < rb_crit) deepening ->
    gradient Richardson (Rg < rg_crit) shear mixing. Winds (m/s) are given at forcing_hours and
    interpolated linearly in time. Density from TEOS-10 (gsw).
    Returns time series of SST and mixed-layer depth and the final profile.
    """
    import gsw
    z = np.arange(dz / 2, max_depth, dz)
    T = np.interp(z, z_levels, T0).astype(float)
    S = np.interp(z, z_levels, S0).astype(float) if np.ndim(S0) else np.full_like(z, float(S0))
    U = np.zeros_like(z)
    V = np.zeros_like(z)
    f = coriolis(lat)
    p = gsw.p_from_z(-z, lat)
    dens = lambda T_, S_: gsw.sigma0(gsw.SA_from_SP(S_, p, lon, lat), gsw.CT_from_pt(gsw.SA_from_SP(S_, p, lon, lat), T_)) + 1000.0  # noqa: E731

    fh = np.asarray(forcing_hours, float)
    uu = np.asarray(u10, float)
    vv = np.asarray(v10, float)
    n_steps = int((fh[-1] - fh[0]) * 3600.0 / dt_s)
    ang = -f * dt_s / 2.0
    out_t, out_sst, out_mld, out_tau = [], [], [], []

    def mix(a, k):
        a[: k + 1] = a[: k + 1].mean()

    for s in range(n_steps + 1):
        t_h = fh[0] + s * dt_s / 3600.0
        uw, vw = np.interp(t_h, fh, uu), np.interp(t_h, fh, vv)
        tx, ty = wind_stress(np.array(uw), np.array(vw), drag_scheme, cd)
        # surface heat flux
        T[0] += heat_flux_wm2 * dt_s / (RHO0 * CP * dz)
        rho = dens(T, S)
        # static instability: mixed layer = cells until density exceeds the surface value
        k = int(np.argmax(rho > rho[0] + 1e-4)) - 1
        if k < 0:
            k = len(z) - 1
        for a in (T, S, U, V):
            mix(a, k)
        rho = dens(T, S)
        k = int(np.argmax(rho > rho[0] + 1e-4)) - 1
        k = max(k, 0)
        h = (k + 1) * dz
        # momentum: rotate half, add stress over the mixed layer, rotate half
        c = (U + 1j * V) * np.exp(1j * ang)
        c[: k + 1] += (tx + 1j * ty) / (RHO0 * h) * dt_s
        c *= np.exp(1j * ang)
        U, V = c.real.copy(), c.imag.copy()
        # bulk Richardson deepening
        while k < len(z) - 1:
            dv2 = (U[k + 1] - U[0]) ** 2 + (V[k + 1] - V[0]) ** 2
            drho = rho[k + 1] - rho[0]
            rb = G * drho * h / (RHO0 * dv2) if dv2 > 0 else np.inf
            if rb >= rb_crit:
                break
            k += 1
            h = (k + 1) * dz
            for a in (T, S, U, V):
                mix(a, k)
            rho = dens(T, S)
        # gradient Richardson shear mixing (partial mixing to Rg' = rg_crit + 0.05)
        for _ in range(200):
            dv2 = np.diff(U) ** 2 + np.diff(V) ** 2
            drho = np.diff(rho)
            with np.errstate(divide="ignore", invalid="ignore"):
                rg = np.where(dv2 > 0, G * drho * dz / (RHO0 * dv2), np.inf)
            j = int(np.argmin(rg))
            if rg[j] >= rg_crit:
                break
            frac = 1.0 - rg[j] / (rg_crit + 0.05)
            for a in (T, S, U, V):
                d = (a[j + 1] - a[j]) * frac / 2.0
                a[j] += d
                a[j + 1] -= d
            rho = dens(T, S)
        if s % max(1, int(3600 / dt_s)) == 0:
            out_t.append(t_h)
            out_sst.append(float(T[0]))
            out_mld.append(float(h))
            out_tau.append(float(np.hypot(tx, ty)))
    return {"hours": np.array(out_t), "sst_c": np.array(out_sst), "mld_m": np.array(out_mld), "tau_n_m2": np.array(out_tau),
            "z_m": z, "T_final_c": T, "S_final": S, "T_initial_c": np.interp(z, z_levels, T0),
            "u_final": U, "v_final": V}


# =============================================================================
# 6. OPTIMAL INTERPOLATION
# =============================================================================
def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(np.asarray(lon2) - lon1) / 2) ** 2
    return 2 * R_EARTH / 1e3 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def optimal_interpolation(bg, lat, lon, obs_lat, obs_lon, obs_val, length_km=150.0, sigma_b=0.8, sigma_o=0.3):
    """
    x_a = x_b + B_go (B_oo + R)^-1 (y - H x_b), with Gaussian background covariance
    B = σb² exp(-d²/2L²), R = σo² I, H = bilinear interpolation. Returns the analysis field,
    increment, and exact leave-one-out statistics: LOO residual_i = [A^-1 d]_i / [A^-1]_ii, A = B_oo + R.
    """
    bg = np.asarray(bg, float)
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    olat, olon, oval = map(lambda a: np.asarray(a, float), (obs_lat, obs_lon, obs_val))
    hx = _bilinear(bg, lat, lon, olat, olon)
    keep = np.isfinite(hx) & np.isfinite(oval)
    olat, olon, oval, hx = olat[keep], olon[keep], oval[keep], hx[keep]
    if oval.size == 0:
        raise ValueError("no observations inside the valid background field")
    d = oval - hx
    D = haversine_km(olat[:, None], olon[:, None], olat[None, :], olon[None, :])
    A = sigma_b ** 2 * np.exp(-D ** 2 / (2 * length_km ** 2)) + sigma_o ** 2 * np.eye(oval.size)
    Ainv = np.linalg.inv(A)
    wts = Ainv @ d
    LAT, LON = np.meshgrid(lat, lon, indexing="ij")
    valid = np.isfinite(bg)
    inc = np.zeros_like(bg)
    gl, go = LAT[valid], LON[valid]
    Dg = haversine_km(gl[:, None], go[:, None], olat[None, :], olon[None, :])
    inc[valid] = (sigma_b ** 2 * np.exp(-Dg ** 2 / (2 * length_km ** 2))) @ wts
    inc[~valid] = np.nan
    loo = wts / np.diag(Ainv)
    return {"analysis": bg + inc, "increment": inc, "n_obs": int(oval.size),
            "innovation": d, "obs_lat": olat, "obs_lon": olon, "obs_val": oval, "bg_at_obs": hx,
            "rmse_background_c": float(np.sqrt(np.mean(d ** 2))), "bias_background_c": float(np.mean(-d)),
            "rmse_loo_analysis_c": float(np.sqrt(np.mean(loo ** 2))), "loo_residual": loo}
