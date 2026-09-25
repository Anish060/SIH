"""
===============================================================================
OceanEmbed — download the model inputs (and a reference profile) for a period
===============================================================================
Writes the files basin_inference.py reads, into --out-dir:
  OSTIA_SST.nc                 analysed_sst (K)
  COPERNICUS_CURRENTS_SSH.nc   uo, vo, so (top level) + zos, merged from three datasets
  ERA5_WINDS.nc                u10, v10 at 12:00 UTC
  <reference>.nc               subsurface temperature to compare against (0–1100 m)

Modes
  --mode reanalysis   same products as training: OSTIA REP, CMEMS analysis-forecast
                      surface fields, ERA5, and GLORYS12 (multiyear, then interim) as
                      reference -> GLORYS12V1.nc
  --mode nrt          near-real-time: OSTIA NRT instead of REP, and the operational
                      Mercator GLO12 analysis as reference -> MERCATOR_ANFC_THETAO.nc.
                      (No GLORYS exists for recent days.) Note OSTIA NRT is a different
                      processing chain from the REP product the model was trained on.

Credentials: `copernicusmarine login` (or COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD)
and a CDS API key in ~/.cdsapirc for ERA5.

Coverage limits (checked again at ingestion; a gap stops the run):
  CMEMS analysis-forecast archive starts 2020-11-01. ERA5 (ERA5T) lags real time by
  about 5 days, which sets the near-real-time lag.
===============================================================================
"""
import argparse
import os

import pandas as pd
import xarray as xr

LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 5.0, 30.0, 45.0, 105.0

SST_DATASETS = {
    "reanalysis": "METOFFICE-GLO-SST-L4-REP-OBS-SST",       # SST_GLO_SST_L4_REP_OBSERVATIONS_010_011 (training product)
    "nrt": "METOFFICE-GLO-SST-L4-NRT-OBS-SST-V2",           # SST_GLO_SST_L4_NRT_OBSERVATIONS_010_001
}
SURFACE_PARTS = [  # GLOBAL_ANALYSISFORECAST_PHY_001_024
    ("cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m", ["uo", "vo"], True),
    ("cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m", ["so"], True),
    ("cmems_mod_glo_phy_anfc_0.083deg_P1D-m", ["zos"], False),
]
REFERENCES = {
    # name, [(dataset_id, variables), ...] tried/merged as noted
    "reanalysis": ("GLORYS12V1.nc", [[("cmems_mod_glo_phy_my_0.083deg_P1D-m", ["thetao", "so", "uo", "vo"])],
                                     [("cmems_mod_glo_phy_myint_0.083deg_P1D-m", ["thetao", "so", "uo", "vo"])]]),
    "nrt": ("MERCATOR_ANFC_THETAO.nc", [[("cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m", ["thetao"]),
                                         ("cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m", ["so"]),
                                         ("cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m", ["uo", "vo"])]]),
}
PROCESSING_LEVEL = {
    "OSTIA_SST.nc": "L4 gap-free SST analysis (satellite + in situ), UK Met Office OSTIA",
    "COPERNICUS_CURRENTS_SSH.nc": "Model analysis (Mercator GLO12 / NEMO with data assimilation)",
    "ERA5_WINDS.nc": "Atmospheric reanalysis (ECMWF ERA5 / ERA5T)",
    "GLORYS12V1.nc": "Ocean reanalysis (GLORYS12, NEMO with data assimilation)",
    "MERCATOR_ANFC_THETAO.nc": "Operational model analysis (Mercator GLO12 / NEMO)",
}


def cm_subset(out_dir, fname, dataset_id, variables, start, end, depth=None):
    import copernicusmarine
    kw = dict(dataset_id=dataset_id, variables=variables,
              minimum_latitude=LAT_MIN, maximum_latitude=LAT_MAX, minimum_longitude=LON_MIN, maximum_longitude=LON_MAX,
              start_datetime=f"{start}T00:00:00", end_datetime=f"{end}T23:59:59",
              output_directory=out_dir, output_filename=fname)
    if depth is not None:
        kw["minimum_depth"], kw["maximum_depth"] = depth
    copernicusmarine.subset(**kw)
    path = os.path.join(out_dir, fname)
    with xr.open_dataset(path) as d:
        d.load()
        d.attrs["oceanembed_source"] = f"Copernicus Marine {dataset_id} {variables}"
        d.attrs["oceanembed_downloaded_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    d.to_netcdf(path + ".tmp")
    os.replace(path + ".tmp", path)
    return path


def fetch(out_dir, start, end, mode):
    os.makedirs(out_dir, exist_ok=True)
    print(f"[+] {mode}: {start}..{end} -> {out_dir}")

    cm_subset(out_dir, "OSTIA_SST.nc", SST_DATASETS[mode], ["analysed_sst"], start, end)

    parts = []
    for i, (ds_id, vars_, surface_only) in enumerate(SURFACE_PARTS):
        parts.append(cm_subset(out_dir, f"_surface_part{i}.nc", ds_id, vars_, start, end, (0.0, 1.0) if surface_only else None))
    merged = xr.merge([xr.open_dataset(p) for p in parts], compat="override", join="exact")
    merged.attrs["oceanembed_source"] = "Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY_001_024: -cur (uo,vo), -so (so), phy_anfc (zos)"
    merged.to_netcdf(os.path.join(out_dir, "COPERNICUS_CURRENTS_SSH.nc"))
    merged.close()

    import cdsapi
    days = pd.date_range(start, end, freq="D")
    era = os.path.join(out_dir, "ERA5_WINDS.nc")
    parts = []
    for (y, m), grp in pd.Series(days).groupby([days.year, days.month]):
        p = os.path.join(out_dir, f"_era5_{y}{m:02d}.nc")
        cdsapi.Client().retrieve("reanalysis-era5-single-levels", {
            "product_type": ["reanalysis"],
            "variable": ["10m_u_component_of_wind", "10m_v_component_of_wind"],
            "year": [str(y)], "month": [f"{m:02d}"], "day": [f"{d.day:02d}" for d in grp],
            "time": ["12:00"], "area": [LAT_MAX, LON_MIN, LAT_MIN, LON_MAX],
            "data_format": "netcdf", "download_format": "unarchived",
        }, p)
        parts.append(p)
    e = xr.open_mfdataset(parts, combine="by_coords")
    e.attrs["oceanembed_source"] = "ERA5 reanalysis-era5-single-levels u10/v10 12:00 UTC (CDS)"
    e.to_netcdf(era)
    e.close()

    ref_name, alternatives = REFERENCES[mode]
    last_err = None
    for parts_spec in alternatives:
        try:
            files = [cm_subset(out_dir, f"_ref_part{i}.nc", ds_id, vars_, start, end, (0.0, 1100.0))
                     for i, (ds_id, vars_) in enumerate(parts_spec)]
            ref = xr.merge([xr.open_dataset(f) for f in files], compat="override", join="exact")
            ref.attrs["oceanembed_source"] = "; ".join(f"{d} {v}" for d, v in parts_spec)
            ref.to_netcdf(os.path.join(out_dir, ref_name))
            ref.close()
            print(f"[✔] reference from {ref.attrs['oceanembed_source']}")
            break
        except Exception as ex:           # the multiyear dataset ends before recent dates; try the interim one
            last_err = ex
            print(f"[!] reference option unavailable ({ex}); trying next")
    else:
        raise RuntimeError(f"No reference dataset covers {start}..{end}: {last_err}")
    for fname, level in PROCESSING_LEVEL.items():
        path = os.path.join(out_dir, fname)
        if os.path.exists(path):
            with xr.open_dataset(path) as d:
                d.load()
            d.attrs["processing_level"] = level
            d.to_netcdf(path + ".tmp")
            os.replace(path + ".tmp", path)
    print(f"[✔] Inputs ready in {out_dir}")
    return ref_name


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--mode", choices=["reanalysis", "nrt"], default="reanalysis")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    fetch(a.out_dir, a.start, a.end, a.mode)
