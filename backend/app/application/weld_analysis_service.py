from app.domain.engine import evaluate_weld
from app.domain.model_registry import compare_and_select
from app.domain.rules_engine import evaluate_compliance

class WeldAnalysisService:
    def analyze(self, request):
        inputs=request.model_dump()
        inputs["layers"]=[x.model_dump() for x in request.layers]
        result=evaluate_weld(inputs)
        t_min=min(x["thickness_mm"] for x in inputs["layers"])
        selection=compare_and_select(material_family=inputs["material_family"],t_min=t_min,nugget_min_mm=result["nugget_min_mm"],nugget_opt_mm=result["nugget_opt_mm"],current_ka=inputs["current_ka"],force_kn=inputs["force_kn"],weld_cycles=inputs["weld_cycles"],cooling_cycles=0,squeeze_cycles=inputs["squeeze_cycles"],hold_cycles=inputs["hold_cycles"])
        compliance=evaluate_compliance(material_family=inputs["material_family"],stack_count=inputs["stack_count"],t_min=t_min,values={"cooling_flow_lpm":inputs["cooling_flow_lpm"],"cooling_temp_c":inputs["cooling_temp_c"],"dc_current":inputs["dc_current"],"tip_diameter_mm":inputs["tip_diameter_mm"],"nugget_min_mm":result["nugget_min_mm"]})
        return {**result,"selected_model":selection["selected_model"],"selected_prediction_mm":selection["selected_prediction_mm"],"model_results":selection["results"],"compliance_summary":compliance["summary"],"compliance_results":compliance["results"],"compliance_conflicts":compliance["conflicts"]}
