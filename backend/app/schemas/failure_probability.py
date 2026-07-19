
from pydantic import BaseModel, Field


class FailureProbabilityRequest(BaseModel):
    material_family: str
    stack_count: str
    coated: bool = False
    adhesive: bool = False
    shunt_risk: bool = False
    thicknesses_mm: list[float] = Field(min_length=2)

    current_ka: float = Field(gt=0)
    weld_cycles: float = Field(gt=0)
    force_kn: float = Field(gt=0)
    tip_diameter_mm: float = Field(gt=0)
    squeeze_cycles: float = Field(ge=0)
    hold_cycles: float = Field(ge=0)
    cooling_flow_lpm: float = Field(ge=0)
    cooling_temp_c: float = Field(ge=0)

    recommended_current_min_ka: float = Field(gt=0)
    recommended_current_max_ka: float = Field(gt=0)
    recommended_time_min_cycles: float = Field(gt=0)
    recommended_time_max_cycles: float = Field(gt=0)
    recommended_force_min_kn: float = Field(gt=0)
    recommended_force_max_kn: float = Field(gt=0)
    recommended_tip_min_mm: float = Field(gt=0)
    recommended_tip_max_mm: float = Field(gt=0)

    predicted_nugget_mm: float = Field(ge=0)
    minimum_nugget_mm: float = Field(gt=0)
