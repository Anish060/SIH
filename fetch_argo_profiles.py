"""
===============================================================================
OceanEmbed — individual Argo float profiles for assimilation and validation
===============================================================================
Downloads Argo profiles in the model domain for a date range with argopy
(Ifremer ERDDAP, 'standard' user mode = quality-controlled, adjusted values
where available), then for each profile:
  * converts pressure to depth (TEOS-10, gsw.z_from_p at the float's latitude),
  * converts in-situ temperature to POTENTIAL temperature (gsw.pt0_from_t), which
    is what GLORYS and OceanEmbed predict (the difference is ~0.1 °C at 1000 m),
  * interpolates linearly to the 15 standard depths, without extrapolation
    (levels above the shallowest or below the deepest measurement stay NaN).
Writes basin_output/argo_profiles_<start>_<end>.nc.

  pip install argopy
  python fetch_argo_profiles.py --start 2023-05-08 --end 2023-05-18
===============================================================================
"""
import argparse
import os

import numpy as np
import pandas as pd
import xarray as xr

HERE = os.path.dirname(os.path.abspath(__file__))
DEPTHS = np.array([0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000], float)


def to_standard_levels(prof_pres, prof_temp, prof_psal, lat, lon):
    import gsw
    ok = np.isfinite(prof_pres) & np.isfinite(prof_temp) & np.isfinite(prof_psal)
    if ok.sum() < 5:
        return None, None
    p, t, s = prof_pres[ok], prof_temp[ok], prof_psal[ok]
    order = np.argsort(p)
    p, t, s = p[order], t[order], s[order]
    z = -gsw.z_from_p(p, lat)
    SA = gsw.SA_from_SP(s, p, lon, lat)
    pt = gsw.pt0_from_t(SA, t, p)
    pt_std = np.interp(DEPTHS, z, pt, left=np.nan, right=np.nan)
    s_std = np.interp(DEPTHS, z, s, left=np.nan, right=np.nan)
    return pt_std, s_std


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--box", default="45,105,5,30", help="lon_min,lon_max,lat_min,lat_max")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    lo0, lo1, la0, la1 = map(float, a.box.split(","))
    from argopy import DataFetcher
    ds = DataFetcher(src="erddap", mode="standard").region(
        [lo0, lo1, la0, la1, 0, 1100, a.start, a.end]).to_xarray().argo.point2profile()
    rows = []
    for i in range(ds.sizes["N_PROF"]):
        pr = ds.isel(N_PROF=i)
        lat, lon = float(pr.LATITUDE), float(pr.LONGITUDE)
        pt, s = to_standard_levels(pr.PRES.values.astype(float), pr.TEMP.values.astype(float), pr.PSAL.values.astype(float), lat, lon)
        if pt is None:
            continue
        rows.append((pd.Timestamp(pr.TIME.values), lat, lon, int(pr.PLATFORM_NUMBER), int(pr.CYCLE_NUMBER), pt, s))
    if not rows:
        raise SystemExit("[!] no usable profiles")
    out = xr.Dataset(
        {"pt_c": (("profile", "depth"), np.stack([r[5] for r in rows]).astype(np.float32), {"units": "degC", "long_name": "potential temperature (TEOS-10 pt0_from_t)"}),
         "psal": (("profile", "depth"), np.stack([r[6] for r in rows]).astype(np.float32), {"units": "PSU"}),
         "time": (("profile",), np.array([r[0] for r in rows], dtype="datetime64[ns]")),
         "latitude": (("profile",), np.array([r[1] for r in rows], np.float32)),
         "longitude": (("profile",), np.array([r[2] for r in rows], np.float32)),
         "platform": (("profile",), np.array([r[3] for r in rows], np.int64)),
         "cycle": (("profile",), np.array([r[4] for r in rows], np.int32))},
        coords={"depth": DEPTHS},
        attrs={"source": "Argo GDAC via argopy (Ifremer ERDDAP), user mode 'standard'",
               "processing_level": "in-situ profiles, real-time/delayed-mode QC ('standard' mode keeps good data, adjusted where available)",
               "citation": "Argo (2000). Argo float data and metadata from GDAC. SEANOE. doi:10.17882/42182",
               "vertical": "pressure -> depth with gsw.z_from_p; in-situ -> potential temperature; linear, no extrapolation"})
    path = a.out or os.path.join(HERE, "basin_output", f"argo_profiles_{a.start}_{a.end}.nc")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.to_netcdf(path)
    print(f"[✔] {len(rows)} profiles -> {path}")


if __name__ == "__main__":
    main()
