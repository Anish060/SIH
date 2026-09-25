"""
API tests against inference files built from the synthetic fixture.
    python tests/make_fixture_netcdf.py /tmp/fx 2023-01-01 2023-01-10
    python basin_inference.py --data-dir /tmp/fx --start 2023-01-01 --end 2023-01-10 --out /tmp/bo/basin_a.nc
    OCEANEMBED_BASIN_DIR=/tmp/bo python -m pytest tests/test_api.py -q
Skipped when OCEANEMBED_BASIN_DIR is not set.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pytestmark = pytest.mark.skipif("OCEANEMBED_BASIN_DIR" not in os.environ, reason="set OCEANEMBED_BASIN_DIR to fixture outputs")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app)


@pytest.fixture(scope="module")
def meta(client):
    r = client.get("/api/basin/meta")
    assert r.status_code == 200
    return r.json()


def a_day(meta, split=None):
    for d in meta["dates"]:
        if split is None or d["split"] == split:
            return d["date"]
    pytest.skip(f"no {split} day")


def test_point_is_read_from_file(client, meta):
    import xarray as xr
    date = a_day(meta, "heldout")
    j = client.get("/api/point", params={"date": date, "lat": 14.5, "lon": 88.0}).json()
    f = [x for x in meta["dates"] if x["date"] == date][0]["file"]
    ds = xr.open_dataset(os.path.join(os.environ["OCEANEMBED_BASIN_DIR"], f))
    t = [str(np.datetime_as_string(v, unit="D")) for v in ds.time.values].index(date)
    stored = ds.pred_temp_c.values[t, :, j["cell"]["row"], j["cell"]["col"]]
    np.testing.assert_allclose(j["model"]["profile_c"], stored, atol=6e-4)
    assert j["cell"]["distance_km"] < 30
    assert len(j["latent"]["vector"]) == 128


def test_sensitivity_zero_delta_reproduces_stored_prediction(client, meta):
    date = a_day(meta, "heldout")
    j = client.post("/api/sensitivity", json={"date": date, "lat": 14.5, "lon": 88.0, "deltas": {}}).json()
    assert j["reconstruction_max_abs_diff_c"] < 1e-3
    assert j["baseline"]["profile_c"] == j["perturbed"]["profile_c"]


def test_sensitivity_changes_output(client, meta):
    date = a_day(meta, "heldout")
    j = client.post("/api/sensitivity", json={"date": date, "lat": 14.5, "lon": 88.0, "deltas": {"sst": 1.0}}).json()
    assert j["baseline"]["profile_c"] != j["perturbed"]["profile_c"]
    assert client.post("/api/sensitivity", json={"date": date, "lat": 14.5, "lon": 88.0, "deltas": {"foo": 1}}).status_code == 400


def test_land_point_is_refused(client, meta):
    r = client.get("/api/point", params={"date": a_day(meta), "lat": 23.0, "lon": 78.0})   # central India
    assert r.status_code == 404


def test_volume_and_similar(client, meta):
    date = a_day(meta, "heldout")
    v = client.get("/api/volume", params={"date": date, "lat": 14.5, "lon": 88.0}).json()
    assert len(v["model_c"]) == 15 and len(v["model_c"][0]) == len(v["lats"])
    s = client.post("/api/similar", json={"date": date, "lat": 14.5, "lon": 88.0, "k": 5}).json()
    assert len(s["matches"]) == 5
    sims = [m["cosine_similarity"] for m in s["matches"]]
    assert sims == sorted(sims, reverse=True) and all(-1.0001 <= x <= 1.0001 for x in sims)
    assert all(not (m["date"] == date and m["distance_km"] < 300) for m in s["matches"])


def test_unknown_date_404(client):
    assert client.get("/api/point", params={"date": "1999-01-01", "lat": 14.5, "lon": 88.0}).status_code == 404
