
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import json
from pathlib import Path

from app.domain.models import (
    minitab_doe_predict,
    oem_table_prediction,
    literature_4sqrt_t,
)


@dataclass
class RegisteredModel:
    key: str
    name: str
    source_type: str
    priority: int
    validation_status: str
    supported_materials: List[str]
    notes: str


MODEL_REGISTRY = [
    RegisteredModel(
        key="oem_table",
        name="OEM Referans Tablosu",
        source_type="OEM / şirket normu",
        priority=1,
        validation_status="Referans",
        supported_materials=["Düşük / Orta Karbonlu Çelik"],
        notes="En ince sac kalınlığına göre minimum ve optimum çekirdek çapı."
    ),
    RegisteredModel(
        key="minitab_doe_linear",
        name="Minitab DOE — doğrusal terimler",
        source_type="Saha / deneysel model",
        priority=3,
        validation_status="Doğrulanmamış",
        supported_materials=["Düşük / Orta Karbonlu Çelik"],
        notes="Birim varsayımları A, daN, çevrim ve mm."
    ),
    RegisteredModel(
        key="literature_4sqrt_t",
        name="4√t Literatür Kriteri",
        source_type="Literatür",
        priority=4,
        validation_status="Minimum kriter",
        supported_materials=["Tümü"],
        notes="Minimum nugget çapı için destekleyici kriter."
    ),
]


def registry_dataframe_rows() -> List[Dict[str, Any]]:
    return [asdict(m) for m in MODEL_REGISTRY]


def load_polynomial_model(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Model dosyası bulunamadı: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    required = ["name", "variables", "intercept", "terms", "units", "validation_status"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError("Model JSON eksik alanlar: " + ", ".join(missing))
    return data


def evaluate_polynomial(model: Dict[str, Any], values: Dict[str, float]) -> float:
    total = float(model["intercept"])
    for term in model["terms"]:
        coef = float(term["coefficient"])
        factors = term["factors"]
        product = 1.0
        for factor in factors:
            variable = factor["variable"]
            power = int(factor.get("power", 1))
            if variable not in values:
                raise ValueError(f"Eksik model girdisi: {variable}")
            product *= float(values[variable]) ** power
        total += coef * product
    return total


def compare_and_select(
    *,
    material_family: str,
    t_min: float,
    nugget_min_mm: float,
    nugget_opt_mm: float,
    current_ka: float,
    force_kn: float,
    weld_cycles: float,
    cooling_cycles: float,
    squeeze_cycles: float,
    hold_cycles: float,
) -> Dict[str, Any]:
    results = []

    oem = oem_table_prediction(nugget_min_mm, nugget_opt_mm)
    results.append({
        "key": "oem_table",
        "model_name": oem.model_name,
        "prediction_mm": oem.prediction_mm,
        "confidence": oem.confidence,
        "status": oem.status,
        "priority": 1,
        "eligible": material_family == "Düşük / Orta Karbonlu Çelik",
        "reason": "Malzeme ailesi OEM referans tablosuyla uyumlu."
                  if material_family == "Düşük / Orta Karbonlu Çelik"
                  else "Bu OEM tablosu yalnız düşük/orta karbonlu çelik için etkin."
    })

    lit = literature_4sqrt_t(t_min)
    results.append({
        "key": "literature_4sqrt_t",
        "model_name": lit.model_name,
        "prediction_mm": lit.prediction_mm,
        "confidence": lit.confidence,
        "status": lit.status,
        "priority": 4,
        "eligible": True,
        "reason": "Destekleyici minimum kriter."
    })

    doe = minitab_doe_predict({
        "current_a": current_ka * 1000,
        "force_dan": force_kn * 100,
        "time_cycle": weld_cycles,
        "cooling_cycle": cooling_cycles,
        "sequence_cycle": squeeze_cycles,
        "holding_cycle": hold_cycles,
        "sheet_thickness_mm": t_min,
    })
    doe_eligible = material_family == "Düşük / Orta Karbonlu Çelik"
    results.append({
        "key": "minitab_doe_linear",
        "model_name": doe.model_name,
        "prediction_mm": doe.prediction_mm,
        "confidence": doe.confidence,
        "status": doe.status,
        "priority": 3,
        "eligible": doe_eligible,
        "reason": "Deneysel model; doğrulama tamamlanmadı."
    })

    eligible = [
        r for r in results
        if r["eligible"] and r["prediction_mm"] is not None and r["prediction_mm"] > 0
    ]

    if not eligible:
        return {
            "selected_model": None,
            "selected_prediction_mm": None,
            "selection_reason": "Uygun ve pozitif tahmin üreten model yok.",
            "results": results,
        }

    # Kaynak hiyerarşisi: düşük priority numarası daha güçlü kaynaktır.
    selected = sorted(eligible, key=lambda x: (x["priority"], -float(x["prediction_mm"])))[0]

    return {
        "selected_model": selected["model_name"],
        "selected_prediction_mm": selected["prediction_mm"],
        "selection_reason": (
            "Kaynak hiyerarşisine göre en yüksek öncelikli uygun model seçildi. "
            "Deneysel model tek başına nihai karar üretmez."
        ),
        "results": results,
    }
