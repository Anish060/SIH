"""
Checks every diagnostic in oceanembed_core against
  (a) closed-form answers worked out by hand, and
  (b) an independent brute-force evaluation on a 1 mm vertical grid.
Run:  python -m pytest tests -q
"""
import os
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import oceanembed_core as core  # noqa: E402

Z = core.DEPTH_LEVELS
RC = core.RHO_SEAWATER * core.CP_SEAWATER * 1e-7   # kJ/cm² per °C·m


def sample(fn):
    return np.array([fn(z) for z in Z], dtype=np.float64)


# ---------------------------------------------------------------- closed form
def test_linear_profile_closed_form():
    # T(z) = 30 - 0.045 z  ->  D26 = 4/0.045, D20 = 10/0.045, ∫0^D26 (T-26) dz = 4²/(2·0.045)
    P = sample(lambda z: 30.0 - 0.045 * z)
    assert core.isotherm_depth(P, 26.0)[0] == pytest.approx(4 / 0.045, rel=1e-12)
    assert core.isotherm_depth(P, 20.0)[0] == pytest.approx(10 / 0.045, rel=1e-12)
    assert core.tchp_kj_cm2(P)[0] == pytest.approx(RC * 16 / (2 * 0.045), rel=1e-12)


def test_unit_conversion():
    # 1 °C·m of excess heat = rho*cp J/m² = rho*cp*1e-7 kJ/cm²
    assert RC == pytest.approx(1026 * 4178 / 1e7)


def test_cold_surface_has_no_d26_and_zero_tchp():
    P = sample(lambda z: 25.0 - 0.01 * z)
    assert np.isnan(core.isotherm_depth(P, 26.0)[0])
    assert core.tchp_kj_cm2(P)[0] == 0.0


def test_column_warmer_than_26_to_bottom_is_undefined():
    P = np.full(15, 28.0)
    assert np.isnan(core.isotherm_depth(P, 26.0)[0])
    assert np.isnan(core.tchp_kj_cm2(P)[0])


def test_isotherm_exactly_on_a_level():
    P = sample(lambda z: 30.0 - 0.04 * z)       # T(100) = 26 exactly
    assert core.isotherm_depth(P, 26.0)[0] == pytest.approx(100.0, abs=1e-9)
    assert core.tchp_kj_cm2(P)[0] == pytest.approx(RC * 16 / (2 * 0.04), rel=1e-12)


def two_layer(z):
    # 29 °C mixed layer to 30 m, -0.08 °C/m to 75 m, -0.12 °C/m to 100 m, -0.05 °C/m to 150 m,
    # then -0.01 °C/m below.
    if z <= 30:
        return 29.0
    if z <= 75:
        return 29.0 - 0.08 * (z - 30)
    t75 = 29.0 - 0.08 * 45
    if z <= 100:
        return t75 - 0.12 * (z - 75)
    t100 = t75 - 0.12 * 25
    if z <= 150:
        return t100 - 0.05 * (z - 100)
    return t100 - 2.5 - 0.01 * (z - 150)


def test_mixed_layer_and_thermocline_closed_form():
    P = sample(two_layer)
    # |T - T(10)| = 0.2 at 30 + 0.2/0.08 = 32.5 m
    assert core.mixed_layer_depth(P)[0] == pytest.approx(32.5, rel=1e-12)
    tc = core.thermocline(P)
    assert tc["depth_mid_m"][0] == pytest.approx(87.5)
    assert tc["top_m"][0] == 75 and tc["bottom_m"][0] == 100
    assert tc["gradient_c_per_m"][0] == pytest.approx(-0.12, rel=1e-12)
    # D26: 29 - 0.08 (z-30) = 26 -> z = 67.5 m ; ∫ = 3*30 + 3²/(2*0.08)
    assert core.isotherm_depth(P, 26.0)[0] == pytest.approx(67.5, rel=1e-12)
    assert core.tchp_kj_cm2(P)[0] == pytest.approx(RC * (90 + 9 / 0.16), rel=1e-12)


def test_mixed_layer_warming_below_reference():
    # temperature inversion: water gets warmer below 10 m; criterion uses |ΔT|
    P = sample(lambda z: 27.0 if z <= 20 else 27.0 + 0.02 * (z - 20) if z <= 50 else 27.6 - 0.02 * (z - 50))
    assert core.mixed_layer_depth(P)[0] == pytest.approx(30.0, rel=1e-12)   # 27 + 0.02*(z-20) = 27.2


def test_isothermal_column_has_no_thermocline_or_mld():
    P = np.full(15, 20.0)
    assert np.isnan(core.thermocline(P)["depth_mid_m"][0])
    assert np.isnan(core.mixed_layer_depth(P)[0])


# ------------------------------------------------------ brute-force agreement
def brute_force(P, iso=26.0):
    zf = np.arange(0, 1000.0005, 0.001)
    Tf = np.interp(zf, Z, P)
    below = np.nonzero(Tf < iso)[0]
    if Tf[0] < iso:
        return np.nan, 0.0
    d = zf[below[0]]
    m = zf <= d
    integral = np.trapezoid(np.maximum(Tf[m] - iso, 0), zf[m])
    return d, RC * integral


def test_matches_brute_force_on_random_realistic_profiles():
    rng = np.random.default_rng(7)
    for _ in range(40):
        sst = rng.uniform(26.5, 31.0)
        mld = rng.uniform(5, 80)
        scale = rng.uniform(60, 250)
        P = np.array([sst if z <= mld else 4 + (sst - 4) * np.exp(-(z - mld) / scale) for z in Z])
        d_ref, tchp_ref = brute_force(P)
        assert core.isotherm_depth(P, 26.0)[0] == pytest.approx(d_ref, abs=2e-3)       # 1 mm grid
        assert core.tchp_kj_cm2(P)[0] == pytest.approx(tchp_ref, rel=1e-4, abs=1e-4)


def test_vectorised_equals_row_by_row():
    rng = np.random.default_rng(1)
    P = np.sort(rng.uniform(4, 31, size=(200, 15)), axis=1)[:, ::-1]
    batch = core.all_diagnostics(P)
    for i in range(0, 200, 17):
        single = core.all_diagnostics(P[i])
        for k in batch:
            np.testing.assert_allclose(batch[k][i], single[k][0], equal_nan=True)


# --------------------------------------------------------------- model / data
CKPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trained", "best_oceanembed_model.pth")


@pytest.mark.skipif(not os.path.exists(CKPT), reason="checkpoint not present")
def test_checkpoint_loads_strictly():
    m = core.load_trained_model(CKPT)
    out, lat = m(torch.zeros(2, 14, 31, 31))
    assert out.shape == (2, 15) and lat.shape == (2, 128)


def test_strict_load_rejects_wrong_architecture(tmp_path):
    bad = torch.nn.Sequential(torch.nn.Linear(2, 2))
    p = tmp_path / "bad.pth"
    torch.save(bad.state_dict(), p)
    with pytest.raises(RuntimeError):
        core.load_trained_model(str(p))


def test_patch_extraction_matches_training_dataset():
    # RealOceanPatchDataset: pad (T,C,H,W) with reflect, slice [r:r+31, c:c+31]
    x = torch.randn(3, 14, 40, 50)
    padded_train = torch.nn.functional.pad(x, (15, 15, 15, 15), mode="reflect")
    rows, cols = np.array([0, 7, 39, 20]), np.array([0, 49, 3, 25])
    for t in range(3):
        mine = core.extract_patches(core.reflect_pad(x[t]), rows, cols)
        for i, (r, c) in enumerate(zip(rows, cols)):
            ref = padded_train[t, :, r:r + 31, c:c + 31]
            assert torch.equal(mine[i], ref)
            assert torch.equal(mine[i][:, 15, 15], x[t, :, r, c])   # patch is centred on the cell


# ------------------------------------------------------------- sound speed
def test_mackenzie_check_value():
    # Mackenzie (1981) published check value
    assert core.sound_speed_mackenzie(25.0, 35.0, 1000.0) == pytest.approx(1550.744, abs=1e-3)


def test_sonic_layer_depth_isothermal_mixed_layer():
    # Isothermal to 40 m, but sampled on the standard levels: 30 m is the last 28 °C level and 50 m
    # is already 27 °C, so under linear interpolation cooling starts at 30 m. Inside the isothermal
    # layer pressure makes c increase with depth, so the sound-speed maximum is at 30 m.
    P = sample(lambda z: 28.0 if z <= 40 else max(4.0, 28.0 - 0.1 * (z - 40)))
    out = core.sonic_layer(P, 34.0)
    assert out["sld_m"] == pytest.approx(30.0, abs=1.0)
    assert out["c_at_sld_ms"] > out["c_surface_ms"]
    assert out["below_layer_gradient_ms_per_m"] < 0


def test_no_surface_duct_when_cooling_starts_at_surface():
    P = sample(lambda z: max(4.0, 29.0 - 0.05 * z))
    assert core.sonic_layer(P, 34.0)["sld_m"] == 0.0


def test_normalise_surface_matches_harmonizer():
    import kaggle_oceanembed_eval as ev
    h = ev.DataHarmonizer()
    rng = np.random.default_rng(3)
    raw = {v: rng.normal(size=(6, 7)) for v in core.SURFACE_VARS}
    raw["sst"] = 27 + rng.normal(size=(6, 7))
    raw["sss"][2, 3] = np.nan
    stats = {v: (float(rng.normal()), float(abs(rng.normal()) + 0.1)) for v in core.SURFACE_VARS}
    stats["sst"] = (300.0, 1.5)
    h.stats = stats
    ref = []
    for v in core.SURFACE_VARS:
        a = raw[v] + 273.15 if v == "sst" else raw[v]
        n, m = h.normalize_with_train_stats(a, v)
        ref += [n, m]
    np.testing.assert_allclose(core.normalise_surface(raw, stats, True), np.stack(ref).astype(np.float32), rtol=1e-6, atol=1e-6)
