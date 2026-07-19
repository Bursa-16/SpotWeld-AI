
from pydantic import BaseModel, Field


class WeldLobeRequest(BaseModel):
    material_family: str
    thickness_mm: float = Field(gt=0, le=10)
    force_kn: float = Field(gt=0, le=50)
    min_nugget_mm: float = Field(gt=0, le=30)
    current_min_ka: float = Field(gt=0)
    current_max_ka: float = Field(gt=0)
    current_step_ka: float = Field(gt=0)
    time_min_cycles: float = Field(gt=0)
    time_max_cycles: float = Field(gt=0)
    time_step_cycles: float = Field(gt=0)


class PulseStrategyRequest(BaseModel):
    material_family: str
    coated: bool
    thickness_ratio: float = Field(ge=1)
    stack_count: str
    adhesive: bool
    current_ka: float = Field(gt=0)
    weld_cycles: float = Field(gt=0)


class ElectrodeLifeRequest(BaseModel):
    material_family: str
    coated: bool
    tip_diameter_mm: float = Field(gt=0)
    cooling_flow_lpm: float = Field(ge=0)
    cooling_temp_c: float = Field(ge=0)
    current_ka: float = Field(gt=0)
    annual_spot_count: int = Field(gt=0)
    stepper_end_current_ka: float | None = None


class DynamicResistanceRequest(BaseModel):
    samples_micro_ohm: list[float] = Field(min_length=5)
