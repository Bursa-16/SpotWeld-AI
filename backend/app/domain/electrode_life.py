
from __future__ import annotations
from typing import Any, Dict, List
import math


def estimate_electrode_life(
    *,
    material_family: str,
    coated: bool,
    tip_diameter_mm: float,
    cooling_flow_lpm: float,
    cooling_temp_c: float,
    current_ka: float,
    annual_spot_count: int,
) -> Dict[str, Any]:
    base_life = {
        "Düşük / Orta Karbonlu Çelik": 3500,
        "Galvanizli / Kaplamalı Çelik": 1800,
        "AHSS / UHSS / PHS": 1500,
        "Paslanmaz Çelik": 2500,
        "Alüminyum Alaşımları": 700,
    }.get(material_family, 1500)

    coating_factor = 0.70 if coated else 1.0
    flow_factor = min(1.15, max(0.50, cooling_flow_lpm / 6.0))
    temp_factor = 1.0 if cooling_temp_c <= 25 else max(0.55, 1.0 - (cooling_temp_c - 25) * 0.025)
    current_factor = max(0.55, min(1.10, 10.0 / max(current_ka, 1.0)))
    tip_factor = max(0.75, min(1.20, tip_diameter_mm / 6.0))

    life = int(base_life * coating_factor * flow_factor * temp_factor * current_factor * tip_factor)
    life = max(100, life)

    dress_interval = max(50, int(life * 0.35))
    replacements_per_year = max(1, math.ceil(annual_spot_count / life))

    return {
        "estimated_life_spots": life,
        "recommended_dress_interval_spots": dress_interval,
        "estimated_replacements_per_year": replacements_per_year,
        "confidence": "Düşük-Orta",
        "note": "Ampirik başlangıç modeli; elektrot malzemesi, gerçek direnç eğrisi ve dressing verisiyle kalibre edilmelidir.",
    }


def build_stepper_profile(
    *,
    initial_current_ka: float,
    end_current_ka: float,
    electrode_life_spots: int,
    step_count: int = 4,
) -> List[Dict[str, Any]]:
    if step_count < 2:
        step_count = 2

    profile = []
    for index in range(step_count):
        ratio = index / (step_count - 1)
        spot_count = round(electrode_life_spots * ratio)
        current = initial_current_ka + (end_current_ka - initial_current_ka) * ratio
        profile.append({
            "spot_count": spot_count,
            "current_ka": round(current, 2),
            "increase_percent": round((current / initial_current_ka - 1) * 100, 2),
        })
    return profile
