
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
import math


SOURCE_PRIORITY = {
    "OEM / Müşteri Normu": 1,
    "Şirket İçi Standart": 2,
    "Doğrulanmış Saha Modeli": 3,
    "Deneysel Model": 4,
    "Literatür": 5,
    "Genel Mühendislik Formülü": 6,
}


@dataclass
class Rule:
    rule_id: str
    name: str
    source_type: str
    source_name: str
    parameter: str
    operator: str
    min_value: Optional[float]
    max_value: Optional[float]
    unit: str
    material_family: str
    stack_count: str
    note: str
    enabled: bool = True

    @property
    def priority(self) -> int:
        return SOURCE_PRIORITY.get(self.source_type, 99)


DEFAULT_RULES: List[Rule] = [
    Rule(
        rule_id="OEM_COOL_FLOW_MIN",
        name="Minimum soğutma debisi",
        source_type="Şirket İçi Standart",
        source_name="Punta Kaynak CheckList Rev01",
        parameter="cooling_flow_lpm",
        operator="min",
        min_value=6.0,
        max_value=None,
        unit="L/dk",
        material_family="Tümü",
        stack_count="Tümü",
        note="Saha checklist referansı."
    ),
    Rule(
        rule_id="OEM_COOL_TEMP_MAX",
        name="Maksimum soğutma suyu sıcaklığı",
        source_type="Şirket İçi Standart",
        source_name="Punta Kaynak CheckList Rev01",
        parameter="cooling_temp_c",
        operator="max",
        min_value=None,
        max_value=25.0,
        unit="°C",
        material_family="Tümü",
        stack_count="Tümü",
        note="Saha checklist referansı."
    ),
    Rule(
        rule_id="OEM_DC_REQUIRED",
        name="DC akım zorunluluğu",
        source_type="Şirket İçi Standart",
        source_name="Punta Kaynak CheckList Rev01",
        parameter="dc_current",
        operator="equals",
        min_value=1.0,
        max_value=1.0,
        unit="bool",
        material_family="Tümü",
        stack_count="Tümü",
        note="İlk saha kural setinde DC akım referansı."
    ),
    Rule(
        rule_id="OEM_TIP_07_09",
        name="0,7–0,9 mm için elektrot uç çapı",
        source_type="OEM / Müşteri Normu",
        source_name="OEM Eğitim Tablosu",
        parameter="tip_diameter_mm",
        operator="range",
        min_value=5.0,
        max_value=5.0,
        unit="mm",
        material_family="Düşük / Orta Karbonlu Çelik",
        stack_count="Tümü",
        note="En ince sac 0,7–0,9 mm olduğunda."
    ),
    Rule(
        rule_id="LIT_4SQRT_T",
        name="Minimum çekirdek çapı 4√t",
        source_type="Literatür",
        source_name="RWMA/AWS destekli kriter",
        parameter="nugget_min_mm",
        operator="derived_min",
        min_value=None,
        max_value=None,
        unit="mm",
        material_family="Tümü",
        stack_count="Tümü",
        note="En ince sac kalınlığına göre hesaplanır."
    ),
]


def rules_to_rows(rules: Optional[List[Rule]] = None) -> List[Dict[str, Any]]:
    return [asdict(r) | {"priority": r.priority} for r in (rules or DEFAULT_RULES)]


def _matches(rule: Rule, material_family: str, stack_count: str) -> bool:
    material_ok = rule.material_family in ("Tümü", material_family)
    stack_ok = rule.stack_count in ("Tümü", stack_count)
    return rule.enabled and material_ok and stack_ok


def _evaluate_rule(rule: Rule, values: Dict[str, Any], t_min: float) -> Dict[str, Any]:
    value = values.get(rule.parameter)
    expected = ""
    status = "İnceleme Gerekli"
    passed = None

    if rule.operator == "derived_min":
        expected_value = 4.0 * math.sqrt(t_min)
        actual = float(values.get("nugget_min_mm", 0.0))
        passed = actual >= expected_value
        expected = f">= {expected_value:.2f} {rule.unit}"
        value = actual
    elif rule.operator == "min":
        passed = float(value) >= float(rule.min_value)
        expected = f">= {rule.min_value} {rule.unit}"
    elif rule.operator == "max":
        passed = float(value) <= float(rule.max_value)
        expected = f"<= {rule.max_value} {rule.unit}"
    elif rule.operator == "range":
        passed = float(rule.min_value) <= float(value) <= float(rule.max_value)
        expected = f"{rule.min_value}–{rule.max_value} {rule.unit}"
    elif rule.operator == "equals":
        passed = float(bool(value)) == float(rule.min_value)
        expected = "Evet" if rule.min_value == 1.0 else str(rule.min_value)
    else:
        expected = "Tanımsız operatör"

    if passed is True:
        status = "Uygun"
    elif passed is False:
        status = "Uygun Değil"

    return {
        "rule_id": rule.rule_id,
        "rule_name": rule.name,
        "source_type": rule.source_type,
        "source_name": rule.source_name,
        "priority": rule.priority,
        "parameter": rule.parameter,
        "actual_value": value,
        "expected": expected,
        "status": status,
        "note": rule.note,
    }


def detect_conflicts(rules: List[Rule]) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[str, str, str], List[Rule]] = {}

    for rule in rules:
        if not rule.enabled:
            continue
        key = (rule.parameter, rule.material_family, rule.stack_count)
        grouped.setdefault(key, []).append(rule)

    for key, items in grouped.items():
        if len(items) < 2:
            continue

        ordered = sorted(items, key=lambda r: r.priority)
        winner = ordered[0]

        for challenger in ordered[1:]:
            conflict = False
            if winner.operator == challenger.operator == "range":
                wmin, wmax = winner.min_value, winner.max_value
                cmin, cmax = challenger.min_value, challenger.max_value
                conflict = max(wmin, cmin) > min(wmax, cmax)
            elif winner.operator == challenger.operator == "min":
                conflict = winner.min_value != challenger.min_value
            elif winner.operator == challenger.operator == "max":
                conflict = winner.max_value != challenger.max_value
            elif winner.operator == challenger.operator == "equals":
                conflict = winner.min_value != challenger.min_value

            if conflict:
                conflicts.append({
                    "parameter": key[0],
                    "material_family": key[1],
                    "stack_count": key[2],
                    "winner_rule": winner.rule_id,
                    "winner_source": winner.source_name,
                    "challenger_rule": challenger.rule_id,
                    "challenger_source": challenger.source_name,
                    "decision": "Daha yüksek öncelikli kaynak esas alındı.",
                })

    return conflicts


def evaluate_compliance(
    *,
    material_family: str,
    stack_count: str,
    t_min: float,
    values: Dict[str, Any],
    custom_rules: Optional[List[Rule]] = None,
) -> Dict[str, Any]:
    all_rules = list(DEFAULT_RULES)
    if custom_rules:
        all_rules.extend(custom_rules)

    applicable = [r for r in all_rules if _matches(r, material_family, stack_count)]
    results = [_evaluate_rule(r, values, t_min) for r in applicable]

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "Uygun")
    failed = sum(1 for r in results if r["status"] == "Uygun Değil")
    review = total - passed - failed
    score = (passed / total * 100.0) if total else 0.0

    return {
        "results": results,
        "conflicts": detect_conflicts(applicable),
        "summary": {
            "total_rules": total,
            "passed": passed,
            "failed": failed,
            "review": review,
            "score": score,
        },
    }


def build_custom_rule(data: Dict[str, Any]) -> Rule:
    return Rule(
        rule_id=str(data["rule_id"]).strip(),
        name=str(data["name"]).strip(),
        source_type=str(data["source_type"]).strip(),
        source_name=str(data["source_name"]).strip(),
        parameter=str(data["parameter"]).strip(),
        operator=str(data["operator"]).strip(),
        min_value=data.get("min_value"),
        max_value=data.get("max_value"),
        unit=str(data.get("unit", "")).strip(),
        material_family=str(data.get("material_family", "Tümü")).strip(),
        stack_count=str(data.get("stack_count", "Tümü")).strip(),
        note=str(data.get("note", "")).strip(),
        enabled=bool(data.get("enabled", True)),
    )
