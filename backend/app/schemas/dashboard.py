
from pydantic import BaseModel


class DashboardResponse(BaseModel):
    total_projects: int
    active_projects: int
    total_weld_points: int
    risky_weld_points: int
    pending_approvals: int
    rejected_approvals: int
    total_users: int
    recent_audit_events: int
