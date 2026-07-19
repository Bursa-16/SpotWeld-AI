export type LayerInput = {
  material_family: string
  material_subtype: string
  thickness_mm: number
  coated: boolean
}

export type WeldAnalysisRequest = {
  material_family: string
  material_subtype: string
  stack_count: '2T' | '3T' | '4T'
  layers: LayerInput[]
  current_ka: number
  weld_cycles: number
  force_kn: number
  tip_diameter_mm: number
  squeeze_cycles: number
  hold_cycles: number
  cooling_flow_lpm: number
  cooling_temp_c: number
  dc_current: boolean
  adhesive: boolean
  shunt_risk: boolean
}

export type WeldAnalysisResponse = {
  score: number
  risk_level: string
  nugget_min_mm: number
  nugget_opt_mm: number
  selected_model: string | null
  selected_prediction_mm?: number | null
  compliance_summary: {
    total_rules?: number
    passed?: number
    failed?: number
    review?: number
    score: number
  }
  risks: Array<{ title: string; detail: string }>
  actions: string[]
  recommended_ranges?: Array<Record<string, unknown>>
}
