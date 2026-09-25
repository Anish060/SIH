"""
===============================================================================
OceanEmbed — gradient-boosted-tree baseline for thermocline depth (D20)
===============================================================================
Trains XGBoost on the SAME cells and days as the CNN, from the basin file:
features = the 7 surface inputs at the cell + latitude/longitude, target = the
reference D20 (20 °C isotherm depth). Trains on 'train' days, tests on
'heldout' (and any 'independent') days, and scores the CNN's D20 on exactly the
same test cells, so the comparison is like for like.
Writes basin_output/xgb_baseline.json.

  python train_xgb_baseline.py --basin basin_output/basin_2023-01-01_2023-01-30.nc
===============================================================================
"""
import argparse
import datetime as dt
import json
import os

import numpy as np
import xarray as xr

HERE = os.path.dirname(os.path.abspath(__file__))
FEATURES = ["in_sst_c", "in_ssh_m", "in_sss", "in_uo_ms", "in_vo_ms", "in_u10_ms", "in_v10_ms"]


def table(ds, sel):
    t = np.nonzero(sel)[0]
    LAT, LON = np.meshgrid(ds.latitude.values, ds.longitude.values, indexing="ij")
    X, y, cnn = [], [], []
    for ti in t:
        cols = [ds[v].values[ti] for v in FEATURES] + [LAT, LON]
        A = np.stack([c.ravel() for c in cols], axis=1)
        yy = ds["ref_d20_m"].values[ti].ravel()
        cc = ds["model_d20_m"].values[ti].ravel()
        ok = np.isfinite(A).all(axis=1) & np.isfinite(yy) & np.isfinite(cc)
        X.append(A[ok]); y.append(yy[ok]); cnn.append(cc[ok])
    return np.concatenate(X), np.concatenate(y), np.concatenate(cnn)


def scores(pred, obs):
    e = pred - obs
    return {"rmse_m": float(np.sqrt(np.mean(e ** 2))), "mae_m": float(np.mean(np.abs(e))), "bias_m": float(np.mean(e)),
            "r2": float(1 - np.sum(e ** 2) / np.sum((obs - obs.mean()) ** 2)), "n": int(obs.size)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basin", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "basin_output", "xgb_baseline.json"))
    ap.add_argument("--n-estimators", type=int, default=400)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    a = ap.parse_args()
    import xgboost as xgb
    ds = xr.open_dataset(a.basin)
    split = ds["split"].values
    Xtr, ytr, _ = table(ds, split == "train")
    test_sel = np.isin(split, ["heldout", "independent"])
    if not test_sel.any():
        raise SystemExit("[!] no held-out/independent days in this file")
    Xte, yte, cnn = table(ds, test_sel)
    m = xgb.XGBRegressor(n_estimators=a.n_estimators, max_depth=a.max_depth, learning_rate=a.learning_rate,
                         subsample=0.8, colsample_bytree=0.9, random_state=0, tree_method="hist")
    m.fit(Xtr, ytr)
    px = m.predict(Xte)
    res = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "basin_file": os.path.basename(a.basin), "input_data": ds.attrs.get("input_data"),
        "target": f"D20 from {ds.attrs.get('reference_name')}", "features": FEATURES + ["latitude", "longitude"],
        "train_days": int((split == "train").sum()), "test_days": int(test_sel.sum()), "n_train": int(ytr.size),
        "hyperparameters": {"n_estimators": a.n_estimators, "max_depth": a.max_depth, "learning_rate": a.learning_rate},
        "xgboost": scores(px, yte), "oceanembed_cnn": scores(cnn, yte),
        "feature_importance": dict(zip(FEATURES + ["latitude", "longitude"], map(float, m.feature_importances_))),
        "note": "Same test cells for both models. Latitude/longitude let the trees learn geography, which the CNN sees only through the input patch.",
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=2)
    m.save_model(os.path.splitext(a.out)[0] + ".ubj")
    print(f"[✔] XGBoost D20 RMSE {res['xgboost']['rmse_m']:.2f} m | OceanEmbed {res['oceanembed_cnn']['rmse_m']:.2f} m -> {a.out}")


if __name__ == "__main__":
    main()
