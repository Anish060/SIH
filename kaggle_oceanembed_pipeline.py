"""
===============================================================================
OceanEmbed — Multi-Source Ocean NetCDF Ingestion, Harmonization & Training
Team OceanSATX | SIH 2026 | Problem Statement 26066
===============================================================================
Production-Grade Features & Coordinate Standardizer:
  ✔ Standardizes `valid_time` (ERA5), `TIME` (ARGO), `lat`/`lon` to standard `('time', 'latitude', 'longitude')`
  ✔ Flexible filename check: handles `COPERNICUS_CURRENTS.nc` or `COPERNICUS_CURRENTS_SSH.nc`
  ✔ Auto-installs missing dependencies (`copernicusmarine`, `cdsapi`) if missing
  ✔ Handles INCOIS ERDDAP SSL Certificate Bypassing (`verify=False`)
  ✔ 100% Real NetCDF Ingestion & Strict File Verification (no synthetic fallback)
  ✔ GLORYS thetao Depth Extrapolation (`kwargs={"fill_value": "extrapolate"}`)
  ✔ True Unweighted RMSE (°C) Evaluation for Summary Results Table
  ✔ Fair 20-Epoch Training across Baselines & OceanEmbed
  ✔ Baseline 1, Baseline 2 & OceanEmbed Checkpoint Saving
  ✔ 7 Surface Input Variables (SST, SSH, SSS, Uo, Vo, U10, V10) + 7 Masks = 14 Channels
  ✔ Depth Bounds (0-1000m) added to copernicusmarine.subset calls for fast downloads
  ✔ ARGO 0m Depth Extrapolation handled (fill_value="extrapolate")
  ✔ Zero-Leakage Normalization (Stats calculated on Training Days ONLY)
===============================================================================
"""

import os
import sys
import subprocess
import requests
import numpy as np
import pandas as pd
import xarray as xr
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import matplotlib.pyplot as plt
import seaborn as sns
import urllib3

# Suppress SSL warnings for ERDDAP endpoints with unverified local certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Auto-install missing packages if running locally or in fresh environment
for pkg in ["copernicusmarine", "cdsapi"]:
    try:
        __import__(pkg)
    except ImportError:
        print(f"[+] Package '{pkg}' missing. Installing automatically via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])

# Set seed for reproducibility
torch.manual_seed(42)
np.random.seed(42)

# =============================================================================
# 1. DOMAIN & DATASET CONFIGURATION
# =============================================================================
LAT_MIN, LAT_MAX = 5.0, 30.0     # Bay of Bengal / North Indian Ocean
LON_MIN, LON_MAX = 45.0, 105.0
GRID_RES = 0.25                  # Common 0.25 degree target grid

# 15 Standard depth levels (meters)
DEPTH_LEVELS = np.array([0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000])
NUM_DEPTHS = len(DEPTH_LEVELS)

# Grid dimensions
LAT_GRID = np.arange(LAT_MIN, LAT_MAX + GRID_RES, GRID_RES) # ~101 points
LON_GRID = np.arange(LON_MIN, LON_MAX + GRID_RES, GRID_RES) # ~241 points
H, W = len(LAT_GRID), len(LON_GRID)

PRODUCT_CATALOG = {
    "GLORYS12V1": {
        "product_id": "GLOBAL_MULTIYEAR_PHY_001_030",
        "dataset_id": "cmems_mod_glo_phy_my_0.083deg_P1D-m",
        "vars": ["thetao"]
    },
    "INCOIS_ARGO": {
        "erddap_url": "https://erddap.incois.gov.in/erddap/griddap/incois_argo_mnt_VAM",
        "vars": ["temp"]
    },
    "ERA5_WINDS": {
        "dataset_id": "reanalysis-era5-single-levels",
        "vars": ["10m_u_component_of_wind", "10m_v_component_of_wind"]
    },
    "OSTIA_SST": {
        "product_id": "SST_GLO_SST_L4_REP_OBSERVATIONS_010_011",
        "dataset_id": "METOFFICE-GLO-SST-L4-REP-OBS-SST",
        "vars": ["analysed_sst"]
    },
    "COPERNICUS_CURRENTS_SSH": {
        "product_id": "GLOBAL_ANALYSISFORECAST_PHY_001_024",
        "dataset_id": "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m",
        "vars": ["uo", "vo", "zos", "so"]
    }
}

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"[+] Active Compute Engine: {device}")

# =============================================================================
# HELPER: COORDINATE STANDARDIZER
# =============================================================================

def standardize_coords(da_or_ds):
    """
    Renames variant coordinate and dimension names (valid_time, TIME, lat, lon, ZAX)
    to standard CF names: ('time', 'latitude', 'longitude', 'depth').
    """
    rename_dict = {}
    
    # Time aliases
    for t_alias in ['valid_time', 'TIME', 'time_counter']:
        if (t_alias in da_or_ds.coords or t_alias in da_or_ds.dims) and t_alias != 'time':
            if 'time' not in da_or_ds.coords and 'time' not in da_or_ds.dims:
                rename_dict[t_alias] = 'time'
            
    # Latitude aliases
    for lat_alias in ['lat', 'LATITUDE', 'nav_lat']:
        if (lat_alias in da_or_ds.coords or lat_alias in da_or_ds.dims) and lat_alias != 'latitude':
            if 'latitude' not in da_or_ds.coords and 'latitude' not in da_or_ds.dims:
                rename_dict[lat_alias] = 'latitude'
            
    # Longitude aliases
    for lon_alias in ['lon', 'LONGITUDE', 'nav_lon']:
        if (lon_alias in da_or_ds.coords or lon_alias in da_or_ds.dims) and lon_alias != 'longitude':
            if 'longitude' not in da_or_ds.coords and 'longitude' not in da_or_ds.dims:
                rename_dict[lon_alias] = 'longitude'

    # Depth aliases
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
# 2. REAL DATA INGESTION & STRICT FILE CHECKER
# =============================================================================

class OceanDataFetcher:
    """Handles downloading real NetCDF data from Copernicus Marine, INCOIS ERDDAP, and ERA5 CDS."""
    
    def __init__(self, output_dir="/kaggle/tmp/ocean_data"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
    def fetch_all_datasets(self, start_date="2023-01-01", end_date="2023-01-30", username=None, password=None):
        """Fetch products for target date range into real NetCDF files."""
        print(f"[+] Initiating multi-source NetCDF data downloads ({start_date} to {end_date})...")
        
        # 1. Copernicus Products with depth bounds (0 - 1000m)
        try:
            import copernicusmarine
            if username and password:
                print("[+] Logging in to Copernicus Marine Service...")
                copernicusmarine.login(username=username, password=password)
                
            for key in ["GLORYS12V1", "OSTIA_SST", "COPERNICUS_CURRENTS_SSH"]:
                cfg = PRODUCT_CATALOG[key]
                out_path = os.path.join(self.output_dir, f"{key}.nc")
                
                alt_path = os.path.join(self.output_dir, "COPERNICUS_CURRENTS.nc") if key == "COPERNICUS_CURRENTS_SSH" else out_path
                if os.path.exists(out_path) or os.path.exists(alt_path):
                    print(f"    - Dataset {key} already exists on disk. Skipping download.")
                    continue
                    
                print(f"    - Subsetting Copernicus {key} -> {out_path}")
                
                kwargs = {
                    "dataset_id": cfg["dataset_id"],
                    "variables": cfg["vars"],
                    "minimum_latitude": LAT_MIN, "maximum_latitude": LAT_MAX,
                    "minimum_longitude": LON_MIN, "maximum_longitude": LON_MAX,
                    "start_datetime": start_date, "end_datetime": end_date,
                    "output_directory": self.output_dir, "output_filename": f"{key}.nc"
                }
                if key in ["GLORYS12V1", "COPERNICUS_CURRENTS_SSH"]:
                    kwargs["minimum_depth"] = 0.0
                    kwargs["maximum_depth"] = 1000.0
                    
                copernicusmarine.subset(**kwargs)
        except Exception as e:
            print(f"[!] Copernicus API download error: {e}")

        # 2. ERA5 Wind Reanalysis via CDS API
        out_era5 = os.path.join(self.output_dir, "ERA5_WINDS.nc")
        if not os.path.exists(out_era5):
            try:
                print("    - Downloading ERA5 Winds via CDS API...")
                import cdsapi
                c = cdsapi.Client()
                
                dates_seq = pd.date_range(start_date, end_date, freq='D')
                years = sorted(list(set([str(d.year) for d in dates_seq])))
                months = sorted(list(set([f"{d.month:02d}" for d in dates_seq])))
                
                c.retrieve(
                    'reanalysis-era5-single-levels',
                    {
                        'product_type': 'reanalysis',
                        'variable': ['10m_u_component_of_wind', '10m_v_component_of_wind'],
                        'year': years if len(years) > 1 else years[0],
                        'month': months,
                        'day': [f"{d:02d}" for d in range(1, 32)],
                        'time': '12:00',
                        'area': [LAT_MAX, LON_MIN, LAT_MIN, LON_MAX],
                        'format': 'netcdf',
                    },
                    out_era5
                )
                print(f"[✔] Downloaded ERA5_WINDS.nc")
            except Exception as e:
                print(f"[!] CDS API download error for ERA5 Winds: {e}")
        else:
            print(f"    - Dataset ERA5_WINDS.nc already exists on disk. Skipping download.")

        # 3. INCOIS ARGO via ERDDAP
        out_argo = os.path.join(self.output_dir, "INCOIS_ARGO.nc")
        if not os.path.exists(out_argo):
            try:
                url = f"{PRODUCT_CATALOG['INCOIS_ARGO']['erddap_url']}.nc"
                query = f"?temp[({start_date}T00:00:00Z):1:({end_date}T00:00:00Z)][][({LAT_MIN}):1:({LAT_MAX})][({LON_MIN}):1:({LON_MAX})]"
                print(f"    - Querying INCOIS ERDDAP: {url + query}")
                r = requests.get(url + query, stream=True, timeout=30, verify=False)
                if r.status_code == 200:
                    with open(out_argo, 'wb') as f:
                        f.write(r.content)
                    print(f"[✔] Downloaded INCOIS_ARGO.nc")
                else:
                    print(f"[!] INCOIS ERDDAP returned HTTP status code: {r.status_code}")
            except Exception as e:
                print(f"[!] INCOIS ERDDAP download error: {e}")
        else:
            print(f"    - Dataset INCOIS_ARGO.nc already exists on disk. Skipping download.")

        self.verify_disk_netcdfs_exist()

    def verify_disk_netcdfs_exist(self):
        """Fails loudly if required NetCDF files are missing from disk."""
        curr_path = os.path.join(self.output_dir, "COPERNICUS_CURRENTS_SSH.nc")
        if not os.path.exists(curr_path):
            alt_curr = os.path.join(self.output_dir, "COPERNICUS_CURRENTS.nc")
            if os.path.exists(alt_curr):
                curr_path = alt_curr
                
        required_files = ["OSTIA_SST.nc", curr_path, "ERA5_WINDS.nc", "GLORYS12V1.nc", "INCOIS_ARGO.nc"]
        missing = [f for f in required_files if not os.path.exists(os.path.join(self.output_dir, f))]
        
        if missing:
            raise FileNotFoundError(
                f"\n[!] MISSING REQUIRED REAL DATASETS: {missing}\n"
                f"Location checked: {self.output_dir}\n"
                f"Please ensure real NetCDF files are downloaded via Copernicus Marine, CDS API, or ERDDAP."
            )
        print("[✔] All required NetCDF datasets verified on disk!")

# =============================================================================
# 3. HARMONIZATION & ZERO-LEAKAGE NORMALIZATION ENGINE
# =============================================================================

class DataHarmonizer:
    """Regrids, masks, and standardizes multi-source NetCDF inputs to common 0.25° grid."""
    
    def __init__(self, lat_grid=LAT_GRID, lon_grid=LON_GRID):
        self.target_lat = lat_grid
        self.target_lon = lon_grid
        self.H = len(self.target_lat)
        self.W = len(self.target_lon)
        self.stats = {}
        
    def regrid_dataarray(self, da):
        """Bilinear interpolation of an xarray DataArray to target grid."""
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
        """Calculates per-variable mean and std strictly on training set dates to prevent data leakage."""
        for var_name, unnorm_3d in train_vars_dict.items():
            valid_pixels = unnorm_3d[~np.isnan(unnorm_3d)]
            mean = float(valid_pixels.mean()) if len(valid_pixels) > 0 else 0.0
            std = float(valid_pixels.std()) if len(valid_pixels) > 0 else 1.0
            self.stats[var_name] = (mean, std)
            print(f"    - Training Stat [{var_name}]: mean = {mean:.4f}, std = {std:.4f}")

    def normalize_with_train_stats(self, arr, var_name):
        """Normalizes arrays using stored training-set statistics ONLY."""
        mask = (~np.isnan(arr)).astype(np.float32)
        clean_arr = np.nan_to_num(arr, nan=0.0)
        
        mean, std = self.stats.get(var_name, (0.0, 1.0))
        norm_arr = (clean_arr - mean) / (std + 1e-6)
        norm_arr = norm_arr * mask
        return norm_arr, mask

def build_ocean_fields_from_netcdf(data_dir="/kaggle/tmp/ocean_data", start_date="2023-01-01", end_date="2023-01-30"):
    """
    Opens NetCDF files, standardizes coordinates (converting valid_time/TIME to time),
    extracts surface slices (depth=0 for 3D SSS/currents), interpolates vertical depths for GLORYS target,
    aligns datetimes, computes training-period-only normalization statistics,
    and constructs aligned 14-channel surface & GLORYS 15-depth target tensors.
    """
    print(f"\n[+] Ingesting & Harmonizing NetCDF datasets from: {data_dir}")
    harmonizer = DataHarmonizer()
    
    # 1. Target Datetime Index
    common_dates = pd.date_range(start=start_date, end=end_date, freq="1D")
    print(f"[+] Datetime Alignment Index: {len(common_dates)} daily steps ({start_date} to {end_date})")
    
    def get_standardized_da(ds, var_name):
        v = var_name if var_name in ds else list(ds.data_vars)[0]
        da = ds[v]
        da = standardize_coords(da)
        if 'time' in da.dims:
            da = da.interp(time=common_dates, method="nearest", kwargs={"fill_value": "extrapolate"})
        return da

    # 2. Open NetCDF DataArrays & Standardize Coordinates
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
    
    # Slice surface depth (depth=0) for 3D ocean fields (SSS, Uo, Vo)
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
    
    # 3. GLORYS12V1 Subsurface Target & Explicit Vertical Depth Interpolation WITH EXTRAPOLATION FOR 0m LEVEL
    ds_glorys = xr.open_dataset(os.path.join(data_dir, "GLORYS12V1.nc"))
    thetao_v = "thetao" if "thetao" in ds_glorys else list(ds_glorys.data_vars)[0]
    da_thetao = standardize_coords(ds_glorys[thetao_v])
    
    depth_dim = 'depth' if ('depth' in da_thetao.coords or 'depth' in da_thetao.dims) else None
    if depth_dim:
        print(f"[+] Interpolating GLORYS thetao along depth dimension '{depth_dim}' onto 15 target levels (with 0m extrapolation)...")
        da_thetao = da_thetao.interp({depth_dim: DEPTH_LEVELS}, method="linear", kwargs={"fill_value": "extrapolate"})
        
    if 'time' in da_thetao.dims:
        da_thetao = da_thetao.interp(time=common_dates, method="nearest", kwargs={"fill_value": "extrapolate"})

    def ensure_2d_surface(arr):
        """Guarantees surface variable arrays are strictly 2D of shape (H, W)."""
        arr = np.squeeze(arr)
        if arr.ndim == 3:
            arr = arr[0]
        return arr

    # 4. Extract unnormalized spatial fields to compute Training-Set-Only statistics
    num_train_t = max(1, int(0.8 * len(common_dates)))
    var_list = ["sst", "ssh", "sss", "uo", "vo", "u10", "v10"]
    da_list = [da_sst, da_ssh, da_sss, da_uo, da_vo, da_u10, da_v10]
    
    unnorm_train_dict = {
        name: np.array([ensure_2d_surface(harmonizer.regrid_dataarray(da.isel(time=t) if 'time' in da.dims else da)) for t in range(num_train_t)])
        for name, da in zip(var_list, da_list)
    }
    
    print("\n[+] Computing Zero-Leakage Normalization Statistics (Train Period Only):")
    harmonizer.compute_train_statistics(unnorm_train_dict)
    
    # 5. Build 14-channel surface tensor & target 15-depth tensor
    all_surface_tensors = []
    all_target_tensors = []
    
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
        
    surface_tensor_4d = np.stack(all_surface_tensors, axis=0) # (T, 14, H, W)
    target_tensor_4d = np.stack(all_target_tensors, axis=0)   # (T, 15, H, W)
    
    # Sanity check: confirm depth 0 m is NOT all-NaN
    nan_frac_0m = np.isnan(target_tensor_4d[:, 0]).mean()
    print(f"\n[✔] Target Field Verification: GLORYS thetao depth 0m NaN fraction: {nan_frac_0m:.4f}")
    if nan_frac_0m == 1.0:
        raise ValueError("[!] ERROR: GLORYS thetao at depth 0m is 100% NaN! Check depth interpolation.")
        
    print(f"[✔] Multi-Source 14-Channel Processing Complete:")
    print(f"    - Aligned Surface Tensor: {surface_tensor_4d.shape} (T, 14 channels, H, W)")
    print(f"    - GLORYS Subsurface Target Tensor: {target_tensor_4d.shape} (T, 15 depths, H, W)")
    
    return surface_tensor_4d, target_tensor_4d, common_dates, harmonizer

# =============================================================================
# 4. PYTORCH DATASET WITH TEMPORAL HOLDOUT SPLIT
# =============================================================================

class RealOceanPatchDataset(Dataset):
    """
    Extracts 31x31 spatial patches from NetCDF surface tensor (14 channels)
    and pairs them with real GLORYS 15-depth target profiles across aligned time steps.
    """
    def __init__(self, surface_4d_tensor, target_4d_tensor, patch_size=31, time_split="train"):
        T, C, H, W = surface_4d_tensor.shape
        split_t = max(1, int(0.8 * T))
        
        if time_split == "train":
            t_indices = list(range(0, split_t))
        else:
            t_indices = list(range(split_t, T)) if split_t < T else list(range(0, T))
            
        self.surface_tensor = torch.from_numpy(surface_4d_tensor[t_indices]).float()
        self.target_profiles = torch.from_numpy(target_4d_tensor[t_indices]).float()
        self.patch_size = patch_size
        self.pad = patch_size // 2
        
        self.padded_surface = torch.nn.functional.pad(
            self.surface_tensor, 
            (self.pad, self.pad, self.pad, self.pad), 
            mode='reflect'
        )
        
        self.samples = []
        for t_idx in range(len(t_indices)):
            valid_mask = ~torch.isnan(self.target_profiles[t_idx, 0])
            valid_indices = torch.nonzero(valid_mask, as_tuple=False)
            
            for idx in range(len(valid_indices)):
                r, c = valid_indices[idx][0].item(), valid_indices[idx][1].item()
                if not torch.isnan(self.target_profiles[t_idx, :, r, c]).any():
                    self.samples.append((t_idx, r, c))
                    
        print(f"[+] Dataset ({time_split} set): {len(self.samples)} valid ocean patch samples across {len(t_indices)} days.")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        t_idx, r, c = self.samples[idx]
        r_pad, c_pad = r + self.pad, c + self.pad
        
        patch = self.padded_surface[
            t_idx,
            :, 
            r_pad - self.pad : r_pad + self.pad + 1, 
            c_pad - self.pad : c_pad + self.pad + 1
        ]
        target_profile = self.target_profiles[t_idx, :, r, c]
        return patch, target_profile

# =============================================================================
# 5. MODEL ARCHITECTURES (PROGRESSIVE BASELINES & OCEANEMBED TARGET)
# =============================================================================

# --- BASELINE 1: SST-Only MLP ---
class Baseline1_MLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(1, 64),
            nn.ReLU(),
            nn.Linear(64, 128),
            nn.ReLU(),
            nn.Linear(128, NUM_DEPTHS)
        )
    def forward(self, sst_single):
        return self.net(sst_single)

# --- BASELINE 2: Multi-Variable Single-Pixel MLP ---
class Baseline2_MultiMLP(nn.Module):
    def __init__(self, in_features=7):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_features, 128),
            nn.ReLU(),
            nn.Linear(128, 256),
            nn.ReLU(),
            nn.Linear(256, NUM_DEPTHS)
        )
    def forward(self, surface_vars):
        return self.net(surface_vars)

# --- TARGET ARCHITECTURE: OceanEmbed (CNN Encoder -> Latent Bottleneck -> Profile Decoder) ---
class OceanEmbed(nn.Module):
    def __init__(self, in_channels=14, patch_size=31, embed_dim=128):
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
        
        self.embedding = nn.Linear(128, embed_dim)
        
        self.decoder = nn.Sequential(
            nn.Linear(embed_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, NUM_DEPTHS)
        )
        
    def forward(self, patch):
        feat = self.encoder(patch)
        latent = self.embedding(feat)
        profile = self.decoder(latent)
        return profile, latent

# Depth-Weighted Loss for Training & Checkpoint Selection
DEPTH_WEIGHTS = torch.tensor([1.0, 1.0, 1.0, 1.2, 1.5, 2.0, 2.5, 2.5, 2.0, 1.8, 1.5, 1.2, 1.0, 1.0, 1.0]).to(device)

def depth_weighted_mse(pred, target):
    mse = (pred - target) ** 2
    return torch.mean(mse * DEPTH_WEIGHTS)

# TRUE UNWEIGHTED RMSE (°C) FOR HONEST REPORTING IN THE SUMMARY TABLE
def evaluate_model_rmse_true(model_obj, val_loader, model_type="oceanembed", patch_size=31):
    """Computes true, unweighted physical RMSE (°C) across the GLORYS validation set."""
    model_obj.eval()
    se_sum, total_count = 0.0, 0
    center_idx = patch_size // 2
    
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

# =============================================================================
# 6. TIMESTAMP-MATCHED GRIDDED INCOIS ARGO EVALUATION MODULE
# =============================================================================

def evaluate_against_incois_argo(model, surface_tensor_4d, common_dates, harmonizer, patch_size=31, data_dir="/kaggle/tmp/ocean_data"):
    """
    Parses INCOIS_ARGO.nc with xarray, interpolates vertical depth (with 0m extrapolation),
    extracts observed temperature profiles matched to the exact timestamp of surface inputs,
    queries OceanEmbed, and calculates true observation MAE & RMSE.
    """
    print("\n[+] Running Timestamp-Matched Gridded INCOIS ARGO Evaluation...")
    argo_path = os.path.join(data_dir, "INCOIS_ARGO.nc")
    
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
    batch_size = 256
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
    print(f"    - Overall MAE against INCOIS ARGO: {mae:.3f} °C")
    print(f"    - Overall True RMSE against INCOIS ARGO: {overall_rmse:.3f} °C")
    print(f"    - Surface (0m) RMSE: {rmse_depth[0]:.3f} °C")
    print(f"    - Thermocline (100m) RMSE: {rmse_depth[7]:.3f} °C")
    print(f"    - Deep Ocean (1000m) RMSE: {rmse_depth[-1]:.3f} °C")
    
    # Plot true timestamp-matched evaluation results
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    
    sample_idx = min(10, len(targets_np) - 1)
    axes[0].plot(targets_np[sample_idx], DEPTH_LEVELS, 'o-', label='Observed (INCOIS ARGO NetCDF)', color='#e74c3c', linewidth=2.5)
    axes[0].plot(preds_np[sample_idx], DEPTH_LEVELS, 's--', label='Predicted (OceanEmbed Model)', color='#2980b9', linewidth=2.5)
    axes[0].invert_yaxis()
    axes[0].set_xlabel('Temperature (°C)', fontsize=12)
    axes[0].set_ylabel('Depth (meters)', fontsize=12)
    axes[0].set_title('INCOIS ARGO Profile vs. OceanEmbed Prediction', fontsize=12, fontweight='bold')
    axes[0].legend()
    
    axes[1].plot(rmse_depth, DEPTH_LEVELS, 'd-', color='#8e44ad', linewidth=2.5)
    axes[1].invert_yaxis()
    axes[1].set_xlabel('RMSE (°C)', fontsize=12)
    axes[1].set_ylabel('Depth (meters)', fontsize=12)
    axes[1].set_title('INCOIS ARGO Independent RMSE vs. Depth', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig("incois_argo_validation.png", dpi=300)
    plt.show()
    print("[✔] Validation plot saved as 'incois_argo_validation.png'.")
    return overall_rmse

# =============================================================================
# 7. MAIN PIPELINE EXECUTION WITH FAIR BASELINE PROGRESSION COMPARISON TABLE
# =============================================================================

def run_pipeline():
    print("=" * 75)
    print("OceanEmbed AI Pipeline — Multi-Source NetCDF Harmonization & Training")
    print("=" * 75)
    
    data_dir = "/kaggle/tmp/ocean_data"
    fetcher = OceanDataFetcher(output_dir=data_dir)
    
    # 1. Fetch NetCDF datasets
    start_date, end_date = "2023-01-01", "2023-01-30"
    fetcher.fetch_all_datasets(start_date=start_date, end_date=end_date)
    
    # 2. Ingest, interpolate depths (WITH 0m EXTRAPOLATION), align datetimes, and normalize using TRAIN stats only
    surface_14ch_tensor, glorys_target_4d, common_dates, harmonizer = build_ocean_fields_from_netcdf(
        data_dir=data_dir, start_date=start_date, end_date=end_date
    )
    
    # 3. Create PyTorch Datasets & DataLoaders (Temporal Holdout Split)
    train_dataset = RealOceanPatchDataset(surface_14ch_tensor, glorys_target_4d, patch_size=31, time_split="train")
    val_dataset   = RealOceanPatchDataset(surface_14ch_tensor, glorys_target_4d, patch_size=31, time_split="val")
    
    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
    val_loader   = DataLoader(val_dataset, batch_size=64, shuffle=False)
    
    center_idx = 31 // 2
    num_epochs = 20 # Fair training across all models
    
    # 4. Train Progressive Baselines (Baseline 1 & Baseline 2) for 20 Epochs with Checkpointing
    print("\n[+] Training Baseline 1 (SST-Only MLP) for 20 Epochs...")
    b1_model = Baseline1_MLP().to(device)
    b1_opt = torch.optim.AdamW(b1_model.parameters(), lr=1e-3)
    best_b1_rmse = float('inf')
    best_b1_path = "best_b1_model.pth"
    
    for epoch in range(1, num_epochs + 1):
        b1_model.train()
        for patches, targets in train_loader:
            sst_center = patches[:, 0:1, center_idx, center_idx].to(device)
            preds = b1_model(sst_center)
            loss = depth_weighted_mse(preds, targets.to(device))
            b1_opt.zero_grad()
            loss.backward()
            b1_opt.step()
            
        b1_val_rmse = evaluate_model_rmse_true(b1_model, val_loader, model_type="b1")
        if b1_val_rmse < best_b1_rmse:
            best_b1_rmse = b1_val_rmse
            torch.save(b1_model.state_dict(), best_b1_path)
            
    b1_model.load_state_dict(torch.load(best_b1_path, map_location=device))
    b1_final_rmse = evaluate_model_rmse_true(b1_model, val_loader, model_type="b1")
    print(f"[✔] Baseline 1 (SST MLP) Final True Val RMSE: {b1_final_rmse:.4f} °C")
            
    print("\n[+] Training Baseline 2 (Multi-Variable Single-Pixel MLP) for 20 Epochs...")
    b2_model = Baseline2_MultiMLP(in_features=7).to(device)
    b2_opt = torch.optim.AdamW(b2_model.parameters(), lr=1e-3)
    best_b2_rmse = float('inf')
    best_b2_path = "best_b2_model.pth"
    
    for epoch in range(1, num_epochs + 1):
        b2_model.train()
        for patches, targets in train_loader:
            vars_center = patches[:, [0, 2, 4, 6, 8, 10, 12], center_idx, center_idx].to(device)
            preds = b2_model(vars_center)
            loss = depth_weighted_mse(preds, targets.to(device))
            b2_opt.zero_grad()
            loss.backward()
            b2_opt.step()
            
        b2_val_rmse = evaluate_model_rmse_true(b2_model, val_loader, model_type="b2")
        if b2_val_rmse < best_b2_rmse:
            best_b2_rmse = b2_val_rmse
            torch.save(b2_model.state_dict(), best_b2_path)
            
    b2_model.load_state_dict(torch.load(best_b2_path, map_location=device))
    b2_final_rmse = evaluate_model_rmse_true(b2_model, val_loader, model_type="b2")
    print(f"[✔] Baseline 2 (Multi-Var MLP) Final True Val RMSE: {b2_final_rmse:.4f} °C")
            
    # 5. Train Target OceanEmbed Architecture (14 Channels) for 20 Epochs
    print("\n[+] Training Target OceanEmbed Model (14 Channels) for 20 Epochs...")
    model = OceanEmbed(in_channels=14, patch_size=31, embed_dim=128).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    
    best_val_loss = float('inf')
    best_model_path = "best_oceanembed_model.pth"
    
    for epoch in range(1, num_epochs + 1):
        model.train()
        train_loss = 0.0
        train_steps = 0
        for patches, targets in train_loader:
            patches, targets = patches.to(device), targets.to(device)
            
            optimizer.zero_grad()
            preds, latent = model(patches)
            loss = depth_weighted_mse(preds, targets)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
            train_steps += 1
            
        # Validation Loop per Epoch
        model.eval()
        val_loss = 0.0
        val_steps = 0
        with torch.no_grad():
            for patches, targets in val_loader:
                patches, targets = patches.to(device), targets.to(device)
                preds, _ = model(patches)
                loss = depth_weighted_mse(preds, targets)
                val_loss += loss.item()
                val_steps += 1
                
        avg_train_loss = train_loss / train_steps
        avg_val_loss = val_loss / val_steps
        
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            torch.save(model.state_dict(), best_model_path)
            
        if epoch % 5 == 0 or epoch == 1:
            print(f"    Epoch [{epoch:02d}/20] | Train Loss: {avg_train_loss:.4f} | Val Loss: {avg_val_loss:.4f} | Best Val: {best_val_loss:.4f}")
            
    print(f"\n[✔] Training Complete! Best OceanEmbed weights saved to '{best_model_path}'.")
    
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

    # Load best checkpoint safely with map_location and evaluate TRUE unweighted RMSE
    load_checkpoint_flexibly(model, best_model_path)
    oceanembed_true_rmse = evaluate_model_rmse_true(model, val_loader, model_type="oceanembed")
    
    # 6. Evaluate independently against Gridded INCOIS_ARGO.nc profiles
    argo_rmse = evaluate_against_incois_argo(model, surface_14ch_tensor, common_dates, harmonizer, patch_size=31, data_dir=data_dir)
    
    # =========================================================================
    # SUMMARY COMPARISON TABLE FOR HACKATHON DEMO SLIDE (TRUE UNWEIGHTED RMSE °C)
    # =========================================================================
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
    run_pipeline()
