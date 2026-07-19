
from __future__ import annotations
from typing import Any, Dict


def recommend_pulse_strategy(
    *,
    material_family: str,
    coated: bool,
    thickness_ratio: float,
    stack_count: str,
    adhesive: bool,
    current_ka: float,
    weld_cycles: float,
) -> Dict[str, Any]:
    score = 0
    reasons = []

    if coated:
        score += 2
        reasons.append("Kaplama tabakası temas direncini ve elektrot davranışını değiştiriyor.")

    if material_family in {"AHSS / UHSS / PHS", "Alüminyum Alaşımları"}:
        score += 2
        reasons.append("Malzeme ailesi dar proses penceresi veya yüzey oksidi nedeniyle pulse stratejisinden fayda görebilir.")

    if thickness_ratio >= 2.0:
        score += 2
        reasons.append("Kalınlık oranı yüksek; ince sacın erken aşırı ısınma riski var.")

    if stack_count in {"3T", "4T"}:
        score += 1
        reasons.append("Çok katlı istifte arayüzler arasında ısı dağılımı karmaşık.")

    if adhesive:
        score += 1
        reasons.append("Yapıştırıcı/mastik arayüz direncini etkiliyor.")

    if weld_cycles >= 16:
        score += 1
        reasons.append("Uzun kaynak süresi tek darbe yerine bölünmüş enerji girişini destekleyebilir.")

    if material_family == "Alüminyum Alaşımları":
        strategy = "Ön temizleme darbesi + ana yüksek akım kısa darbe"
        pulse_count = 2
        first_pulse_ratio = 0.55
    elif score >= 5:
        strategy = "Çift darbe"
        pulse_count = 2
        first_pulse_ratio = 0.65
    elif score >= 3:
        strategy = "Opsiyonel çift darbe / laboratuvar doğrulaması"
        pulse_count = 2
        first_pulse_ratio = 0.75
    else:
        strategy = "Tek darbe"
        pulse_count = 1
        first_pulse_ratio = 1.0

    return {
        "strategy": strategy,
        "pulse_count": pulse_count,
        "first_pulse_current_ka": round(current_ka * first_pulse_ratio, 2),
        "main_pulse_current_ka": round(current_ka, 2),
        "pre_pulse_cycles": max(1, round(weld_cycles * 0.25)) if pulse_count == 2 else 0,
        "main_pulse_cycles": max(1, round(weld_cycles * 0.75)) if pulse_count == 2 else round(weld_cycles),
        "decision_score": score,
        "reasons": reasons or ["Tek darbe için temel koşullar uygun."],
        "validation_required": True,
    }
