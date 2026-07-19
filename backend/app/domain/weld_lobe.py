
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import math


@dataclass
class WeldLobePoint:
    current_ka: float
    weld_cycles: float
    nugget_mm: float
    expulsion_risk: float
    fusion_risk: float
    zone: str


def _family_factor(material_family: str) -> float:
    mapping = {
        "Düşük / Orta Karbonlu Çelik": 1.00,
        "Galvanizli / Kaplamalı Çelik": 0.92,
        "AHSS / UHSS / PHS": 0.88,
        "Paslanmaz Çelik": 1.08,
        "Alüminyum Alaşımları": 0.48,
    }
    return mapping.get(material_family, 0.80)


def estimate_nugget(
    material_family: str,
    thickness_mm: float,
    current_ka: float,
    weld_cycles: float,
    force_kn: float,
) -> float:
    factor = _family_factor(material_family)
    thermal_input = max(current_ka, 0.0) ** 1.35 * max(weld_cycles, 0.1) ** 0.45
    force_effect = 1.0 / max(force_kn, 0.5) ** 0.12
    thickness_effect = max(thickness_mm, 0.3) ** 0.40
    nugget = factor * 0.24 * thermal_input * force_effect / thickness_effect
    return max(0.0, nugget)


def classify_zone(
    nugget_mm: float,
    min_nugget_mm: float,
    current_ka: float,
    weld_cycles: float,
    force_kn: float,
    material_family: str,
) -> tuple[str, float, float]:
    lower_ratio = nugget_mm / max(min_nugget_mm, 0.1)

    expulsion_index = (
        (current_ka ** 2) * max(weld_cycles, 1.0)
        / max(force_kn, 0.5)
    )

    material_limit = {
        "Düşük / Orta Karbonlu Çelik": 4200,
        "Galvanizli / Kaplamalı Çelik": 3500,
        "AHSS / UHSS / PHS": 3200,
        "Paslanmaz Çelik": 3000,
        "Alüminyum Alaşımları": 16000,
    }.get(material_family, 3200)

    expulsion_risk = min(1.0, expulsion_index / material_limit)
    fusion_risk = max(0.0, min(1.0, 1.0 - lower_ratio))

    if lower_ratio < 1.0:
        zone = "Yetersiz Füzyon"
    elif expulsion_risk >= 0.75:
        zone = "Expulsion Riski"
    elif expulsion_risk >= 0.50:
        zone = "Uyarı"
    else:
        zone = "Güvenli"

    return zone, expulsion_risk, fusion_risk


def generate_weld_lobe(
    *,
    material_family: str,
    thickness_mm: float,
    force_kn: float,
    min_nugget_mm: float,
    current_min_ka: float,
    current_max_ka: float,
    current_step_ka: float,
    time_min_cycles: float,
    time_max_cycles: float,
    time_step_cycles: float,
) -> Dict[str, Any]:
    points: List[Dict[str, Any]] = []

    current = current_min_ka
    while current <= current_max_ka + 1e-9:
        time_value = time_min_cycles
        while time_value <= time_max_cycles + 1e-9:
            nugget = estimate_nugget(
                material_family,
                thickness_mm,
                current,
                time_value,
                force_kn,
            )
            zone, expulsion_risk, fusion_risk = classify_zone(
                nugget,
                min_nugget_mm,
                current,
                time_value,
                force_kn,
                material_family,
            )
            points.append({
                "current_ka": round(current, 3),
                "weld_cycles": round(time_value, 3),
                "nugget_mm": round(nugget, 3),
                "expulsion_risk": round(expulsion_risk, 4),
                "fusion_risk": round(fusion_risk, 4),
                "zone": zone,
            })
            time_value += time_step_cycles
        current += current_step_ka

    safe = [p for p in points if p["zone"] == "Güvenli"]
    warning = [p for p in points if p["zone"] == "Uyarı"]

    if safe:
        optimum = min(
            safe,
            key=lambda p: (
                abs(p["nugget_mm"] - min_nugget_mm * 1.20),
                p["expulsion_risk"],
            ),
        )
    elif warning:
        optimum = min(warning, key=lambda p: p["expulsion_risk"])
    else:
        optimum = None

    return {
        "points": points,
        "safe_count": len(safe),
        "warning_count": len(warning),
        "unsafe_count": len(points) - len(safe) - len(warning),
        "optimum": optimum,
        "model_status": "Surrogate v0.9 — saha kalibrasyonu gerekli",
    }
