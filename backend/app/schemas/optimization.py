from pydantic import BaseModel, Field
class Model4Input(BaseModel):
    Current: float; Force: float; Time: float; Cooling: float; Sequence: float; Holding: float; SheetThick: float
class EnsembleMemberInput(BaseModel):
    model_name: str; prediction_mm: float; weight: float=Field(gt=0); validation_status: str="Unknown"
class EnsembleRequest(BaseModel): members: list[EnsembleMemberInput]
class DoeOptimizationRequest(BaseModel):
    material_family:str; thickness_mm:float=Field(gt=0); min_nugget_mm:float=Field(gt=0); target_nugget_mm:float=Field(gt=0)
    current_min_ka:float=Field(gt=0); current_max_ka:float=Field(gt=0); current_step_ka:float=Field(gt=0)
    time_min_cycles:float=Field(gt=0); time_max_cycles:float=Field(gt=0); time_step_cycles:float=Field(gt=0)
    force_min_kn:float=Field(gt=0); force_max_kn:float=Field(gt=0); force_step_kn:float=Field(gt=0)
class ValidationRow(BaseModel):
    Current:float; Force:float; Time:float; Cooling:float; Sequence:float; Holding:float; SheetThick:float; actual_nugget_mm:float
class ModelValidationRequest(BaseModel): rows:list[ValidationRow]=Field(min_length=3)
