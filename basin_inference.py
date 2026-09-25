"""
===============================================================================
OceanEmbed — basin-wide inference on real NetCDF inputs
Team OceanSATX | SIH 2026 | Problem Statement 26066
===============================================================================
Runs the trained network on every deep-water cell of the 0.25° grid
(5–30°N, 45–105°E) for every day in a folder of NetCDF inputs and writes one
NetCDF file that the API serves. Nothing is synthesised: cells with no valid
input or reference profile stay NaN.

Two modes:

1. Training period (writes the normalisation statistics):
     python basin_inference.py --data-dir DATA --start 2023-01-01 --end 2023-01-30
   Uses the training code's own ingestion over the training range, so
   regridding, masking and the train-period statistics are reproduced
   exactly. Writes basin_output/normalisation_stats.json.

2. Any other period (cyclone case study, near-real-time):
     python basin_inference.py --data-dir DATA2 --start 2023-05-08 --end 2023-05-16 \
         --stats-json basin_output/normalisation_stats.json
   Inputs are normalised with the FROZEN training statistics, exactly as the
   network saw them in training. The reference profile can be GLORYS12 or the
   operational Mercator analysis (--reference-file/--reference-name).

What is stored (time, [depth,] latitude, longitude):
  pred_temp_c, ref_temp_c             15-level temperature, model and reference
  in_sst_c, in_ssh_m, in_sss, ...     the de-normalised model inputs
  in_max_abs_z                        largest |z| of the 7 inputs vs training data
  model_<diag>, ref_<diag>            D26, D20, TCHP, MLD, thermocline, T100
  profile_rmse_c                      per-cell RMSE, model vs reference
  <out>.latent.npy (time, cell, 128)  float16 embeddings for similarity search
  split (time)                        train / heldout / independent
===============================================================================
"""

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd
import torch
import xarray as xr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import oceanembed_core as core  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="/kaggle/tmp/ocean_data")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2023-01-30")
    ap.add_argument("--stats-json", default=None,
                    help="frozen training statistics; required for any period other than the training range")
    ap.add_argument("--reference-file", default="GLORYS12V1.nc")
    ap.add_argument("--reference-var", default="thetao")
    ap.add_argument("--reference-name", default="GLORYS12 reanalysis")
    ap.add_argument("--checkpoint", default=os.path.join(HERE, "trained", "best_oceanembed_model.pth"))
    ap.add_argument("--out", default=None, help="default: basin_output/basin_<start>_<end>.nc")
    ap.add_argument("--batch", type=int, default=2048)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    out_path = args.out or os.path.join(HERE, "basin_output", f"basin_{args.start}_{args.end}.nc")

    import kaggle_oceanembed_eval as ev

    fixed = None
    train_info = None
    if args.stats_json:
        with open(args.stats_json) as f:
            sj = json.load(f)
        fixed = {k: (v["mean"], v["std"]) for k, v in sj["stats"].items()}
        train_info = sj

    surface, target, dates, harmonizer = ev.build_ocean_fields_from_netcdf(
        data_dir=args.data_dir, start_date=args.start, end_date=args.end, fixed_stats=fixed,
        reference_file=args.reference_file, reference_var=args.reference_var)
    T, C, H, W = surface.shape
    assert C == core.IN_CHANNELS and target.shape == (T, core.NUM_DEPTHS, H, W)

    # Day labels
    if train_info is None:
        n_train = max(1, int(0.8 * T))              # identical split to RealOceanPatchDataset
        split = np.array(["train"] * n_train + ["heldout"] * (T - n_train))
        train_meta = {"date_range": f"{args.start}..{args.end}", "train_days": n_train}
    else:
        t0, t1 = [pd.Timestamp(x) for x in train_info["date_range"].split("..")]
        tr_days = pd.date_range(t0, t1, freq="D")
        train_set = set(tr_days[: train_info["train_days"]])
        held_set = set(tr_days[train_info["train_days"]:])
        split = np.array(["train" if d in train_set else "heldout" if d in held_set else "independent" for d in dates])
        train_meta = {"date_range": train_info["date_range"], "train_days": train_info["train_days"]}

    device = torch.device(args.device)
    model = core.load_trained_model(args.checkpoint, device)
    ckpt_hash = core.file_sha256(args.checkpoint)
    print(f"[+] Loaded {args.checkpoint} (sha256 {ckpt_hash[:12]}…) on {device}")

    # Cells predicted: complete 0–1000 m reference profile (the rule that selected training samples)
    valid_cells = ~np.isnan(target).any(axis=1)             # (T, H, W)
    any_valid = valid_cells.any(axis=0)
    cell_r, cell_c = np.nonzero(any_valid)
    cell_index = -np.ones((H, W), dtype=np.int64)
    cell_index[cell_r, cell_c] = np.arange(cell_r.size)

    pred = np.full((T, core.NUM_DEPTHS, H, W), np.nan, dtype=np.float32)
    latent = np.full((T, cell_r.size, 128), np.nan, dtype=np.float16)
    with torch.no_grad():
        for t in range(T):
            padded = core.reflect_pad(torch.from_numpy(surface[t]).float()).to(device)
            rows, cols = np.nonzero(valid_cells[t])
            for s in range(0, rows.size, args.batch):
                r, c = rows[s:s + args.batch], cols[s:s + args.batch]
                out, lat_vec = model(core.extract_patches(padded, r, c))
                pred[t][:, r, c] = out.cpu().numpy().T
                latent[t, cell_index[r, c]] = lat_vec.cpu().numpy().astype(np.float16)
            print(f"    day {t + 1:02d}/{T} {dates[t].date()} [{split[t]}]: {rows.size} deep-water cells")

    # De-normalise the inputs exactly (x = x' (σ + 1e-6) + μ where mask = 1) and score them against training
    inputs, zmax = {}, np.zeros((T, H, W), dtype=np.float32)
    for i, name in enumerate(core.SURFACE_VARS):
        mean, std = harmonizer.stats[name]
        norm, mask = surface[:, 2 * i], surface[:, 2 * i + 1]
        inputs[name] = np.where(mask > 0.5, norm * (std + 1e-6) + mean, np.nan).astype(np.float32)
        zmax = np.fmax(zmax, np.where(mask > 0.5, np.abs(norm), np.nan).astype(np.float32))
    sst_units = "K" if harmonizer.stats["sst"][0] > 100 else "degC"
    if sst_units == "K":
        inputs["sst"] = inputs["sst"] - np.float32(273.15)

    diag_names = list(core.DIAGNOSTIC_META)
    diags = {f"{src}_{k}": np.full((T, H, W), np.nan, dtype=np.float32) for src in ("model", "ref") for k in diag_names}
    rmse = np.full((T, H, W), np.nan, dtype=np.float32)
    for t in range(T):
        m = valid_cells[t]
        P, G = pred[t][:, m].T, target[t][:, m].T
        for src, prof in (("model", P), ("ref", G)):
            for k, v in core.all_diagnostics(prof).items():
                diags[f"{src}_{k}"][t][m] = v
        rmse[t][m] = core.profile_rmse(P, G)

    def pooled(sel):
        if not sel.any():
            return None, None
        e = pred[sel] - target[sel]
        return float(np.sqrt(np.nanmean(e ** 2))), np.sqrt(np.nanmean(e ** 2, axis=(0, 2, 3))).tolist()
    skill = {s: pooled(split == s) for s in ("train", "heldout", "independent")}
    for s, (v, _) in skill.items():
        if v is not None:
            print(f"[✔] RMSE vs {args.reference_name} on {s} days: {v:.4f} °C")

    fixture_flags = []
    for fname in ("OSTIA_SST.nc", "ERA5_WINDS.nc", "COPERNICUS_CURRENTS_SSH.nc", args.reference_file):
        p = os.path.join(args.data_dir, fname)
        if os.path.exists(p):
            with xr.open_dataset(p) as src:
                if str(src.attrs.get("fixture", "")).lower() == "synthetic":
                    fixture_flags.append(fname)
    input_data = "SYNTHETIC TEST FIXTURE" if fixture_flags else "real NetCDF downloads"
    if fixture_flags:
        print(f"[!] {fixture_flags} are synthetic test fixtures — output is flagged accordingly.")
    source_products = {}
    for fname in ("OSTIA_SST.nc", "ERA5_WINDS.nc", "COPERNICUS_CURRENTS_SSH.nc", args.reference_file):
        p = os.path.join(args.data_dir, fname)
        if os.path.exists(p):
            with xr.open_dataset(p) as src:
                source_products[fname] = str(src.attrs.get("oceanembed_source", src.attrs.get("title", "")))[:200]

    # Extra reference profiles (salinity, currents) when the reference file has them: same depth
    # interpolation, time matching and regridding as the temperature target.
    extra = {}
    ref_path = os.path.join(args.data_dir, args.reference_file)
    with xr.open_dataset(ref_path) as rds:
        for var, out_name in (("so", "ref_so_psu"), ("uo", "ref_uo_ms"), ("vo", "ref_vo_ms")):
            if var not in rds.data_vars:
                continue
            da = ev.standardize_coords(rds[var])
            da = da.interp(depth=core.DEPTH_LEVELS, method="linear", kwargs={"fill_value": "extrapolate"})
            ev.check_time_coverage(da, dates, var)
            da = da.interp(time=dates, method="nearest")
            arr = np.stack([harmonizer.regrid_dataarray(da.isel(time=t)) for t in range(T)]).astype(np.float32)
            arr[~np.broadcast_to(valid_cells[:, None], arr.shape)] = np.nan
            extra[out_name] = arr
            print(f"[+] stored reference {var} profiles")

    lat = np.asarray(ev.LAT_GRID, dtype=np.float32)
    lon = np.asarray(ev.LON_GRID, dtype=np.float32)
    d4, d3 = ("time", "depth", "latitude", "longitude"), ("time", "latitude", "longitude")
    dv = {
        "pred_temp_c": (d4, pred, {"units": "degC", "long_name": "OceanEmbed predicted temperature"}),
        "ref_temp_c": (d4, target.astype(np.float32), {"units": "degC", "long_name": f"{args.reference_name} on standard levels"}),
        "profile_rmse_c": (d3, rmse, {"units": "degC", "long_name": "RMSE over 15 levels, model vs reference"}),
        "in_max_abs_z": (d3, zmax, {"long_name": "largest |z| of the 7 inputs w.r.t. training statistics"}),
        "split": (("time",), split.astype("U11"), {"long_name": "train / heldout (training period) / independent"}),
        "cell_row": (("cell",), cell_r.astype(np.int32)),
        "cell_col": (("cell",), cell_c.astype(np.int32)),
    }
    in_meta = {"sst": ("in_sst_c", "degC"), "ssh": ("in_ssh_m", "m"), "sss": ("in_sss", "PSU (as in source)"),
               "uo": ("in_uo_ms", "m/s"), "vo": ("in_vo_ms", "m/s"), "u10": ("in_u10_ms", "m/s"), "v10": ("in_v10_ms", "m/s")}
    for k, arr in extra.items():
        dv[k] = (d4, arr, {"units": "PSU" if "so" in k else "m/s", "long_name": f"{args.reference_name} {k.split('_')[1]} on standard levels"})
    for k, (vname, units) in in_meta.items():
        dv[vname] = (d3, inputs[k], {"units": units, "long_name": f"model input {k} (de-normalised)"})
    for k, arr in diags.items():
        meta = core.DIAGNOSTIC_META[k.split("_", 1)[1]]
        dv[k] = (d3, arr, {"units": meta["units"], "long_name": meta["label"], "method": meta["method"]})

    ds = xr.Dataset(
        dv,
        coords={"time": dates.values, "depth": core.DEPTH_LEVELS.astype(np.float32), "latitude": lat, "longitude": lon},
        attrs={
            "title": "OceanEmbed basin-wide inference",
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "input_data": input_data,
            "source_files_json": json.dumps(source_products),
            "checkpoint": os.path.basename(args.checkpoint),
            "checkpoint_sha256": ckpt_hash,
            "date_range": f"{args.start}..{args.end}",
            "reference_name": args.reference_name,
            "training_period_json": json.dumps(train_meta),
            "normalisation": "frozen training statistics" if fixed else "recomputed on this (training) range",
            "normalisation_stats_json": json.dumps({k: list(v) for k, v in harmonizer.stats.items()}),
            "sst_source_units": sst_units,
            "skill_json": json.dumps({s: {"rmse_c": v, "rmse_by_depth_c": d} for s, (v, d) in skill.items()}),
            "tchp_constants": f"rho={core.RHO_SEAWATER} kg/m3, cp={core.CP_SEAWATER} J/kg/K",
            "valid_cell_rule": "complete 0-1000 m reference profile (same rule used to select training samples)",
        },
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    enc = {v: {"zlib": True, "complevel": 4} for v in ds.data_vars if ds[v].dtype == np.float32}
    ds.attrs["latent_file"] = os.path.basename(out_path) + ".latent.npy"
    ds.to_netcdf(out_path, encoding=enc)
    np.save(out_path + ".latent.npy", latent)          # (time, cell, 128) float16; cell -> (cell_row, cell_col)
    print(f"[✔] Wrote {out_path} ({os.path.getsize(out_path) / 1e6:.1f} MB) and its embeddings "
          f"({os.path.getsize(out_path + '.latent.npy') / 1e6:.1f} MB)")

    if fixed is None:
        stats_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "normalisation_stats.json")
        with open(stats_path, "w") as f:
            json.dump({"stats": {k: {"mean": float(v[0]), "std": float(v[1])} for k, v in harmonizer.stats.items()},
                       "sst_units": sst_units, "input_data": input_data,
                       "method": "build_ocean_fields_from_netcdf over the training range (first 80% of days)",
                       **train_meta}, f, indent=2)
        print(f"[✔] Wrote {stats_path}")


if __name__ == "__main__":
    main()
