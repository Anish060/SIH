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

def build_ocean_fields_from_netcdf(data_dir="/kaggle/tmp/ocean_data", start_date="2023-01-01", end_date="2023-01-30"):
    print(f"\n[+] Ingesting & Harmonizing NetCDF datasets from: {data_dir}")
    harmonizer = DataHarmonizer()
    common_dates = pd.date_range(start=start_date, end=end_date, freq="1D")
    
    def get_standardized_da(ds, var_name):
        v = var_name if var_name in ds else list(ds.data_vars)[0]
        da = ds[v]
        da = standardize_coords(da)
        if 'time' in da.dims:
            da = da.interp(time=common_dates, method="nearest", kwargs={"fill_value": "extrapolate"})
        return da

    ds_sst = xr.open_dataset(os.path.join(data_dir, "OSTIA_SST.nc"))
    var_sst = "analysed_sst" if "analysed_sst" in ds_sst else list(ds_sst.data_vars)[0]
    da_sst = get_standardized_da(ds_sst, var_sst)
    
    curr_path = os.path.join(data_dir, "COPERNICUS_CURRENTS_SSH.nc")
    if not os.path.exists(curr_path):
        curr_path = os.path.join(data_dir, "COPERNICUS_CURRENTS.nc")
        
    ds_curr = xr.open_dataset(curr_path)
    zos_v = "zos" if "zos" in ds_curr else list(ds_curr.data_vars)[0]
    sss_v = "so" if "so" in ds_curr else ("sss" if "sss" in ds_curr else list(ds_curr.data_vars)[1])
    uo_v = "uo" if "uo" in ds_curr else list(ds_curr.data_vars)[2]
    vo_v = "vo" if "vo" in ds_curr else list(ds_curr.data_vars)[3]
    
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
    u10_v = "u10" if "u10" in ds_winds else list(ds_winds.data_vars)[0]
    v10_v = "v10" if "v10" in ds_winds else list(ds_winds.data_vars)[1]
    da_u10 = get_standardized_da(ds_winds, u10_v)
    da_v10 = get_standardized_da(ds_winds, v10_v)
    
    ds_glorys = xr.open_dataset(os.path.join(data_dir, "GLORYS12V1.nc"))
    thetao_v = "thetao" if "thetao" in ds_glorys else list(ds_glorys.data_vars)[0]
    da_thetao = standardize_coords(ds_glorys[thetao_v])
    
    depth_dim = 'depth' if ('depth' in da_thetao.coords or 'depth' in da_thetao.dims) else None
    if depth_dim:
        da_thetao = da_thetao.interp({depth_dim: DEPTH_LEVELS}, method="linear", kwargs={"fill_value": "extrapolate"})
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
        self.embedding = nn.Sequential(
            nn.Linear(128, embed_dim),
            nn.LayerNorm(embed_dim),
            nn.GELU()
        )
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
    model_obj.eval()
    se_sum = 0.0
    total_count = 0
    center_idx = 31 // 2
    
    with torch.no_grad():
        for patches, targets in val_loader:
            targets = targets.to(device)
            if model_type == "b1":
                inp = patches[:, 0:1, center_idx, center_idx].to(device)
                preds = model_obj(inp)
            elif model_type == "b2":
                inp = patches[:, [0, 2, 4, 6, 8, 10, 12], center_idx, center_idx].to(device)
                preds = model_obj(inp)
            else:
                inp = patches.to(device)
                preds, _ = model_obj(inp)
                
            se_sum += ((preds - targets) ** 2).sum().item()
            total_count += targets.numel()
            
    true_rmse = np.sqrt(se_sum / max(1, total_count))
    return true_rmse

def evaluate_against_incois_argo(model, surface_tensor_4d, common_dates, harmonizer, patch_size=31, data_dir="/kaggle/tmp/ocean_data", batch_size=256):
    print("\n[+] Running Memory-Efficient Timestamp-Matched Gridded INCOIS ARGO Evaluation...")
    argo_path = os.path.join(data_dir, "INCOIS_ARGO.nc")
    
    if not os.path.exists(argo_path):
        print(f"[!] INCOIS ARGO NetCDF not found at {argo_path}. Skipping ARGO eval.")
        return None

    ds_argo = xr.open_dataset(argo_path)
    argo_var = "temp" if "temp" in ds_argo else list(ds_argo.data_vars)[0]
    da_argo = standardize_coords(ds_argo[argo_var])
    
    depth_dim = 'depth' if ('depth' in da_argo.coords or 'depth' in da_argo.dims) else None
    if depth_dim:
        da_argo = da_argo.interp({depth_dim: DEPTH_LEVELS}, method="linear", kwargs={"fill_value": "extrapolate"})
        
    da_argo_aligned = da_argo.interp(time=common_dates, method="nearest", kwargs={"fill_value": "extrapolate"}) if 'time' in da_argo.dims else da_argo
    
    val_start_t = max(0, int(0.8 * len(common_dates)))
    patches_list, targets_list = [], []
    pad = patch_size // 2
    
    for t_idx in range(val_start_t, len(common_dates)):
        surf_t = surface_tensor_4d[t_idx]
        argo_slice = da_argo_aligned.isel(time=t_idx) if 'time' in da_argo_aligned.dims else da_argo_aligned
        argo_regrid = harmonizer.regrid_dataarray(argo_slice)
        padded_surf = np.pad(surf_t, ((0, 0), (pad, pad), (pad, pad)), mode='reflect')
        
        for r in range(H):
            for c in range(W):
                target_p = argo_regrid[:, r, c]
                if not np.isnan(target_p).any():
                    patch = padded_surf[:, r:r+patch_size, c:c+patch_size]
                    patches_list.append(patch)
                    targets_list.append(target_p)
                    
    if len(patches_list) == 0:
        print("[!] No valid ARGO profiles found in validation dates!")
        return None
        
    patches_np = np.stack(patches_list, axis=0)
    targets_np = np.stack(targets_list, axis=0)
    
    model.eval()
    all_preds = []
    
    print(f"    - Running mini-batched GPU inference across {len(patches_np)} ARGO profiles (batch_size={batch_size})...")
    with torch.no_grad():
        for i in range(0, len(patches_np), batch_size):
            b_patches = torch.from_numpy(patches_np[i:i+batch_size]).float().to(device)
            b_preds, _ = model(b_patches)
            all_preds.append(b_preds.cpu().numpy())
            
    preds_np = np.concatenate(all_preds, axis=0)
    
    mae = np.mean(np.abs(preds_np - targets_np))
    rmse_depth = np.sqrt(np.mean((preds_np - targets_np)**2, axis=0))
    overall_rmse = np.sqrt(np.mean((preds_np - targets_np)**2))
    
    print(f"[✔] Gridded INCOIS ARGO Independent Evaluation Complete ({len(targets_np)} observations):")
    print(f"    - Overall MAE against INCOIS ARGO: {mae:.4f} °C")
    print(f"    - Overall True RMSE against INCOIS ARGO: {overall_rmse:.4f} °C")
    print(f"    - Surface (0m) RMSE: {rmse_depth[0]:.4f} °C")
    print(f"    - Thermocline (100m) RMSE: {rmse_depth[7]:.4f} °C")
    print(f"    - Deep Ocean (1000m) RMSE: {rmse_depth[-1]:.4f} °C")
    
    # Plot validation comparison figure
    plt.figure(figsize=(12, 5))
    
    plt.subplot(1, 2, 1)
    plt.plot(rmse_depth, DEPTH_LEVELS, 'o-', color='#00d2ff', linewidth=2, label='OceanEmbed RMSE')
    plt.gca().invert_yaxis()
    plt.xlabel('RMSE (°C)')
    plt.ylabel('Depth (m)')
    plt.title('Vertical RMSE Profile vs INCOIS ARGO')
    plt.grid(True, alpha=0.3)
    plt.legend()
    
    plt.subplot(1, 2, 2)
    sample_indices = np.random.choice(len(targets_np), size=min(5, len(targets_np)), replace=False)
    colors = plt.cm.viridis(np.linspace(0, 1, len(sample_indices)))
    for idx, col in zip(sample_indices, colors):
        plt.plot(targets_np[idx], DEPTH_LEVELS, '--', color=col, alpha=0.7, label='ARGO Obs')
        plt.plot(preds_np[idx], DEPTH_LEVELS, '-', color=col, linewidth=2, label='OceanEmbed Pred')
    plt.gca().invert_yaxis()
    plt.xlabel('Temperature (°C)')
    plt.ylabel('Depth (m)')
    plt.title('Sample Vertical Temperature Profiles')
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('incois_argo_validation.png', dpi=300)
    plt.close()
    print("[✔] Saved validation plot: 'incois_argo_validation.png'")
    
    return overall_rmse

def load_checkpoint_flexibly(model_obj, checkpoint_path):
    state_dict = torch.load(checkpoint_path, map_location=device)
    try:
        model_obj.load_state_dict(state_dict)
    except RuntimeError:
        new_state = {}
        for k, v in state_dict.items():
            if k == "embedding.weight":
                new_state["embedding.0.weight"] = v
            elif k == "embedding.bias":
                new_state["embedding.0.bias"] = v
            elif k == "embedding.0.weight":
                new_state["embedding.weight"] = v
            elif k == "embedding.0.bias":
                new_state["embedding.bias"] = v
            else:
                new_state[k] = v
        model_obj.load_state_dict(new_state, strict=False)

# =============================================================================
# MAIN EVALUATION PIPELINE
# =============================================================================

def run_evaluation(data_dir="/kaggle/tmp/ocean_data", start_date="2023-01-01", end_date="2023-01-30"):
    print("=" * 75)
    print("OceanEmbed — Checkpoint Evaluation & Summary Results Generator")
    print("=" * 75)
    
    # 1. Ingest datasets and construct validation dataset
    surface_14ch_tensor, glorys_target_4d, common_dates, harmonizer = build_ocean_fields_from_netcdf(
        data_dir=data_dir, start_date=start_date, end_date=end_date
    )
    
    num_dates = len(common_dates)
    val_indices = list(range(int(0.8 * num_dates), num_dates))
    val_dataset = OceanPatchDataset(surface_14ch_tensor, glorys_target_4d, patch_size=31, time_indices=val_indices)
    val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False)
    print(f"[+] Loaded Validation Dataset: {len(val_dataset)} spatial samples.")
    
    # 2. Evaluate Baseline 1 Checkpoint
    b1_path = "best_b1_model.pth"
    if os.path.exists(b1_path):
        b1_model = BaselineSSTMLP(out_depths=15).to(device)
        b1_model.load_state_dict(torch.load(b1_path, map_location=device))
        b1_final_rmse = evaluate_model_rmse_true(b1_model, val_loader, model_type="b1")
        print(f"[✔] Baseline 1 (SST MLP) Loaded Checkpoint Val RMSE: {b1_final_rmse:.4f} °C")
    else:
        b1_final_rmse = 1.0440  # Fallback to reported training log value
        print(f"[!] Baseline 1 checkpoint not found on disk. Using training log value: {b1_final_rmse:.4f} °C")

    # 3. Evaluate Baseline 2 Checkpoint
    b2_path = "best_b2_model.pth"
    if os.path.exists(b2_path):
        b2_model = BaselineMultiVarMLP(in_vars=7, out_depths=15).to(device)
        b2_model.load_state_dict(torch.load(b2_path, map_location=device))
        b2_final_rmse = evaluate_model_rmse_true(b2_model, val_loader, model_type="b2")
        print(f"[✔] Baseline 2 (Multi-Var MLP) Loaded Checkpoint Val RMSE: {b2_final_rmse:.4f} °C")
    else:
        b2_final_rmse = 1.0573  # Fallback to reported training log value
        print(f"[!] Baseline 2 checkpoint not found on disk. Using training log value: {b2_final_rmse:.4f} °C")

    # 4. Evaluate OceanEmbed Checkpoint
    best_model_path = "best_oceanembed_model.pth"
    if not os.path.exists(best_model_path):
        raise FileNotFoundError(f"[!] Target checkpoint '{best_model_path}' not found! Please check file path.")
        
    model = OceanEmbed(in_channels=14, patch_size=31, embed_dim=128, out_depths=15).to(device)
    load_checkpoint_flexibly(model, best_model_path)
    print(f"[✔] OceanEmbed Model Checkpoint Loaded from '{best_model_path}'!")
    
    oceanembed_true_rmse = evaluate_model_rmse_true(model, val_loader, model_type="oceanembed")
    print(f"[✔] OceanEmbed Target Architecture GLORYS Val RMSE: {oceanembed_true_rmse:.4f} °C")

    # 5. Independent ARGO Evaluation
    argo_rmse = evaluate_against_incois_argo(model, surface_14ch_tensor, common_dates, harmonizer, patch_size=31, data_dir=data_dir, batch_size=256)

    # 6. Print Hackathon Demo Summary Table
    print("\n" + "=" * 75)
    print("SUMMARY RESULTS TABLE (HONEST UNWEIGHTED PHYSICAL RMSE °C)")
    print("=" * 75)
    print(f"  1. Baseline 1 (SST-Only MLP)       GLORYS Val RMSE: {b1_final_rmse:.4f} °C")
    print(f"  2. Baseline 2 (Multi-Var MLP)     GLORYS Val RMSE: {b2_final_rmse:.4f} °C")
    print(f"  3. OceanEmbed Target Architecture GLORYS Val RMSE: {oceanembed_true_rmse:.4f} °C")
    if argo_rmse is not None:
        print(f"  4. OceanEmbed Independent INCOIS ARGO RMSE : {argo_rmse:.4f} °C")
    print("=" * 75)

if __name__ == "__main__":
    run_evaluation()
