from typing import List, Optional
from pydantic import BaseModel, Field, model_validator

class LayerInput(BaseModel):
    material_family: str
    material_subtype: str
    thickness_mm: float = Field(gt=0, le=10)
    coated: bool = False

class WeldAnalysisRequest(BaseModel):
    material_family: str
    material_subtype: str
    stack_count: str
    layers: List[LayerInput]
    current_ka: float = Field(ge=0, le=100)
    weld_cycles: float = Field(ge=0, le=500)
    force_kn: float = Field(ge=0, le=50)
    tip_diameter_mm: float = Field(gt=0, le=50)
    squeeze_cycles: float = Field(ge=0, le=500)
    hold_cycles: float = Field(ge=0, le=500)
    cooling_flow_lpm: float = Field(ge=0, le=100)
    cooling_temp_c: float = Field(ge=0, le=100)
    dc_current: bool = True
    adhesive: bool = False
    shunt_risk: bool = False

    @model_validator(mode="after")
    def validate_stack(self):
        if self.stack_count not in {"2T","3T","4T"}:
            raise ValueError("stack_count must be 2T, 3T or 4T")
        if len(self.layers) != int(self.stack_count[0]):
            raise ValueError("Layer count must match stack_count")
        return self

class WeldAnalysisResponse(BaseModel):
    score: float
    risk_level: str
    nugget_min_mm: float
    nugget_opt_mm: float
    recommended_ranges: list
    risks: list
    actions: list
    notes: list = []
    selected_model: Optional[str]
    selected_prediction_mm: Optional[float]
    model_results: list
    compliance_summary: dict
    compliance_results: list
    compliance_conflicts: list
