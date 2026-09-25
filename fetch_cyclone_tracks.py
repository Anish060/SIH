"""
===============================================================================
OceanEmbed — cyclone best tracks from IBTrACS (NOAA NCEI)
===============================================================================
Downloads the North Indian basin IBTrACS CSV and writes the requested storms to
basin_output/cyclone_tracks.json, which the API serves to the cyclone replay.
Positions, winds and pressures are the WMO-agency best track (IMD for the North
Indian Ocean). Nothing is typed in by hand.

  python fetch_cyclone_tracks.py --storm MOCHA:2023 --storm MICHAUNG:2023

The model's ocean heat along a track is only shown for days you have also run
basin_inference.py on (with --stats-json). Pick storms inside the input archives:
CMEMS analysis-forecast surface fields start 2020-11-01.

Knapp et al. (2010), BAMS 91, 363–376, doi:10.1175/2009BAMS2755.1
===============================================================================
"""
import argparse
import io
import json
import os
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
URLS = [
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.NI.list.v04r01.csv",
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r00/access/csv/ibtracs.NI.list.v04r00.csv",
]


def load_ibtracs(path_or_url=None):
    sources = [path_or_url] if path_or_url else URLS
    last = None
    for src in sources:
        try:
            if os.path.exists(src):
                raw = open(src, "rb").read()
            else:
                with urllib.request.urlopen(src, timeout=120) as r:
                    raw = r.read()
            df = pd.read_csv(io.BytesIO(raw), skiprows=[1], low_memory=False, keep_default_na=False)
            return df, src
        except Exception as e:
            last = e
            print(f"[!] could not read {src}: {e}")
    raise RuntimeError(f"IBTrACS unavailable: {last}")


def num(series):
    return pd.to_numeric(series.astype(str).str.strip().replace("", None), errors="coerce")


def extract(df, name, season):
    sel = df[(df["NAME"].str.upper() == name.upper()) & (num(df["SEASON"]) == season)]
    if "TRACK_TYPE" in sel:
        sel = sel[sel["TRACK_TYPE"].str.lower() == "main"]
    if sel.empty:
        raise ValueError(f"{name} {season} not found in IBTrACS")
    pts = []
    for _, r in sel.iterrows():
        def f(col):
            if col not in r:
                return None
            v = pd.to_numeric(str(r[col]).strip() or "nan", errors="coerce")
            return None if pd.isna(v) else float(v)
        pts.append({
            "time": pd.Timestamp(r["ISO_TIME"]).isoformat(),
            "lat": f("LAT"), "lon": f("LON"),
            "wmo_wind_kt": f("WMO_WIND"), "wmo_pres_hpa": f("WMO_PRES"),
            "imd_grade": (str(r.get("NEWDELHI_GRADE", "")).strip() or None),
        })
    return {"sid": str(sel["SID"].iloc[0]), "name": name.upper(), "season": int(season),
            "wmo_agency": next((a for a in sel.get("WMO_AGENCY", pd.Series(dtype=str)).astype(str).str.strip() if a), None),
            "points": pts}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--storm", action="append", default=None, help="NAME:SEASON (repeatable)")
    ap.add_argument("--csv", default=None, help="local IBTrACS CSV instead of downloading")
    ap.add_argument("--out", default=os.path.join(HERE, "basin_output", "cyclone_tracks.json"))
    a = ap.parse_args()
    storms = a.storm or ["MOCHA:2023", "MICHAUNG:2023"]
    df, src = load_ibtracs(a.csv)
    tracks = []
    for s in storms:
        name, season = s.split(":")
        t = extract(df, name, int(season))
        print(f"[✔] {t['name']} {t['season']}: {len(t['points'])} track points")
        tracks.append(t)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump({"source": f"IBTrACS North Indian basin ({os.path.basename(src)}), NOAA NCEI",
                   "citation": "Knapp et al. 2010, BAMS 91, 363-376", "tracks": tracks}, f, indent=2)
    print(f"[✔] Wrote {a.out}")


if __name__ == "__main__":
    main()
