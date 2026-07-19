
from __future__ import annotations
from typing import Any, Callable, Dict, List


def parameter_sensitivity(
    base_values: Dict[str, float],
    evaluator: Callable[[Dict[str, float]], float],
    delta_ratio: float = 0.05,
) -> List[Dict[str, Any]]:
    base_prediction = evaluator(base_values)
    results = []

    for parameter in ["current_ka", "weld_cycles", "force_kn"]:
        value = float(base_values[parameter])
        delta = max(abs(value) * delta_ratio, 0.01)

        low_values = dict(base_values)
        high_values = dict(base_values)
        low_values[parameter] = max(0.001, value - delta)
        high_values[parameter] = value + delta

        low_prediction = evaluator(low_values)
        high_prediction = evaluator(high_values)
        sensitivity = (high_prediction - low_prediction) / (2 * delta)

        results.append({
            "parameter": parameter,
            "base_value": value,
            "low_prediction_mm": round(low_prediction, 3),
            "high_prediction_mm": round(high_prediction, 3),
            "sensitivity_mm_per_unit": round(sensitivity, 4),
            "absolute_impact": round(abs(high_prediction - low_prediction), 4),
        })

    results.sort(key=lambda item: item["absolute_impact"], reverse=True)
    for index, item in enumerate(results, start=1):
        item["priority_rank"] = index
    return results
