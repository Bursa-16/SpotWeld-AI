
from datetime import datetime
from pydantic import BaseModel


class TestResultCreate(BaseModel):
    test_type: str
    result_value: float | None = None
    result_unit: str = ""
    acceptance_status: str
    note: str = ""


class TestResultResponse(TestResultCreate):
    id: int
    weld_point_id: int
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}
