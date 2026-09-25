"""
===============================================================================
OceanEmbed — near-real-time update (run once a day, e.g. from cron)
===============================================================================
1. Picks the latest window for which every input exists: ERA5 lags real time by
   about 5 days, so the window ends --lag-days before today (UTC).
2. Downloads OSTIA NRT SST, CMEMS surface fields, ERA5 winds and the operational
   Mercator analysis (fetch_period.py --mode nrt).
3. Runs the model with the FROZEN training statistics (basin_inference.py
   --stats-json), comparing against the Mercator analysis.
4. Keeps the newest --keep near-real-time files in basin_output/.

  python realtime_update.py                      # last 7 available days
  crontab:  15 9 * * *  cd /path/SIH-main && python realtime_update.py >> nrt.log 2>&1

Honest limits, also shown in the dashboard:
  * "Near-real-time" means about 5–6 days behind today, set by ERA5 latency.
  * The network was trained on January 2023 only. For other seasons the inputs can be
    outside the training range; every cell stores in_max_abs_z so this is visible.
===============================================================================
"""
import argparse
import glob
import os
import subprocess
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--lag-days", type=int, default=6)
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--work-dir", default=os.path.join(HERE, "nrt_data"))
    ap.add_argument("--stats-json", default=os.path.join(HERE, "basin_output", "normalisation_stats.json"))
    a = ap.parse_args()

    if not os.path.exists(a.stats_json):
        sys.exit(f"[!] {a.stats_json} missing: run basin_inference.py on the training period first.")
    end = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=a.lag_days)).date()
    start = (pd.Timestamp(end) - pd.Timedelta(days=a.days - 1)).date()
    data_dir = os.path.join(a.work_dir, f"{start}_{end}")

    import fetch_period
    ref = fetch_period.fetch(data_dir, str(start), str(end), "nrt")

    out = os.path.join(HERE, "basin_output", f"basin_nrt_{start}_{end}.nc")
    subprocess.check_call([sys.executable, os.path.join(HERE, "basin_inference.py"), "--data-dir", data_dir,
                           "--start", str(start), "--end", str(end), "--stats-json", a.stats_json,
                           "--reference-file", ref, "--reference-name", "Mercator GLO12 operational analysis",
                           "--out", out])
    nrt = sorted(glob.glob(os.path.join(HERE, "basin_output", "basin_nrt_*.nc")))
    for old in nrt[:-a.keep]:
        for f in (old, old + ".latent.npy"):
            if os.path.exists(f):
                os.remove(f)
    print(f"[✔] Near-real-time file ready: {out}")


if __name__ == "__main__":
    main()
