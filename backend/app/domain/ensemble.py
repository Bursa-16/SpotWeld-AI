from __future__ import annotations
from typing import Any, Dict, List
import math, statistics

def weighted_ensemble(members: List[Dict[str,Any]], confidence_multiplier:float=1.96) -> Dict[str,Any]:
    valid=[m for m in members if m.get("prediction_mm") is not None and float(m.get("weight",0))>0 and math.isfinite(float(m["prediction_mm"]))]
    if not valid: raise ValueError("No valid ensemble members")
    total_weight=sum(float(m["weight"]) for m in valid)
    mean=sum(float(m["prediction_mm"])*float(m["weight"]) for m in valid)/total_weight
    preds=[float(m["prediction_mm"]) for m in valid]
    spread=statistics.pstdev(preds) if len(preds)>1 else 0.0
    confidence="Yüksek" if spread<=0.25 else "Orta" if spread<=0.75 else "Düşük"
    return {
        "prediction_mm":mean,"lower_mm":max(0,mean-confidence_multiplier*spread),
        "upper_mm":max(0,mean+confidence_multiplier*spread),"model_spread_mm":spread,
        "confidence_level":confidence,
        "members":[{**m,"normalized_weight":float(m["weight"])/total_weight,"distance_from_ensemble_mm":float(m["prediction_mm"])-mean} for m in valid]
    }
