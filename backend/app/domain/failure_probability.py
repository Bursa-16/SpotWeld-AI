
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List
import math


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _deviation_above(value: float, upper: float) -> float:
    if upper <= 0:
        return 0.0
    return max(0.0, (value - upper) / upper)


def _deviation_below(value: float, lower: float) -> float:
    if lower <= 0:
        return 0.0
    return max(0.0, (lower - value) / lower)


def _range_center(lower: float, upper: float) -> float:
    return (lower + upper) / 2.0


@dataclass(frozen=True)
class RiskContribution:
    factor: str
    normalized_effect: float
    explanation: str


@dataclass(frozen=True)
class FailureModeResult:
    code: str
    title: str
    probability: float
    confidence: str
    severity: str
    contributions: List[RiskContribution]
    validation_tests: List[str]
    recommended_actions: List[str]


MATERIAL_FACTORS = {
    "Düşük / Orta Karbonlu Çelik": {
        "expulsion": 0.00,
        "fusion": 0.00,
        "sticking": 0.00,
        "wear": 0.00,
        "lme": -0.90,
        "coating": -0.90,
    },
    "Galvanizli / Kaplamalı Çelik": {
        "expulsion": 0.22,
        "fusion": 0.08,
        "sticking": 0.28,
        "wear": 0.35,
        "lme": 0.32,
        "coating": 0.42,
    },
    "AHSS / UHSS / PHS": {
        "expulsion": 0.25,
        "fusion": 0.16,
        "sticking": 0.12,
        "wear": 0.18,
        "lme": 0.48,
        "coating": 0.20,
    },
    "Paslanmaz Çelik": {
        "expulsion": 0.12,
        "fusion": -0.05,
        "sticking": 0.10,
        "wear": 0.08,
        "lme": -0.80,
        "coating": -0.70,
    },
    "Alüminyum Alaşımları": {
        "expulsion": 0.30,
        "fusion": 0.28,
        "sticking": 0.45,
        "wear": 0.52,
        "lme": -0.90,
        "coating": 0.18,
    },
    "Süper Alaşımlar": {
        "expulsion": 0.18,
        "fusion": 0.26,
        "sticking": 0.20,
        "wear": 0.20,
        "lme": 0.05,
        "coating": -0.50,
    },
    "Karma Malzeme": {
        "expulsion": 0.35,
        "fusion": 0.42,
        "sticking": 0.28,
        "wear": 0.25,
        "lme": 0.18,
        "coating": 0.20,
    },
}


def _material_value(material_family: str, key: str) -> float:
    return MATERIAL_FACTORS.get(material_family, MATERIAL_FACTORS["Karma Malzeme"]).get(key, 0.0)


def _probability(raw_score: float) -> float:
    # Raw score 0 ≈ 12%, 1 ≈ 31%, 2 ≈ 60%, 3 ≈ 83%.
    return _clamp(_sigmoid(1.35 * raw_score - 2.0))


def _confidence(
    *,
    supported_family: bool,
    input_count: int,
    warning_count: int,
) -> str:
    score = input_count - warning_count * 2 + (2 if supported_family else -2)
    if score >= 9:
        return "Orta-Yüksek"
    if score >= 5:
        return "Orta"
    return "Düşük"


def _severity(probability: float, critical_mode: bool = False) -> str:
    if probability >= 0.72:
        return "Kritik" if critical_mode else "Yüksek"
    if probability >= 0.45:
        return "Yüksek" if critical_mode else "Orta"
    return "Düşük"


def _top(contributions: Iterable[RiskContribution], limit: int = 5) -> List[RiskContribution]:
    return sorted(
        contributions,
        key=lambda item: abs(item.normalized_effect),
        reverse=True,
    )[:limit]


def _result(
    *,
    code: str,
    title: str,
    raw_score: float,
    contributions: List[RiskContribution],
    confidence: str,
    critical_mode: bool,
    validation_tests: List[str],
    recommended_actions: List[str],
) -> FailureModeResult:
    probability = _probability(raw_score)
    return FailureModeResult(
        code=code,
        title=title,
        probability=probability,
        confidence=confidence,
        severity=_severity(probability, critical_mode),
        contributions=_top(contributions),
        validation_tests=validation_tests,
        recommended_actions=recommended_actions,
    )


def analyze_failure_probabilities(
    *,
    material_family: str,
    stack_count: str,
    coated: bool,
    adhesive: bool,
    shunt_risk: bool,
    thicknesses_mm: List[float],
    current_ka: float,
    weld_cycles: float,
    force_kn: float,
    tip_diameter_mm: float,
    squeeze_cycles: float,
    hold_cycles: float,
    cooling_flow_lpm: float,
    cooling_temp_c: float,
    recommended_current_min_ka: float,
    recommended_current_max_ka: float,
    recommended_time_min_cycles: float,
    recommended_time_max_cycles: float,
    recommended_force_min_kn: float,
    recommended_force_max_kn: float,
    recommended_tip_min_mm: float,
    recommended_tip_max_mm: float,
    predicted_nugget_mm: float,
    minimum_nugget_mm: float,
) -> Dict[str, Any]:
    if not thicknesses_mm:
        raise ValueError("At least one sheet thickness is required")

    t_min = min(thicknesses_mm)
    t_max = max(thicknesses_mm)
    thickness_ratio = t_max / max(t_min, 0.01)

    current_high = _deviation_above(current_ka, recommended_current_max_ka)
    current_low = _deviation_below(current_ka, recommended_current_min_ka)
    time_high = _deviation_above(weld_cycles, recommended_time_max_cycles)
    time_low = _deviation_below(weld_cycles, recommended_time_min_cycles)
    force_high = _deviation_above(force_kn, recommended_force_max_kn)
    force_low = _deviation_below(force_kn, recommended_force_min_kn)
    tip_high = _deviation_above(tip_diameter_mm, recommended_tip_max_mm)
    tip_low = _deviation_below(tip_diameter_mm, recommended_tip_min_mm)
    nugget_shortfall = max(
        0.0,
        (minimum_nugget_mm - predicted_nugget_mm) / max(minimum_nugget_mm, 0.1),
    )
    cooling_flow_shortfall = max(0.0, (6.0 - cooling_flow_lpm) / 6.0)
    cooling_temp_excess = max(0.0, (cooling_temp_c - 25.0) / 25.0)
    stack_complexity = {"2T": 0.0, "3T": 0.24, "4T": 0.42}.get(stack_count, 0.30)
    asymmetry = max(0.0, (thickness_ratio - 1.35) / 1.65)
    low_squeeze = max(0.0, (10.0 - squeeze_cycles) / 10.0)
    low_hold = max(0.0, (10.0 - hold_cycles) / 10.0)
    high_hold = max(0.0, (hold_cycles - 25.0) / 25.0)

    supported = material_family in MATERIAL_FACTORS
    warnings = int(material_family in {"Süper Alaşımlar", "Karma Malzeme"})
    common_confidence = _confidence(
        supported_family=supported,
        input_count=16,
        warning_count=warnings,
    )

    results: List[FailureModeResult] = []

    # 1. Expulsion
    expulsion_contrib = [
        RiskContribution("Akım üst limit sapması", 2.6 * current_high, "Akım önerilen üst aralığın üzerinde."),
        RiskContribution("Kaynak süresi üst limit sapması", 1.7 * time_high, "Uzun süre toplam ısı girdisini yükseltiyor."),
        RiskContribution("Düşük elektrot kuvveti", 2.2 * force_low, "Düşük kuvvet temas direncini ve sıçrama riskini artırıyor."),
        RiskContribution("Kaplama etkisi", 0.45 if coated else 0.0, "Kaplama arayüz davranışını kararsızlaştırabilir."),
        RiskContribution("Çok katlı istif", stack_complexity, "Çoklu arayüzlerde ısı dağılımı daha karmaşıktır."),
        RiskContribution("Malzeme ailesi", _material_value(material_family, "expulsion"), "Malzeme ailesine özgü proses penceresi etkisi."),
    ]
    results.append(_result(
        code="expulsion",
        title="Expulsion / metal sıçraması",
        raw_score=0.35 + sum(item.normalized_effect for item in expulsion_contrib),
        contributions=expulsion_contrib,
        confidence=common_confidence,
        critical_mode=True,
        validation_tests=["Görsel proses kontrolü", "Makro kesit", "Dinamik direnç eğrisi"],
        recommended_actions=[
            "Önce elektrot kuvvetini önerilen aralığa yaklaştırın.",
            "Akımı kontrollü olarak azaltın.",
            "Kaynak süresini alt-orta aralığa çekerek doğrulama numunesi üretin.",
        ],
    ))

    # 2. Insufficient fusion
    fusion_contrib = [
        RiskContribution("Akım alt limit sapması", 2.8 * current_low, "Akım düşük olduğu için yeterli ısı oluşmayabilir."),
        RiskContribution("Kaynak süresi alt limit sapması", 2.0 * time_low, "Kaynak süresi füzyon için yetersiz kalabilir."),
        RiskContribution("Yüksek elektrot kuvveti", 1.3 * force_high, "Yüksek kuvvet temas direncini fazla düşürebilir."),
        RiskContribution("Büyük elektrot uç çapı", 1.0 * tip_high, "Büyük temas alanı akım yoğunluğunu azaltabilir."),
        RiskContribution("Şönt etkisi", 0.65 if shunt_risk else 0.0, "Komşu kaynak noktası akımın bir bölümünü kaçırabilir."),
        RiskContribution("Yapıştırıcı / mastik", 0.30 if adhesive else 0.0, "Arayüz malzemesi akım yolunu ve temas koşulunu değiştirebilir."),
        RiskContribution("Malzeme ailesi", _material_value(material_family, "fusion"), "Malzeme ailesine özgü füzyon hassasiyeti."),
    ]
    results.append(_result(
        code="insufficient_fusion",
        title="Yetersiz füzyon",
        raw_score=0.25 + sum(item.normalized_effect for item in fusion_contrib),
        contributions=fusion_contrib,
        confidence=common_confidence,
        critical_mode=True,
        validation_tests=["Peel testi", "Chisel testi", "Makro kesit"],
        recommended_actions=[
            "Akımı önerilen aralığın altından orta bölgesine çıkarın.",
            "Kaynak süresini kontrollü artırın.",
            "Şönt koşulu ve komşu punta sırasını doğrulayın.",
        ],
    ))

    # 3. Small nugget
    small_nugget_contrib = [
        RiskContribution("Tahmini çap eksikliği", 3.2 * nugget_shortfall, "Tahmini çekirdek çapı minimum kriterin altında."),
        RiskContribution("Akım alt limit sapması", 1.8 * current_low, "Düşük akım çekirdek büyümesini sınırlar."),
        RiskContribution("Süre alt limit sapması", 1.3 * time_low, "Kısa süre çekirdek gelişimini sınırlar."),
        RiskContribution("Elektrot uç aşırı büyük", 0.8 * tip_high, "Akım yoğunluğu düşebilir."),
        RiskContribution("Şönt etkisi", 0.45 if shunt_risk else 0.0, "Akımın kaynak noktasından kaçması olasıdır."),
    ]
    results.append(_result(
        code="small_nugget",
        title="Küçük çekirdek çapı",
        raw_score=0.20 + sum(item.normalized_effect for item in small_nugget_contrib),
        contributions=small_nugget_contrib,
        confidence=common_confidence,
        critical_mode=True,
        validation_tests=["Peel testi", "Makro kesit", "Çekirdek çapı ölçümü"],
        recommended_actions=[
            "Tahmini çap minimum kriteri sağlayana kadar akımı kademeli artırın.",
            "Akım değişikliği yeterli değilse süreyi artırın.",
            "Elektrot uç çapını ve dressing durumunu kontrol edin.",
        ],
    ))

    # 4. Excessive indentation
    indentation_contrib = [
        RiskContribution("Yüksek elektrot kuvveti", 2.3 * force_high, "Yüksek kuvvet yüzey çökmesini artırabilir."),
        RiskContribution("Küçük elektrot uç çapı", 1.7 * tip_low, "Küçük uç temas basıncını yükseltir."),
        RiskContribution("Akım üst limit sapması", 1.2 * current_high, "Yüksek ısı sacın yumuşamasını artırır."),
        RiskContribution("Süre üst limit sapması", 1.0 * time_high, "Uzun süre deformasyonu artırabilir."),
        RiskContribution("İnce sac", max(0.0, (1.0 - t_min) / 1.0) * 0.55, "İnce sac yüzey çökmesine daha hassastır."),
    ]
    results.append(_result(
        code="excessive_indentation",
        title="Aşırı indentation / yüzey çökmesi",
        raw_score=0.10 + sum(item.normalized_effect for item in indentation_contrib),
        contributions=indentation_contrib,
        confidence=common_confidence,
        critical_mode=False,
        validation_tests=["Indentation derinlik ölçümü", "Yüzey profil kontrolü"],
        recommended_actions=[
            "Elektrot kuvvetini üst limitten orta aralığa düşürün.",
            "Uç çapı düşükse uygun çapa yükseltin.",
            "Akım ve süreyi birlikte değil, tek tek azaltarak doğrulayın.",
        ],
    ))

    # 5. Electrode sticking
    sticking_contrib = [
        RiskContribution("Akım üst limit sapması", 1.8 * current_high, "Yüksek akım elektrot-yüzey yapışmasını artırabilir."),
        RiskContribution("Süre üst limit sapması", 1.2 * time_high, "Uzun kaynak süresi elektrot sıcaklığını yükseltir."),
        RiskContribution("Düşük soğutma debisi", 1.5 * cooling_flow_shortfall, "Yetersiz su debisi elektrot sıcaklığını artırır."),
        RiskContribution("Yüksek soğutma sıcaklığı", 1.1 * cooling_temp_excess, "Sıcak soğutma suyu ısı uzaklaştırmayı düşürür."),
        RiskContribution("Kaplama etkisi", 0.45 if coated else 0.0, "Kaplama elektrot yüzeyinde malzeme toplamasına yol açabilir."),
        RiskContribution("Düşük hold", 0.35 * low_hold, "Yetersiz hold erken ayrılma ve yapışma davranışını etkileyebilir."),
        RiskContribution("Malzeme ailesi", _material_value(material_family, "sticking"), "Malzeme ailesine özgü yapışma eğilimi."),
    ]
    results.append(_result(
        code="electrode_sticking",
        title="Elektrot yapışması",
        raw_score=0.12 + sum(item.normalized_effect for item in sticking_contrib),
        contributions=sticking_contrib,
        confidence=common_confidence,
        critical_mode=False,
        validation_tests=["Elektrot yüzey kontrolü", "Ayrılma kuvveti gözlemi", "Punta sonrası uç sıcaklığı"],
        recommended_actions=[
            "Soğutma debisi ve sıcaklığını doğrulayın.",
            "Akım/süre ısı girdisini azaltın.",
            "Elektrot yüzeyini ve dressing kalitesini kontrol edin.",
        ],
    ))

    # 6. Electrode wear
    wear_contrib = [
        RiskContribution("Kaplama etkisi", 0.75 if coated else 0.0, "Kaplama elektrot aşınmasını hızlandırabilir."),
        RiskContribution("Akım üst limit sapması", 1.2 * current_high, "Yüksek akım elektrot termal yükünü artırır."),
        RiskContribution("Yetersiz soğutma debisi", 1.4 * cooling_flow_shortfall, "Düşük debi elektrot ömrünü düşürür."),
        RiskContribution("Yüksek su sıcaklığı", 1.0 * cooling_temp_excess, "Yetersiz soğutma kapasitesi elektrot ömrünü düşürür."),
        RiskContribution("Uzun kaynak süresi", 0.8 * time_high, "Uzun süre termal aşınmayı artırır."),
        RiskContribution("Malzeme ailesi", _material_value(material_family, "wear"), "Malzeme ailesine özgü elektrot ömrü etkisi."),
    ]
    results.append(_result(
        code="electrode_wear",
        title="Hızlı elektrot aşınması",
        raw_score=0.18 + sum(item.normalized_effect for item in wear_contrib),
        contributions=wear_contrib,
        confidence=common_confidence,
        critical_mode=False,
        validation_tests=["Uç çapı trendi", "Dressing sonrası profil kontrolü", "Dinamik direnç trendi"],
        recommended_actions=[
            "Dressing sıklığını artırın veya stepper profilini gözden geçirin.",
            "Soğutma performansını düzeltin.",
            "Akım üst sınırını elektrot ömrüyle birlikte optimize edin.",
        ],
    ))

    # 7. LME / surface crack risk
    lme_contrib = [
        RiskContribution("Malzeme ailesi", _material_value(material_family, "lme"), "Kaplamalı AHSS/PHS gruplarında LME hassasiyeti artabilir."),
        RiskContribution("Kaplama", 0.45 if coated else -0.20, "Çinko kaplama ve yüksek gerilme LME riskini artırabilir."),
        RiskContribution("Akım üst limit sapması", 1.4 * current_high, "Yüksek tepe sıcaklığı çatlak riskini artırabilir."),
        RiskContribution("Süre üst limit sapması", 0.9 * time_high, "Uzun ısı girdisi sıvı metal temas süresini artırabilir."),
        RiskContribution("Yüksek kuvvet", 0.8 * force_high, "Yüksek mekanik gerilme çatlak oluşumunu destekleyebilir."),
        RiskContribution("Kalınlık asimetrisi", 0.45 * asymmetry, "Asimetrik istif yerel gerilme ve ısı dağılımını etkiler."),
    ]
    results.append(_result(
        code="lme_surface_crack",
        title="LME / yüzey çatlağı riski",
        raw_score=-0.10 + sum(item.normalized_effect for item in lme_contrib),
        contributions=lme_contrib,
        confidence="Düşük-Orta" if material_family in {"AHSS / UHSS / PHS", "Galvanizli / Kaplamalı Çelik"} else "Düşük",
        critical_mode=True,
        validation_tests=["Makro kesit", "Mikro yapı incelemesi", "Yüzey çatlak kontrolü"],
        recommended_actions=[
            "Akım tepesini ve toplam ısı girdisini azaltın.",
            "Pulse/upslope stratejisini değerlendirin.",
            "Malzeme-kaplama kombinasyonu için doğrulanmış OEM prosedürünü esas alın.",
        ],
    ))

    # 8. Coating damage
    coating_contrib = [
        RiskContribution("Kaplama varlığı", 0.80 if coated else -0.80, "Kaplamasız sacda bu risk düşük kabul edilir."),
        RiskContribution("Akım üst limit sapması", 1.2 * current_high, "Yüksek akım kaplama yanığı ve sıçramasını artırır."),
        RiskContribution("Süre üst limit sapması", 0.8 * time_high, "Uzun ısı girdisi kaplama hasarını artırır."),
        RiskContribution("Düşük kuvvet", 0.8 * force_low, "Düşük kuvvet temas direncini yükseltir."),
        RiskContribution("Malzeme ailesi", _material_value(material_family, "coating"), "Malzeme ailesine özgü kaplama davranışı."),
    ]
    results.append(_result(
        code="coating_damage",
        title="Kaplama yanığı / kaplama hasarı",
        raw_score=-0.05 + sum(item.normalized_effect for item in coating_contrib),
        contributions=coating_contrib,
        confidence=common_confidence,
        critical_mode=False,
        validation_tests=["Yüzey kaplama kontrolü", "Kaplama kalınlığı ölçümü", "Korozyon doğrulaması"],
        recommended_actions=[
            "Akım ve süreyi kaplama için doğrulanmış aralığa çekin.",
            "Elektrot kuvvetini temas direncini kontrol edecek seviyeye yükseltin.",
            "Ön darbe veya çoklu pulse ihtiyacını değerlendirin.",
        ],
    ))

    # 9. Shunt-related instability
    shunt_contrib = [
        RiskContribution("Şönt koşulu", 1.20 if shunt_risk else -0.60, "Komşu punta veya iletken yol akımı kaçırabilir."),
        RiskContribution("Akım alt limit sapması", 1.2 * current_low, "Şönt varken düşük akım füzyon kaybını büyütür."),
        RiskContribution("Çok katlı istif", 0.55 * stack_complexity, "Çoklu arayüz akım dağılımını karmaşıklaştırır."),
        RiskContribution("Kalınlık asimetrisi", 0.55 * asymmetry, "Asimetrik istif akım yoğunluğunu dengesizleştirebilir."),
    ]
    results.append(_result(
        code="shunt_instability",
        title="Şönt etkisi kaynaklı proses kararsızlığı",
        raw_score=0.10 + sum(item.normalized_effect for item in shunt_contrib),
        contributions=shunt_contrib,
        confidence=common_confidence,
        critical_mode=False,
        validation_tests=["Kaynak sırası deneyi", "Akım ölçümü", "Dinamik direnç karşılaştırması"],
        recommended_actions=[
            "Komşu punta mesafesini ve kaynak sırasını doğrulayın.",
            "Şöntlü ve şöntsüz numuneleri karşılaştırın.",
            "Gerekirse akım telafisini kontrollü olarak uygulayın.",
        ],
    ))

    # 10. Cooling-related instability
    cooling_contrib = [
        RiskContribution("Debi eksikliği", 2.0 * cooling_flow_shortfall, "Soğutma debisi saha minimumunun altında."),
        RiskContribution("Su sıcaklığı fazlalığı", 1.4 * cooling_temp_excess, "Yüksek su sıcaklığı elektrot ve proses kararlılığını düşürür."),
        RiskContribution("Uzun kaynak süresi", 0.6 * time_high, "Uzun çevrim termal birikimi artırır."),
        RiskContribution("Yüksek hold", 0.25 * high_hold, "Uzun çevrim toplam ekipman termal yükünü artırabilir."),
    ]
    results.append(_result(
        code="cooling_instability",
        title="Soğutma kaynaklı proses kararsızlığı",
        raw_score=0.10 + sum(item.normalized_effect for item in cooling_contrib),
        contributions=cooling_contrib,
        confidence=common_confidence,
        critical_mode=False,
        validation_tests=["Debimetre kontrolü", "Giriş/çıkış su sıcaklığı", "Elektrot sıcaklık trendi"],
        recommended_actions=[
            "Debiyi en az 6 L/dk seviyesine çıkarın.",
            "Soğutma suyunu 25 °C veya altına indirin.",
            "Filtre, hortum ve chiller kapasitesini kontrol edin.",
        ],
    ))

    ordered = sorted(results, key=lambda item: item.probability, reverse=True)

    # Aggregate recommendations with duplicate removal.
    priority_actions: List[str] = []
    for mode in ordered[:4]:
        for action in mode.recommended_actions:
            if action not in priority_actions:
                priority_actions.append(action)
            if len(priority_actions) >= 6:
                break
        if len(priority_actions) >= 6:
            break

    return {
        "engine_version": "1.1.0",
        "input_summary": {
            "material_family": material_family,
            "stack_count": stack_count,
            "coated": coated,
            "thickness_ratio": round(thickness_ratio, 3),
            "predicted_nugget_mm": round(predicted_nugget_mm, 3),
            "minimum_nugget_mm": round(minimum_nugget_mm, 3),
        },
        "failure_modes": [
            {
                "code": item.code,
                "title": item.title,
                "probability": round(item.probability, 4),
                "probability_percent": round(item.probability * 100.0, 1),
                "confidence": item.confidence,
                "severity": item.severity,
                "contributions": [
                    {
                        "factor": contribution.factor,
                        "normalized_effect": round(contribution.normalized_effect, 4),
                        "explanation": contribution.explanation,
                    }
                    for contribution in item.contributions
                ],
                "validation_tests": item.validation_tests,
                "recommended_actions": item.recommended_actions,
            }
            for item in ordered
        ],
        "priority_actions": priority_actions,
        "disclaimer": (
            "Olasılıklar parametre tabanlı mühendislik ön tahminidir. "
            "Gerçek proses ve test verisiyle kalibrasyon yapılmadan kesin hata oranı olarak kullanılmamalıdır."
        ),
    }
