# OceanEmbed — Multi-Source 3D Subsurface Ocean Structure & Latent Representation
**Team OceanSATX | Smart India Hackathon (SIH) 2026 | Problem Statement 26066**

---

## 🌊 Overview

**OceanEmbed** is a production-grade AI framework that ingests **multi-source satellite and atmospheric NetCDF data** (SST, SSH, SSS, Ocean Currents, 10m Winds) to reconstruct **3D subsurface ocean temperature profiles (0m to 1000m)** and generate **128-Dimensional compact ocean latent embeddings**.

By transforming 2D surface satellite measurements into a complete 3D ocean volume, OceanEmbed directly solves critical challenges in **cyclone disaster prediction**, **naval anti-submarine warfare (ASW)**, and **marine fisheries management**.

---

## 🚀 The 4 Core Application Pillars

While the model outputs an array of **15 subsurface depth temperatures**, oceanographic physics allows us to mathematically derive **four key real-world application pillars**:

### 1. 🌀 Cyclone Intensification & Natural Disaster Prediction
- **Physical Rationale**: Cyclones draw thermal energy from subsurface ocean heat stored above the **$26^\circ\text{C}$ isotherm depth ($D_{26}$)**. If $D_{26}$ is deep ($>60\text{ m}$), cyclones rapidly intensify into severe tropical storms.
- **Mathematical Derivation**:
  - **$D_{26}$ Isotherm Depth**: Depth where $T(z) = 26.0^\circ\text{C}$.
  - **Tropical Cyclone Heat Potential (TCHP)**: 
    $$\text{TCHP} = c_p \rho \int_{0}^{D_{26}} (T(z) - 26.0) \, dz$$
- **Code Formula**:
  ```python
  # D26 Isotherm Depth
  D26_depth = np.interp(26.0, profile_celsius[::-1], DEPTH_LEVELS[::-1])
  # Cyclone Heat Energy (kJ/cm²)
  TCHP = np.trapz(np.maximum(0, profile_celsius - 26.0), DEPTH_LEVELS)
  ```

---

### 2. 🛡️ Thermocline Layer & Submarine Acoustic Shadow Zone (Defense / ASW)
- **Physical Rationale**: The **Thermocline** (layer between 30m and 150m where temperature drops rapidly) creates a sharp density gradient that refracts active sonar waves. Submarines exploit this **sonic layer shadow zone** to evade surface ship detection.
- **Mathematical Derivation**:
  - The thermocline core depth corresponds to the maximum vertical thermal gradient:
    $$\text{Thermocline Core} = \arg\min_z \left( \frac{\partial T}{\partial z} \right)$$
- **Code Formula**:
  ```python
  dT = np.diff(profile_celsius)
  dz = np.diff(DEPTH_LEVELS)
  steepest_idx = np.argmin(dT / dz)
  thermocline_depth = DEPTH_LEVELS[steepest_idx]
  # Result: e.g. 50 meters (exact depth where active sonar refracts)
  ```

---

### 3. 🐟 Potential Fishing Zones (PFZ) & International Border Alerts
- **Physical Rationale**: Commercial pelagic fish (Tuna, Mackerel, Sardines) congregate at **nutrient-rich upwelling zones** where cold thermocline water is driven to the surface by ocean currents.
- **Mathematical Derivation**:
  - **Upwelling Intensity Index**: $T_{\text{surface}} - T_{50\text{m}}$
- **Code Formula**:
  ```python
  upwelling_index = profile_celsius[0] - profile_celsius[5]  # T(0m) - T(50m)
  if upwelling_index > 4.0:
      print("High Potential Fishing Zone (PFZ) Detected: Strong Nutrient Upwelling!")
  ```
- **Border Alert Feature**: Overlaying predicted PFZ zones with maritime boundary limits (Exclusive Economic Zones / EEZ) generates automated alerts when fish shoals drift near international borders.

---

### 4. 🌐 Complete 3-Dimensional Ocean Data Volume
- **Physical Rationale**: Standard satellite radiometers and altimeters only measure 2D surface skin. OceanEmbed transforms 2D satellite surface grids into a **full 3D ocean data matrix $(T, 15, H, W)$** across 15 standard depth levels:
  - **Surface Mixed Layer**: `0m`, `5m`, `10m`, `20m`
  - **Thermocline Layer**: `30m`, `50m`, `75m`, `100m`, `125m`, `150m`
  - **Deep Ocean Layer**: `200m`, `300m`, `500m`, `750m`, `1000m`

---

## 📥 Input & Output Specifications

### Model Input
A **14-channel spatial patch ($31 \times 31$ pixels)** centered at the target location ($\approx 775\text{ km} \times 775\text{ km}$ area at $0.25^\circ$ resolution):

| Channel # | Physical Variable | Unit | Function |
| :--- | :--- | :---: | :--- |
| **Ch 0 & 1** | **Sea Surface Temperature (SST)** + Mask | ${}^\circ\text{C}$ | Surface thermal state & satellite validity mask |
| **Ch 2 & 3** | **Sea Surface Height (SSH)** + Mask | $\text{m}$ | Altimetry anomaly (eddies & sea level) |
| **Ch 4 & 5** | **Sea Surface Salinity (SSS)** + Mask | $\text{PSU}$ | Salinity anomaly (freshwater river plumes) |
| **Ch 6 & 7** | **Eastward Ocean Current ($U_o$)** + Mask | $\text{m/s}$ | Zonal ocean current velocity |
| **Ch 8 & 9** | **Northward Ocean Current ($V_o$)** + Mask | $\text{m/s}$ | Meridional ocean current velocity |
| **Ch 10 & 11** | **10m Eastward Wind ($U_{10}$)** + Mask | $\text{m/s}$ | Atmospheric zonal wind stress |
| **Ch 12 & 13** | **10m Northward Wind ($V_{10}$)** + Mask | $\text{m/s}$ | Atmospheric meridional wind stress |

- **Input Tensor Shape**: `(Batch_Size, 14, 31, 31)`

### Model Output
1. **Subsurface Temperature Profile**: Array of 15 temperatures ($^\circ\text{C}$) from 0m to 1000m. Shape: `(Batch_Size, 15)`
2. **128-D Ocean Latent Embedding**: Dense representation vector suitable for Vector DB similarity search (Milvus/FAISS) and downstream AI forecasting models. Shape: `(Batch_Size, 128)`

---

## 📊 Benchmark Results & In-Situ Verification

OceanEmbed was benchmarked against **54,606 independent, timestamp-matched INCOIS ARGO buoy float profiles** across the Bay of Bengal & Arabian Sea ($5^\circ\text{N} - 30^\circ\text{N}, 45^\circ\text{E} - 105^\circ\text{E}$):

```text
===========================================================================
SUMMARY RESULTS TABLE (HONEST UNWEIGHTED PHYSICAL RMSE °C)
===========================================================================
  1. Baseline 1 (SST-Only MLP)       GLORYS Val RMSE: 1.0440 °C
  2. Baseline 2 (Multi-Var MLP)     GLORYS Val RMSE: 1.0573 °C
  3. OceanEmbed Target Architecture GLORYS Val RMSE: 1.3892 °C
  4. OceanEmbed Independent INCOIS ARGO RMSE : 1.3892 °C
===========================================================================
```

### INCOIS ARGO Depth Breakdown:
- **Surface (0m) RMSE**: `1.4315 °C`
- **Thermocline (100m) RMSE**: `1.5689 °C`
- **Deep Ocean (1000m) RMSE**: `0.6813 °C`

---

## 💻 Quickstart & Code Example

To run inference using the self-contained script:

```python
# Run the self-contained test script in Python or Kaggle
import test
```

### Or load model directly:

```python
import torch
import numpy as np
from test import OceanEmbed, DEPTH_LEVELS, load_checkpoint_flexibly

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load trained model
model = OceanEmbed(in_channels=14, patch_size=31, embed_dim=128, out_depths=15).to(device)
load_checkpoint_flexibly(model, "best_oceanembed_model.pth")
model.eval()

# Sample 14-channel input patch (1, 14, 31, 31)
input_patch = torch.randn(1, 14, 31, 31).to(device)

with torch.no_grad():
    predicted_profile, ocean_embedding = model(input_patch)

profile_celsius = predicted_profile.cpu().numpy().squeeze()
print("Predicted 15-Depth Profile (°C):", profile_celsius)
```

---

## 🛠️ Data Sources & Technologies Used

- **Data Ingestion**: Copernicus Marine Service (`GLORYS12V1`, `PHY_001_024`, `SST_010_011`), ERA5 Reanalysis (`CDS API`), INCOIS ERDDAP (`incois_argo_mnt_VAM`).
- **Processing & Standardizer**: PyTorch, xarray, NumPy, Pandas, Matplotlib, Seaborn.
- **Hardware Acceleration**: NVIDIA CUDA GPU (Kaggle P100 / T4).
