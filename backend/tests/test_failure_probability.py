
def _base_payload():
    return {
        "material_family": "Galvanizli / Kaplamalı Çelik",
        "stack_count": "2T",
        "coated": True,
        "adhesive": False,
        "shunt_risk": False,
        "thicknesses_mm": [1.0, 1.0],
        "current_ka": 9.0,
        "weld_cycles": 11,
        "force_kn": 3.0,
        "tip_diameter_mm": 6.0,
        "squeeze_cycles": 15,
        "hold_cycles": 15,
        "cooling_flow_lpm": 6.0,
        "cooling_temp_c": 20,
        "recommended_current_min_ka": 8.0,
        "recommended_current_max_ka": 10.5,
        "recommended_time_min_cycles": 10,
        "recommended_time_max_cycles": 12,
        "recommended_force_min_kn": 2.5,
        "recommended_force_max_kn": 3.5,
        "recommended_tip_min_mm": 6,
        "recommended_tip_max_mm": 6,
        "predicted_nugget_mm": 5.0,
        "minimum_nugget_mm": 4.2,
    }


def test_failure_probability_endpoint(client, auth_headers):
    payload = _base_payload()
    response = client.post(
        "/api/v1/failure-probability/analyze",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["failure_modes"]) == 10
    assert body["failure_modes"][0]["probability_percent"] >= 0
    assert len(body["priority_actions"]) > 0


def test_high_heat_low_force_increases_expulsion(client, auth_headers):
    safe_payload = _base_payload()
    risky_payload = _base_payload()
    risky_payload.update({
        "current_ka": 13.0,
        "weld_cycles": 18,
        "force_kn": 1.8,
    })

    safe = client.post(
        "/api/v1/failure-probability/analyze",
        headers=auth_headers,
        json=safe_payload,
    ).json()
    risky = client.post(
        "/api/v1/failure-probability/analyze",
        headers=auth_headers,
        json=risky_payload,
    ).json()

    def probability(result, code):
        return next(
            item["probability"]
            for item in result["failure_modes"]
            if item["code"] == code
        )

    assert probability(risky, "expulsion") > probability(safe, "expulsion")


def test_low_heat_increases_fusion_and_small_nugget_risk(client, auth_headers):
    payload = _base_payload()
    payload.update({
        "current_ka": 6.0,
        "weld_cycles": 7,
        "predicted_nugget_mm": 3.2,
    })

    response = client.post(
        "/api/v1/failure-probability/analyze",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 200
    body = response.json()

    modes = {item["code"]: item for item in body["failure_modes"]}
    assert modes["insufficient_fusion"]["probability"] > 0.45
    assert modes["small_nugget"]["probability"] > 0.45


def test_cooling_failure_increases_cooling_and_wear_risk(client, auth_headers):
    payload = _base_payload()
    payload.update({
        "cooling_flow_lpm": 2.5,
        "cooling_temp_c": 40,
    })

    body = client.post(
        "/api/v1/failure-probability/analyze",
        headers=auth_headers,
        json=payload,
    ).json()

    modes = {item["code"]: item for item in body["failure_modes"]}
    assert modes["cooling_instability"]["probability"] > 0.50
    assert modes["electrode_wear"]["probability"] > 0.35
