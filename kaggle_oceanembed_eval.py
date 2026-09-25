"""
===============================================================================
OceanEmbed — Evaluation & Hackathon Summary Generator
Team OceanSATX | SIH 2026 | Problem Statement 26066
===============================================================================
Fast, Memory-Efficient Standalone Evaluation Script:
  ✔ Loads pre-trained checkpoints: best_b1_model.pth, best_b2_model.pth, best_oceanembed_model.pth
  ✔ Mini-batched GPU evaluation (batch_size=256) preventing CUDA Out-Of-Memory
  ✔ Gridded INCOIS ARGO Independent Profile Verification
  ✔ Saves validation comparison plot: incois_argo_validation.png
  ✔ Prints clean Summary Results Table (True Unweighted Physical RMSE °C)
===============================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
import xarray as xr
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import matplotlib.pyplot as plt
import seaborn as sns

# Set seed for reproducibility
torch.manual_seed(42)
np.random.seed(42)

# =============================================================================
# 1. DOMAIN & DATASET CONFIGURATION
# =============================================================================
LAT_MIN, LAT_MAX = 5.0, 30.0     # Bay of Bengal / North Indian Ocean
LON_MIN, LON_MAX = 45.0, 105.0
GRID_RES = 0.25                  # Common 0.25 degree target grid

DEPTH_LEVELS = np.array([0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000])
NUM_DEPTHS = len(DEPTH_LEVELS)

LAT_GRID = np.arange(LAT_MIN, LAT_MAX + GRID_RES, GRID_RES)
LON_GRID = np.arange(LON_MIN, LON_MAX + GRID_RES, GRID_RES)
H, W = len(LAT_GRID), len(LON_GRID)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"[+] Active Compute Engine for Evaluation: {device}")

# =============================================================================
# HELPER: COORDINATE STANDARDIZER
# =============================================================================

def standardize_coords(da_or_ds):
    rename_dict = {}
    for t_alias in ['valid_time', 'TIME', 'time_counter']:
        if (t_alias in da_or_ds.coords or t_alias in da_or_ds.dims) and t_alias != 'time':
            if 'time' not in da_or_ds.coords and 'time' not in da_or_ds.dims:
                rename_dict[t_alias] = 'time'
            
    for lat_alias in ['lat', 'LATITUDE', 'nav_lat']:
        if (lat_alias in da_or_ds.coords or lat_alias in da_or_ds.dims) and lat_alias != 'latitude':
            if 'latitude' not in da_or_ds.coords and 'latitude' not in da_or_ds.dims:
                rename_dict[lat_alias] = 'latitude'
            
    for lon_alias in ['lon', 'LONGITUDE', 'nav_lon']:
        if (lon_alias in da_or_ds.coords or lon_alias in da_or_ds.dims) and lon_alias != 'longitude':
            if 'longitude' not in da_or_ds.coords and 'longitude' not in da_or_ds.dims:
                rename_dict[lon_alias] = 'longitude'

    for depth_alias in ['deptho', 'lev', 'ZAX', 'DEPTH', 'depth_std']:
        if (depth_alias in da_or_ds.coords or depth_alias in da_or_ds.dims) and depth_alias != 'depth':
            if 'depth' not in da_or_ds.coords and 'depth' not in da_or_ds.dims:
                rename_dict[depth_alias] = 'depth'
            
    if rename_dict:
        actual_rename = {
            k: v for k, v in rename_dict.items() 
            if (k in da_or_ds.coords or k in da_or_ds.dims) 
            and v not in da_or_ds.dims and v not in da_or_ds.coords
        }
        if actual_rename:
            da_or_ds = da_or_ds.rename(actual_rename)
    return da_or_ds

# =============================================================================
# DATA HARMONIZER & DATASET
# =============================================================================

class DataHarmonizer:
    def __init__(self, lat_grid=LAT_GRID, lon_grid=LON_GRID):
        self.target_lat = lat_grid
        self.target_lon = lon_grid
        self.H = len(self.target_lat)
        self.W = len(self.target_lon)
        self.stats = {}
        
    def regrid_dataarray(self, da):
        da = standardize_coords(da)
        lat_coord = 'latitude' if 'latitude' in da.coords else ('lat' if 'lat' in da.coords else None)
        lon_coord = 'longitude' if 'longitude' in da.coords else ('lon' if 'lon' in da.coords else None)
        
        if lat_coord and lon_coord:
            da_regrid = da.interp(
                {lat_coord: self.target_lat, lon_coord: self.target_lon},
                method='linear'
            )
            dim_order = []
            if 'depth' in da_regrid.dims:
                dim_order.append('depth')
            dim_order.extend(['latitude', 'longitude'])
            dim_order = [d for d in dim_order if d in da_regrid.dims]
            if dim_order:
                da_regrid = da_regrid.transpose(*dim_order)
            return da_regrid.values
        return da.values

    def compute_train_statistics(self, train_vars_dict):
        for var_name, unnorm_3d in train_vars_dict.items():
            valid_pixels = unnorm_3d[~np.isnan(unnorm_3d)]
            mean = float(valid_pixels.mean()) if len(valid_pixels) > 0 else 0.0
            std = float(valid_pixels.std()) if len(valid_pixels) > 0 else 1.0
            self.stats[var_name] = (mean, std)

    def normalize_with_train_stats(self, arr, var_name):
        mask = (~np.isnan(arr)).astype(np.float32)
        clean_arr = np.nan_to_num(arr, nan=0.0)
        mean, std = self.stats.get(var_name, (0.0, 1.0))
        norm_arr = (clean_arr - mean) / (std + 1e-6)
        return norm_arr * mask, mask

# -----------------------------------------------------------------------------
# Strict input checks. No silent fallbacks: a missing variable or a date the file
# does not cover must stop the run, not quietly substitute another field/day.
# -----------------------------------------------------------------------------
def require_var(ds, candidates):
    """Returns the first name in `candidates` present in ds, else raises with what IS in the file."""
    if isinstance(candidates, str):
        candidates = [candidates]
    for c in candidates:
        if c in ds.data_vars:
            return c
    raise KeyError(f"[!] None of {candidates} found. Variables in this file: {list(ds.data_vars)}. "
                   f"Refusing to guess (a positional fallback would silently feed the wrong physical field).")

def check_time_coverage(da, dates, label, tolerance=pd.Timedelta("1D")):
    """Raises unless every requested date has a sample within `tolerance` (no nearest-day extrapolation)."""
    if 'time' not in da.dims:
        raise ValueError(f"[!] {label}: no time dimension; daily data required.")
    t = pd.DatetimeIndex(pd.to_datetime(da['time'].values)).sort_values()
    idx = t.get_indexer(pd.DatetimeIndex(dates), method="nearest")
    gaps = np.abs((t[idx] - pd.DatetimeIndex(dates)).to_numpy())
    if (gaps >= tolerance.to_timedelta64()).any():
        bad = [str(d.date()) for d, g in zip(dates, gaps) if g >= tolerance.to_timedelta64()]
        raise ValueError(f"[!] {label}: file covers {t[0]}..{t[-1]} but these requested dates have no sample "
                         f"within {tolerance}: {bad[:5]}{' ...' if len(bad) > 5 else ''}")


def build_ocean_fields_from_netcdf(data_dir="/kaggle/tmp/ocean_data", start_date="2023-01-01", end_date="2023-01-30",
                                   fixed_stats=None, reference_file="GLORYS12V1.nc", reference_var="thetao"):
    """fixed_stats: {var: (mean, std)} from the training period. Pass it for any period other than the
    training range so inputs are normalised exactly as in training (otherwise stats are recomputed on
    the first 80% of this range, which is only correct for the training range itself).
    reference_file/var: the subsurface temperature used as target / comparison (GLORYS12 for training)."""
    print(f"\n[+] Ingesting & Harmonizing NetCDF datasets from: {data_dir}")
    harmonizer = DataHarmonizer()
    common_dates = pd.date_range(start=start_date, end=end_date, freq="1D")
    
    def get_standardized_da(ds, var_name):
        v = require_var(ds, var_name)
        da = ds[v]
        da = standardize_coords(da)
        check_time_coverage(da, common_dates, v)
        if 'time' in da.dims:
            da = da.interp(time=common_dates, method="nearest", kwargs={"fill_value": "extrapolate"})
        return da

    ds_sst = xr.open_dataset(os.path.join(data_dir, "OSTIA_SST.nc"))
    var_sst = require_var(ds_sst, "analysed_sst")
    da_sst = get_standardized_da(ds_sst, var_sst)
    
    curr_path = os.path.join(data_dir, "COPERNICUS_CURRENTS_SSH.nc")
    if not os.path.exists(curr_path):
        curr_path = os.path.join(data_dir, "COPERNICUS_CURRENTS.nc")
        
    ds_curr = xr.open_dataset(curr_path)
    zos_v = require_var(ds_curr, "zos")
    sss_v = require_var(ds_curr, ["so", "sss"])
    uo_v = require_var(ds_curr, "uo")
    vo_v = require_var(ds_curr, "vo")
    
    da_ssh = get_standardized_da(ds_curr, zos_v)
    da_sss = get_standardized_da(ds_curr, sss_v)
    da_uo = get_standardized_da(ds_curr, uo_v)
    da_vo = get_standardized_da(ds_curr, vo_v)
    
    if 'depth' in da_sss.dims: da_sss = da_sss.isel(depth=0)
    elif 'depth' in da_sss.coords: da_sss = da_sss.isel(depth=0)
    if 'depth' in da_uo.dims: da_uo = da_uo.isel(depth=0)
    elif 'depth' in da_uo.coords: da_uo = da_uo.isel(depth=0)
    if 'depth' in da_vo.dims: da_vo = da_vo.isel(depth=0)
    elif 'depth' in da_vo.coords: da_vo = da_vo.isel(depth=0)

    ds_winds = xr.open_dataset(os.path.join(data_dir, "ERA5_WINDS.nc"))
    u10_v = require_var(ds_winds, "u10")
    v10_v = require_var(ds_winds, "v10")
    da_u10 = get_standardized_da(ds_winds, u10_v)
    da_v10 = get_standardized_da(ds_winds, v10_v)
    
    ds_glorys = xr.open_dataset(os.path.join(data_dir, reference_file))
    thetao_v = require_var(ds_glorys, reference_var)
    da_thetao = standardize_coords(ds_glorys[thetao_v])
    
    depth_dim = 'depth' if ('depth' in da_thetao.coords or 'depth' in da_thetao.dims) else None
    if depth_dim:
        da_thetao = da_thetao.interp({depth_dim: DEPTH_LEVELS}, method="linear", kwargs={"fill_value": "extrapolate"})
    check_time_coverage(da_thetao, common_dates, thetao_v)
    if 'time' in da_thetao.dims:
        da_thetao = da_thetao.interp(time=common_dates, method="nearest", kwargs={"fill_value": "extrapolate"})

    def ensure_2d_surface(arr):
        arr = np.squeeze(arr)
        if arr.ndim == 3:
            arr = arr[0]
        return arr

    num_train_t = max(1, int(0.8 * len(common_dates)))
    var_list = ["sst", "ssh", "sss", "uo", "vo", "u10", "v10"]
    da_list = [da_sst, da_ssh, da_sss, da_uo, da_vo, da_u10, da_v10]
    
    unnorm_train_dict = {
        name: np.array([ensure_2d_surface(harmonizer.regrid_dataarray(da.isel(time=t) if 'time' in da.dims else da)) for t in range(num_train_t)])
        for name, da in zip(var_list, da_list)
    }
    if fixed_stats is not None:
        harmonizer.stats = {k: (float(v[0]), float(v[1])) for k, v in fixed_stats.items()}
        print("[+] Using fixed training-period normalisation statistics (not recomputed).")
    else:
        harmonizer.compute_train_statistics(unnorm_train_dict)
    
    all_surface_tensors, all_target_tensors = [], []
    for t_idx in range(len(common_dates)):
        arrs = [ensure_2d_surface(harmonizer.regrid_dataarray(da.isel(time=t_idx) if 'time' in da.dims else da)) for da in da_list]
        channels = []
        for var_name, var_arr in zip(var_list, arrs):
            norm_arr, mask = harmonizer.normalize_with_train_stats(var_arr, var_name)
            channels.append(norm_arr)
            channels.append(mask)
            
        surface_14ch_t = np.stack(channels, axis=0)
        all_surface_tensors.append(surface_14ch_t)
        thetao_arr = harmonizer.regrid_dataarray(da_thetao.isel(time=t_idx) if 'time' in da_thetao.dims else da_thetao)
        all_target_tensors.append(thetao_arr)
        
    surface_tensor_4d = np.stack(all_surface_tensors, axis=0)
    target_tensor_4d = np.stack(all_target_tensors, axis=0)
    return surface_tensor_4d, target_tensor_4d, common_dates, harmonizer

class OceanPatchDataset(Dataset):
    def __init__(self, surface_4d, target_4d, patch_size=31, time_indices=None):
        self.surface_4d = surface_4d
        self.target_4d = target_4d
        self.patch_size = patch_size
        self.pad = patch_size // 2
        
        T, C, H, W = surface_4d.shape
        self.time_indices = time_indices if time_indices is not None else list(range(T))
        
        self.samples = []
        for t in self.time_indices:
            surf_t = surface_4d[t]
            targ_t = target_4d[t]
            padded_surf = np.pad(surf_t, ((0, 0), (self.pad, self.pad), (self.pad, self.pad)), mode='reflect')
            
            for r in range(H):
                for c in range(W):
                    targ_profile = targ_t[:, r, c]
                    if not np.isnan(targ_profile).any():
                        self.samples.append((t, r, c, padded_surf[:, r:r+patch_size, c:c+patch_size], targ_profile))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        t, r, c, patch, target = self.samples[idx]
        return torch.from_numpy(patch).float(), torch.from_numpy(target).float()

# =============================================================================
# MODEL ARCHITECTURES
# =============================================================================

class BaselineSSTMLP(nn.Module):
    def __init__(self, out_depths=15):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(1, 64),
            nn.ReLU(),
            nn.Linear(64, 128),
            nn.ReLU(),
            nn.Linear(128, out_depths)
        )
    def forward(self, x_sst):
        return self.net(x_sst)

class BaselineMultiVarMLP(nn.Module):
    def __init__(self, in_vars=7, out_depths=15):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_vars, 128),
            nn.ReLU(),
            nn.Linear(128, 256),
            nn.ReLU(),
            nn.Linear(256, out_depths)
        )
    def forward(self, x_vars):
        return self.net(x_vars)

class OceanEmbed(nn.Module):
    def __init__(self, in_channels=14, patch_size=31, embed_dim=128, out_depths=15):
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
            nn.Flatten()
        )
        # Must match the trained checkpoint exactly (kaggle_oceanembed_pipeline.py):
        # a single Linear layer. No LayerNorm / GELU.
        self.embedding = nn.Linear(128, embed_dim)
        self.decoder = nn.Sequential(
            nn.Linear(embed_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, out_depths)
        )
        
    def forward(self, patch):
        feat = self.encoder(patch)
        latent = self.embedding(feat)
        profile = self.decoder(latent)
        return profile, latent

# =============================================================================
# EVALUATION ENGINE
# =============================================================================

def evaluate_model_rmse_true(model_obj, val_loader, model_type="oceanembed"):
    """Unweighted RMSE (°C) over all validation samples and levels, plus RMSE per level."""
    model_obj.eval()
    se_depth = torch.zeros(NUM_DEPTHS, dtype=torch.float64)
    n = 0
    center_idx = 31 // 2
    with torch.no_grad():
        for patches, targets in val_loader:
            targets = targets.to(device)
            if model_type == "b1":
                preds = model_obj(patches[:, 0:1, center_idx, center_idx].to(device))
            elif model_type == "b2":
                preds = model_obj(patches[:, [0, 2, 4, 6, 8, 10, 12], center_idx, center_idx].to(device))
            else:
                preds, _ = model_obj(patches.to(device))
            se_depth += ((preds - targets) ** 2).sum(dim=0).double().cpu()
            n += targets.shape[0]
    per_depth = torch.sqrt(se_depth / max(1, n)).numpy()
    overall = float(np.sqrt(se_depth.sum().item() / max(1, n * NUM_DEPTHS)))
    return overall, per_depth.tolist()


def evaluate_against_incois_argo(model, surface_tensor_4d, common_dates, harmonizer, patch_size=31,
                                 data_dir="/kaggle/tmp/ocean_data", batch_size=256, scatter_n=3000):
    """
    Compares predictions with the INCOIS gridded Argo product (incois_argo_mnt_VAM).
    That product is a MONTHLY gridded analysis of Argo data, not individual float profiles, so:
      * each validation day is matched to the monthly field covering it (tolerance 31 days, reported);
      * the unit counted is "grid-cell-days", not "profiles";
      * levels outside the product's depth range are NOT extrapolated; they are left out per level.
    Returns a dict of statistics (or None if the file is missing).
    """
    print("\n[+] Comparing with the INCOIS gridded monthly Argo analysis...")
    argo_path = os.path.join(data_dir, "INCOIS_ARGO.nc")
    if not os.path.exists(argo_path):
        print(f"[!] INCOIS ARGO NetCDF not found at {argo_path}. Skipping Argo comparison.")
        return None

    ds_argo = xr.open_dataset(argo_path)
    argo_var = require_var(ds_argo, "temp")
    da_argo = standardize_coords(ds_argo[argo_var])
    if 'depth' in da_argo.dims:
        dmin, dmax = float(da_argo['depth'].min()), float(da_argo['depth'].max())
        da_argo = da_argo.interp(depth=DEPTH_LEVELS, method="linear")        # NaN outside [dmin, dmax]
    else:
        raise ValueError("[!] Argo file has no depth dimension")
    check_time_coverage(da_argo, common_dates, "INCOIS Argo (monthly)", tolerance=pd.Timedelta("31D"))
    t_argo = pd.DatetimeIndex(pd.to_datetime(da_argo['time'].values))

    val_start_t = max(0, int(0.8 * len(common_dates)))
    pad = patch_size // 2
    patches_list, targets_list, match_info = [], [], []
    for t_idx in range(val_start_t, len(common_dates)):
        k = int(np.argmin(np.abs((t_argo - common_dates[t_idx]).to_numpy())))
        match_info.append({"day": str(common_dates[t_idx].date()), "argo_field_time": str(t_argo[k].date())})
        argo_regrid = harmonizer.regrid_dataarray(da_argo.isel(time=k))
        padded_surf = np.pad(surface_tensor_4d[t_idx], ((0, 0), (pad, pad), (pad, pad)), mode='reflect')
        rows, cols = np.nonzero(np.isfinite(argo_regrid).any(axis=0))
        for r, c in zip(rows, cols):
            patches_list.append(padded_surf[:, r:r + patch_size, c:c + patch_size])
            targets_list.append(argo_regrid[:, r, c])
    if not patches_list:
        print("[!] No Argo grid cells overlap the validation days.")
        return None

    targets_np = np.stack(targets_list).astype(np.float64)
    preds = []
    model.eval()
    with torch.no_grad():
        for i in range(0, len(patches_list), batch_size):
            b = torch.from_numpy(np.stack(patches_list[i:i + batch_size])).float().to(device)
            preds.append(model(b)[0].cpu().numpy())
    preds_np = np.concatenate(preds).astype(np.float64)

    ok = np.isfinite(targets_np)
    err = np.where(ok, preds_np - targets_np, np.nan)
    n_depth = ok.sum(axis=0)
    rmse_depth = np.sqrt(np.nanmean(err ** 2, axis=0))
    o, p = targets_np[ok], preds_np[ok]
    rmse = float(np.sqrt(np.mean((p - o) ** 2)))
    bias = float(np.mean(p - o))
    mae = float(np.mean(np.abs(p - o)))
    r2 = float(1.0 - np.sum((p - o) ** 2) / np.sum((o - o.mean()) ** 2))
    rng = np.random.default_rng(0)
    pick = rng.choice(o.size, size=min(scatter_n, o.size), replace=False)
    depth_of = np.broadcast_to(DEPTH_LEVELS[None, :], ok.shape)[ok]

    print(f"[✔] {ok.any(axis=1).sum()} grid-cell-days, {o.size} level values: RMSE {rmse:.4f} °C, bias {bias:+.4f} °C, R² {r2:.4f}")
    return {
        "product": "INCOIS gridded monthly Argo analysis (incois_argo_mnt_VAM)",
        "unit": "grid-cell-days (monthly gridded field matched to each validation day)",
        "n_grid_cell_days": int(ok.any(axis=1).sum()),
        "n_values": int(o.size),
        "n_per_depth": n_depth.tolist(),
        "product_depth_range_m": [dmin, dmax],
        "time_matching": match_info,
        "rmse_c": rmse, "mae_c": mae, "bias_c": bias, "r2": r2,
        "rmse_by_depth_c": [None if not np.isfinite(v) else float(v) for v in rmse_depth],
        "scatter_sample": {"observed_c": o[pick].round(3).tolist(), "predicted_c": p[pick].round(3).tolist(),
                           "depth_m": depth_of[pick].tolist(), "n": int(pick.size), "seed": 0},
    }


def run_evaluation(data_dir="/kaggle/tmp/ocean_data", start_date="2023-01-01", end_date="2023-01-30",
                   ckpt_dir=".", out_json="basin_output/eval_results.json"):
    import json, hashlib, datetime as _dt
    print("=" * 75)
    print("OceanEmbed — Checkpoint Evaluation")
    print("=" * 75)
    surface_14ch_tensor, glorys_target_4d, common_dates, harmonizer = build_ocean_fields_from_netcdf(
        data_dir=data_dir, start_date=start_date, end_date=end_date)
    num_dates = len(common_dates)
    val_indices = list(range(int(0.8 * num_dates), num_dates))
    val_dataset = OceanPatchDataset(surface_14ch_tensor, glorys_target_4d, patch_size=31, time_indices=val_indices)
    val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False)
    print(f"[+] Validation set: {len(val_dataset)} samples on {len(val_indices)} held-out days.")

    def sha(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()

    models = []
    specs = [("Baseline 1: SST-only MLP", "best_b1_model.pth", "b1", "SST at the cell (1 value)", lambda: BaselineSSTMLP(out_depths=15)),
             ("Baseline 2: multi-variable MLP", "best_b2_model.pth", "b2", "7 surface variables at the cell", lambda: BaselineMultiVarMLP(in_vars=7, out_depths=15)),
             ("OceanEmbed CNN", "best_oceanembed_model.pth", "oceanembed", "14-channel 31x31 patch", lambda: OceanEmbed(in_channels=14, patch_size=31, embed_dim=128, out_depths=15))]
    oceanembed = None
    for name, fname, kind, inputs, ctor in specs:
        path = os.path.join(ckpt_dir, fname)
        if not os.path.exists(path):
            print(f"[!] {fname} not found: {name} not evaluated (no value is reported).")
            models.append({"model": name, "inputs": inputs, "checkpoint": fname, "evaluated": False})
            continue
        m = ctor().to(device)
        m.load_state_dict(torch.load(path, map_location=device), strict=True)
        rmse, per_depth = evaluate_model_rmse_true(m, val_loader, model_type=kind)
        print(f"[✔] {name}: RMSE vs GLORYS on held-out days = {rmse:.4f} °C")
        models.append({"model": name, "inputs": inputs, "checkpoint": fname, "checkpoint_sha256": sha(path),
                       "evaluated": True, "glorys_heldout_rmse_c": rmse, "glorys_heldout_rmse_by_depth_c": per_depth})
        if kind == "oceanembed":
            oceanembed = m
    if oceanembed is None:
        raise FileNotFoundError("best_oceanembed_model.pth not found")

    argo = evaluate_against_incois_argo(oceanembed, surface_14ch_tensor, common_dates, harmonizer, data_dir=data_dir)
    for mdl in models:
        if mdl["model"] == "OceanEmbed CNN":
            mdl["argo"] = argo

    results = {
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "date_range": f"{start_date}..{end_date}",
        "heldout_days": [str(common_dates[i].date()) for i in val_indices],
        "n_validation_samples": len(val_dataset),
        "depth_levels_m": DEPTH_LEVELS.tolist(),
        "models": models,
        "glorys_note": "GLORYS12 is a reanalysis (model product) and was the training target; agreement with it is teacher-consistency, not observation skill.",
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[✔] Wrote {out_json}")
    return results


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="/kaggle/tmp/ocean_data")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2023-01-30")
    ap.add_argument("--ckpt-dir", default=".")
    ap.add_argument("--out", default="basin_output/eval_results.json")
    a = ap.parse_args()
    run_evaluation(a.data_dir, a.start, a.end, a.ckpt_dir, a.out)
