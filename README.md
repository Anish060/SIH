# OceanEmbed — subsurface ocean temperature from satellite surface data
**Team OceanSATX | Smart India Hackathon 2026 | Problem Statement 26066**

OceanEmbed is a small convolutional network. For each 0.25° cell of the North Indian Ocean (5–30°N, 45–105°E), it looks at a 31 × 31 patch of seven gridded surface fields and predicts temperature at 15 depths from 0 to 1000 m. It also produces a 128-number embedding of that ocean state.

The inputs are:

| Variable | Source |
|---|---|
| SST | OSTIA |
| Sea surface height (zos) | Copernicus GLO12 |
| Surface salinity (so) | Copernicus GLO12 |
| Currents (uo, vo) | Copernicus GLO12 |
| 10 m winds (u10, v10) | ERA5 |

**Every number in the dashboard comes from files produced from real inputs.** When a file is missing, the dashboard shows the command that creates it. Nothing is filled in with example values.

---

## How to run it (in order)

Needs a Copernicus Marine login (`copernicusmarine login`) and a CDS API key (`~/.cdsapirc`) for ERA5.

```bash
pip install -r requirements.txt

# 1. Training period: download, train, evaluate
python kaggle_oceanembed_pipeline.py                  # downloads Jan-2023 inputs + GLORYS12, trains 3 models
python kaggle_oceanembed_eval.py --data-dir /kaggle/tmp/ocean_data --ckpt-dir . --out basin_output/eval_results.json

# 2. Basin fields for the training month (also writes basin_output/normalisation_stats.json)
python basin_inference.py --data-dir /kaggle/tmp/ocean_data --start 2023-01-01 --end 2023-01-30

# 3. Cyclone case study: real IBTrACS tracks + model output for those days
python fetch_cyclone_tracks.py --storm MOCHA:2023 --storm MICHAUNG:2023
python fetch_period.py --mode reanalysis --start 2023-05-08 --end 2023-05-18 --out-dir data_mocha
python basin_inference.py --data-dir data_mocha --start 2023-05-08 --end 2023-05-18 \
       --stats-json basin_output/normalisation_stats.json

# 4. Near-real-time (daily, e.g. cron): latest ~7 days, about 6 days behind today (ERA5 latency)
python realtime_update.py

# 5. Serve
python server.py                        # API on :8000, reads basin_output/
cd frontend && npm install && npm run dev   # dashboard on :3000
```

Copy the trained `best_*.pth` files into `trained/` and the contents of `basin_output/` next to `server.py`.

---

## What each part computes

The profile is treated as piecewise-linear between the 15 levels, and every diagnostic is exact under that assumption. All of them live in `oceanembed_core.py`. `tests/test_physics.py` checks each one against closed-form answers, a 1 mm brute-force integration and published check values.

| Quantity | Definition |
|---|---|
| D26, D20 | First downward crossing of 26 °C or 20 °C, linearly interpolated. Blank where the surface is already colder. |
| TCHP | ρ c_p ∫₀^D26 (T − 26) dz, with ρ = 1026 kg m⁻³ and c_p = 4178 J kg⁻¹ K⁻¹, in kJ cm⁻². 0 when T(0) < 26 °C. |
| Mixed-layer depth | Depth where \|T − T(10 m)\| first reaches 0.2 °C (de Boyer Montégut et al., 2004). |
| Thermocline | Mid-point of the layer with the most negative dT/dz. The layer bounds are also given, because level spacing limits the precision. |
| Sound speed, sonic layer depth | Mackenzie (1981) equation; the check value 1550.744 m/s is tested. The sonic layer depth is the near-surface sound-speed maximum. Salinity is taken as the cell's surface value at all depths (stated in the UI). |
| Cold wake along a cyclone track | OSTIA SST 3 days after minus 1 day before, at the same cell, when both days have been run. |
| Similar ocean states | Cosine similarity of the stored 128-D embeddings. |
| What-if | The stored real 31 × 31 patch plus a uniform change, re-normalised and run through the network. The unchanged run reproduces the stored prediction to about 1e-5 °C, and every run reports this check. |

**Domain.** Predictions are made only where the reference has a complete 0–1000 m profile, which is the rule that selected the training samples. Shelf and land stay blank.

**Distribution check.** Each cell also stores `in_max_abs_z`: how far its inputs are from the training data, in standard deviations. Above about 4 the prediction is an extrapolation, and the UI flags it.

**What is deliberately not claimed**
- **Potential fishing zones.** These need chlorophyll, which the model does not predict.
- **Acoustic propagation loss.** The sound-speed profile is only a profile diagnostic.
- **Cyclone intensity forecasts.** TCHP is one ingredient only.
- **Maritime-boundary distances.** Removed; the old formula was a placeholder.

---

## Validation

`kaggle_oceanembed_eval.py` writes `basin_output/eval_results.json`, and the dashboard reads only that file. It covers:
- **GLORYS12, held-out days.** RMSE on the last 20 % of the training month, overall and per depth. GLORYS12 was the training target, so this measures teacher-consistency, not observation skill.
- **INCOIS gridded Argo (`incois_argo_mnt_VAM`).** This is a *monthly gridded analysis* of Argo data, not individual float profiles. Each validation day is matched to its monthly field, and the dates are recorded. The counting unit is grid-cell-days. Levels outside the product's depth range are not extrapolated.
- **Baselines.** A missing checkpoint is reported as "not evaluated", never as a typed-in number.

---

## Data-integrity fixes and why retraining is needed

- **Model definition.** `test.py`, the eval script and the old server described a different network from the trained one (an extra LayerNorm and GELU), and loaded the weights with `strict=False`, so those layers ran untrained. Everything now uses one architecture and loads with `strict=True`.
- **Ingestion no longer guesses.** A missing variable used to be replaced by whichever variable came first in the file. The Copernicus `-cur` dataset holds only `uo`/`vo`, so the salinity channel most likely received `vo`: the old salinity statistics equal the `vo` statistics. Missing variables, and dates a file does not cover, now stop the run.
- **Downloads fixed.** Currents, salinity and SSH now come from their own datasets. GLORYS is fetched to 1100 m, so the 1000 m level is interpolated rather than extrapolated.
- **Synthetic API paths removed.** The old API built patches from 7 typed numbers with invented gradients, shifted the output to match SST, made up SSH and salinity for "live" data, and returned placeholder similarity scores. All of these are gone.
- **→ Retrain with `kaggle_oceanembed_pipeline.py`.** The current checkpoint was trained on the old inputs, and on one month only (January 2023). For other seasons, expect large input |z| values; train on a full year for year-round use.

---

## Workspaces by role

| Role | Pages | Sign-in |
|---|---|---|
| End user | Public dashboard (`/dashboard`) | none |
| Decision maker | + Ocean heat brief (`/brief`), exportable to PDF | yes |
| Scientist | + Science (`/science`) and Data Explorer (`/explorer`) | yes |
| Admin | + Admin console (`/admin`): feeds and alerts, jobs, users, system health | yes |

Create the first admin with `python auth.py add <name> --role admin`; further users can then be added in the Admin console.

How access works:
- **Enforcement is server-side**, from an HMAC-signed token (`auth.py`), so hiding a page in the browser is not what protects it.
- **Passwords** are hashed with scrypt.
- **Local state** (users, secret key, job logs) is kept in `state/`.

### Science tools (`physics.py`, all tested in `tests/test_ocean_physics.py`)

| Tool | What it does | Adjustable (only genuinely free parameters) |
|---|---|---|
| Currents | Geostrophic currents from CMEMS sea-surface height, u = −(g/f)∂η/∂y, v = (g/f)∂η/∂x, compared with the CMEMS total surface current. Ekman transport and pumping from ERA5 wind stress. | Drag coefficient: Large & Pond (1981) or a constant |
| Particle drift | RK4 on daily CMEMS surface currents, with optional windage and a random walk | Particles, release radius, diffusivity, windage, time step, seed |
| Storm mixing (PWP) | Price–Weller–Pinkel (1986) 1-D model: static, bulk-Ri and gradient-Ri mixing with inertial rotation, TEOS-10 density. Starts from the OceanEmbed or reference profile, forced by ERA5 winds or a constant what-if wind. Compared with the observed OSTIA SST change. | Critical Ri values, heat flux, wind (what-if), drag scheme |
| Stratification | TEOS-10 density, σ0, N², sound speed, and the gradient Richardson number from reference currents | Temperature source (model or reference) |
| Assimilation | Optimal interpolation of the model field with individual Argo floats (`fetch_argo_profiles.py`; in-situ temperature converted to potential temperature), scored by exact leave-one-out cross-validation | Correlation length, σb, σo, time window |
| ML baseline | XGBoost predicting D20 from the same inputs, on the same test cells as the CNN (`train_xgb_baseline.py`) | n/a |

**Deliberately not sliders:**
- **Coriolis parameter:** set by latitude.
- **N² and the Richardson number:** computed from the profiles, not chosen.

**Heavy ocean models** (ROMS, MITgcm, NEMO, FVCOM, SWAN, WAVEWATCH III) are not run live. They need grids, boundary data and cluster time. NEMO-based operational output (Mercator GLO12) is already used as the input and reference data.

### Data Explorer
- Every input and output file, with dimensions, variables, units, global attributes, processing level, source dataset ID, download time and sha256.
- Point time series at any latitude/longitude (and depth), downloadable as CSV.
- Vertical profiles (temperature, salinity, TEOS-10 σ0 and sound speed), downloadable as CSV or NetCDF.

### Admin console
- **Feeds and alerts:** readability of each file, date coverage, synthetic-data and checkpoint-mismatch warnings, near-real-time lag.
- **Jobs:** whitelisted re-processing runs with logs. Dates are validated, paths must stay inside `OCEANEMBED_DATA_ROOT`, and at most two jobs run at once. Failed jobs are POSTed to `OCEANEMBED_ALERT_WEBHOOK` if it is set.
- **Users and roles.**
- **System health:** CPU, RAM, disk, per-route latency, and file-cache hit ratio.

### Decision brief
The brief is computed per date and prints to PDF. It covers:
- the area with TCHP ≥ 50 and ≥ 80 kJ/cm², and its overlap with the reference
- the top 5 hotspots
- TCHP relative to the mean of the period on file (explicitly not a climatology)
- input-quality flags
- IBTrACS storms within a day

---

## Tests

```bash
python -m pytest tests -q                                     # physics, model loading, normalisation
python tests/make_fixture_netcdf.py /tmp/fx 2023-01-01 2023-01-10   # format-matching SYNTHETIC files
python basin_inference.py --data-dir /tmp/fx --start 2023-01-01 --end 2023-01-10 --out /tmp/bo/basin_a.nc
OCEANEMBED_BASIN_DIR=/tmp/bo python -m pytest tests -q        # + API, role and physics-endpoint tests
```

Output built from fixture files is flagged `SYNTHETIC TEST FIXTURE`, and the dashboard shows a red banner for it.

## Sources
- Copernicus Marine Service (OSTIA; GLOBAL_ANALYSISFORECAST_PHY_001_024; GLOBAL_MULTIYEAR_PHY_001_030 / GLORYS12)
- ECMWF ERA5 via the CDS
- INCOIS ERDDAP (gridded Argo)
- IBTrACS (NOAA NCEI; Knapp et al., 2010)
