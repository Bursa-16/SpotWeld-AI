
from __future__ import annotations
from typing import Any, Dict, List
import statistics


def analyze_dynamic_resistance(samples: List[float]) -> Dict[str, Any]:
    if len(samples) < 5:
        raise ValueError("At least 5 resistance samples are required")

    peak = max(samples)
    peak_index = samples.index(peak)
    final_value = samples[-1]
    initial_value = samples[0]
    mean_value = statistics.fmean(samples)

    post_peak = samples[peak_index:]
    drop_ratio = 0.0
    if peak > 0:
        drop_ratio = (peak - final_value) / peak

    slope = (final_value - initial_value) / max(len(samples) - 1, 1)

    flags = []
    if peak_index >= len(samples) * 0.75:
        flags.append("Direnç tepesi geç oluştu; geç ısı girişi veya temas problemi olabilir.")
    if drop_ratio < 0.08:
        flags.append("Tepe sonrası direnç düşüşü zayıf; nugget büyümesi sınırlı olabilir.")
    if drop_ratio > 0.45:
        flags.append("Direnç düşüşü çok yüksek; expulsion veya ani temas alanı değişimi riski.")
    if slope > 0:
        flags.append("Çevrim sonunda direnç hâlâ yükseliyor.")

    quality = "Normal"
    if len(flags) >= 2:
        quality = "İnceleme Gerekli"
    if drop_ratio > 0.60:
        quality = "Yüksek Risk"

    return {
        "sample_count": len(samples),
        "initial_micro_ohm": round(initial_value, 3),
        "peak_micro_ohm": round(peak, 3),
        "peak_index": peak_index,
        "final_micro_ohm": round(final_value, 3),
        "mean_micro_ohm": round(mean_value, 3),
        "post_peak_drop_ratio": round(drop_ratio, 4),
        "overall_slope": round(slope, 4),
        "quality": quality,
        "flags": flags,
    }
