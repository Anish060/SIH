# OceanEmbed — AI / Training Approach
### Team OceanSATX | SIH 2026 | Problem Statement 26066

---

## 0. Purpose of This Document

This is the working plan for the AI/ML side of OceanEmbed: how the model gets built, what data feeds it, how it's trained, and how it's validated for the demo. It assumes the reader has already read the team's knowledge base — this document is the *execution plan* derived from it, written for whoever owns the AI pipeline.

Core principle driving every decision below: **protect a working baseline at all times.** A hackathon is lost by having a broken complex model at hour 40, not by having a simple one that works.

---

## 1. The Problem, Restated

Learn a mapping:

```
X(x, y, t)  →  T̂(x, y, z, t)
```

- `X` = harmonized surface observations (SST, SSH, SSS, wind, currents)
- `T̂` = predicted temperature at 15 depth levels, surface to 1000 m
- Region: 5–30°N, 45–105°E (Bay of Bengal / North Indian Ocean)

Formally:

```
Ê = f_θ(X)          (CNN encoder → ocean embedding)
T̂ = g_φ(Ê)          (profile decoder → 15-depth profile)
```

This is a spatiotemporal regression problem, not classification, not an LLM task, not a full ocean simulator.

---

## 2. Time Budget Philosophy

Rough allocation for a ~36–48 hour hackathon window:

| Phase | % of time | Why |
|---|---|---|
| Data acquisition + harmonization | 35–40% | Multiple sources, different grids/units/coverage — this is where hours disappear |
| Baseline models (MLP) | 10% | Fast to build, gives you a safety-net result immediately |
| CNN encoder–decoder (OceanEmbed proper) | 20% | The actual proposed architecture |
| Validation (Argo, thermocline, cyclone case study) | 20% | This is what makes the demo credible, not the architecture |
| Dashboard / packaging | 10–15% | Web map, depth slider, plots |

**Do not flip this ratio.** It's tempting to spend most of the time on the model; the model is the easy part once data is clean.

---

## 3. Data Sources and Their Role

| Source | Role | Notes |
|---|---|---|
| NOAA OISST | SST input channel | Gridded product, not raw radiance |
| Copernicus Marine Service | SSH, currents (and optionally SSS) | Document the exact product ID used |
| GLORYS12V1 | **Training target / teacher** for subsurface temperature | ~1/12°, 50 vertical levels, reanalysis — not ground truth |
| Argo floats | **Independent validation only** | Never used in training or tuning |
| World Ocean Atlas 2018 | Optional climatology reference / sanity check | Not primary training data |

**Critical distinction to keep straight throughout:** GLORYS is a *model product*. Training against it teaches OceanEmbed to reproduce a reanalysis. Argo is a *real measurement*. Only Argo agreement is evidence the model works, not just that it imitates GLORYS.

---

## 4. Data Harmonization Pipeline

```
Raw/processed products
        ↓
Variable selection
        ↓
Quality control
        ↓
Unit conversion
        ↓
Coordinate normalization
        ↓
Spatial resampling → common grid
        ↓
Temporal alignment (match dates across sources)
        ↓
Land/ocean masking
        ↓
Missing-data mask generation
        ↓
Normalization (train-set statistics only)
        ↓
Model-ready tensors
```

**Implementation notes:**
- Pick one fixed grid resolution early (e.g. 0.25°) and don't revisit it. Resolution should be driven by data availability and GPU memory, not by wanting the output map to look impressive.
- Every variable gets an accompanying binary mask (`1` = valid, `0` = missing/land/cloud). Feed `value + mask` together — this lets the network distinguish "true zero" from "missing."
- Normalize per-variable using **training-period statistics only**:
  `x' = (x − μ_train) / σ_train`
- Start the whole pipeline on a short date range (a few weeks) before scaling to the full training period — debug on small data.

---

## 5. Data Splitting (Leakage Prevention)

This is the single easiest way to accidentally invalidate the whole project.

**Do:**
```
Earlier dates  → training
Later dates    → validation / test   (temporal holdout)

Selected Argo profiles → NEVER touched during training or tuning
                        → held out for final independent validation only
```

**Do not:** randomly shuffle-split neighboring days/pixels and then claim the result generalizes. Adjacent days are highly correlated; this inflates validation scores meaninglessly.

Document whichever holdout strategy is used (temporal / event / region / float-level) — a judge asking "how did you split your data" is a near-certainty, and "randomly" is the wrong answer.

---

## 6. Model Progression (Build in This Order)

### Baseline 1 — SST-only MLP
```
SST (single point) → MLP → 15 temperatures
```
Sanity check: does even the crudest signal predict anything at all?

### Baseline 2 — Multi-variable MLP
```
SST + SSH + SSS + wind + current (single point) → MLP → 15 temperatures
```
Tests whether the extra surface variables add value before adding spatial complexity.

### Baseline 3 — CNN, no embedding bottleneck
```
Multi-channel spatial patch → CNN → 15 temperatures
```
Tests whether spatial context (fronts, eddies, nearby structure) helps.

### OceanEmbed (target architecture)
```
Multi-channel spatial patch
        ↓
   CNN encoder (f_θ)
        ↓
   Ocean embedding (E)
        ↓
   Profile decoder (g_φ)
        ↓
   15-depth temperature profile
```

Each stage should produce a real, recorded RMSE. The four numbers side by side *are* your technical results slide — this progression is itself a scientific argument for why the proposed architecture is justified, not just asserted.

**Why not 15 independent models, one per depth?** Duplicated parameters, no shared vertical representation, and no guarantee predictions are physically coherent from one depth to the next. A shared embedding decoded into all 15 levels at once enforces vertical consistency for free.

---

## 7. Training Details

- **Loss:** plain per-depth MSE to start. Only move to a depth-weighted loss (e.g. upweighting the thermocline region where gradients are sharp) once the basic model is working and you want a documented v2 improvement.
- **Train from scratch.** No need for a large pretrained foundation model — a small network is sufficient to test the core hypothesis, and it's easier to train, debug, explain, and validate under time pressure.
- **Self-supervised pretraining (masked variable reconstruction):** valuable in principle, but implement *only after* the supervised baseline works end-to-end. Treat it as a stretch goal.
- **Transformer (temporal context across days):** only add if there's time left *and* it measurably improves validation RMSE over the CNN baseline. Don't add it because it sounds more advanced in the pitch — an unfinished Transformer beats nothing, but a working CNN beats an unfinished Transformer every time.
- **Compute:** modest. A 0.25° regional grid × 15 depths with a small CNN trains fine on a single Colab-class GPU, and the MLP baselines will run on CPU in minutes.

---

## 8. Validation Strategy

Two distinct evaluation layers — keep them conceptually separate in the demo:

### Teacher-consistency
Does OceanEmbed reproduce the GLORYS field it was trained on? (Necessary but not sufficient.)

### Observation-consistency (the one that matters)
Does OceanEmbed also agree with **Argo floats it never saw**? This is what avoids the circular claim *"the model predicts GLORYS, therefore it's correct."*

**Deliverables for the demo:**
- Scatter plot: predicted vs. observed Argo temperature
- Depth-profile plot: one predicted profile overlaid on the matching Argo profile
- Error-vs-depth plot (expect error to grow with depth — explain this rather than hide it)
- Spatial error map across the region

This Argo-validation set of plots should be the scientific center of the demo, not a footnote after the architecture diagram.

---

## 9. Downstream Applications (Build After Core Model Works)

### Thermocline depth
```
Predicted profile → dT/dz → thermocline depth
```
Produces a thermocline-depth map — a direct, self-contained deliverable.

### Cyclone / ocean heat case study
```
Historical storm track + OceanEmbed temperature + 26°C isotherm depth + heat-content indicator
```
Overlay a real historical storm track against the reconstructed subsurface heat structure. This ties the ML output back to the Disaster Management theme and is the applied payoff of the whole pipeline.

---

## 10. What to Claim vs. Not Claim

**Claim confidently (backed by the pipeline above):**
- Surface-to-subsurface temperature reconstruction, 15 depth levels, regional daily field
- Embedding-based architecture with GLORYS as teacher, Argo as independent validation
- Thermocline derivation
- Ocean-heat analysis in support of cyclone intensity assessment

**Do not claim without dedicated experiments:**
- Precise operational-grade temperature accuracy
- Operational cyclone prediction or genesis forecasting
- Direct fish-school or submarine detection
- Complete global ocean state
- That all five surface variables come from a single satellite image (they don't — they're distinct processed products)

---

## 11. Final Architecture Diagram

```
        SST + SSH + SSS + Wind + Currents
                       │
                       ▼
              DATA HARMONIZATION
                       │
                       ▼
                 CNN ENCODER
                       │
                       ▼
                OCEAN EMBEDDING
                       │
                       ▼
                PROFILE DECODER
                       │
                       ▼
           15-DEPTH TEMPERATURE
                       │
                       ▼
              3D OCEAN FIELD
                       │
          ┌────────────┼─────────────┐
          ▼            ▼             ▼
     Thermocline    Argo         Cyclone
       Depth      Validation    Heat Support
          │            │             │
          └────────────┼─────────────┘
                       ▼
                FINAL DASHBOARD
```

```
T̂(x,y,z,t) = g_φ( f_θ( X(x,y,t) ) )
```

---

## 12. Execution Checklist (In Order)

1. **Data pipeline** — pull a short date-range slice of OISST, GLORYS12V1, Copernicus SSH/SSS; regrid to common grid; mask; normalize on train stats only.
2. **Argo validation set** — match Argo profiles to region/grid, lock away, never touch during training.
3. **Baseline 1 & 2** — SST-only MLP, then multi-variable MLP → first RMSE numbers.
4. **Baseline 3 & OceanEmbed** — CNN with spatial patch, then full encoder–embedding–decoder.
5. **Argo validation** — scatter, depth-profile overlay, error-vs-depth, spatial error map.
6. **Thermocline + cyclone case study** — dT/dz map, storm-track overlay on reconstructed heat structure.
7. **Stretch (only if time remains and clearly helps):** self-supervised pretraining, temporal Transformer.

---

*This document is the execution plan derived from the team's submitted SIH proposal and expanded knowledge base. Formal project specifications remain those in the submitted document.*
