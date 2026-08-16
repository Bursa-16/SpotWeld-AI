# Engineering Rule Registry Design

## Document Info
- **Status**: DESIGN ONLY — No implementation code
- **Version**: 1.0 (Draft)
- **Date**: 2026-08-15
- **Applies To**: Machine Readiness Check ([docs/112_MACHINE_READINESS_CHECK_DESIGN.md](112_MACHINE_READINESS_CHECK_DESIGN.md)), Digital Weld Passport ([docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md](113_DIGITAL_WELD_PASSPORT_DESIGN.md)), Engineering Validation Modules (future)
- **Supersedes**: None
- **Related ADRs**: ADR-004, ADR-005, ADR-008, ADR-009, ADR-010

---

## 1. Executive Summary

This design document defines a centralized **Engineering Rule Registry** that serves as the single source of truth for engineering validation rules across all SpotWeld-AI subsystems. The registry is architected to support:

- **Machine Readiness Check (MRC)** — equipment readiness validation
- **Digital Weld Passport (DWP)** — weld-point compliance documentation
- **Future validation modules** — extensible rule consumption architecture

Key principle: **Unknown engineering values remain unresolved.** A missing or weakly supported rule must never produce an automatic PASS.

---

## 2. Current State Analysis

### 2.1 Existing Architecture
- [103_RULE_ENGINE_DESIGN.md](103_RULE_ENGINE_DESIGN.md): Basic rule provider outline (OEM, ISO, AWS, SEP, Custom)
- [11_RULE_AND_NORM_ENGINE.md](11_RULE_AND_NORM_ENGINE.md): Conflict handling and priority hierarchy
- [backend/app/domain/rules_engine.py](../backend/app/domain/rules_engine.py): Working Rule dataclass with 5 example rules
- [28_ARCHITECTURE_DECISIONS_AND_BOUNDARIES.md](28_ARCHITECTURE_DECISIONS_AND_BOUNDARIES.md): ADR-004 through ADR-010 provide governance framework

### 2.2 Existing Rule Implementation
**Current Rule Structure** (from rules_engine.py):
```
rule_id, name, source_type, source_name, parameter, operator, 
min_value, max_value, unit, material_family, stack_count, note, enabled
```

**Current Source Priority** (from rules_engine.py):
1. OEM / Müşteri Normu (OEM / Customer Norm)
2. Şirket İçi Standart (Company Standard)
3. Doğrulanmış Saha Modeli (Validated Field Model)
4. Deneysel Model (Experimental Model)
5. Literatür (Literature)
6. Genel Mühendislik Formülü (General Engineering Formula)

**Current Operators** (from rules_engine.py):
- `min` — minimum threshold (value >= min_value)
- `max` — maximum threshold (value <= max_value)
- `range` — bounded interval (min_value <= value <= max_value)
- `equals` — exact match (typically for boolean or categorical)
- `derived_min` — calculated from other parameters (e.g., nugget diameter from sheet thickness)

### 2.3 Existing Rule Implementation Status
Rules currently in backend/app/domain/rules_engine.py:

| rule_id | parameter | operator | min_value | max_value | unit | source_type | current_evidence_class | issue |
|---------|-----------|----------|-----------|-----------|------|-------------|------------------------|-------|
| OEM_COOL_FLOW_MIN | cooling_flow_lpm | min | 6.0 | — | L/dk | Company Standard | UNRESOLVED | Numeric threshold 6.0 lacks authoritative source documentation in project |
| OEM_COOL_TEMP_MAX | cooling_temp_c | max | — | 25.0 | °C | Company Standard | UNRESOLVED | Numeric threshold 25.0 lacks authoritative source documentation in project |
| OEM_DC_REQUIRED | dc_current | equals | 1.0 | 1.0 | bool | Company Standard | UNRESOLVED | Boolean value lacks explicit source-backed engineering requirement |
| OEM_TIP_07_09 | tip_diameter_mm | range | 5.0 | 5.0 | mm | OEM Norm | UNRESOLVED | Numeric threshold 5.0 lacks authoritative source documentation in project |
| ISO_NUGGET_MIN_4SQRT_T | nugget_min_mm | derived_min | — | — | mm | ISO 18278-2 | UNRESOLVED | Repository contains no authoritative engineering source that verifies the exact formula, edition, and section |

**Architecture Note — Prototype Boundary**: Existing backend `DEFAULT_RULES`, hard-coded thresholds, evaluators, and automatic conflict-winner behavior are implementation prototypes only. They are not authoritative engineering evidence, do not establish applicability, and must not be promoted to SOURCE_BACKED merely because they exist or execute in code. A prototype value may enter the registry only as UNRESOLVED with its engineering value disabled/null until qualifying evidence is reviewed under this design. Conflict decisions produced by prototype priority logic are likewise non-authoritative unless an approved deterministic registry policy fully resolves the conflict and records its trace.

### 2.4 Known Gaps / Blockers
- **Code constants are not engineering evidence**: DEFAULT_RULES in rules_engine.py are implementation examples, not authoritative engineering sources
- **OEM_RULES**, **ISO_RULES**, **SEP_RULES** documents exist as templates but contain no actual rule specifications
- **MRC design exists** in `112_MACHINE_READINESS_CHECK_DESIGN.md`; production architecture and rule integration remain unimplemented
- **DWP design exists** in [docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md](113_DIGITAL_WELD_PASSPORT_DESIGN.md); production architecture and Registry integration remain unimplemented
- **No centralized rule registry** with lifecycle management and audit trail
- **No versioning or dating** for rule changes
- **No implemented handling** for the designed PROPOSED, UNRESOLVED, or SUPERSEDED states
- **No implemented evidence-class taxonomy** for traceability
- **No implemented fail-safe enforcement** preventing UNRESOLVED or missing rules from producing auto-PASS/READY decisions
- **MRC inventory defined but unresolved**: exactly 16 engineering thresholds require evidence/calibration

---

## 3. Registry Data Model

### 3.1 Rule Record Structure

```
{
  // Identity
  rule_id: String (immutable, globally unique, e.g. "OEM_COOL_FLOW_MIN")
  name: String (human-readable, may be translated)
  
  // Classification & Governance
  category: String (enum: EQUIPMENT, MATERIAL, PARAMETER, ELECTRODE, MACHINE, COOLING, OTHER)
  parameter: String (e.g. "cooling_flow_lpm", "nugget_min_mm")
  evidence_class: String (enum: SOURCE_BACKED, PROPOSED, UNRESOLVED)
  
  // Validation Logic
  operator: String (enum: MIN, MAX, RANGE, EQUALS, DERIVED_MIN, CUSTOM)
  min_value: Float | null (lower bound or derived formula coefficient)
  max_value: Float | null (upper bound)
  unit: String (canonical unit, e.g. "L/dk", "°C", "mm", "A", "bool")
  
  // Applicability & Context
  material_family: String | Array[String] ("Tümü" = all, or specific: "Düşük Karbonlu Çelik", etc.)
  stack_count: String | Array[String] ("Tümü" = all, or specific: "2", "3+", etc.)
  machine_type: String | Array[String] | null (optional: restricts to specific equipment types)
  source_type: String (enum: OEM, ISO, AWS, SEP, COMPANY_STANDARD, FIELD_MODEL, LITERATURE, DERIVED)
  source_name: String (e.g. "OEM Eğitim Tablosu", "ISO 18278-2:2020")
  source_document: String (e.g. "OEM_TRAINING_TABLE_REV03", "ISO18278-2_SECTION_4.2.1")
  source_url: String | null (optional: external reference)
  
  // Lifecycle & Audit
  status: String (enum: ACTIVE, DEPRECATED, SUPERSEDED, EXPIRED, DRAFT, REVIEW)
  revision: String (e.g. "1", "1.1", "2.0-beta")
  effective_date: ISO8601 (when this rule version became active)
  expiry_date: ISO8601 | null (when this rule is no longer applicable)
  superseded_by: String | null (rule_id of replacement rule)
  created_by: String (user or system identifier)
  created_at: ISO8601
  updated_by: String (last editor)
  updated_at: ISO8601
  
  // Explanation & Handling
  description: String (why this rule exists, engineering justification)
  note: String (implementation notes, warnings, or caveats)
  
  // Fail-Safe Behavior
  safe_default: String (enum: UNRESOLVED, MANUAL_REVIEW)
  missing_handling: String (required input: DATA_INSUFFICIENT; optional input: SKIP_OPTIONAL only)
  conflict_handling: String (approved deterministic policy reference or REQUIRE_ENGINEERING_REVIEW)
  unit_mismatch_handling: String (CONVERT only through approved conversion; otherwise UNIT_MISMATCH)
  
  // Enabled/Disabled State
  enabled: Boolean (can be disabled without deletion, preserving audit trail)
}
```

### 3.2 Evidence Classification

**SOURCE_BACKED**
- Rule is explicitly supported by an engineering document or authoritative source
- Examples: OEM training table, ISO standard, validated field study, published model formula
- Minimum requirement: source document name + revision + section/page reference

**PROPOSED**
- Rule is recommended but not yet verified against production data
- May be: pilot study result, internal hypothesis, consensus recommendation
- Must be explicitly marked and locked out from automatic PASS decisions
- Requires human review before promotion to SOURCE_BACKED

**UNRESOLVED**
- Rule parameter exists in the system but lacks engineering support
- Engineering judgment or customer calibration is required
- Must never be PASS or conditional PASS; it must first be promoted to SOURCE_BACKED through documented engineering review
- Examples: "cooling flow minimum" may be known for one OEM but unconfirmed for another material family

---

## 4. Registry Lifecycle & Versioning

### 4.1 Rule States

```
DRAFT
  ↓
REVIEW ← (human approval + evidence verification)
  ↓
ACTIVE ← (in use for validation)
  ↓
DEPRECATED → (phase-out period)
  ↓
SUPERSEDED → (replaced by newer rule)
  ↓
EXPIRED → (no longer applicable, archived)
```

### 4.2 Version Numbering
- Format: `MAJOR.MINOR[-QUALIFIER]`
- `1.0` — first release
- `1.1` — minor clarification in note or description
- `2.0` — significant change to threshold or operator
- `1.0-beta` — not yet validated
- `1.0-review` — under human review

### 4.3 Effective Date Rules
- Each rule must specify when it becomes active
- A rule version becomes active on `effective_date`
- Prior versions may remain in database for audit trail
- Implementation must enforce: "Use active rule as of context date"

---

## 5. Example Registry Entries

### Example 1: Unresolved Cooling Flow Minimum (Requires Source Evidence)
```yaml
rule_id: OEM_COOL_FLOW_MIN
name: Minimum soğutma debisi
category: COOLING
parameter: cooling_flow_lpm
evidence_class: UNRESOLVED  # ⚠ Numeric threshold lacks authoritative source
operator: MIN
min_value: null  # UNRESOLVED — value 6.0 lacks documented source
max_value: null
unit: L/dk
material_family: Tümü
stack_count: Tümü
source_type: COMPANY_STANDARD
source_name: Punta Kaynak CheckList
source_document: PUNTA_KAYNAK_CHECKLIST_REV01
source_url: (not found in project repository)
effective_date: null  # Cannot activate without evidenced threshold
status: DRAFT  # ← Not yet SOURCE_BACKED
revision: "0.1-unresolved"
description: |
  Soğutma sıvısı debisi minimum gereksinimi tanımlanmamıştır.
  UNRESOLVED: Punta Kaynak CheckList referenced in code but not supplied to project.
  Numeric value "6.0 L/dk" exists in code DEFAULT_RULES but lacks authoritative engineering source.
note: |
  UNRESOLVED — do NOT use for automatic pass/fail decisions.
  Required engineering source: 
    - Authoritative company checklist document with revision date and signature
    - OR OEM equipment specification sheet
    - OR field study report with calibration data and ≥30 weld sample validation
  Until sourced, this rule remains UNRESOLVED and requires ENGINEERING_REVIEW_REQUIRED.
safe_default: UNRESOLVED  # Required applicable unresolved rule → ENGINEERING_REVIEW_REQUIRED
missing_handling: DATA_INSUFFICIENT  # Missing required observation → MANUAL_REVIEW_REQUIRED as a retained secondary blocker
conflict_handling: REQUIRE_ENGINEERING_REVIEW
unit_mismatch_handling: UNIT_MISMATCH
enabled: false  # ← Not yet active; awaiting source documentation
superseded_by: null
```

**Evidence Requirements to Promote to SOURCE_BACKED**:
- Submit authoritative document (checklist, OEM spec, field study report) with:
  - Document title, revision, date of issue
  - Specific section/table/page number
  - Engineering justification for numeric value 6.0 L/dk
  - Applicability scope (material family, stack count, machine type)
  - Validation data (≥30 welds if field study)
  - Approval signature or certification

### Example 2: Unresolved Electrode Tip Wear Limit (Requires Production Validation)
```yaml
rule_id: UNRESOLV_TIP_WEAR_LIMIT_PCT
name: Maximum electrode tip wear percentage
category: ELECTRODE
parameter: tip_wear_percent
evidence_class: UNRESOLVED  # ⚠ Preliminary observation, not production-validated
operator: MAX
min_value: null
max_value: null  # Value 15% lacks production validation
unit: percent
material_family:
  - Düşük Karbonlu Çelik
  - Orta Karbonlu Çelik
stack_count: Tümü
machine_type: null
source_type: FIELD_MODEL
source_name: Internal wear study 2024 (preliminary)
source_document: WEAR_STUDY_Q2_2024_PRELIMINARY_NOT_APPROVED
effective_date: null  # Cannot activate without production validation
status: DRAFT  # ← Not yet SOURCE_BACKED
revision: "0.1-preliminary"
description: |
  Preliminary observation: tip wear > 15% correlates with increased expulsion risk.
  UNRESOLVED: This is a hypothesis from internal study, not yet customer-validated.
  Numeric value "15%" exists in proposal but lacks ≥500 production weld validation.
note: |
  UNRESOLVED — MUST NOT be used for automatic pass/fail decisions.
  Status: Internal hypothesis requiring customer field validation.
  Required validation before promotion to SOURCE_BACKED:
    - ≥500 production welds from customer(s)
    - Correlation data linking tip wear % to defect frequency
    - Statistical confidence interval (recommend ≥95%)
    - Cross-validation across material families and machine types
    - Approval by customer quality engineering
  Until validated, this rule remains UNRESOLVED and requires ENGINEERING_REVIEW_REQUIRED.
safe_default: UNRESOLVED  # Required applicable unresolved rule → ENGINEERING_REVIEW_REQUIRED
missing_handling: DATA_INSUFFICIENT  # Missing required observation → MANUAL_REVIEW_REQUIRED as a retained secondary blocker
conflict_handling: REQUIRE_ENGINEERING_REVIEW
unit_mismatch_handling: UNIT_MISMATCH
enabled: false  # ← Not yet active; awaiting production validation
superseded_by: null
```

**Path to Production Validation**:
- Customer field study with ≥500 welds
- Correlation analysis: tip_wear_percent vs. defect_rate
- Statistical significance test
- Approval document signed by customer quality/engineering
- Update evidence_class to SOURCE_BACKED, status to ACTIVE, set min_value/max_value

### Example 3: Unresolved Cooling Water Conductivity Threshold
```yaml
rule_id: UNRESOLV_COOL_WATER_QUALITY
name: Cooling water conductivity limit
category: COOLING
parameter: cooling_water_conductivity_us_cm
evidence_class: UNRESOLVED  # ⚠ Machine/facility-specific; no standard known
operator: MAX
min_value: null
max_value: null  # ← No threshold defined
unit: µS/cm
material_family: Tümü
stack_count: Tümü
machine_type: null
source_type: DERIVED
source_name: (None — requires customer calibration)
source_document: TBD
effective_date: null  # ← No activation date
status: DRAFT
revision: "0.0-placeholder"
description: |
  Tap water conductivity can interfere with electrode heat balance and cooling circuit impedance.
  UNRESOLVED: No standard engineering threshold published for this parameter.
  Each facility must establish acceptable range based on machine design, cooling circuit materials, 
  and local water quality.
note: |
  UNRESOLVED — parameter is measured but threshold is unknown.
  This is a customer-specific engineering requirement, not a universal rule.
  Each OEM/facility must:
    - Measure baseline cooling water conductivity
    - Establish a facility-approved range from qualifying evidence
    - Validate impact on weld quality and electrode life
    - Document approval
  Until a customer-specific threshold is established, this rule remains UNRESOLVED and requires ENGINEERING_REVIEW_REQUIRED.
safe_default: UNRESOLVED  # ← System reports unresolved state
missing_handling: DATA_INSUFFICIENT  # Missing required observation → MANUAL_REVIEW_REQUIRED as a retained secondary blocker
conflict_handling: REQUIRE_ENGINEERING_REVIEW  # if a conflict becomes applicable
unit_mismatch_handling: UNIT_MISMATCH  # Measurement unit must be precise
enabled: false
superseded_by: null
```

### Example 4: Unresolved ISO Nugget Minimum Claim (Engineering Source Required)
```yaml
rule_id: ISO_NUGGET_MIN_4SQRT_T
name: Minimum nugget diameter per ISO 18278-2
category: PARAMETER
parameter: nugget_min_mm
evidence_class: UNRESOLVED  # Repository-authoritative engineering source not present
operator: DERIVED_MIN
min_value: null  # Claimed coefficient 4.0 is not approved for evaluation
max_value: null
unit: mm
material_family: Tümü
stack_count: Tümü
machine_type: null  # Applies to all machine types
source_type: ISO
source_name: "Claimed ISO 18278-2:2020 reference — unverified"
source_document: null
source_url: null
effective_date: null
status: DRAFT
revision: "0.1-unresolved"
description: |
  UNRESOLVED — engineering source required. The repository contains claims that
  d_min = 4√t appears in ISO 18278-2:2020 Section/Clause 5.3, but it contains no
  authoritative standard text or controlled engineering extract verifying the
  formula, edition, section, definitions, units, or applicability.
note: |
  Do not evaluate this rule and do not use it for PASS, FAIL, compliance, or READY.
  Promotion requires an approved, repository-controlled copy or controlled extract
  of the applicable ISO edition that shows the exact formula and identifies the
  exact clause/page/table, variable definitions, units, sheet-thickness convention,
  material/process scope, and any normative conditions or exceptions; engineering
  review must confirm applicability and record document control metadata.
safe_default: UNRESOLVED
missing_handling: DATA_INSUFFICIENT
conflict_handling: REQUIRE_ENGINEERING_REVIEW
unit_mismatch_handling: UNRESOLVED
enabled: false
created_by: engineering_team
created_at: 2026-08-15T00:00:00Z
updated_at: 2026-08-15T00:00:00Z
```

**Evidence Summary**:
- Repository verification result: **UNRESOLVED — engineering source required**
- No qualifying repository evidence verifies `d_min = 4√t`, the 2020 edition, or Section/Clause 5.3
- Python constants, generated Markdown, templates, examples, and prior AI-authored assertions are not acceptable evidence
- Future promotion requires the controlled evidence and engineering applicability review listed in the rule note

### Example 5: Unresolved AWS Guideline (External Standard Not in Project)
```yaml
rule_id: UNRESOLV_AWS_CURRENT_DENSITY_RANGE
name: AWS recommended current density range
category: PARAMETER
parameter: current_density_kA_per_mm2
evidence_class: UNRESOLVED  # ⚠ External standard; not in project repository
operator: RANGE
min_value: null  # Values 180–360 not verified in project
max_value: null
unit: kA/mm²
material_family:
  - Düşük Karbonlu Çelik
  - Orta Karbonlu Çelik
stack_count: "2"
machine_type: AC_TRANSFORMER  # Restriction not verified in project
source_type: AWS
source_name: AWS C1.1M/C1.1:2008 - Recommended Practices
source_document: AWS_C1_1_2008_TABLE_3 (external; not in project repository)
source_url: https://aws.org/... (external reference)
effective_date: null  # Cannot activate without project approval
status: DRAFT
revision: "0.1-unresolved"
description: |
  AWS C1.1 recommends current density between 180–360 kA/mm² for
  two-sheet low and medium carbon steel using AC machines.
  UNRESOLVED: AWS standard is external to this project; values not verified against
  company equipment, field data, or customer requirements.
note: |
  UNRESOLVED — External standard reference; not yet approved for project use.
  This is a recommendation from AWS, not a project-specific engineering requirement.
  Status: Pending explicit approval and validation against field data.
  To promote to SOURCE_BACKED:
    - Import AWS C1.1 document into project documentation
    - Verify applicability to customer equipment and materials
    - Cross-validate with field performance data (≥30 weld samples)
    - Obtain customer approval for use in production rules
    - Document applicability scope and exceptions
  Until approved, this rule remains UNRESOLVED and requires ENGINEERING_REVIEW_REQUIRED.
safe_default: UNRESOLVED  # Required applicable unresolved rule → ENGINEERING_REVIEW_REQUIRED
missing_handling: DATA_INSUFFICIENT  # Missing required observation → MANUAL_REVIEW_REQUIRED as a retained secondary blocker
conflict_handling: REQUIRE_ENGINEERING_REVIEW  # unresolved external-source conflict
unit_mismatch_handling: CONVERT  # But only if source is approved
enabled: false  # ← Not yet approved for project
superseded_by: null
```

**Promotion Path**:
- Import AWS C1.1M/C1.1:2008 standard document into project (if licensed)
- Verify values (180–360 kA/mm²) against company equipment specifications
- Validate against field performance data (≥30 welds per condition)
- Obtain customer(s) approval for use
- Update status to ACTIVE, evidence_class to SOURCE_BACKED, set min_value/max_value

---

## 6. Handling Missing, Conflicting, and Unresolved Rules

### 6.1 Missing Rule Handling
**Principle**: Unknown engineering values remain unknown; do not invent PASS.

| Scenario | Action |
|----------|--------|
| Required applicable rule exists but required input data is missing | Report DATA_INSUFFICIENT; aggregate MRC result is MANUAL_REVIEW_REQUIRED unless a higher-precedence blocker applies; retain it as a secondary blocker and always block automatic READY |
| Optional rule input is missing | SKIP only when the rule is explicitly non-required; record the omission; never use the skip to satisfy a READY prerequisite |
| No rule exists for parameter + material family | Report as NOT_EVALUATED, not PASS |
| No rule exists for parameter + machine type | Same as above |
| Required rule is DRAFT or UNRESOLVED | Report as UNRESOLVED, block auto-approval |

**Code Principle**:
```
if required_applicable_rule_exists(parameter, material_family):
    if required_input_data_missing(parameter):
        return DATA_INSUFFICIENT  # aggregate MRC result is MANUAL_REVIEW_REQUIRED
    else:
        return evaluate(rule, input_data)
else:
    return NOT_EVALUATED  # Not PASS, not FAIL — explicitly unknown
```

### 6.2 Conflicting Rule Handling
**Principle**: Retain both rules, identify the conflict, and record source and version. A selection is final only when an approved deterministic policy fully resolves the conflict; otherwise require engineering review and block automatic READY.

| Scenario | Action |
|----------|--------|
| Two rules same parameter, same material, different thresholds | Apply an approved SOURCE_PRIORITY policy only if it fully resolves the conflict; otherwise ENGINEERING_REVIEW_REQUIRED |
| Source-backed rule conflicts with PROPOSED rule | Do not evaluate the PROPOSED rule; retain and document it; any remaining applicability conflict requires engineering review |
| Same-priority rules (e.g., two different OEMs) | Apply an approved deterministic policy only if fully resolving; otherwise ENGINEERING_REVIEW_REQUIRED |

**Code Principle**:
```
applicable_rules = filter(rules, parameter, material_family, effective_date)
if len(applicable_rules) > 1:
    resolution = approved_conflict_policy.resolve(applicable_rules)
    log_audit_entry(
        event="CONFLICT_DETECTED",
        candidate_rules=[r.rule_id for r in applicable_rules],
        policy_version=approved_conflict_policy.version,
        resolution=resolution,
    )
    if not resolution.fully_resolved:
        return ENGINEERING_REVIEW_REQUIRED  # automatic READY blocked
    selected_rule = resolution.selected_rule
else:
    selected_rule = applicable_rules[0]

return evaluate(selected_rule, input_data)
```

### 6.3 Unit Mismatch Handling
**Principle**: Explicit conversion or rejection; never silent conversion.

| Scenario | Action |
|----------|--------|
| Input unit matches rule unit | Proceed with evaluation |
| Input unit different but convertible (A ↔ kA) | Convert if rule allows; log conversion in audit trail |
| Input unit incompatible (temperature vs. flow rate) | Report UNIT_MISMATCH; do not evaluate; if input is required, aggregate to MANUAL_REVIEW_REQUIRED and block READY |
| No unit information in required input | DATA_INSUFFICIENT; request explicit unit metadata; aggregate MRC result is MANUAL_REVIEW_REQUIRED |

**Code Principle**:
```
if input_unit == rule_unit:
    return evaluate(rule, input_value)
elif can_convert(input_unit, rule_unit):
    if rule.unit_mismatch_handling == "CONVERT":
        converted_value = convert(input_value, input_unit, rule_unit)
        log_audit_entry(conversion_record)
        return evaluate(rule, converted_value)
    else:
        return UNIT_MISMATCH  # required input → MANUAL_REVIEW_REQUIRED
else:
    return UNIT_MISMATCH  # required input → MANUAL_REVIEW_REQUIRED
```

### 6.4 Duplicate Rule Handling
**Principle**: Prevent multiple active rules with identical rule_id; archive superseded versions.

| Scenario | Action |
|----------|--------|
| rule_id exists with status=ACTIVE, new version submitted | Check revision; if higher, update superseded_by link; mark old as SUPERSEDED |
| rule_id exists with status=DRAFT, human requests activation | Perform evidence review; set effective_date; transition to ACTIVE |
| rule_id exists, human requests deletion | Do not delete; set status=EXPIRED; set expiry_date; preserve audit trail |

**Database Constraint**:
```
UNIQUE(rule_id, status) WHERE status IN ('ACTIVE', 'REVIEW')
→ Only one rule per ID may be ACTIVE or REVIEW at a time
```

### 6.5 Superseded Rule Handling
**Principle**: Link obsolete rules to replacements; maintain audit trail.

| Scenario | Action |
|----------|--------|
| Rule is SUPERSEDED | Set superseded_by = new_rule_id; mark status = SUPERSEDED; do not evaluate |
| Historical audit asks "why was old rule used?" | Query by effective_date; show superseded chain |
| Restore prior rule content for future use | Create a new rule revision from the prior content with a new approved effective date; retain all old versions and effective dates unchanged; link the supersession chain |

**Audit Example**:
```
Query: What rule applied to weld point W-001 on 2024-03-15?
Answer: 
  - OEM_COOL_FLOW_MIN revision 1.0 (active 2024-01-15 to 2024-08-01)
  - Superseded by OEM_COOL_FLOW_MIN revision 1.1 (active 2024-08-01 onwards)
  - W-001 created on 2024-03-15, evaluated against revision 1.0
  - Audit link: [show both rule versions]
```

---

## 7. Machine Readiness Check (MRC) Integration Boundary

The authoritative MRC subsystem design is [docs/112_MACHINE_READINESS_CHECK_DESIGN.md](112_MACHINE_READINESS_CHECK_DESIGN.md). This section defines how MRC consumes Registry rules. Document 111 owns rule evidence, lifecycle, and rule applicability; document 112 owns MRC check selection, assessment orchestration, aggregation, and the final MRC state.

### 7.1 MRC Purpose
Validates that manufacturing equipment and setup meet minimum engineering standards before production weld points are created.

### 7.2 MRC Consumes Shared Registry
```
┌──────────────────────────────┐
│ Engineering Rule Registry    │
│  (docs/111_ENGINEERING_      │
│   RULE_REGISTRY_DESIGN.md)   │
└──────────────────────────────┘
             ↓
    ┌────────┴────────┐
    ↓                 ↓
┌─────────┐      ┌─────────┐
│   MRC   │      │   DWP   │
│ Machine │      │  Digital│
│Readiness│      │  Weld   │
│ Check   │      │Passport │
└─────────┘      └─────────┘
```

### 7.3 MRC Rule Filter
MRC applies rules where:
- `category` in {EQUIPMENT, MACHINE, ELECTRODE, COOLING, PARAMETER, MATERIAL}; `PARAMETER` and `MATERIAL` are required because U-007 and U-016 are part of the authoritative 16-item MRC inventory
- applicability discovery includes ACTIVE validated rules and DRAFT/UNRESOLVED requirements; only ACTIVE + SOURCE_BACKED rules may be evaluated for PASS/FAIL
- `material_family` matches manufacturing context (or is "Tümü")
- no inventory item may be silently omitted solely because of category; category changes require a versioned design/registry decision

### 7.4 MRC Decision Logic — Safe-Default Principle

**CRITICAL RULE**: Machine READY only when at least one applicable validated engineering rule exists, every required applicable SOURCE_BACKED rule passes, all required inputs are available, no required applicable UNRESOLVED rule exists, no unresolved conflict exists, and no manual-review condition exists.

```
INPUT: Machine ID, material family, electrode type, cooling circuit parameters

STEP 1: Discover all applicable rule requirements, including non-active UNRESOLVED requirements
  - Select requirements whose applicability matches the machine and manufacturing context
  - Separately identify validated rules: status = ACTIVE, evidence_class = SOURCE_BACKED,
    effective_date <= now, and expiry_date > now
  - Filter: category IN (EQUIPMENT, MACHINE, ELECTRODE, COOLING, PARAMETER, MATERIAL)
  - Filter: material_family matches input OR material_family = "Tümü"
  
STEP 2: Evaluate each SOURCE_BACKED rule
  - Rule: OEM_COOL_FLOW_MIN (status=DRAFT, evidence_class=UNRESOLVED) → SKIP (not ACTIVE)
  - Rule: [source_backed_rule_2] (status=ACTIVE, evidence_class=SOURCE_BACKED) → evaluate
    - Input: X  vs. Threshold: Y → PASS or FAIL
  - [continue for all ACTIVE source-backed rules]
  
STEP 3: Identify unresolved/draft rules that apply but cannot be evaluated
  - OEM_COOL_FLOW_MIN (status=DRAFT, applies to material family) → UNRESOLVED
  - UNRESOLV_TIP_WEAR_LIMIT_PCT (status=DRAFT, applies) → UNRESOLVED
  - UNRESOLV_AWS_CURRENT_DENSITY_RANGE (status=DRAFT, applies) → UNRESOLVED
  - [all DRAFT/UNRESOLVED rules that match applicability]
  
STEP 4: Aggregate result and gating conditions
  - PASS: all evaluated source-backed rules passed
  - FAIL: any evaluated source-backed rule failed
  - UNRESOLVED: [list of unresolved rules]
  - DATA_INSUFFICIENT: [required SOURCE_BACKED rules with missing required input]
  - NOT_EVALUATED: no applicable validated engineering rule exists
  - CONFLICT: [unresolved conflicts among required applicable rules]
  - MANUAL_REVIEW: [conditions explicitly requiring human engineering judgment]
  
STEP 5: Decision
  IF (any FAIL exists):
    → Machine NOT_READY; report failing rule(s)
  ELIF (any required applicable UNRESOLVED rule or unresolved conflict exists):
    → Machine ENGINEERING_REVIEW_REQUIRED; report blockers + resolution path
  ELIF (any required input is DATA_INSUFFICIENT or manual-review condition exists):
    → Machine MANUAL_REVIEW_REQUIRED; report missing required inputs/review conditions
  ELIF (no applicable validated engineering rule exists):
    → Machine NOT_EVALUATED; automatic READY is blocked
  ELIF (at least one applicable validated engineering rule exists AND all required
        applicable SOURCE_BACKED rules PASS AND all required inputs are available
        AND no required applicable UNRESOLVED rule, unresolved conflict, or
        manual-review condition exists):
    → Machine READY
  ELSE:
    → Machine MANUAL_REVIEW_REQUIRED; automatic READY is blocked
```

**MRC Output Example — Schematic Only; No Engineering Values**:
```
Machine Readiness: ENGINEERING_REVIEW_REQUIRED

Evaluated Rules (ACTIVE + SOURCE_BACKED):
  None in the current example registry; SOURCE_BACKED count is 0.

Unresolved Requirements (DRAFT + UNRESOLVED):
  ⚠ UNRESOLVED: OEM_COOL_FLOW_MIN (requires authoritative source documentation)
  ⚠ UNRESOLVED: UNRESOLV_TIP_WEAR_LIMIT_PCT (requires approved production validation)
  ⚠ UNRESOLVED: UNRESOLV_AWS_CURRENT_DENSITY_RANGE (requires project approval)

Resolution Path:
  1. Obtain and review qualifying evidence for each required applicable rule.
  2. Promote a rule only through the registry evidence/lifecycle process.
  3. Re-evaluate with complete, valid required inputs after promotion.

Machine Status: DO NOT PROCEED. UNRESOLVED is not PASS or conditional PASS and blocks automatic READY.
```

### 7.5 MRC State Distinction and Data Insufficient Handling

**MRC Result States** (precise definitions):

| State | Meaning | Action | Example |
|-------|---------|--------|---------|
| **READY** | At least one applicable validated engineering rule exists; all required applicable SOURCE_BACKED rules PASS; all required inputs are available; and no required applicable UNRESOLVED rule, unresolved conflict, or manual-review condition exists | Proceed with production setup | All readiness prerequisites are affirmatively satisfied |
| **NOT_READY** | At least one required applicable SOURCE_BACKED rule FAILS | STOP; correct the failed condition and re-evaluate | Cooling temperature exceeds a validated maximum |
| **ENGINEERING_REVIEW_REQUIRED** | A required applicable UNRESOLVED rule or unresolved engineering conflict exists | STOP; engineering must resolve and document the blocker | Tip-wear threshold is unresolved |
| **MANUAL_REVIEW_REQUIRED** | Required input is DATA_INSUFFICIENT or another explicit manual-review condition exists | STOP; obtain required data or complete documented review | Cooling-flow measurement is unavailable |
| **NOT_EVALUATED** | No applicable validated engineering rule exists | STOP; automatic READY is unavailable until applicable rules are validated | No ACTIVE SOURCE_BACKED rule matches the context |

**DATA_INSUFFICIENT Handling** (important distinction):

DATA_INSUFFICIENT is NOT a final MRC state; it is an **input data condition** during rule evaluation. Any missing input required by an applicable SOURCE_BACKED rule blocks automatic READY and produces `MANUAL_REVIEW_REQUIRED`.

```
if required_input_data_missing:
    return "DATA_INSUFFICIENT"  # aggregate result → MANUAL_REVIEW_REQUIRED

if optional_input_data_missing:
    return "SKIPPED_OPTIONAL"  # audited; never satisfies a READY prerequisite
```

**Treatment of UNRESOLVED Rules in MRC**:

- UNRESOLVED rules (status=DRAFT, evidence_class=UNRESOLVED) are **NOT evaluated** during normal MRC flow
- They **ARE listed** in the MRC report as "Unresolved Requirements"
- They **BLOCK automatic READY** decision
- Human acknowledgement does not convert an UNRESOLVED rule to PASS and does not permit automatic READY
- UNRESOLVED rules do **NOT count as PASS** and do **NOT count as conditional PASS**; they require `ENGINEERING_REVIEW_REQUIRED`

**Distinction: PROPOSED vs. UNRESOLVED**

- **PROPOSED** (evidence_class) — recommended but not yet production-validated; numeric threshold exists but lacks ≥500 weld validation
- **UNRESOLVED** (evidence_class) — threshold undefined or lacks any authoritative source; no numeric value known

Both PROPOSED and UNRESOLVED rules:
- Have status=DRAFT (not ACTIVE)
- Are NOT used for automatic pass/fail
- PROPOSED escalates to MANUAL_REVIEW_REQUIRED; UNRESOLVED escalates to ENGINEERING_REVIEW_REQUIRED
- Block automatic READY decision

---

### 7.6 MRC Unresolved Engineering Threshold Inventory

This section explicitly inventories unresolved engineering thresholds and parameters that MRC must evaluate but currently lack SOURCE_BACKED definitions. These are required dependencies for MRC implementation.

**Critical**: Each unresolved threshold blocks automatic READY decision until resolved.

| ID | Category | Parameter | Issue | Resolution Path | Priority |
|----|-----------| --------|-------|-----------------|----------|
| U-001 | COOLING | cooling_flow_lpm | Numeric threshold 6.0 L/dk lacks authoritative source; exists in code but not documented | Submit authoritative cooling system specification (company checklist, OEM doc, field study) | HIGH |
| U-002 | COOLING | cooling_temp_c | Numeric threshold 25°C lacks authoritative source | Submit cooling circuit temperature limit documentation | HIGH |
| U-003 | COOLING | cooling_water_conductivity_us_cm | No standard threshold known; facility-specific | Customer to establish baseline and acceptable range; document approval | MEDIUM |
| U-004 | ELECTRODE | tip_wear_percent | Preliminary observation (15%) lacks ≥500 weld production validation | Customer field study: ≥500 welds, correlation analysis, statistical validation | HIGH |
| U-005 | MACHINE | dc_current_required | Boolean requirement lacks explicit source documentation | Clarify if OEM requirement or company standard; document source | MEDIUM |
| U-006 | ELECTRODE | tip_diameter_mm | Numeric range 5.0 mm lacks authoritative source | Submit OEM electrode specification or validation data | MEDIUM |
| U-007 | PARAMETER | current_density_kA_per_mm2 | AWS range (180–360) not verified against project equipment or customer data | If adopting AWS: import standard, validate against field data (≥30 welds), obtain customer approval | LOW |
| U-008 | MACHINE | machine_maintenance_interval_hours | No threshold defined for maintenance-based readiness | Define based on machine OEM recommendations; customer operational policy | MEDIUM |
| U-009 | ELECTRODE | electrode_life_welds_count | No standard count before electrode replacement | OEM specification + field study validation | MEDIUM |
| U-010 | COOLING | water_supply_pressure_bar | No min/max range defined | OEM cooling circuit specification | MEDIUM |
| U-011 | MACHINE | gun_cable_integrity_check | Qualitative requirement; no numeric threshold | Define inspection criteria; acceptance/rejection standard | LOW |
| U-012 | COOLING | coolant_pH_level | No range defined for water chemistry | Cooling circuit design specification + field validation | LOW |
| U-013 | ELECTRODE | tip_geometry_verification_method | No standard measurement procedure defined | Define measurement method, acceptance criteria, tolerance | MEDIUM |
| U-014 | MACHINE | transformer_secondary_resistance_ohms | No range or test method defined | Electrical system specification + OEM maintenance manual | MEDIUM |
| U-015 | MACHINE | air_gap_tolerance_mm | No tolerance defined for electrode-to-work distance | OEM gun design specification; measurement procedure | MEDIUM |
| U-016 | MATERIAL | stack_alignment_tolerance_mm | No tolerance defined for sheet-stack perpendicularity | Fixture design specification + process validation | LOW |

**Summary**:
- **Total Unresolved**: 16 engineering thresholds
- **HIGH Priority** (blocks MRC): 3 (cooling flow, cooling temp, tip wear)
- **MEDIUM Priority** (needed for complete MRC): 9
- **LOW Priority** (nice-to-have for MRC): 4

**Action Required Before MRC Implementation**:
1. For each HIGH priority item: obtain authoritative source documentation or field validation data
2. For each MEDIUM priority item: confirm customer requirements and OEM specifications
3. For each LOW priority item: decide whether to include in MRC or defer to operational procedures
4. Update registry with SOURCE_BACKED rules as evidence is obtained
5. Update MRC decision logic to reference this inventory

**Schematic Promotion Workflow for U-001 — No Value or Evidence Is Asserted**:
```
CURRENT STATE (U-001):
  rule_id: OEM_COOL_FLOW_MIN
  evidence_class: UNRESOLVED
  status: DRAFT
  min_value: null
  safe_default: UNRESOLVED
  missing_handling: DATA_INSUFFICIENT

ACTION: Customer submits a controlled source that states a threshold, exact applicability, revision, and document location; authorized engineering review verifies it.

NEW STATE:
  rule_id: OEM_COOL_FLOW_MIN
  evidence_class: SOURCE_BACKED
  status: ACTIVE
  min_value: <verified value from controlled source>
  max_value: null
  source_document: <controlled document ID + revision + exact section/page/table>
  effective_date: <approved effective date>
  safe_default: MANUAL_REVIEW  # Missing required flow data → DATA_INSUFFICIENT → MANUAL_REVIEW_REQUIRED
  
MRC IMPACT: OEM_COOL_FLOW_MIN is now evaluable and may cease to be an UNRESOLVED blocker; READY still requires every prerequisite in Section 7.4.
```

---

## 8. Digital Weld Passport (DWP) Integration Boundary

The authoritative DWP subsystem design is [docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md](113_DIGITAL_WELD_PASSPORT_DESIGN.md). This section defines the Registry-to-DWP boundary only. Document 111 owns rules and evaluations; document 113 owns the passport lifecycle, immutable revisions, references/snapshots, workflow, and reporting boundary.

### 8.1 DWP Purpose
Records weld-point-specific compliance evidence; enables traceability from parameter to rule to engineering source.

### 8.2 DWP References Shared Registry Evaluations
DWP references immutable Registry evaluation results and their exact rule/evidence versions. It does not duplicate applicability, threshold, conflict, or evaluation logic. The same Registry serves MRC (Section 7.2) and DWP, while each subsystem retains its own authoritative responsibilities.

### 8.3 Registry Evaluation References Required by DWP
The Registry evaluates applicability using category, lifecycle/evidence state, material family, stack context, and other versioned applicability dimensions. DWP records references for:
- applicable ACTIVE + SOURCE_BACKED evaluations;
- applicable DRAFT/UNRESOLVED requirements and their review state;
- NOT_EVALUATED results where no applicable validated rule exists;
- conflicts, evidence references, and exact applicability snapshots.

DWP does not run an independent category/status filter and cannot omit an unresolved applicable requirement merely because it is not ACTIVE.

### 8.4 DWP Example Entry — Schematic Only; No Engineering Values
```
Weld Point ID: <weld-point-id>
Context Snapshot: <material/stack/machine/process snapshot reference>

Rule Unresolved: OEM_COOL_FLOW_MIN (revision 0.1-unresolved)
  - Status: ENGINEERING_REVIEW_REQUIRED
  - Compliance: NOT EVALUATED; do not report PASS
  - Resolution: Supply controlled source evidence and complete engineering review

Rule Unresolved: ISO_NUGGET_MIN_4SQRT_T (revision 0.1-unresolved)
  - Claimed formula: d_min = 4√t (not verified by repository-authoritative evidence)
  - Status: ENGINEERING_REVIEW_REQUIRED
  - Compliance: NOT EVALUATED; do not report PASS
  - Resolution: Supply controlled ISO source evidence and complete engineering applicability review

Rule Unresolved: UNRESOLV_COOL_WATER_QUALITY
  - Reason: No engineering threshold defined for this facility
  - Rule State: UNRESOLVED
  - Review State: ENGINEERING_REVIEW_REQUIRED
  - Evaluation: NOT_EVALUATED because no validated threshold exists
  - Note: Customer to define acceptable range
```

---

## 9. Unresolved Engineering Thresholds — Representation

### 9.1 Structural Representation

**In Registry Entry**:
```yaml
rule_id: UNRESOLV_COOL_WATER_QUALITY
evidence_class: UNRESOLVED
min_value: null
max_value: null
unit: µS/cm
status: DRAFT
safe_default: UNRESOLVED
description: Customer-specific calibration required
```

**In Evaluation Result**:
```json
{
  "rule_id": "UNRESOLV_COOL_WATER_QUALITY",
  "status": "UNRESOLVED",
  "message": "Engineering threshold not yet defined",
  "reason": "No source document specifies acceptable conductivity range for this machine type",
  "recommended_action": "Collect baseline data; engage engineering to establish threshold",
  "resolution_path": "Submit customer-specific water quality study to update rule"
}
```

### 9.2 How MRC/DWP Handle Unresolved Rules — CRITICAL BEHAVIOR

**MRC Treatment of UNRESOLVED Rules** (machine readiness decision):

| Scenario | MRC Decision | Reason | Machine Status |
|----------|--------------|--------|-----------------|
| Rule is UNRESOLVED and applies to material family | STOP; block automatic READY | Unresolved rule = missing engineering validation | ENGINEERING_REVIEW_REQUIRED |
| Input data missing for a required applicable rule | STOP; block automatic READY | Required evidence cannot be evaluated | MANUAL_REVIEW_REQUIRED (DATA_INSUFFICIENT) |
| All SOURCE_BACKED rules PASS + unresolved rules apply | STOP; block automatic READY | UNRESOLVED is neither PASS nor conditional PASS | ENGINEERING_REVIEW_REQUIRED |
| Human acknowledges an unresolved requirement | Record acknowledgement; automatic READY remains blocked | Acknowledgement is not engineering validation | ENGINEERING_REVIEW_REQUIRED |
| At least one validated rule applies + all required SOURCE_BACKED rules PASS + all other READY prerequisites hold | PROCEED | Every READY prerequisite is affirmatively satisfied | READY |
| No applicable validated engineering rule exists | STOP; do not infer compliance from absence | No validated basis for readiness | NOT_EVALUATED |

**Detailed MRC Logic** (pseudo-code):
```
def evaluate_mrc_readiness(machine, material_family):
    source_backed_rules = filter_active_source_backed_rules(material_family)
    unresolved_rules = filter_draft_unresolved_rules(material_family)
    
    # Evaluate all source-backed rules
    failures = []
    missing_required_inputs = []
    for rule in source_backed_rules:
        if rule.required_input_missing(machine):
            missing_required_inputs.append(rule.rule_id)
            continue
        if rule.evaluate(machine) == FAIL:
            failures.append(rule)
    
    # Check for failures
    if failures:
        return NOT_READY, reason="Failed rules: " + failures
    
    # Check for unresolved rules that apply
    if unresolved_rules:
        return ENGINEERING_REVIEW_REQUIRED, reason=[
            "All source-backed rules passed.",
            "Unresolved thresholds apply to this configuration:",
            [rule.rule_id for rule in unresolved_rules],
            "Resolution path: See registry for each unresolved rule."
        ]

    if unresolved_conflict_exists():
        return ENGINEERING_REVIEW_REQUIRED

    if missing_required_inputs or manual_review_condition_exists():
        return MANUAL_REVIEW_REQUIRED, reason={
            "data_insufficient": missing_required_inputs,
            "manual_review": manual_review_reasons(),
        }

    if not source_backed_rules:
        return NOT_EVALUATED, reason="No applicable validated engineering rule"

    # All READY prerequisites passed affirmatively
    return READY
```

**DWP Treatment of UNRESOLVED Rules** (weld-point documentation):

| Scenario | DWP Behavior |
|----------|--------------|
| Required applicable rule is UNRESOLVED | Preserve `UNRESOLVED` and `ENGINEERING_REVIEW_REQUIRED`; DWP record may exist, but compliance/production release remains blocked |
| Required input is missing | Preserve `DATA_INSUFFICIENT` and `MANUAL_REVIEW_REQUIRED` as a blocker or secondary blocker; never label compliance as passed |
| All SOURCE_BACKED evaluations PASS + required UNRESOLVED rule applies | Preserve passing evaluations and the unresolved blocker separately; overall engineering compliance remains `ENGINEERING_REVIEW_REQUIRED` |
| Qualifying evidence later promotes the rule | Registry creates/promotes a new rule version; reevaluation and a new immutable DWP revision reference the new result; historical DWP revisions remain unchanged |

**Key Difference**: 
- **MRC** (machine readiness): Unresolved rules **BLOCK** automatic READY and require engineering review
- **DWP** (weld passport): Unresolved and missing-data truth is preserved; the passport may exist, but required blockers prevent compliance/release, and later reevaluation creates a new immutable revision

---

## 10. Safe-Default & Fail-Closed Behavior

### 10.1 Principle: Never Auto-PASS Without Engineering Support

**Rule of Thumb**:
- Explicit SOURCE_BACKED rule + passing evaluation → PASS
- No rule OR PROPOSED rule OR UNRESOLVED state → NOT PASS (report reason)
- Conflicting rules → Apply an approved deterministic resolution only when it fully resolves the conflict; otherwise block automatic READY and escalate to engineering review

### 10.2 Safe-Default Field in Registry

Each rule has `safe_default` (enum):

| Value | Meaning | Example |
|-------|---------|---------|
| UNRESOLVED | Registry fallback for a rule whose engineering threshold/evidence is unresolved; never PASS | unresolved rule → ENGINEERING_REVIEW_REQUIRED |
| MANUAL_REVIEW | Missing required input produces DATA_INSUFFICIENT and escalates to human review | required observation absent → MANUAL_REVIEW_REQUIRED |

`safe_default` does not manufacture engineering truth. For every required applicable rule, missing input is always `DATA_INSUFFICIENT → MANUAL_REVIEW_REQUIRED`; it is never PASS, FAIL, REJECT-as-engineering-truth, or automatic READY.

### 10.3 Implementation Guarantee

```python
def evaluate_rule_safely(rule: Rule, input_data: dict) -> EvaluationResult:
    """
    GUARANTEE: Return PASS only when the rule is applicable, ACTIVE,
    SOURCE_BACKED, all required input is present and valid, and evaluation passes.
    """
    
    # Check 1: Preserve evidence truth before lifecycle filtering.
    if rule.evidence_class == 'UNRESOLVED':
        return EvaluationResult(status='ENGINEERING_REVIEW_REQUIRED',
                               reason='required applicable rule is unresolved')
    if rule.evidence_class == 'PROPOSED':
        return EvaluationResult(status='MANUAL_REVIEW_REQUIRED',
                               reason='proposed rule is not production-validated')

    # Check 2: Is a SOURCE_BACKED rule active and not superseded?
    if rule.status != 'ACTIVE':
        return EvaluationResult(status='NOT_EVALUATED',
                               reason='source-backed rule is not active')

    # Check 3: Does required input data exist?
    if rule.parameter not in input_data or input_data[rule.parameter] is None:
        return EvaluationResult(status='DATA_INSUFFICIENT',
                               reason='required input missing; automatic READY blocked')

    # Check 4: Unit validation
    if not validate_units(input_data[rule.parameter], rule.unit):
        return EvaluationResult(status='MANUAL_REVIEW_REQUIRED',
                               reason='UNIT_MISMATCH; automatic READY blocked')

    # Check 5: Evaluate only an applicable ACTIVE SOURCE_BACKED rule.
    return evaluate_logic(rule, input_data)
```

### 10.4 Consequences of Safe-Default Violation

If implementation violates safe-default:
- **Security Impact**: Unsafe weld production, compliance violations, liability
- **Audit Finding**: "Missing rule safety guarantee" → CRITICAL
- **Response**: Code review required before merge; must add unit test

---

## 11. Traceability & Audit Trail

### 11.1 Audit Entry Schema
Each rule evaluation must create an audit entry:

```
{
  timestamp: ISO8601
  rule_id: String
  rule_revision: String
  weld_point_id: String (if applicable)
  user_id: String (who triggered evaluation)
  input_values: { parameter: value, ... }
  evaluation_result: PASS | FAIL | UNRESOLVED | NOT_EVALUATED | DATA_INSUFFICIENT | ENGINEERING_REVIEW_REQUIRED | MANUAL_REVIEW_REQUIRED
  decision_rationale: String (why this result)
  conflicting_rules: [rule_id, ...] (if multiple rules applied)
  source_priority_applied: Integer (which source won)
  conversion_applied: Boolean (if unit conversion occurred)
  data_quality_flags: [flag, ...]
}
```

### 11.2 Traceability Chain — Schematic Only

```
Weld Point <weld-point-id>
  └─ Evaluation Result <evaluation-id + timestamp>
      └─ Rule <rule-id + exact revision/content hash>
          ├─ Source: <controlled source ID + revision + location>
          ├─ Evidence Class: <pinned evidence class>
          ├─ Applicability Snapshot: <context hash>
          ├─ Conflict Policy: <policy ID + version, if used>
          └─ Input: <measured value + supplied unit>
              └─ Measurement Equipment: <equipment ID + version>
                  └─ Calibration Reference: <certificate ID + revision>
```

### 11.3 Audit Queries
System must support:
1. "What rules applied to weld W-001?" → show all rules + results
2. "What changed between rule revision 1.0 and 1.1?" → diff view
3. "Which welds failed rule XYZ?" → query by rule_id + status
4. "Show conflict history for rule OEM_COOL_FLOW_MIN" → conflicting rules over time
5. "When did rule status change from DRAFT to ACTIVE?" → timeline view

---

## 12. API & Data Persistence

### 12.1 Registry Storage
- **System**: PostgreSQL (existing backend)
- **Table**: `engineering_rule_registry` (primary)
- **Indexes**: rule_id, status, effective_date, parameter, evidence_class
- **Constraints**: 
  - rule_id + status UNIQUE (only one ACTIVE per id)
  - created_at, updated_at auto-managed
  - effective_date must be ≤ created_at or <= now

### 12.2 Proposed API Endpoints
```
GET    /api/v1/rules/                        (list all rules, filtered)
GET    /api/v1/rules/{rule_id}               (get specific rule)
POST   /api/v1/rules/                        (create rule; draft status)
PATCH  /api/v1/rules/{rule_id}               (update rule; creates new revision)
GET    /api/v1/rules/{rule_id}/history       (show all revisions)
POST   /api/v1/rules/{rule_id}/activate      (transition DRAFT → ACTIVE)
POST   /api/v1/rules/{rule_id}/supersede     (mark SUPERSEDED)

POST   /api/v1/evaluate                      (evaluate inputs against rules)
GET    /api/v1/conflicts/                    (list rule conflicts)
GET    /api/v1/audit-trail/{weld_id}        (show evaluation audit for weld)
```

### 12.3 Example Evaluate Endpoint Request — Schematic Only
```json
POST /api/v1/evaluate

{
  "context": {
    "material_family": "<material-family>",
    "stack_count": "<stack-count>",
    "machine_type": "<machine-type>",
    "as_of_date": "<ISO-8601 timestamp>"
  },
  "inputs": {
    "<parameter>": {"value": "<measured-value>", "unit": "<supplied-unit>"}
  }
}
```

### 12.4 Example Evaluate Endpoint Response
```json
{
  "evaluation_id": "<evaluation-id>",
  "timestamp": "<ISO-8601 timestamp>",
  "context": { ... },
  "results": [
    {
      "rule_id": "<required-applicable-unresolved-rule-id>",
      "rule_revision": "<unresolved-revision>",
      "status": "UNRESOLVED",
      "reason": "no engineering threshold defined",
      "evidence_class": "UNRESOLVED"
    }
  ],
  "aggregate_status": "ENGINEERING_REVIEW_REQUIRED",
  "aggregate_reason": "required applicable rule is unresolved; automatic READY blocked"
}
```

---

## 13. Implementation Prerequisites & Blockers

### 13.1 Before Implementation

**MUST BE RESOLVED**:
1. ✓ Rule dataclass exists in [backend/app/domain/rules_engine.py](../backend/app/domain/rules_engine.py)
2. ✓ Priority hierarchy exists in SOURCE_PRIORITY
3. ✓ Basic rule evaluation logic exists (_evaluate_rule)
4. ❌ **BLOCKER**: No centralized rule registry table in database (currently rules are inline in code)
5. ❌ **BLOCKER**: No lifecycle state management (DRAFT, ACTIVE, SUPERSEDED, etc.)
6. ❌ **BLOCKER**: No audit trail schema
7. ❌ **BLOCKER**: No evidence_class taxonomy (SOURCE_BACKED, PROPOSED, UNRESOLVED)
8. ❌ **BLOCKER**: No safe_default field in Rule dataclass
9. ❌ **BLOCKER**: No version/revision tracking

### 13.2 Before MRC/DWP Implementation

**MUST BE RESOLVED**:
1. Engineering Rule Registry must be implemented and populated with SOURCE_BACKED rules
2. MRC design in [docs/112_MACHINE_READINESS_CHECK_DESIGN.md](112_MACHINE_READINESS_CHECK_DESIGN.md) must pass review and its required production dependencies must be implemented
3. DWP design in [docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md](113_DIGITAL_WELD_PASSPORT_DESIGN.md) must pass review and its required production dependencies must be implemented
4. Rule conflict handling logic must be tested with realistic conflict scenarios
5. Audit trail must be queryable and reproducible

### 13.3 Known Constraints
- Rules are in Turkish (Türkçe); internationalization deferred to v2.0+
- Machine type filter is optional; not all rules specify machine types yet
- Derived-formula operators exist in prototype code, but no formula claim is engineering-approved merely because it is hardcoded

---

## 14. Documentation & Source References

### 14.1 Key Source Documents (To Be Migrated)
- [27_OEM_RULES.md](27_OEM_RULES.md) — OEM-specific rules (currently a template)
- [28_ISO_RULES.md](28_ISO_RULES.md) — ISO standard rules (currently a template)
- [30_SEP_RULES.md](30_SEP_RULES.md) — SEP rules (currently a template)
- [103_RULE_ENGINE_DESIGN.md](103_RULE_ENGINE_DESIGN.md) — Basic rule engine (to be superseded)
- [11_RULE_AND_NORM_ENGINE.md](11_RULE_AND_NORM_ENGINE.md) — Priority hierarchy (to be absorbed)

### 14.2 Related Architecture Documents
- [28_ARCHITECTURE_DECISIONS_AND_BOUNDARIES.md](28_ARCHITECTURE_DECISIONS_AND_BOUNDARIES.md) — ADR-004 through ADR-010
- [01_SOFTWARE_REQUIREMENTS_SPECIFICATION.md](01_SOFTWARE_REQUIREMENTS_SPECIFICATION.md) — FR-006, FR-007
- [29_INDEPENDENT_REVIEW_AND_AI_WORKFLOW.md](29_INDEPENDENT_REVIEW_AND_AI_WORKFLOW.md) — Evidence hierarchy

### 14.3 Example Rule Sources (To Be Documented)
- Punta Kaynak CheckList REV01 (Company Standard)
- OEM Eğitim Tablosu (OEM Training Table)
- ISO 18278-2 controlled source or approved extract (required; not currently present in the repository)
- AWS C1.1M/C1.1:2008 (Recommended Practices)
- Internal wear study Q2 2024 (Field Model)

---

## 15. Recommended Next Steps

### Phase 1: Registry Initialization (Foundation)
1. **Database Schema**: Implement `engineering_rule_registry` table with all fields in Section 3.1
2. **Rule Dataclass Update**: Add evidence_class, status, revision, effective_date, safe_default fields to backend Rule
3. **Prototype Rule Intake**: Do not migrate existing DEFAULT_RULES as validated rules. If retained for traceability, import only as disabled/DRAFT UNRESOLVED candidates with engineering values null until qualifying evidence is reviewed.
4. **Audit Trail**: Implement audit_entry table and logging for all rule evaluations

### Phase 2: Registry API & Evaluation (Feature Complete)
5. **Registry Endpoints**: Implement CRUD API for rules (GET, POST, PATCH)
6. **Rule Evaluation Engine**: Implement evaluation logic per Section 10 (safe-default guarantees)
7. **Conflict Resolution**: Implement conflict detection + SOURCE_PRIORITY logic per Section 6.2
8. **Unit Handling**: Implement unit validation + conversion per Section 6.3

### Phase 3: MRC & DWP Integration (Subsystem Integration)
9. **Machine Readiness Check Design**: [docs/112_MACHINE_READINESS_CHECK_DESIGN.md](112_MACHINE_READINESS_CHECK_DESIGN.md)
10. **Digital Weld Passport Design**: [docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md](113_DIGITAL_WELD_PASSPORT_DESIGN.md)
11. **Integration Tests**: Test MRC and DWP consuming shared registry

### Phase 4: Production Readiness (Release Candidate)
12. **Engineering Rule Population**: Migrate OEM, ISO, AWS, SEP rules from template documents into registry
13. **Compliance Verification**: Audit against ADR-004 through ADR-010
14. **Production Testing**: Field validation with customer data
15. **Release**: Merge to main; tag v1.5 (per ROADMAP.md)

---

## 16. Design Verification Checklist

### Revision 1.0 Corrections Applied
- [x] Document renamed: 110 → 111 (resolved numbering collision with SDS master index)
- [x] All unsupported numeric rules downgraded from SOURCE_BACKED to UNRESOLVED
  - OEM_COOL_FLOW_MIN (6.0 L/dk) → UNRESOLVED (no authoritative source in project)
  - OEM_COOL_TEMP_MAX (25°C) → UNRESOLVED (no authoritative source in project)
  - OEM_TIP_07_09 (5.0 mm) → UNRESOLVED (no authoritative source in project)
  - AWS_CURRENT_DENSITY_RANGE (180–360 kA/mm²) → UNRESOLVED (external standard, not project-approved)
  - TIP_WEAR_LIMIT_PCT (15%) → UNRESOLVED (preliminary, not production-validated)
- [x] ISO_NUGGET_MIN_4SQRT_T downgraded to UNRESOLVED — engineering source required; repository contains no qualifying evidence for the formula, edition, or section
- [x] MRC unresolved-threshold safety principle restored
  - Machine READY only when all six prerequisites in Section 7.4 are affirmatively satisfied
  - UNRESOLVED rules now BLOCK automatic READY decision
  - MRC state: READY | NOT_READY | ENGINEERING_REVIEW_REQUIRED | MANUAL_REVIEW_REQUIRED | NOT_EVALUATED
- [x] MRC unresolved-rule inventory created (Section 7.6)
  - 16 total unresolved engineering thresholds documented
  - 3 HIGH priority (cooling flow, cooling temp, tip wear)
  - 9 MEDIUM priority (maintenance, electrode life, water pressure, etc.)
  - 4 LOW priority (gun cable, pH, tip geometry, etc.)
- [x] DATA_INSUFFICIENT handling specified (Section 7.5)
  - Distinguished from UNRESOLVED (input missing vs. threshold missing)
  - Distinct handling for each rule's missing_handling field
- [x] No fabricated engineering values
  - Every numeric threshold without source documentation marked UNRESOLVED
  - Evidence requirements documented for promotion to SOURCE_BACKED
- [x] Design-only scope maintained
  - No database implementation
  - No API implementation
  - No code or unit tests created
  - No commit or push

### Definition of Done: Engineering Rule Registry Design (REVISED)
- [x] Design document created at [docs/111_ENGINEERING_RULE_REGISTRY_DESIGN.md](111_ENGINEERING_RULE_REGISTRY_DESIGN.md)
- [x] Data model specified with evidence_class and safe_default fields (Section 3.1)
- [x] Evidence classification defined with SOURCE_BACKED, PROPOSED, UNRESOLVED (Section 3.2)
- [x] Example entries corrected:
  - Example 1: OEM_COOL_FLOW_MIN → UNRESOLVED (with evidence requirements)
  - Example 2: UNRESOLV_TIP_WEAR_LIMIT_PCT → UNRESOLVED (with validation path)
  - Example 3: UNRESOLV_COOL_WATER_QUALITY → UNRESOLVED (facility-specific)
  - Example 4: ISO_NUGGET_MIN_4SQRT_T → UNRESOLVED (repository-authoritative engineering source required)
  - Example 5: UNRESOLV_AWS_CURRENT_DENSITY_RANGE → UNRESOLVED (external standard)
- [x] Handling strategies documented (Section 6: missing, conflicting, unresolved, duplicate, superseded, unit mismatch)
- [x] Registry-to-MRC integration boundary outlined with fail-safe decision logic (Section 7); document 112 is authoritative for MRC
- [x] MRC unresolved inventory created with 16 items and resolution paths (Section 7.6)
- [x] Registry-to-DWP integration boundary outlined (Section 8); document 113 is authoritative for DWP
- [x] Safe-default behavior specified with implementation guarantee (Section 10.3)
- [x] Traceability & audit trail designed (Section 11)
- [x] Implementation blockers identified (Section 13.1)
- [x] MRC/DWP prerequisites documented (Section 13.2)
- [x] Next steps recommended (Section 15)
- [x] No authoritative source assumption — all unsupported values marked UNRESOLVED
- [x] Code-only rule values NOT treated as engineering evidence
- [x] No production code implementation

### Critical Requirements Satisfied
- [x] UNRESOLVED rules block automatic READY/PASS decisions
- [x] Fail-safe behavior guaranteed: no auto-PASS without SOURCE_BACKED evidence
- [x] MRC reports: READY | NOT_READY | ENGINEERING_REVIEW_REQUIRED | MANUAL_REVIEW_REQUIRED | NOT_EVALUATED (per Section 7.4)
- [x] DATA_INSUFFICIENT is input condition, not rule classification
- [x] Document numbering conflict resolved (110 → 111)
- [x] Design-only scope strictly maintained

---

## 17. Version History

| Version | Date | Author | Status | Summary |
|---------|------|--------|--------|---------|
| 1.0-draft | 2026-08-15 | Engineering Team | REVISED | Initial design (1.0); DESIGN ONLY — not approved |
| 1.0-revision | 2026-08-15 | Engineering Team | AWAITING REVIEW | Corrections applied per requirements: unsupported numeric rules downgraded to UNRESOLVED; MRC unresolved-threshold safety principle restored; 16-item MRC inventory added; DATA_INSUFFICIENT handling specified; document renamed to 111; implementation code removed |
| — | TBD | — | FUTURE | Implementation phase (separate phase) |

**Current Status**: DESIGN REVISION COMPLETE — AWAITING HUMAN REVIEW

**Not yet approved for implementation.**

---

## 18. Appendix: Turkish/English Term Mapping

| Turkish | English | Context |
|---------|---------|---------|
| OEM / Müşteri Normu | OEM / Customer Norm | source_type |
| Şirket İçi Standart | Company Standard | source_type |
| Doğrulanmış Saha Modeli | Validated Field Model | source_type |
| Deneysel Model | Experimental Model | source_type |
| Literatür | Literature | source_type |
| Genel Mühendislik Formülü | General Engineering Formula | source_type |
| Punta Kaynak | Spot Welding | domain term |
| Sac | Sheet | material term |
| Elektrot Uç | Electrode Tip | component |
| Çekirdek | Nugget | weld feature |
| Soğutma Debisi | Cooling Flow Rate | parameter |
| Soğutma Suyu Sıcaklığı | Cooling Water Temperature | parameter |
| DC Akım | DC Current | parameter |

---

**END OF DESIGN DOCUMENT**

---

### Summary for Design Verification

**Files Inspected During Design**:
1. [README.md](../README.md) — baseline v1.1 with 17 tests
2. [ROADMAP.md](../ROADMAP.md) — v1.2-v2.0 phases
3. [100_SDS_MASTER_INDEX.md](../100_SDS_MASTER_INDEX.md) — authoritative SDS-100 master index; the shorter `docs/` copy is non-authoritative
4. [28_ARCHITECTURE_DECISIONS_AND_BOUNDARIES.md](28_ARCHITECTURE_DECISIONS_AND_BOUNDARIES.md) — ADRs 001-010
5. [103_RULE_ENGINE_DESIGN.md](103_RULE_ENGINE_DESIGN.md) — basic rule provider outline
6. [11_RULE_AND_NORM_ENGINE.md](11_RULE_AND_NORM_ENGINE.md) — priority hierarchy
7. [104_MODEL_REGISTRY.md](104_MODEL_REGISTRY.md) — model registry (not rules)
8. [29_INDEPENDENT_REVIEW_AND_AI_WORKFLOW.md](29_INDEPENDENT_REVIEW_AND_AI_WORKFLOW.md) — evidence hierarchy
9. [01_SOFTWARE_REQUIREMENTS_SPECIFICATION.md](01_SOFTWARE_REQUIREMENTS_SPECIFICATION.md) — FR-006, FR-007
10. [backend/app/domain/rules_engine.py](../backend/app/domain/rules_engine.py) — working Rule implementation

**Main Design Components**:
1. Rule record structure with lifecycle management
2. Evidence classification (SOURCE_BACKED, PROPOSED, UNRESOLVED)
3. Safe-default behavior guarantees
4. Conflict resolution strategy
5. MRC/DWP shared-registry architecture
6. Audit trail and traceability
7. Handling of missing, conflicting, unresolved rules
8. 5 example registry entries, all currently UNRESOLVED pending qualifying evidence

**SOURCE_BACKED Items** (engineering-verified): **0**

**PROPOSED Items** (not yet production-validated): **0**

**UNRESOLVED Example Items**: **5**
- Cooling flow minimum
- Electrode tip wear limit
- Cooling water conductivity threshold
- ISO nugget minimum formula claim
- AWS current density range

The separate MRC unresolved engineering threshold inventory in Section 7.6 remains exactly 16 items.

**MRC/DWP Shared Architecture**: Document 111 owns Registry rules, evidence, and evaluations. MRC consumes them under document 112 and owns readiness orchestration/final state. DWP preserves exact immutable Registry-evaluation and MRC references under document 113 and owns passport lifecycle, revisions, workflow, and reporting.

**Blockers Before Implementation**:
1. Database schema for persistent registry
2. Lifecycle state management in Rule dataclass
3. Audit trail schema and logging
4. Evidence_class and safe_default fields
5. Version/revision tracking

**Recommended Next Step**: Design Machine Readiness Check subsystem in separate document.
