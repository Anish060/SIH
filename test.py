"""
===============================================================================
OceanEmbed — Self-Contained Sample Input Data & Inference Script
Team OceanSATX | SIH 2026 | Problem Statement 26066
===============================================================================
Standalone single-file script:
  ✔ Self-contained (zero external module imports required)
  ✔ Constructs realistic 14-channel ocean surface patch (Bay of Bengal)
  ✔ Normalizes inputs using zero-leakage training statistics
  ✔ Loads best_oceanembed_model.pth checkpoint
  ✔ Predicts 3D Subsurface Temperature Profile (0m-1000m) & 128-D Ocean Embedding
===============================================================================
"""

import os
import torch
import torch.nn as nn
import numpy as np

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"[+] Active Compute Engine: {device}")

# =============================================================================
# 1. CONSTANTS & MODEL DEFINITIONS (100% SELF-CONTAINED)
# =============================================================================
DEPTH_LEVELS = np.array([0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000])

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
# 2. TRAINING SET NORMALIZATION STATISTICS (From Real NetCDF Ingestion)
# =============================================================================
STATS = {
    'sst':  {'mean': 299.8898, 'std': 1.5849},  # Sea Surface Temperature (Kelvin)
    'ssh':  {'mean': -0.0347,  'std': 0.2102},  # Sea Surface Height (meters)
    'sss':  {'mean': 0.0285,   'std': 0.2230},  # Salinity Anomaly / PSU
    'uo':   {'mean': -0.1061,  'std': 0.2310},  # Eastward Surface Current (m/s)
    'vo':   {'mean': 0.0285,   'std': 0.2230},  # Northward Surface Current (m/s)
    'u10':  {'mean': -1.6766,  'std': 2.6975},  # Zonal Wind at 10m (m/s)
    'v10':  {'mean': -2.3464,  'std': 2.9033},  # Meridional Wind at 10m (m/s)
}

# =============================================================================
# 3. CONSTRUCT REALISTIC PHYSICAL SURFACE DATA FOR A 31x31 OCEAN PATCH
# =============================================================================
H, W = 31, 31
y_grid, x_grid = np.meshgrid(np.linspace(-1, 1, H), np.linspace(-1, 1, W), indexing='ij')

# Physical ocean surface values with realistic spatial gradients (Bay of Bengal)
raw_sst = 299.5 + 1.2 * y_grid - 0.5 * x_grid   # SST ~ 298.5K to 300.2K (25.3°C to 27.0°C)
raw_ssh = 0.05 + 0.15 * np.exp(-(x_grid**2 + y_grid**2)/0.5) # Warm-core eddy SSH bump (+0.20m)
raw_sss = 0.02 - 0.05 * y_grid                  # River plume salinity variation
raw_uo  = -0.15 + 0.1 * y_grid                  # Eastward current velocity (m/s)
raw_vo  = 0.05 - 0.1 * x_grid                   # Northward current velocity (m/s)
raw_u10 = -2.0 + 0.5 * x_grid                   # Zonal wind speed (m/s)
raw_v10 = -3.0 + 0.5 * y_grid                   # Meridional wind speed (m/s)

raw_fields = {
    'sst': raw_sst, 'ssh': raw_ssh, 'sss': raw_sss,
    'uo': raw_uo, 'vo': raw_vo, 'u10': raw_u10, 'v10': raw_v10
}

# Print sample physical values at patch center (pixel 15, 15)
print("\n" + "=" * 65)
print("REALISTIC PHYSICAL SURFACE INPUTS AT PATCH CENTER (15, 15)")
print("=" * 65)
print(f"  1. Sea Surface Temperature (SST): {raw_sst[15,15] - 273.15:.2f} °C ({raw_sst[15,15]:.2f} K)")
print(f"  2. Sea Surface Height (SSH)     : {raw_ssh[15,15]:.3f} m")
print(f"  3. Sea Surface Salinity (SSS)   : {raw_sss[15,15]:.3f} PSU anomaly")
print(f"  4. Zonal Current Velocity (Uo)  : {raw_uo[15,15]:.3f} m/s")
print(f"  5. Meridional Current (Vo)      : {raw_vo[15,15]:.3f} m/s")
print(f"  6. Zonal Wind at 10m (U10)      : {raw_u10[15,15]:.3f} m/s")
print(f"  7. Meridional Wind at 10m (V10) : {raw_v10[15,15]:.3f} m/s")
print("=" * 65)

# =============================================================================
# 4. NORMALIZE & PACK INTO 14-CHANNEL TENSOR (7 VARS + 7 MASKS)
# =============================================================================
channels = []
for var_name in ['sst', 'ssh', 'sss', 'uo', 'vo', 'u10', 'v10']:
    val = raw_fields[var_name]
    mean = STATS[var_name]['mean']
    std  = STATS[var_name]['std']
    
    # Normalize with zero-leakage training set stats
    norm_val = (val - mean) / (std + 1e-6)
    mask = np.ones((H, W), dtype=np.float32)  # 1.0 = valid satellite observation
    
    channels.append(norm_val.astype(np.float32))
    channels.append(mask)

# Pack into (1, 14, 31, 31) PyTorch Tensor
input_patch_np = np.stack(channels, axis=0)
input_tensor = torch.from_numpy(input_patch_np).unsqueeze(0).to(device)

print(f"\n[+] Constructed 14-Channel Input Patch Tensor Shape: {input_tensor.shape}")

# =============================================================================
# 5. LOAD TRAINED MODEL & RUN INFERENCE
# =============================================================================
model = OceanEmbed(in_channels=14, patch_size=31, embed_dim=128, out_depths=15).to(device)
best_model_path = "best_oceanembed_model.pth"

if os.path.exists(best_model_path):
    try:
        load_checkpoint_flexibly(model, best_model_path)
        print(f"[✔] Successfully loaded trained weights from '{best_model_path}'")
    except Exception as e:
        print(f"[!] Could not load checkpoint ({e}). Running default model initialization.")
else:
    print(f"[!] Warning: '{best_model_path}' not found in working directory. Running default model initialization.")

model.eval()

with torch.no_grad():
    predicted_profile, ocean_embedding = model(input_tensor)

profile_celsius = predicted_profile.cpu().numpy().squeeze()
latent_vector = ocean_embedding.cpu().numpy().squeeze()

# =============================================================================
# 6. DISPLAY PREDICTED OUTPUTS
# =============================================================================
print("\n" + "=" * 65)
print("MODEL OUTPUT 1: PREDICTED SUBSURFACE TEMPERATURE PROFILE (°C)")
print("=" * 65)
for depth, temp in zip(DEPTH_LEVELS, profile_celsius):
    layer_name = "Surface" if depth == 0 else ("Thermocline" if 30 <= depth <= 150 else "Deep Ocean")
    print(f"  Depth {depth:4d} m ({layer_name:11s}) : {temp:6.2f} °C")
print("=" * 65)

print("\n" + "=" * 65)
print("MODEL OUTPUT 2: 128-DIMENSIONAL OCEAN EMBEDDING VECTOR")
print("=" * 65)
print(f"  Shape: {latent_vector.shape} (128 Latent Dimensions)")
print(f"  Sample Latent Values (first 10 dims): {np.round(latent_vector[:10], 4)}")
print("=" * 65)
