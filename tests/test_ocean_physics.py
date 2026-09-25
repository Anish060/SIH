"""Analytic and conservation checks for physics.py."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import physics as ph  # noqa: E402
import oceanembed_core as core  # noqa: E402

LAT = np.arange(5.0, 30.01, 0.25)
LON = np.arange(45.0, 105.01, 0.25)


def test_geostrophy_linear_ssh():
    s = 1e-6                                   # dη/dy = 1 m per 1000 km
    y = np.radians(LAT - 15.0) * ph.R_EARTH
    eta = np.repeat((s * y)[:, None], LON.size, axis=1)
    u, v = ph.geostrophic_currents(eta, LAT, LON)
    np.testing.assert_allclose(u[:, 10], -ph.G * s / ph.coriolis(LAT), rtol=1e-9)
    np.testing.assert_allclose(v, 0.0, atol=1e-12)


def test_drag_and_ekman_transport():
    assert ph.drag_coefficient(15.0, "large_pond") == pytest.approx(1.465e-3)
    assert ph.drag_coefficient(8.0, "large_pond") == pytest.approx(1.2e-3)
    u10 = np.full((LAT.size, LON.size), 10.0)
    v10 = np.zeros_like(u10)
    e = ph.ekman(u10, v10, LAT, LON, "constant", 1.3e-3)
    tau = ph.RHO_AIR * 1.3e-3 * 100.0
    np.testing.assert_allclose(e["taux"], tau)
    np.testing.assert_allclose(e["my"][:, 0], -tau / (ph.RHO0 * ph.coriolis(LAT)), rtol=1e-12)
    # uniform eastward stress: w = τx β / (ρ0 f²) with β = 2Ω cosφ / R  (beta-effect upwelling)
    beta = 2 * ph.OMEGA * np.cos(np.radians(LAT)) / ph.R_EARTH
    w_exact = tau * beta / (ph.RHO0 * ph.coriolis(LAT) ** 2) * 86400
    # second-order central differences on the 0.25° grid: truncation error is ~0.2% near 5°N, where f varies fastest
    np.testing.assert_allclose(e["w_ekman_m_per_day"][2:-2, 5], w_exact[2:-2], rtol=5e-3)


def test_drift_uniform_current_and_land():
    T = 3
    u = np.full((T, LAT.size, LON.size), 0.2)
    v = np.zeros_like(u)
    out = ph.drift(u, v, [0, 24, 48], LAT, LON, 15.0, 80.0, 0, 24, dt_hours=1.0, n_particles=1)
    d = ph.haversine_km(15.0, 80.0, out["lat"][-1, 0], out["lon"][-1, 0])
    assert d == pytest.approx(0.2 * 86400 / 1e3, rel=1e-3)
    u2 = u.copy()
    u2[:, :, LON > 80.1] = np.nan                                   # "land" east of 80.1°E
    out2 = ph.drift(u2, v, [0, 24, 48], LAT, LON, 15.0, 80.0, 0, 24, n_particles=1)
    assert out2["status"][0].startswith("stopped")
    assert out2["lon"][-1, 0] < 80.35


def stable_profile():
    return np.array([29.0 if z <= 30 else max(4.0, 29.0 - 0.08 * (z - 30)) for z in core.DEPTH_LEVELS])


def test_pwp_no_forcing_leaves_profile_unchanged():
    out = ph.pwp(stable_profile(), 34.5, core.DEPTH_LEVELS, 15.0, 88.0, [0, 24], [0, 0], [0, 0], dt_s=1800)
    np.testing.assert_allclose(out["T_final_c"], out["T_initial_c"], atol=1e-10)


def test_pwp_mixing_conserves_heat_and_cools_surface():
    out = ph.pwp(stable_profile(), 34.5, core.DEPTH_LEVELS, 15.0, 88.0, [0, 36], [25, 25], [0, 0], dt_s=900)
    assert out["T_final_c"].sum() == pytest.approx(out["T_initial_c"].sum(), rel=1e-10)
    assert out["sst_c"][-1] < 29.0 - 0.5
    assert out["mld_m"][-1] > 40


def test_pwp_surface_heat_flux_budget():
    q, hours = 200.0, 24
    out = ph.pwp(stable_profile(), 34.5, core.DEPTH_LEVELS, 15.0, 88.0, [0, hours], [0, 0], [0, 0], heat_flux_wm2=q, dt_s=900)
    n_steps = int(hours * 3600 / 900) + 1
    gained = (out["T_final_c"] - out["T_initial_c"]).sum() * 2.0          # dz = 2 m
    assert gained == pytest.approx(q * 900 * n_steps / (ph.RHO0 * ph.CP), rel=1e-9)


def test_stratification_teos10():
    P = stable_profile()
    s = ph.stratification(P, np.full(15, 34.5), core.DEPTH_LEVELS, 15.0, 88.0, np.zeros(15), np.zeros(15))
    assert np.all(np.diff(s["sigma0_kg_m3"]) >= -1e-9)
    assert np.all(s["n2_s2"] >= -1e-12)
    assert np.all(np.isinf(s["ri"]))
    mk = core.sound_speed_mackenzie(P, 34.5, core.DEPTH_LEVELS)
    assert np.max(np.abs(s["sound_speed_ms"] - mk)) < 1.0            # TEOS-10 vs Mackenzie (1981)


def test_oi_single_observation_and_loo():
    bg = np.zeros((LAT.size, LON.size))
    r = ph.optimal_interpolation(bg, LAT, LON, [15.0], [88.0], [1.0], length_km=100, sigma_b=1.0, sigma_o=0.5)
    i, j = np.argmin(abs(LAT - 15)), np.argmin(abs(LON - 88))
    assert r["analysis"][i, j] == pytest.approx(1.0 / (1.0 + 0.25), rel=1e-9)
    far = ph.optimal_interpolation(bg, LAT, LON, [10.0, 25.0], [60.0, 95.0], [1.0, -2.0], length_km=100, sigma_b=1.0, sigma_o=0.5)
    np.testing.assert_allclose(far["loo_residual"], [1.0, -2.0], rtol=1e-9)    # independent obs: LOO = innovation
