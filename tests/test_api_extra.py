"""
Role checks and science / explorer / admin / brief endpoints, against fixture outputs.
OCEANEMBED_BASIN_DIR=<fixture outputs> python -m pytest tests/test_api_extra.py -q
"""
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pytestmark = pytest.mark.skipif("OCEANEMBED_BASIN_DIR" not in os.environ, reason="set OCEANEMBED_BASIN_DIR to fixture outputs")


@pytest.fixture(scope="module")
def c():
    os.environ.setdefault("OCEANEMBED_STATE_DIR", tempfile.mkdtemp())
    from fastapi.testclient import TestClient
    import auth
    import server
    for u, r in [("ana", "admin"), ("sci", "scientist"), ("dm", "decision_maker"), ("eu", "end_user")]:
        auth.add_user(u, "password123", r)
    return TestClient(server.app)


def tok(c, u):
    r = c.post("/api/auth/login", json={"username": u, "password": "password123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def date(c):
    return [d["date"] for d in c.get("/api/basin/meta").json()["dates"] if d["split"] == "independent"][0]


def test_rbac(c):
    assert c.post("/api/auth/login", json={"username": "sci", "password": "wrong-pass"}).status_code == 401
    assert c.get("/api/science/xgb").status_code == 401
    assert c.get("/api/science/xgb", headers=tok(c, "dm")).status_code == 403
    assert c.get("/api/science/xgb", headers=tok(c, "sci")).status_code == 200
    assert c.get("/api/admin/health", headers=tok(c, "sci")).status_code == 403
    assert c.get("/api/brief", headers=tok(c, "eu")).status_code == 403
    assert c.get("/api/brief", headers=tok(c, "dm")).status_code == 200
    assert c.get("/api/auth/me", headers={"Authorization": "Bearer forged.token"}).json()["signed_in"] is False


def test_science(c):
    h, d = tok(c, "sci"), date(c)
    cu = c.get("/api/science/currents", params={"date": d}, headers=h).json()
    assert cu["comparison"]["n_cells"] > 100 and len(cu["arrows"]["geostrophic"]["u"]) > 10
    dr = c.post("/api/science/drift", json={"date": d, "lat": 14.5, "lon": 88.0, "days": 2, "n_particles": 20}, headers=h).json()
    assert len(dr["lat"][0]) == 20 and dr["summary"]["mean_displacement_km"] > 0
    t0 = time.time()
    pw = c.post("/api/science/pwp", json={"date": d, "lat": 14.5, "lon": 88.0, "days": 2, "forcing": "constant", "wind_speed_ms": 25}, headers=h).json()
    assert pw["simulated_dsst_c"] < 0 and time.time() - t0 < 60
    st = c.get("/api/science/stratification", params={"date": d, "lat": 14.5, "lon": 88.0}, headers=h).json()
    assert st["ri"] is not None and st["notes"]["salinity"].startswith("reference")
    oi = c.post("/api/science/assimilate", json={"date": d, "depth_m": 100, "window_days": 7}, headers=h).json()
    assert oi["stats"]["n_obs"] > 5 and oi["synthetic_obs"] is True
    assert c.post("/api/science/drift", json={"date": "1990-01-01", "lat": 14.5, "lon": 88.0}, headers=h).status_code == 404


def test_explorer(c):
    h = tok(c, "sci")
    f = c.get("/api/explorer/files", headers=h).json()
    assert any(x["name"].startswith("basin_") for x in f["files"])
    s = c.get("/api/explorer/series", params={"lat": 14.5, "lon": 88.0, "var": "pred_temp_c", "depth_m": 100, "fmt": "csv"}, headers=h)
    assert s.status_code == 200 and s.text.startswith("# variable=pred_temp_c")
    p = c.get("/api/explorer/profile", params={"date": date(c), "lat": 14.5, "lon": 88.0, "fmt": "nc"}, headers=h)
    assert p.status_code == 200 and len(p.content) > 500


def test_admin_and_brief(c):
    h = tok(c, "ana")
    assert "alerts" in c.get("/api/admin/feeds", headers=h).json()
    assert c.get("/api/admin/health", headers=h).json()["cache"]["hits"] >= 0
    assert c.post("/api/admin/jobs", json={"kind": "fetch_period", "args": {"mode": "nrt", "start": "2023-01-01", "end": "2023-01-02", "out_dir": "/etc"}}, headers=h).status_code == 400
    assert c.post("/api/admin/jobs", json={"kind": "rm_rf", "args": {}}, headers=h).status_code == 400
    j = c.post("/api/admin/jobs", json={"kind": "cyclone_tracks", "args": {"storms": ["NOSUCH:2023"]}}, headers=h).json()
    for _ in range(60):
        st = [x for x in c.get("/api/admin/jobs", headers=h).json() if x["id"] == j["id"]][0]["status"]
        if st in ("failed", "succeeded"):
            break
        time.sleep(1)
    assert st == "failed"                                     # no network / unknown storm -> recorded as failed
    assert c.get(f"/api/admin/jobs/{j['id']}/log", headers=h).json()["lines"]
    b = c.get("/api/brief", headers=tok(c, "dm")).json()
    assert b["summary_lines"] and "anomaly" in b
