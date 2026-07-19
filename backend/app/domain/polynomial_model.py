from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List

@dataclass
class PolynomialTerm:
    coefficient: float
    factors: list[dict[str, Any]]

@dataclass
class PolynomialModel:
    name: str
    intercept: float
    variables: list[str]
    units: dict[str, str]
    terms: list[PolynomialTerm]
    validation_status: str
    model_version: str = "1.0"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolynomialModel":
        required=["name","intercept","variables","units","terms","validation_status"]
        missing=[k for k in required if k not in data]
        if missing: raise ValueError("Model definition missing fields: "+", ".join(missing))
        return cls(
            name=str(data["name"]), intercept=float(data["intercept"]),
            variables=list(data["variables"]), units=dict(data["units"]),
            terms=[PolynomialTerm(float(t["coefficient"]), list(t["factors"])) for t in data["terms"]],
            validation_status=str(data["validation_status"]),
            model_version=str(data.get("model_version","1.0")),
        )

    def predict(self, values: Dict[str,float]) -> float:
        missing=[v for v in self.variables if v not in values]
        if missing: raise ValueError("Missing model inputs: "+", ".join(missing))
        total=self.intercept
        for term in self.terms:
            product=1.0
            for factor in term.factors:
                product*=float(values[factor["variable"]])**int(factor.get("power",1))
            total+=term.coefficient*product
        return float(total)

    def explain(self, values: Dict[str,float], top_n:int=8) -> List[Dict[str,Any]]:
        rows=[]
        for term in self.terms:
            product=1.0; labels=[]
            for factor in term.factors:
                var=factor["variable"]; power=int(factor.get("power",1))
                product*=float(values[var])**power
                labels.append(var if power==1 else f"{var}^{power}")
            contribution=term.coefficient*product
            rows.append({"term":" × ".join(labels),"coefficient":term.coefficient,"contribution":contribution,"absolute_contribution":abs(contribution)})
        rows.sort(key=lambda r:r["absolute_contribution"], reverse=True)
        return rows[:top_n]
