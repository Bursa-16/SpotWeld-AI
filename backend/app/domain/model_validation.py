from __future__ import annotations
from typing import Any, Callable, Dict, List
import math, statistics

def validate_model(rows:List[Dict[str,float]], predictor:Callable[[Dict[str,float]],float], target_key:str="actual_nugget_mm")->Dict[str,Any]:
    if not rows: raise ValueError("Validation data is empty")
    actual=[]; pred=[]; details=[]
    for i,row in enumerate(rows,1):
        a=float(row[target_key]); p=float(predictor(row)); e=p-a
        actual.append(a); pred.append(p); details.append({"row":i,"actual_mm":a,"predicted_mm":p,"error_mm":e,"absolute_error_mm":abs(e)})
    errors=[p-a for p,a in zip(pred,actual)]; sq=[e*e for e in errors]
    mean=statistics.fmean(actual); ss_tot=sum((a-mean)**2 for a in actual); ss_res=sum(sq)
    rmse=math.sqrt(statistics.fmean(sq)); mae=statistics.fmean(abs(e) for e in errors); bias=statistics.fmean(errors); r2=1-ss_res/ss_tot if ss_tot>0 else 0.0
    status="Validated" if rmse<=0.35 and r2>=0.85 else "Conditional" if rmse<=0.75 and r2>=0.60 else "Not Validated"
    return {"sample_count":len(rows),"rmse_mm":rmse,"mae_mm":mae,"bias_mm":bias,"r2":r2,"status":status,"details":details}
