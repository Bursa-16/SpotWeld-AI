
from __future__ import annotations
from typing import Dict, Any


def estimate_energy(
    current_ka: float,
    resistance_micro_ohm: float,
    weld_cycles: float,
    frequency_hz: float = 50.0,
) -> Dict[str, float]:
    current_a = current_ka * 1000.0
    resistance_ohm = resistance_micro_ohm * 1e-6
    time_s = weld_cycles / frequency_hz
    energy_j = (current_a ** 2) * resistance_ohm * time_s
    energy_wh = energy_j / 3600.0
    return {
        "energy_j": energy_j,
        "energy_wh": energy_wh,
        "time_s": time_s,
    }


def compare_energy(
    current_ka: float,
    weld_cycles: float,
    recommended_current_ka: float,
    recommended_cycles: float,
    resistance_micro_ohm: float,
    annual_spot_count: int,
    electricity_kgco2_per_kwh: float,
) -> Dict[str, float]:
    actual = estimate_energy(current_ka, resistance_micro_ohm, weld_cycles)
    recommended = estimate_energy(
        recommended_current_ka, resistance_micro_ohm, recommended_cycles
    )

    delta_wh = actual["energy_wh"] - recommended["energy_wh"]
    annual_kwh = delta_wh * annual_spot_count / 1000.0
    annual_co2_kg = annual_kwh * electricity_kgco2_per_kwh

    return {
        "actual_wh_per_spot": actual["energy_wh"],
        "recommended_wh_per_spot": recommended["energy_wh"],
        "delta_wh_per_spot": delta_wh,
        "annual_kwh_difference": annual_kwh,
        "annual_co2_kg_difference": annual_co2_kg,
    }
