import type { WeldAnalysisRequest, WeldAnalysisResponse } from './weld'
export type Project={id:number;project_code:string;project_name:string;customer:string;vehicle_platform:string;status:string;created_at:string;updated_at:string}
export type ProjectCreate={project_code:string;project_name:string;customer?:string;vehicle_platform?:string;status?:string}
export type WeldPoint={id:number;project_id:number;point_code:string;part_no:string;part_revision:string;station:string;robot:string;gun:string;operation_no:string;criticality:string;approval_status:string;version_no:number;analysis_input:WeldAnalysisRequest;analysis_result:WeldAnalysisResponse;created_at:string;updated_at:string}
export type WeldPointCreate={point_code:string;part_no?:string;part_revision?:string;station?:string;robot?:string;gun?:string;operation_no?:string;criticality?:string;changed_by?:string;change_reason?:string;analysis_input:WeldAnalysisRequest}
