"""
===============================================================================
OceanEmbed — shared core: the trained network + physical diagnostics
Team OceanSATX | SIH 2026 | Problem Statement 26066
===============================================================================
Everything that turns numbers into science lives here, so that the batch
inference script, the API server and the tests all use one implementation.

1. `OceanEmbed` is the architecture that produced `trained/*.pth`
   (kaggle_oceanembed_pipeline.py). The embedding is a single nn.Linear.
   Weights are always loaded with strict=True so an architecture mismatch
   fails loudly instead of silently running untrained layers.

2. Diagnostics treat each predicted profile as piecewise-linear between the
   15 standard levels. Under that assumption every quantity below is computed
   exactly (no extra numerical error beyond the vertical sampling itself):

   - Isotherm depth D_T (D26, D20): the first depth, going down from the
     surface, where the profile crosses T. Undefined (NaN) if the surface is
     already colder than T, or if the column stays >= T down to 1000 m.
   - Tropical Cyclone Heat Potential (Leipper & Volgenau 1972):
         TCHP = rho * cp * integral_0^{D26} (T(z) - 26 °C) dz
     integrated exactly for a piecewise-linear T(z). Reported in kJ/cm².
     TCHP = 0 when the surface is colder than 26 °C.
   - Mixed-layer depth, temperature criterion of de Boyer Montégut et al.
     (2004): the depth where |T(z) - T(10 m)| first reaches 0.2 °C.
   - Thermocline: the layer between two standard levels with the most
     negative dT/dz. Its depth is reported as the mid-point of that layer,
     together with the layer bounds, because the vertical resolution does
     not allow anything finer.

Limitation to keep in mind: with levels at 20, 30, 50, 75, 100 m, a diagnostic
cannot be more precise than its interpolation interval. The layer bounds are
returned so the UI can show that uncertainty rather than hide it.
===============================================================================
"""

from __future__ import annotations

import hashlib
import os

import numpy as np
import torch
import torch.nn as nn

# 15 standard levels used for training (metres, positive down)
DEPTH_LEVELS = np.array([0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000], dtype=np.float64)
NUM_DEPTHS = len(DEPTH_LEVELS)
PATCH_SIZE = 31
IN_CHANNELS = 14
SURFACE_VARS = ["sst", "ssh", "sss", "uo", "vo", "u10", "v10"]  # channel order: var0, mask0, var1, mask1, ...

# TCHP constants: the convention used in operational TCHP products
# (e.g. Goni et al. 2009, Oceanography 22(3)). Seawater density and the
# specific heat value used in those products.
RHO_SEAWATER = 1026.0      # kg m^-3
CP_SEAWATER = 4178.0       # J kg^-1 K^-1
J_PER_M2_TO_KJ_PER_CM2 = 1.0e-7   # 1 kJ/cm² = 1e3 J / 1e-4 m² = 1e7 J/m²

MLD_REFERENCE_DEPTH_M = 10.0
MLD_DELTA_T_C = 0.2


# =============================================================================
# 1. MODEL (must match the architecture that was trained)
# =============================================================================
class OceanEmbed(nn.Module):
    """CNN encoder -> 128-D linear embedding -> 15-depth profile decoder."""

    def __init__(self, in_channels=IN_CHANNELS, embed_dim=128, out_depths=NUM_DEPTHS):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
        )
        self.embedding = nn.Linear(128, embed_dim)
        self.decoder = nn.Sequential(
            nn.Linear(embed_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, out_depths),
        )

    def forward(self, patch):
        latent = self.embedding(self.encoder(patch))
        return self.decoder(latent), latent


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_trained_model(path: str, device: torch.device | str = "cpu") -> OceanEmbed:
    """Loads a checkpoint with strict=True. Raises if the architecture does not match."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Checkpoint not found: {path}")
    model = OceanEmbed().to(device)
    state = torch.load(path, map_location=device)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def extract_patches(padded_surface: torch.Tensor, rows: np.ndarray, cols: np.ndarray) -> torch.Tensor:
    """
    Cuts 31x31 patches centred on (rows, cols) out of a surface tensor that was
    reflect-padded by PATCH_SIZE // 2 on each side (the same padding used in
    training, RealOceanPatchDataset). Returns (N, 14, 31, 31).
    """
    windows = padded_surface.unfold(1, PATCH_SIZE, 1).unfold(2, PATCH_SIZE, 1)  # (C, H, W, 31, 31) view
    r = torch.as_tensor(rows, dtype=torch.long)
    c = torch.as_tensor(cols, dtype=torch.long)
    return windows[:, r, c].permute(1, 0, 2, 3).contiguous()


def reflect_pad(surface_chw: torch.Tensor) -> torch.Tensor:
    p = PATCH_SIZE // 2
    return torch.nn.functional.pad(surface_chw.unsqueeze(0), (p, p, p, p), mode="reflect")[0]


# =============================================================================
# 2. PHYSICAL DIAGNOSTICS (vectorised over profiles, shape (N, 15))
# =============================================================================
def _as_profiles(profiles) -> np.ndarray:
    P = np.asarray(profiles, dtype=np.float64)
    if P.ndim == 1:
        P = P[None, :]
    if P.shape[-1] != NUM_DEPTHS:
        raise ValueError(f"Expected {NUM_DEPTHS} depth levels, got {P.shape[-1]}")
    return P


def isotherm_depth(profiles, iso_c: float, z=DEPTH_LEVELS) -> np.ndarray:
    """
    First downward crossing of `iso_c` (°C), linear interpolation between levels.
    NaN if T(0) < iso_c (isotherm absent) or if T >= iso_c all the way to the bottom level.
    """
    P = _as_profiles(profiles)
    z = np.asarray(z, dtype=np.float64)
    warm = P >= iso_c
    crossing = warm[:, :-1] & ~warm[:, 1:]           # interval k: T_k >= iso > T_{k+1}
    has_crossing = crossing.any(axis=1)
    k = np.argmax(crossing, axis=1)                   # first crossing interval
    valid = warm[:, 0] & has_crossing
    # With T(0) >= iso, the first interval where the next level is colder is the first crossing,
    # and every level above it is >= iso.
    rows = np.arange(P.shape[0])
    t0, t1 = P[rows, k], P[rows, k + 1]
    z0, z1 = z[k], z[k + 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        d = z0 + (iso_c - t0) * (z1 - z0) / (t1 - t0)
    return np.where(valid, d, np.nan)


def tchp_kj_cm2(profiles, z=DEPTH_LEVELS, rho=RHO_SEAWATER, cp=CP_SEAWATER) -> np.ndarray:
    """
    TCHP = rho * cp * ∫_0^{D26} (T - 26) dz, exact for piecewise-linear T(z).
    0 where T(0) < 26 °C. NaN where the column is >= 26 °C down to 1000 m (D26 undefined).
    """
    P = _as_profiles(profiles)
    z = np.asarray(z, dtype=np.float64)
    a = P - 26.0
    dz = np.diff(z)
    warm = a >= 0
    crossing = warm[:, :-1] & ~warm[:, 1:]
    has_crossing = crossing.any(axis=1)
    k = np.argmax(crossing, axis=1)

    # Full trapezoids for intervals entirely above the first crossing
    trapz = 0.5 * (a[:, :-1] + a[:, 1:]) * dz                 # (N, L-1)
    idx = np.arange(dz.size)[None, :]
    full = np.where(idx < k[:, None], trapz, 0.0).sum(axis=1)

    # Triangle in the crossing interval: a_k >= 0 > a_{k+1}
    rows = np.arange(P.shape[0])
    ak, ak1 = a[rows, k], a[rows, k + 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        tri = 0.5 * ak * ak * dz[k] / (ak - ak1)
    integral = full + tri                                      # °C·m

    out = rho * cp * integral * J_PER_M2_TO_KJ_PER_CM2
    out = np.where(warm[:, 0] & has_crossing, out, np.nan)
    out = np.where(~warm[:, 0], 0.0, out)
    return out


def mixed_layer_depth(profiles, z=DEPTH_LEVELS, ref_depth=MLD_REFERENCE_DEPTH_M, delta=MLD_DELTA_T_C) -> np.ndarray:
    """
    de Boyer Montégut et al. (2004) temperature criterion: shallowest depth below
    `ref_depth` where |T(z) - T(ref_depth)| = `delta`, T linearly interpolated.
    NaN if the criterion is never met above the deepest level.
    """
    P = _as_profiles(profiles)
    z = np.asarray(z, dtype=np.float64)
    ref_idx = int(np.where(z == ref_depth)[0][0])
    tref = P[:, ref_idx]
    d = P - tref[:, None]
    exceed = np.abs(d) >= delta
    exceed[:, : ref_idx + 1] = False
    has = exceed.any(axis=1)
    j = np.argmax(exceed, axis=1)                  # first level below ref reaching the threshold
    j = np.maximum(j, ref_idx + 1)
    rows = np.arange(P.shape[0])
    target = tref + np.sign(d[rows, j]) * delta    # T value at the mixed-layer base
    t0, t1 = P[rows, j - 1], P[rows, j]
    with np.errstate(invalid="ignore", divide="ignore"):
        mld = z[j - 1] + (target - t0) * (z[j] - z[j - 1]) / (t1 - t0)
    return np.where(has, mld, np.nan)


def thermocline(profiles, z=DEPTH_LEVELS):
    """
    Layer with the most negative dT/dz between adjacent standard levels.
    Returns dict of arrays: depth_mid_m, top_m, bottom_m, gradient_c_per_m.
    NaN where temperature never decreases with depth.
    """
    P = _as_profiles(profiles)
    z = np.asarray(z, dtype=np.float64)
    g = np.diff(P, axis=1) / np.diff(z)[None, :]
    k = np.argmin(g, axis=1)
    rows = np.arange(P.shape[0])
    gk = g[rows, k]
    ok = gk < 0
    return {
        "depth_mid_m": np.where(ok, 0.5 * (z[k] + z[k + 1]), np.nan),
        "top_m": np.where(ok, z[k], np.nan),
        "bottom_m": np.where(ok, z[k + 1], np.nan),
        "gradient_c_per_m": np.where(ok, gk, np.nan),
    }


def profile_rmse(pred, ref) -> np.ndarray:
    """Per-profile RMSE across the 15 levels (°C)."""
    P, R = _as_profiles(pred), _as_profiles(ref)
    return np.sqrt(np.mean((P - R) ** 2, axis=1))


def all_diagnostics(profiles) -> dict:
    """Every diagnostic for a batch of profiles, as float32 arrays of shape (N,)."""
    P = _as_profiles(profiles)
    tc = thermocline(P)
    i100 = int(np.where(DEPTH_LEVELS == 100)[0][0])
    out = {
        "d26_m": isotherm_depth(P, 26.0),
        "d20_m": isotherm_depth(P, 20.0),
        "tchp_kj_cm2": tchp_kj_cm2(P),
        "mld_m": mixed_layer_depth(P),
        "thermocline_mid_m": tc["depth_mid_m"],
        "thermocline_top_m": tc["top_m"],
        "thermocline_bottom_m": tc["bottom_m"],
        "thermocline_grad_c_per_m": tc["gradient_c_per_m"],
        "t100_c": P[:, i100],
    }
    return {k: v.astype(np.float32) for k, v in out.items()}


# =============================================================================
# 3. SOUND SPEED AND SONIC LAYER DEPTH
# =============================================================================
def sound_speed_mackenzie(T, S, D):
    """
    Mackenzie (1981, J. Acoust. Soc. Am. 70, 807) nine-term equation, m/s.
    Valid for T 2–30 °C, S 25–40 PSU, D 0–8000 m. Check value: T=25, S=35, D=1000 -> 1550.744 m/s.
    """
    T = np.asarray(T, dtype=np.float64)
    S = np.asarray(S, dtype=np.float64)
    D = np.asarray(D, dtype=np.float64)
    return (1448.96 + 4.591 * T - 5.304e-2 * T ** 2 + 2.374e-4 * T ** 3
            + 1.340 * (S - 35.0) + 1.630e-2 * D + 1.675e-7 * D ** 2
            - 1.025e-2 * T * (S - 35.0) - 7.139e-13 * T * D ** 3)


def sonic_layer(profile, salinity_psu, z=DEPTH_LEVELS, dz_fine=1.0):
    """
    Sonic layer depth (SLD): depth of the near-surface sound-speed maximum, found above the
    sound-speed minimum of the column. T is linearly interpolated to a 1 m grid; salinity is
    taken as uniform with depth (only surface salinity is available), which the result
    therefore assumes. Below the SLD sound speed decreases with depth, so rays from a source
    in the layer bend downward and leave a shadow zone beneath the layer at range.
    Returns dict with sld_m (0 = no surface duct), c_surface, c_at_sld, below_layer_gradient
    (m/s per m, over the 50 m below the SLD), and the sound-speed profile on the standard levels.
    """
    P = np.asarray(profile, dtype=np.float64).reshape(-1)
    zf = np.arange(0.0, float(z[-1]) + dz_fine / 2, dz_fine)
    Tf = np.interp(zf, z, P)
    c = sound_speed_mackenzie(Tf, salinity_psu, zf)
    i_min = int(np.argmin(c))
    i_max = int(np.argmax(c[: i_min + 1]))
    sld = float(zf[i_max])
    j = min(len(zf) - 1, i_max + int(round(50.0 / dz_fine)))
    below = float((c[j] - c[i_max]) / (zf[j] - zf[i_max])) if j > i_max else float("nan")
    in_range = bool((P.min() >= 2.0) and (P.max() <= 30.0) and (25.0 <= salinity_psu <= 40.0))
    return {
        "sld_m": sld,
        "c_surface_ms": float(c[0]),
        "c_at_sld_ms": float(c[i_max]),
        "c_min_ms": float(c[i_min]),
        "c_min_depth_m": float(zf[i_min]),
        "below_layer_gradient_ms_per_m": below,
        "c_levels_ms": sound_speed_mackenzie(P, salinity_psu, z).tolist(),
        "within_mackenzie_validity": in_range,
        "assumption": "salinity uniform with depth, equal to the surface value",
    }


# =============================================================================
# 4. REBUILDING THE MODEL INPUT FROM STORED (DE-NORMALISED) FIELDS
# =============================================================================
def normalise_surface(raw: dict, stats: dict, sst_stats_in_kelvin: bool) -> np.ndarray:
    """
    raw: {var: (H, W) array in physical units, NaN where the source had no data}; SST in °C.
    stats: {var: (mean, std)} training-period statistics.
    Returns the (14, H, W) float32 input exactly as DataHarmonizer.normalize_with_train_stats builds it:
    value channel (x - mean) / (std + 1e-6) with 0 where missing, followed by the 0/1 mask.
    """
    chans = []
    for v in SURFACE_VARS:
        arr = np.asarray(raw[v], dtype=np.float64)
        if v == "sst" and sst_stats_in_kelvin:
            arr = arr + 273.15
        mask = np.isfinite(arr).astype(np.float32)
        mean, std = stats[v]
        norm = (np.nan_to_num(arr, nan=0.0) - mean) / (std + 1e-6)
        chans.append((norm * mask).astype(np.float32))
        chans.append(mask)
    return np.stack(chans, axis=0)


DIAGNOSTIC_META = {
    "d26_m": {"label": "26 °C isotherm depth (D26)", "units": "m",
              "method": "first downward crossing of 26 °C, linear interpolation between standard levels"},
    "d20_m": {"label": "20 °C isotherm depth (D20)", "units": "m",
              "method": "first downward crossing of 20 °C, linear interpolation; standard thermocline proxy"},
    "tchp_kj_cm2": {"label": "Tropical cyclone heat potential", "units": "kJ/cm²",
                    "method": f"rho*cp*∫0^D26 (T-26) dz, exact for piecewise-linear T; rho={RHO_SEAWATER}, cp={CP_SEAWATER}"},
    "mld_m": {"label": "Mixed-layer depth", "units": "m",
              "method": f"|T(z)-T({MLD_REFERENCE_DEPTH_M:g} m)| = {MLD_DELTA_T_C} °C (de Boyer Montégut et al. 2004)"},
    "thermocline_mid_m": {"label": "Thermocline depth", "units": "m",
                          "method": "mid-point of the layer with the most negative dT/dz"},
    "thermocline_top_m": {"label": "Thermocline layer top", "units": "m", "method": "upper level of that layer"},
    "thermocline_bottom_m": {"label": "Thermocline layer bottom", "units": "m", "method": "lower level of that layer"},
    "thermocline_grad_c_per_m": {"label": "Steepest temperature gradient", "units": "°C/m",
                                 "method": "(T_k+1 - T_k)/(z_k+1 - z_k) in that layer"},
    "t100_c": {"label": "Temperature at 100 m", "units": "°C", "method": "value at the 100 m level"},
}
