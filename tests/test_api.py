"""M0 API 冒烟测试。"""

from fastapi.testclient import TestClient

from tripcraft.api.app import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_health_and_contracts():
    c = client()
    assert c.get("/").json()["service"] == "TripCraft"
    assert len(c.get("/contracts/steps").json()) == 13
    assert len(c.get("/contracts/dimensions").json()) == 8
    assert len(c.get("/contracts/skill-points").json()) == 61
    assert len(c.get("/contracts/skill-points", params={"dimension": "C6"}).json()) == 7


def test_rubric_example_and_missing():
    c = client()
    r = c.get("/contracts/rubric/C2.2")
    assert r.status_code == 200
    assert len(r.json()["anchors"]) == 5
    # C1.1 已入库；不存在的技能点应 404
    assert c.get("/contracts/rubric/C1.1").status_code == 200
    assert c.get("/contracts/rubric/C9.9").status_code == 404


def test_run_gate_then_advance():
    c = client()
    run = c.post("/runs", json={"user_id": "u1"}).json()
    assert run["current_step"] == "S0"
    assert run["gate"]["passed"] is False
    c.post("/runs/run-1/flags", json={"name": "hard_rules_recited"})
    adv = c.post("/runs/run-1/advance").json()
    assert adv["ok"] is True
    assert adv["to"] == "S1"


def test_profile_ability_and_dimensions():
    c = client()
    c.post("/runs", json={"user_id": "u2"})
    c.post("/profiles/u2/abilities", json={"skill_point_id": "C2.2", "value": 45})
    prof = c.get("/profiles/u2").json()
    assert "C2.2" in prof["weak_points"]
    assert prof["mastery"]["C2.2"]["level"] == "M1"
    assert "C2" in prof["dimensions"]