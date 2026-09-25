"""
TEST FIXTURE ONLY — writes small NetCDF files with the same file names, variable
names, dimensions and units as the real downloads (OSTIA, Copernicus currents,
ERA5, GLORYS12V1) so the ingestion -> inference -> API -> dashboard path can be
exercised without Copernicus credentials.

The values are idealised, NOT observations. Never publish results produced
from these files. Every file carries the attribute  fixture = "synthetic".

    python tests/make_fixture_netcdf.py /tmp/fixture_data 2023-01-01 2023-01-10
"""
import os
import sys

import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.path import Path

# Rough land polygons (lon, lat) for masking only
LAND = [
    [(68, 23.5), (72.5, 21), (73, 16), (74.5, 12), (76.5, 8.1), (77.5, 8), (80.2, 13), (80.2, 15.5), (82.3, 17),
     (85, 19.3), (86.9, 21.5), (88.5, 21.8), (91.8, 22.5), (92.3, 21), (94.3, 16), (97.6, 16.5), (98.5, 13),
     (98.3, 8.5), (100.3, 6), (100.3, 13.5), (105, 13.5), (105, 30.5), (44, 30.5), (44, 12.5), (51.5, 15.5),
     (56, 18), (58.5, 20.5), (59.8, 22.5), (57, 24), (61.5, 25.2), (66.5, 25.3)],
    [(79.8, 6), (81.8, 7), (81.3, 8.6), (80, 9.8)],                                # Sri Lanka
    [(44, 11.5), (51, 11.8), (51.3, 10.4), (48, 4.5), (44, 4.5)],                     # Horn of Africa
    [(95.2, 5.6), (97.5, 5.2), (99, 4.4), (105, 4.4), (105, 5.6), (100, 5.6)],        # N Sumatra/Malaya
]
GLORYS_DEPTHS = np.array([0.494, 1.54, 2.65, 5.08, 9.82, 11.4, 21.6, 25.2, 29.4, 34.4, 47.4, 55.8, 77.9, 92.3,
                          109.7, 130.7, 155.9, 186.1, 222.5, 266.0, 318.1, 380.2, 453.9, 541.1, 643.6, 763.3,
                          902.3, 1062.4, 1245.3])


def land_mask(lat, lon):
    LON, LAT = np.meshgrid(lon, lat)
    pts = np.c_[LON.ravel(), LAT.ravel()]
    m = np.zeros(len(pts), bool)
    for poly in LAND:
        m |= Path(poly).contains_points(pts)
    return m.reshape(LAT.shape)


def main(out, start, end):
    os.makedirs(out, exist_ok=True)
    dates = pd.date_range(start, end, freq="D")
    nt = len(dates)
    rng = np.random.default_rng(0)
    attrs = {"fixture": "synthetic", "note": "TEST FIXTURE ONLY - idealised values, not observations"}

    lat = np.arange(4.0, 31.01, 0.25)
    lon = np.arange(44.0, 106.01, 0.25)
    LON, LAT = np.meshgrid(lon, lat)
    land = land_mask(lat, lon)
    tday = np.arange(nt)[:, None, None]

    # idealised surface fields
    sst_c = 28.6 - 0.12 * (LAT - 10) + 0.6 * np.sin(np.radians(LON * 3)) + 0.05 * np.sin(tday / 3.0)
    ssh = 0.1 * np.exp(-(((LAT - 14.5) / 2.5) ** 2 + ((LON - 88) / 3) ** 2)) - 0.08 * np.exp(-(((LAT - 17.5) / 1.5) ** 2 + ((LON - 84) / 1.5) ** 2))
    sss = 34.5 - 2.5 * np.exp(-(((LAT - 21) / 3) ** 2 + ((LON - 89) / 3) ** 2))
    uo = -0.1 + 0.05 * np.cos(np.radians(LAT * 8))
    vo = 0.05 * np.sin(np.radians(LON * 6))

    def surf(a):
        a = np.broadcast_to(a, (nt,) + LAT.shape).astype(np.float32).copy()
        a[:, land] = np.nan
        return a

    xr.Dataset({"analysed_sst": (("time", "latitude", "longitude"), surf(sst_c + 273.15), {"units": "kelvin"})},
               coords={"time": dates, "latitude": lat, "longitude": lon}, attrs=attrs).to_netcdf(f"{out}/OSTIA_SST.nc")

    d1 = np.array([0.494])
    four = lambda a: surf(a)[:, None]  # noqa: E731
    xr.Dataset({"zos": (("time", "latitude", "longitude"), surf(ssh)),
                "so": (("time", "depth", "latitude", "longitude"), four(sss)),
                "uo": (("time", "depth", "latitude", "longitude"), four(uo)),
                "vo": (("time", "depth", "latitude", "longitude"), four(vo))},
               coords={"time": dates, "depth": d1, "latitude": lat, "longitude": lon}, attrs=attrs
               ).to_netcdf(f"{out}/COPERNICUS_CURRENTS_SSH.nc")

    lat_desc = lat[::-1]                                       # ERA5 stores latitude descending
    u10 = -2 + 3 * np.sin(np.radians(LAT * 10))[::-1] + rng.normal(0, 0.3, (nt,) + LAT.shape)
    v10 = -3 + 2 * np.cos(np.radians(LON * 5))[::-1] + rng.normal(0, 0.3, (nt,) + LAT.shape)
    xr.Dataset({"u10": (("valid_time", "latitude", "longitude"), u10.astype(np.float32)),
                "v10": (("valid_time", "latitude", "longitude"), v10.astype(np.float32))},
               coords={"valid_time": dates, "latitude": lat_desc, "longitude": lon}, attrs=attrs
               ).to_netcdf(f"{out}/ERA5_WINDS.nc")

    # idealised subsurface: mixed layer + exponential decay; D shallower near coasts (continental shelf)
    dist_coast = np.full(LAT.shape, 99.0)
    li, lj = np.nonzero(land)
    for i in range(0, LAT.shape[0]):
        d = np.hypot(LAT[i][:, None] - lat[li][None, :], LON[i][:, None] - lon[lj][None, :]).min(axis=1)
        dist_coast[i] = d
    seabed = np.where(dist_coast < 0.6, 200.0, 5000.0)
    mld = 25 + 30 * np.exp(-(((LAT - 14.5) / 3) ** 2 + ((LON - 88) / 4) ** 2)) + 400 * ssh
    scale = 150 + 300 * ssh
    z = GLORYS_DEPTHS[None, :, None, None]
    th = np.where(z <= mld[None, None], sst_c[None, None] if sst_c.ndim == 2 else sst_c[:, None],
                  4 + (sst_c[:, None] - 4) * np.exp(-(z - mld[None, None]) / scale[None, None]))
    th = np.broadcast_to(th, (nt, len(GLORYS_DEPTHS)) + LAT.shape).astype(np.float32).copy()
    th[:, :, land] = np.nan
    th[:, GLORYS_DEPTHS[:, None, None] * np.ones_like(seabed)[None] > seabed[None]] = np.nan
    so3 = (34.9 + 0.0 * th - 1.5 * np.exp(-GLORYS_DEPTHS[None, :, None, None] / 40.0)
           * np.exp(-(((LAT - 21) / 4) ** 2))[None, None]).astype(np.float32)
    so3[np.isnan(th)] = np.nan
    uo3 = (0.3 * np.exp(-GLORYS_DEPTHS[None, :, None, None] / 80.0) * np.cos(np.radians(LAT * 8))[None, None] + 0 * th).astype(np.float32)
    vo3 = (0.2 * np.exp(-GLORYS_DEPTHS[None, :, None, None] / 80.0) * np.sin(np.radians(LON * 6))[None, None] + 0 * th).astype(np.float32)
    xr.Dataset({"thetao": (("time", "depth", "latitude", "longitude"), th, {"units": "degrees_C"}),
                "so": (("time", "depth", "latitude", "longitude"), so3, {"units": "PSU"}),
                "uo": (("time", "depth", "latitude", "longitude"), uo3, {"units": "m/s"}),
                "vo": (("time", "depth", "latitude", "longitude"), vo3, {"units": "m/s"})},
               coords={"time": dates, "depth": GLORYS_DEPTHS, "latitude": lat, "longitude": lon}, attrs=attrs
               ).to_netcdf(f"{out}/GLORYS12V1.nc")
    # Monthly gridded "Argo" analysis on its own 1° grid, top level 5 m (no 0 m level), mid-month stamp
    alat, alon = np.arange(4.5, 31, 1.0), np.arange(44.5, 106, 1.0)
    adepth = np.array([5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 750, 1000], dtype=float)
    months = pd.date_range(dates[0] - pd.Timedelta(days=dates[0].day - 1), dates[-1], freq="MS") + pd.Timedelta(days=14)
    A = xr.DataArray(th.mean(axis=0), coords={"depth": GLORYS_DEPTHS, "latitude": lat, "longitude": lon},
                     dims=("depth", "latitude", "longitude")).interp(depth=adepth, latitude=alat, longitude=alon)
    A = A + 0.3 * rng.standard_normal(A.shape)          # "observation" noise so it differs from GLORYS
    arr = np.broadcast_to(A.values, (len(months),) + A.shape).astype(np.float32)
    xr.Dataset({"temp": (("time", "depth", "latitude", "longitude"), arr, {"units": "degC"})},
               coords={"time": months, "depth": adepth, "latitude": alat, "longitude": alon}, attrs=attrs
               ).to_netcdf(f"{out}/INCOIS_ARGO.nc")
    print(f"[fixture] wrote synthetic test files to {out} for {nt} days")


if __name__ == "__main__":
    main(*(sys.argv[1:4] if len(sys.argv) >= 4 else ("/tmp/fixture_data", "2023-01-01", "2023-01-10")))
