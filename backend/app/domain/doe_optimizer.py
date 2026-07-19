from __future__ import annotations
from itertools import product
from typing import Any, Callable, Dict, List

def _rng(start:float, stop:float, step:float)->List[float]:
    if step<=0: raise ValueError("Step must be greater than zero")
    out=[]; x=start; guard=0
    while x<=stop+1e-9:
        out.append(round(x,8)); x+=step; guard+=1
        if guard>10000: raise ValueError("DOE range too large")
    return out

def optimize_doe(*,current_min_ka:float,current_max_ka:float,current_step_ka:float,time_min_cycles:float,time_max_cycles:float,time_step_cycles:float,force_min_kn:float,force_max_kn:float,force_step_kn:float,target_nugget_mm:float,min_nugget_mm:float,evaluator:Callable[[Dict[str,float]],Dict[str,float]],top_n:int=20)->Dict[str,Any]:
    rows=[]
    for c,t,f in product(_rng(current_min_ka,current_max_ka,current_step_ka),_rng(time_min_cycles,time_max_cycles,time_step_cycles),_rng(force_min_kn,force_max_kn,force_step_kn)):
        result=evaluator({"current_ka":c,"weld_cycles":t,"force_kn":f})
        nug=float(result["nugget_mm"]); exp=float(result["expulsion_risk"]); fus=float(result["fusion_risk"])
        objective=abs(nug-target_nugget_mm)+max(0,min_nugget_mm-nug)*5+exp*4+fus*4
        rows.append({"current_ka":c,"weld_cycles":t,"force_kn":f,"nugget_mm":nug,"expulsion_risk":exp,"fusion_risk":fus,"objective":objective,"eligible":nug>=min_nugget_mm and exp<0.75})
    rows.sort(key=lambda r:(not r["eligible"],r["objective"]))
    return {"evaluated_count":len(rows),"best":rows[0] if rows else None,"top_candidates":rows[:top_n],"objective_definition":"Target error + minimum nugget penalty + expulsion penalty + fusion penalty"}
