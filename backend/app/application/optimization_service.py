from __future__ import annotations
import json
from pathlib import Path
from app.domain.doe_optimizer import optimize_doe
from app.domain.ensemble import weighted_ensemble
from app.domain.model_validation import validate_model
from app.domain.polynomial_model import PolynomialModel
from app.domain.weld_lobe import estimate_nugget, classify_zone
class OptimizationService:
    def __init__(self):
        path=Path(__file__).resolve().parent.parent/'domain'/'model4_full.json'
        self.model4=PolynomialModel.from_dict(json.loads(path.read_text(encoding='utf-8')))
    def model4_predict(self,payload):
        values=payload.model_dump(); return {"model_name":self.model4.name,"prediction_mm":self.model4.predict(values),"validation_status":self.model4.validation_status,"top_contributions":self.model4.explain(values)}
    def ensemble(self,payload): return weighted_ensemble([m.model_dump() for m in payload.members])
    def optimize(self,payload):
        def evaluator(v):
            nug=estimate_nugget(payload.material_family,payload.thickness_mm,v['current_ka'],v['weld_cycles'],v['force_kn'])
            zone,exp,fus=classify_zone(nug,payload.min_nugget_mm,v['current_ka'],v['weld_cycles'],v['force_kn'],payload.material_family)
            return {"nugget_mm":nug,"expulsion_risk":exp,"fusion_risk":fus,"zone":zone}
        return optimize_doe(current_min_ka=payload.current_min_ka,current_max_ka=payload.current_max_ka,current_step_ka=payload.current_step_ka,time_min_cycles=payload.time_min_cycles,time_max_cycles=payload.time_max_cycles,time_step_cycles=payload.time_step_cycles,force_min_kn=payload.force_min_kn,force_max_kn=payload.force_max_kn,force_step_kn=payload.force_step_kn,target_nugget_mm=payload.target_nugget_mm,min_nugget_mm=payload.min_nugget_mm,evaluator=evaluator)
    def validate_model4(self,payload): return validate_model([r.model_dump() for r in payload.rows],lambda row:self.model4.predict(row))
