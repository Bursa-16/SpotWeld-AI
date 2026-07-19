
def test_weld_lobe(client, auth_headers):
    response = client.post(
        "/api/v1/engineering/weld-lobe",
        headers=auth_headers,
        json={
            "material_family": "Düşük / Orta Karbonlu Çelik",
            "thickness_mm": 1.0,
            "force_kn": 3.0,
            "min_nugget_mm": 4.2,
            "current_min_ka": 6.0,
            "current_max_ka": 12.0,
            "current_step_ka": 0.5,
            "time_min_cycles": 8,
            "time_max_cycles": 18,
            "time_step_cycles": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["points"]) > 10
    assert "sensitivity" in body


def test_pulse_strategy(client, auth_headers):
    response = client.post(
        "/api/v1/engineering/pulse-strategy",
        headers=auth_headers,
        json={
            "material_family": "AHSS / UHSS / PHS",
            "coated": True,
            "thickness_ratio": 2.2,
            "stack_count": "3T",
            "adhesive": True,
            "current_ka": 10.5,
            "weld_cycles": 16,
        },
    )
    assert response.status_code == 200
    assert response.json()["pulse_count"] == 2


def test_electrode_life(client, auth_headers):
    response = client.post(
        "/api/v1/engineering/electrode-life",
        headers=auth_headers,
        json={
            "material_family": "Galvanizli / Kaplamalı Çelik",
            "coated": True,
            "tip_diameter_mm": 6.0,
            "cooling_flow_lpm": 6.0,
            "cooling_temp_c": 22.0,
            "current_ka": 11.0,
            "annual_spot_count": 1000000,
            "stepper_end_current_ka": 12.0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["estimated_life_spots"] > 100
    assert len(body["stepper_profile"]) == 4


def test_dynamic_resistance(client, auth_headers):
    response = client.post(
        "/api/v1/engineering/dynamic-resistance",
        headers=auth_headers,
        json={"samples_micro_ohm": [180, 210, 245, 270, 255, 230, 220]},
    )
    assert response.status_code == 200
    assert response.json()["peak_micro_ohm"] == 270
