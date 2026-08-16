# 112 — Machine Readiness Check Design

**Document ID:** SDS-112  
**Status:** Design only — architecture-ready subject to blockers in Section 20  
**Authoritative parent:** [Engineering Rule Registry Design](111_ENGINEERING_RULE_REGISTRY_DESIGN.md)  
**Scope:** Machine and process-equipment readiness evaluation; no production implementation

## 1. Purpose and safety boundary

The Machine Readiness Check (MRC) determines whether a welding machine and its relevant process equipment are sufficiently verified for a stated welding operation. It is a deterministic, traceable engineering assessment, not merely a checklist UI.

MRC consumes machine configuration, process context, observations and measurements, rule evidence, rule versions, check requirements, conflicts, and human-review records. It produces one deterministic engineering state plus a complete explanation.

The subsystem is fail-safe:

- absence of a rule, evidence, context, or required measurement never becomes `PASS` or `READY`;
- implementation constants are not engineering evidence;
- `UNRESOLVED` is neither `PASS` nor conditional pass;
- a workflow approval does not rewrite deterministic engineering truth;
- thresholds owned by the Engineering Rule Registry are never hard-coded in MRC.

## 2. Repository baseline and discovered context

### 2.1 Governing design and architecture

- `100_SDS_MASTER_INDEX.md` is the authoritative SDS master index.
- Document 111 owns rule identity, evidence classification, lifecycle, versioning, rule applicability, source provenance, conflict handling, unit policy, and the 16-item MRC unresolved inventory.
- ADR-002 keeps domain logic independent of FastAPI, SQLAlchemy, environment variables, and deployment concerns.
- ADR-004 requires provider-based rules registered in one rule registry.
- ADR-005 requires versioned, reproducible engineering assets.
- ADR-009 forbids presenting a rule as normative without source, revision, applicability, and validation state.
- ADR-010 forbids silent extrapolation.
- FR-006 defines the existing source-priority hierarchy; FR-007 prevents automatic production approval of unvalidated or low-confidence results.

### 2.2 Existing implementation context

No dedicated MRC model, application service, endpoint, frontend workflow, or test exists.

Related components discovered:

- `backend/app/domain/rules_engine.py`: generic rules, applicability, evaluation, and conflict detection. Its constants are prototypes only and are not MRC evidence. Its automatic priority winner is insufficient when a conflict remains unresolved.
- engineering/analysis schemas: current, force, weld time, tip diameter, material/stack, cooling flow and temperature, and DC-current inputs.
- `Project`, `WeldPoint`, `WeldPointRevision`, `Approval`, `TestResult`, `User`, and `AuditLog`: useful identity, snapshot, approval, test, authentication, and audit concepts; none is an MRC persistence model.
- versioned `/api/v1` FastAPI conventions, JWT authentication, structured authorization dependencies, and OpenAPI generation.
- roles: System Admin, Process Engineer, Quality Engineer, Manufacturing Engineer, Maintenance, Operator, Read Only, and Customer.
- existing permissions are coarse (`project:*`, `weld:*`, `approval:*`, `test:*`); dedicated MRC permissions do not yet exist.

### 2.3 Domain coverage found

Repository evidence supports cooling, machine, electrode, equipment, material/stack, current, force, gun, station, robot, schedule parameters, and maintenance concepts. The 16-item baseline additionally includes water chemistry and pressure, electrode life and geometry, cable integrity, transformer resistance, air-gap tolerance, and stack alignment.

The requested concepts were inspected as follows:

| Concept | Repository finding | Design treatment |
|---|---|---|
| Cooling water / flow | Present in schemas, code, documents, and U-001/U-002/U-003/U-010/U-012 | Included; all inventory thresholds remain unresolved |
| Compressed air / air pressure | No authoritative MRC inventory item or engineering rule found | Not added to the 16; proposed future check definition only, with all engineering fields TBD |
| Actual electrode force | Input concept exists; no item in the 16-item MRC inventory | Proposed future check only; no threshold |
| Actual welding current | Current input and DC-current concepts exist; U-005 covers DC-current requirement | U-005 included; numeric actual-current readiness check remains proposed/TBD |
| Electrode alignment | U-015 and U-016 address related air-gap/stack alignment; no validated acceptance threshold | Included only as the inventory defines it |
| Dressing / tip condition | Dressing and tip wear appear in engineering context; U-004/U-006/U-009/U-013 apply | Included; no threshold invented |

## 3. Relationship to the Engineering Rule Registry

MRC does not own a second rule system.

```text
MRC Check Definition
  → Engineering Rule ID
    → immutable Rule Version
      → Evidence Reference(s)
        → Observation(s) and unit conversion trace
          → Check Evaluation
            → deterministic MRC Result
              → append-only Audit Trail
```

| Information | Owner |
|---|---|
| Check purpose, required/optional designation, observation type, execution order, review trigger | MRC check definition |
| Threshold/operator/formula, evidence class, applicability, source, revision, lifecycle, canonical unit | Engineering Rule Registry |
| Actual value, supplied unit, method/device, observed time, observer, machine/configuration identity | Machine/process observation |
| Resolved rule version, normalized value, comparison outcome, reason codes, per-check state | Check evaluation result |
| Deterministic aggregate state and complete blocker list | Readiness decision |
| Actor, action, before/after references, timestamps, correlation and software version | Audit event |

An assessment pins exact check-definition and rule versions before evaluation. Registry changes create new versions; they do not mutate a completed assessment.

## 4. MRC state model and invariants

### 4.1 Final states

| State | Meaning |
|---|---|
| `READY` | Every READY prerequisite in Section 4.2 is affirmatively satisfied |
| `NOT_READY` | At least one required applicable `SOURCE_BACKED` rule evaluated `FAIL` |
| `ENGINEERING_REVIEW_REQUIRED` | A required applicable rule is `UNRESOLVED`, required evidence is unavailable/unverifiable, or an engineering-rule conflict remains unresolved |
| `MANUAL_REVIEW_REQUIRED` | Required data is insufficient/invalid/stale, a required observation is absent, or an explicit human judgment/system-recovery condition exists |
| `NOT_EVALUATED` | No applicable validated engineering rule exists and no higher-precedence blocker determines the state |

`DATA_INSUFFICIENT` is an evaluation condition, not a final MRC state. It aggregates to `MANUAL_REVIEW_REQUIRED`.

### 4.2 Exact READY prerequisites

`READY` is permitted only when all six conditions are true:

1. At least one applicable validated engineering rule exists.
2. Every required applicable `SOURCE_BACKED` rule passes.
3. All required input data is available and valid.
4. No required applicable `UNRESOLVED` rule exists.
5. No unresolved conflict exists.
6. No manual-review condition exists.

### 4.3 Mandatory invariants

- `UNRESOLVED != PASS`.
- `UNRESOLVED != CONDITIONAL PASS`.
- `UNRESOLVED` blocks automatic `READY`.
- `DATA_INSUFFICIENT` blocks automatic `READY`.
- No applicable validated rule blocks automatic `READY`.
- `NOT_EVALUATED` never maps to `READY`.
- Human disposition never changes a check evaluation from `FAIL` or `UNRESOLVED` to `PASS`.

### 4.4 Deterministic aggregation precedence

All check conditions and secondary blockers are retained even when a higher-precedence final state wins.

1. `NOT_READY` — any required applicable `SOURCE_BACKED` `FAIL` is direct validated evidence of non-readiness.
2. `ENGINEERING_REVIEW_REQUIRED` — otherwise, any required applicable `UNRESOLVED` rule, unavailable required rule evidence, or unresolved engineering conflict requires engineering resolution.
3. `MANUAL_REVIEW_REQUIRED` — otherwise, any `DATA_INSUFFICIENT`, invalid/stale input, absent required observation, explicit manual judgment, or recoverable evaluation/integrity exception requires controlled review.
4. `NOT_EVALUATED` — otherwise, zero applicable validated engineering rules means there is no validated basis for readiness.
5. `READY` — otherwise, and only after all six prerequisites pass.

This order distinguishes a validated failure from uncertainty while never hiding secondary uncertainty. A persistence or audit-write failure prevents finalization/publication; the attempted result remains non-authoritative and cannot be reported as `READY`.

## 5. Baseline 16-item unresolved inventory mapping

This table maps exactly the 16 items in document 111. `TBD` means the repository provides insufficient information. Every row is `UNRESOLVED`; none is eligible for automatic evaluation or READY support.

Common audit minimum for every row: assessment/check IDs, rule ID/version if present, evidence status, applicability inputs, observation/value/unit/method/time/actor, evaluation condition, action/review identity, timestamps, and software/check-definition versions.

| check_id | Check name / engineering purpose | Required inputs and units | Status | Applicability | Missing-data behavior | Unresolved behavior / output | Operator or engineer action | Additional audit requirement |
|---|---|---|---|---|---|---|---|---|
| U-001 | Cooling flow; verify adequate electrode cooling | flow (`L/dk` as inventory notation); measurement method TBD | UNRESOLVED | Cooling circuit; machine/OEM context TBD | `DATA_INSUFFICIENT` → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain controlled cooling-system specification or approved field study | device/circuit and source revision |
| U-002 | Cooling-water temperature; verify thermal condition | temperature (`°C`); location/method TBD | UNRESOLVED | Cooling circuit; machine/OEM context TBD | `DATA_INSUFFICIENT` → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain controlled temperature-limit documentation | sensor/location and source revision |
| U-003 | Water conductivity; assess facility/circuit water quality | conductivity (`µS/cm` inferred from parameter name; confirm unit) | UNRESOLVED | Facility and cooling-circuit materials TBD | `DATA_INSUFFICIENT` → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Establish approved baseline/range through customer study | sampling method, instrument, facility |
| U-004 | Electrode tip wear; control degradation | wear (`%`); measurement method TBD | UNRESOLVED | Electrode/gun/material/process context TBD | absent measurement → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Perform production validation and approve criterion | weld count, dressing history, study ID |
| U-005 | DC-current requirement; verify machine-current type requirement | DC-current flag (`bool`); configuration source TBD | UNRESOLVED | Machine/OEM/customer context TBD | missing configuration → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Clarify and document authoritative requirement | machine configuration revision |
| U-006 | Electrode tip diameter; verify geometry suitability | diameter (`mm`); thickness/material inputs; method TBD | UNRESOLVED | Electrode, material family, thickness/stack TBD | missing diameter/context → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain OEM specification or validation data | electrode identity and measurement method |
| U-007 | Current density; assess parameter/electrode loading | current density (`kA/mm²` per inventory); derivation inputs TBD | UNRESOLVED | Machine/process/electrode applicability TBD | missing inputs → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain controlled standard, validate applicability, approve use | derivation and source/evidence trace |
| U-008 | Maintenance interval; verify maintenance currency | operating hours (`h`); maintenance record | UNRESOLVED | Machine model/OEM/operating policy TBD | missing hours/history → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Define from OEM recommendation and approved policy | meter reading and maintenance record IDs |
| U-009 | Electrode life; verify replacement/dressing lifecycle | weld count (`count`); electrode and dressing history | UNRESOLVED | Electrode, material, schedule, cooling context TBD | missing lifecycle data → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain OEM specification plus field validation | counter source, resets, dressing events |
| U-010 | Water-supply pressure; verify cooling supply condition | pressure (`bar` per inventory); measurement location TBD | UNRESOLVED | Cooling circuit/machine configuration TBD | `DATA_INSUFFICIENT` → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain OEM cooling-circuit specification | sensor/location and calibration |
| U-011 | Gun-cable integrity; detect unsafe/degraded connection | qualitative observation; units N/A; procedure TBD | UNRESOLVED | Weld gun/cable configuration | absent observation → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Define inspection method and acceptance criteria | checklist revision, observer, evidence attachment |
| U-012 | Coolant pH; assess water chemistry compatibility | pH (dimensionless); sampling method TBD | UNRESOLVED | Facility/circuit materials/coolant TBD | absent sample → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain circuit specification and validation | sample point, instrument/calibration |
| U-013 | Tip-geometry verification; ensure repeatable profile measurement | geometry observations; units/method TBD | UNRESOLVED | Electrode type, cap/profile, dresser TBD | absent observation → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Define measurement method, tolerances, acceptance criteria | instrument/profile/dresser identities |
| U-014 | Transformer secondary resistance; assess electrical condition | resistance (`Ω` from parameter); test method TBD | UNRESOLVED | Transformer/machine configuration TBD | missing measurement → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain electrical/OEM maintenance specification | test conditions, instrument/calibration |
| U-015 | Air-gap tolerance; verify electrode-to-work geometry | gap (`mm`); measurement method TBD | UNRESOLVED | Gun, fixture, electrode, stack context TBD | absent measurement/context → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain gun specification and approved procedure | gun/fixture/configuration snapshots |
| U-016 | Sheet-stack alignment; verify fixture/stack positioning | alignment (`mm`); datum and method TBD | UNRESOLVED | Material stack, fixture, operation context TBD | absent measurement/context → `MANUAL_REVIEW_REQUIRED` | `ENGINEERING_REVIEW_REQUIRED` | Obtain fixture specification and process validation | stack revision, fixture/datum, method |

Inventory counts relevant to MRC: `SOURCE_BACKED = 0`, `PROPOSED = 0`, `UNRESOLVED = 16`.

## 6. Conceptual data model

No SQL, ORM, or migration is defined here.

| Entity | Responsibility and key fields | Relationships | Mutability and lifecycle |
|---|---|---|---|
| `MachineReadinessAssessment` | `assessment_id`, machine/gun/station/process/material/stack/schedule/configuration snapshot IDs, status, correlation ID, requested/evaluated times, software version | owns check results, observations, decision, reviews, audit events | Draft while collecting; sealed on evaluation; reevaluation creates a new revision/assessment |
| `MachineReadinessCheckDefinition` | stable `check_id`, version, domain, purpose, required flag, observation specification, rule-selection contract, applicability fields, review triggers | references registry rule selector; instantiated into results | Versioned immutable once published; lifecycle DRAFT/ACTIVE/SUPERSEDED/RETIRED |
| `MachineObservation` | observation ID, parameter, raw value, supplied unit, canonical value/unit, conversion ID, method/device/calibration, observed time, observer, quality/staleness state | belongs to assessment; consumed by results | Append/correct by superseding; evaluated values are immutable snapshots |
| `EngineeringRuleReference` | rule ID, exact version, lifecycle/evidence class, applicability resolution, content hash | points to authoritative registry record | Immutable assessment snapshot/reference |
| `EvidenceReference` | evidence ID, document/revision/location/hash, availability and verification state | tied to rule reference and evaluation | Immutable reference; later evidence change creates new version |
| `MachineReadinessCheckResult` | result ID, check/version, rule/version, inputs, conversions, state/condition, actual/expected representation, reason codes, conflict refs | belongs to assessment and feeds decision | Immutable after evaluation; corrected inputs require reevaluation |
| `ManualReview` | review ID/type, trigger/reason, reviewer, role, comments, disposition, timestamp, attachments | references assessment/check result; does not replace it | Append-only dispositions; withdrawal/supersession retained |
| `ReadinessDecision` | decision ID, deterministic state, prerequisite truth values, precedence winner, all blockers, evaluated time | one finalized decision per assessment revision | Immutable and reproducible |
| `AuditEvent` | event ID, actor, action, entity/version, timestamp, correlation, before/after refs, detail hash | spans all MRC entities | Append-only; audit failure blocks finalization |

Identifiers must be stable and globally unique. Completed assessment payloads must preserve exact contextual snapshots rather than relying only on mutable current records.

## 7. Deterministic evaluation pipeline

```text
Create assessment request
  → authenticate/authorize and validate machine/process identity
  → snapshot machine, gun, material, stack, schedule, customer/OEM context
  → resolve applicable versioned check definitions
  → query the Engineering Rule Registry and pin exact rule/evidence versions
  → validate required observations, freshness, units, methods, and configuration
  → evaluate only applicable ACTIVE SOURCE_BACKED rules
  → record required applicable UNRESOLVED rules and unavailable evidence
  → detect and resolve-or-record conflicts
  → identify manual-review conditions
  → aggregate all check results using Section 4.4
  → atomically persist decision and audit trace
  → expose immutable assessment result to authorized consumers
```

Separation of responsibilities:

- applicability decides what must be checked; it does not evaluate values;
- measurement validation decides whether inputs are usable; it does not imply engineering compliance;
- rule evaluation compares valid canonical inputs only against pinned `SOURCE_BACKED` rules;
- aggregation selects the final state without discarding secondary blockers;
- human review records workflow disposition separately;
- persistence publishes a decision only after its audit trace succeeds.

## 8. Missing and invalid data behavior

| Condition | Per-check condition | Final-state effect | Fail-safe behavior |
|---|---|---|---|
| Missing required measurement | `DATA_INSUFFICIENT` | `MANUAL_REVIEW_REQUIRED` unless higher precedence applies | block READY; identify field and collection action |
| Invalid/non-finite/out-of-domain measurement | `DATA_INVALID` | `MANUAL_REVIEW_REQUIRED` | retain raw value; do not evaluate rule |
| Unsupported unit/dimension | `UNIT_UNSUPPORTED` | `MANUAL_REVIEW_REQUIRED` | reject conversion/evaluation |
| Unit conversion failure | `UNIT_CONVERSION_FAILED` | `MANUAL_REVIEW_REQUIRED` | retain raw/canonical attempt and converter version |
| Stale measurement | `DATA_STALE` | `MANUAL_REVIEW_REQUIRED` | require new observation; freshness policy must be versioned |
| Missing machine configuration | `CONTEXT_INSUFFICIENT` | `MANUAL_REVIEW_REQUIRED` | applicability cannot be trusted |
| Missing process context | `CONTEXT_INSUFFICIENT` | `MANUAL_REVIEW_REQUIRED` | applicability cannot be trusted |
| Required rule missing / zero validated applicable rules | `NOT_EVALUATED` | `NOT_EVALUATED`, unless another higher blocker applies | never infer no constraint |
| Required applicable unresolved rule | `UNRESOLVED` | `ENGINEERING_REVIEW_REQUIRED` | no numeric comparison; resolution path required |
| Conflicting rules | `RULE_CONFLICT` | `ENGINEERING_REVIEW_REQUIRED` when not deterministically resolved | retain every candidate and policy trace |
| Superseded rule | `NOT_APPLICABLE_VERSION` | use correct active version or block evaluation | never silently use superseded version for a new assessment |
| Inactive rule | `NOT_APPLICABLE_VERSION` | cannot support READY | report why it was excluded |
| Required evidence unavailable/unverifiable | `EVIDENCE_UNAVAILABLE` | `ENGINEERING_REVIEW_REQUIRED` | rule cannot support automatic READY |
| Required manual observation absent | `OBSERVATION_MISSING` | `MANUAL_REVIEW_REQUIRED` | collect and identify responsible role |

Optional checks may be skipped only when the versioned check definition explicitly marks them optional. The skip is audited and never satisfies a required READY prerequisite.

## 9. Unit-safe evaluation

- Every registry rule declares a canonical unit and dimension.
- Every numeric observation carries its supplied unit; unitless values are explicitly declared as such.
- Conversion is allowed only through an approved, versioned conversion catalog after dimensional compatibility is proven.
- The trace records raw value/unit, normalized value/unit, conversion formula/catalog version, rounding policy, and result.
- Unsupported, missing, or dimensionally incompatible units are not coerced and cannot produce PASS.
- Unit conversion occurs before rule evaluation; thresholds are never converted ad hoc without trace.
- Boolean and categorical observations use enumerated semantics rather than numeric unit conversion.

## 10. Rule applicability

Repository-supported dimensions are machine, weld gun, station/robot/operation, material family, sheet stack/count/layers/thickness, electrode/tip, process parameters/schedule, customer/OEM source context, category, rule lifecycle/effective date, and equipment configuration. Adhesive, coating, and shunt appear in weld context but are not automatically MRC applicability dimensions; adding them requires versioned check-definition justification.

| Resolution | Behavior |
|---|---|
| Zero applicable validated rules | `NOT_EVALUATED`; READY blocked |
| One applicable rule | Pin exact version; evaluate only if ACTIVE and SOURCE_BACKED with verified evidence |
| Multiple compatible rules | Evaluate every required rule; all required SOURCE_BACKED rules must pass |
| Multiple conflicting rules | Apply only an approved deterministic registry conflict policy that fully resolves the conflict; otherwise `ENGINEERING_REVIEW_REQUIRED` |

The category filter cannot exclude any of the 16 baseline requirements merely because U-007 is `PARAMETER` or U-016 is `MATERIAL`; document 111 explicitly declares all 16 as MRC dependencies. Future category refinements require synchronized rule/check versioning, not silent omission.

## 11. Controlled human review

### 11.1 Review distinction

- `ENGINEERING_REVIEW_REQUIRED`: triggered by missing/unverified engineering truth—an unresolved threshold, unavailable evidence, or unresolved rule conflict. Authorized engineering personnel must resolve evidence/applicability or create a new registry rule version.
- `MANUAL_REVIEW_REQUIRED`: triggered by missing/invalid/stale observations, required qualitative inspection, or operational/system condition requiring a person to collect, validate, or disposition workflow data.

### 11.2 Review record

Every review requires reason code, scope, required comments, reviewer user ID and role, timestamp, disposition, attachments/evidence references, and links to original assessment/check results.

Permitted workflow dispositions are `RETURN_FOR_DATA`, `REQUEST_ENGINEERING_EVIDENCE`, `ACKNOWLEDGED_BLOCKED`, `CANCELLED`, and `REEVALUATE`. A future policy may define a controlled operational exception, but it must remain separate as `workflow_disposition`; it must not change deterministic state, check status, or engineering truth and must never relabel an unresolved/failed assessment as READY.

Dedicated permissions are proposed and must be mapped into the existing JWT/RBAC system:

- `mrc:read`, `mrc:create`, `mrc:observe`, `mrc:evaluate`
- `mrc:manual-review`, `mrc:engineering-review`, `mrc:disposition`
- `mrc:audit-read`

System Admin configures access but does not gain engineering authority merely from administration. Proposed role mapping requires security-owner approval: Operator/Maintenance submit observations; Process/Manufacturing/Quality Engineers perform scope-appropriate review; engineering-rule promotion requires explicitly delegated engineering authority.

## 12. Auditability, traceability, and reproducibility

A future auditor must reconstruct:

- assessment/revision and request correlation IDs;
- machine, gun, station, robot, operation, project/weld-point, process, schedule, material, stack, electrode, customer/OEM, and configuration snapshots;
- every check definition ID/version and required/optional designation;
- every candidate and selected rule ID/version, evidence class, source/evidence reference, applicability result, and conflict;
- raw observations, supplied units, methods/devices/calibration, actors, timestamps, freshness, conversions, and normalized values;
- per-check evaluation inputs, outputs, reason codes, exceptions, and status;
- every READY prerequisite truth value, aggregation precedence decision, all primary/secondary blockers, and final state;
- human reviews and workflow dispositions without overwriting deterministic results;
- software build/commit, evaluator and conversion-catalog versions, clock/time-zone context, and audit integrity metadata.

Completed assessments are immutable. Reevaluation references the prior assessment and produces a new assessment revision with newly pinned snapshots.

## 13. DWP integration boundary

The Digital Weld Passport defined in [docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md](113_DIGITAL_WELD_PASSPORT_DESIGN.md) references, but does not duplicate or recalculate, MRC truth. The boundary exposes:

- immutable assessment ID/revision and integrity hash;
- final deterministic readiness state and evaluated timestamp;
- machine/gun/process/material-stack context identifiers and snapshot references;
- rule/check/evidence trace summary;
- unresolved, conflict, and review-status summary;
- URI/reference for authorized detail retrieval.

DWP records the exact MRC reference used for its weld operation. Later MRC reevaluation does not mutate an existing passport; a new DWP revision may reference the newer assessment. DWP cannot convert a non-READY MRC result into readiness.

## 14. Conceptual API contracts

All routes are proposed under existing `/api/v1`, JWT, structured-error, permission-dependency, and OpenAPI conventions. No endpoint is implemented by this design.

| Operation | Purpose / request concept | Response concept | Authorization and fail-safe behavior |
|---|---|---|---|
| `POST /api/v1/mrc/assessments` | Create draft from machine/process/context IDs and expected operation | assessment ID, context-validation issues, required checks | `mrc:create`; invalid/missing context is explicit, never READY |
| `POST /api/v1/mrc/assessments/{id}/observations` | Submit typed observations with unit, method, time, device, attachments | accepted observation IDs and validation conditions | `mrc:observe`; append/supersede, never silently overwrite |
| `POST /api/v1/mrc/assessments/{id}/evaluate` | Pin definitions/rules/evidence and evaluate idempotently using an idempotency key | immutable decision, prerequisite matrix, check results, blockers, trace IDs | `mrc:evaluate`; registry/integrity/audit failure prevents publication |
| `GET /api/v1/mrc/assessments/{id}` | Retrieve assessment and final/draft status | context snapshot, decision summary, reviews | `mrc:read`; field-level evidence access policy applies |
| `GET /api/v1/mrc/assessments/{id}/checks` | Retrieve per-check details | check/rule/evidence/input/conversion/result records | `mrc:read`; no recomputation on read |
| `GET /api/v1/mrc/assessments/{id}/audit` | Retrieve ordered audit trail | append-only events and integrity metadata | `mrc:audit-read`; pagination and access logging required |
| `POST /api/v1/mrc/assessments/{id}/reviews` | Submit engineering/manual review and workflow disposition | review record plus unchanged deterministic state | matching review permission; cannot rewrite PASS/FAIL/UNRESOLVED |

Important errors use stable reason codes: unauthorized/forbidden, assessment sealed, context insufficient, registry unavailable, evidence unavailable, unit invalid, stale observation, conflict unresolved, audit persistence failed, and idempotency conflict. HTTP success does not imply `READY`; engineering state is explicit in the body.

## 15. Security and authorization

MRC reuses existing authentication and authorization architecture; it creates no parallel identity system.

- Least privilege separates viewing, observation, evaluation, engineering review, manual review, disposition, and audit access.
- Machine/customer/project scope authorization must accompany role permission.
- Evidence attachments and audit histories may require stricter access than decision summaries.
- Every state-affecting request is authenticated, authorized, correlated, and audited.
- Service identities used for automatic evaluation are distinct from human reviewers.
- Reviewer identity, role, and delegated authority are evaluated at review time and snapshotted.
- Audit events must avoid secrets while retaining engineering traceability; integrity/tamper controls are required before production.

## 16. Versioning policy

The assessment pins:

- check-definition ID/version/content hash;
- engineering rule ID/version/evidence class/content hash;
- evidence document revision/location/hash and availability status;
- applicability/conflict-policy and unit-conversion catalog versions;
- machine/gun/configuration, material/stack, electrode, and schedule snapshots;
- evaluator/software build version.

Rule, evidence, definition, software, or machine-configuration changes never alter an old assessment. They may trigger a new assessment or reevaluation linked by `supersedes_assessment_id`. Historical READY remains explainable, not retroactively recomputed; later invalidation is a separate traceable event and may require operational notification policy.

## 17. Failure modes

| Failure mode | Detection | Result / READY blocked | User behavior | Audit behavior |
|---|---|---|---|---|
| Rule Registry unavailable | provider health/timeout | no authoritative finalization; READY blocked | retry or service unavailable | record attempt when audit available; operational incident |
| Required rule missing | applicability resolution | `NOT_EVALUATED`; yes | show missing-rule reason | candidates/context/query version |
| Unresolved threshold | evidence class | `ENGINEERING_REVIEW_REQUIRED`; yes | show resolution path | rule/check/evidence status |
| Conflicting rules | conflict detector | `ENGINEERING_REVIEW_REQUIRED`; yes | list every conflict | candidates and policy outcome |
| Missing measurement | input validation | `MANUAL_REVIEW_REQUIRED`; yes | request measurement | missing field/check/actor |
| Invalid measurement | type/range/domain validation | `MANUAL_REVIEW_REQUIRED`; yes | correct/recollect | raw value and validation reasons |
| Unit mismatch | dimensional validation | `MANUAL_REVIEW_REQUIRED`; yes | supply supported unit | raw unit, expected dimension |
| Stale measurement | versioned freshness policy | `MANUAL_REVIEW_REQUIRED`; yes | recollect | observed/evaluated times and policy |
| Machine context missing | context validation | `MANUAL_REVIEW_REQUIRED`; yes | complete configuration | missing dimensions and request |
| Persistence failure | transaction outcome | result not finalized; yes | retry safely with idempotency key | failure telemetry; no false success |
| Audit write failure | atomic audit transaction | result not published; yes | retry/escalate | external operational alert if primary audit unavailable |
| Review required | reason-code generation | engineering/manual review state; yes | route to authorized reviewer | trigger and dispositions |
| Unexpected evaluation exception | exception boundary | `MANUAL_REVIEW_REQUIRED` only if safely persisted as an error result; otherwise no final result; yes | generic safe error, correlation ID | sanitized exception, versions, trace ID |

## 18. Acceptance criteria for future implementation

- Aggregation is deterministic and exhaustively tested for mixed states.
- No READY occurs without at least one applicable validated rule.
- No READY occurs with any required applicable unresolved rule.
- No READY occurs with missing, invalid, stale, or unit-invalid required data.
- No READY occurs with an unresolved conflict or manual-review condition.
- Required applicable `SOURCE_BACKED FAIL` produces `NOT_READY`.
- `DATA_INSUFFICIENT` produces `MANUAL_REVIEW_REQUIRED` unless a higher-precedence state applies.
- Zero applicable validated rules produces `NOT_EVALUATED` unless a higher-precedence blocker applies.
- Required applicable `UNRESOLVED` produces `ENGINEERING_REVIEW_REQUIRED` unless `NOT_READY` also exists.
- Exact rule, version, evidence, check-definition, input, unit/conversion, and software trace is retained.
- Evaluation is unit-safe and rejects incompatible/unsupported units.
- Historical results reproduce from pinned snapshots without mutable lookups.
- Assessment finalization and audit persistence are atomic or equivalently fail-safe.
- Human disposition remains separate from deterministic engineering state.
- DWP can reference an immutable MRC assessment without duplicating it.
- All 16 baseline items remain unresolved until qualifying repository-controlled evidence is reviewed and promoted in the Engineering Rule Registry.

## 19. Implementation boundaries

Future implementation may build versioned MRC definitions, assessment orchestration, observation validation, Registry integration, deterministic aggregation, review workflows, audit persistence, conceptual APIs, and DWP reference contracts.

It must not:

- hard-code unverified engineering thresholds;
- treat code constants, tests, templates, examples, generated Markdown, or AI-authored claims as engineering evidence;
- infer PASS/READY from missing rules, data, evidence, or context;
- collapse unresolved into conditional pass;
- overwrite deterministic engineering truth with workflow disposition;
- bypass the Engineering Rule Registry;
- silently use inactive/superseded rules or incompatible units;
- silently omit any applicable baseline requirement.

## 20. Implementation readiness and blockers

### A. Architecture blockers

- Registry design exists, but its production provider/persistence/version APIs do not.
- MRC entities, atomic decision/audit persistence, idempotency, and integrity mechanisms are not implemented.
- Exact boundary between project/weld-point records and machine/configuration master data requires decision.
- Check-definition lifecycle and context snapshot strategy require formal approval.

### B. Engineering evidence blockers

- All 16 baseline MRC items are `UNRESOLVED`.
- No baseline item may support PASS/FAIL/READY until promoted through document 111’s evidence process.
- Compressed-air pressure, actual electrode force, numeric actual-current readiness, and other possible checks lack defined inventory/evidence and remain proposed/TBD.

### C. Data-model decisions required

- Identifier formats, retention, content hashes, snapshot granularity, attachment storage, calibration/device model, freshness policies, correction/supersession, and atomic audit strategy.

### D. API decisions required

- Final resource naming, draft/sealed transitions, synchronous versus asynchronous evaluation, idempotency, pagination, error schema, attachment flow, and registry-unavailable behavior.

### E. Security/authorization decisions required

- Approval of dedicated permissions and role mapping, scope authorization, reviewer delegation, separation of duties, evidence visibility, audit integrity, and any operational-exception governance.

### F. Safe to implement now

- Threshold-free state types and reason codes.
- Versioned check-definition and observation contracts with all engineering values absent/TBD.
- Unit/dimension validation framework, trace envelopes, immutable identifiers, authorization hooks, and aggregation tests using non-engineering fixtures.
- Registry adapter interfaces and failure handling without populating thresholds.

### G. Must remain blocked until evidence exists

- Numeric/boolean/qualitative acceptance criteria for all 16 unresolved items.
- Any production PASS/FAIL evaluation or automatic READY based on those items.
- New compressed-air, force, current, alignment, or dressing thresholds.

The architecture is design-ready for threshold-free scaffolding. The MRC rule set is not engineering-rule-ready.

## 21. Repository consistency findings

### 21.1 Alignment with document 111

This design preserves document 111’s five final states, six READY prerequisites, evidence taxonomy, fail-safe behavior, and exact 16-item inventory. It creates no independent rules and invents no thresholds.

### 21.2 Remaining implementation risks outside these designs

- `backend/app/domain/rules_engine.py` contains hard-coded prototype thresholds, evaluates them without document 111’s evidence/lifecycle fields, and automatically chooses a priority winner for some conflicts. Those behaviors cannot be reused as authoritative MRC decisions.
- current analysis/failure/electrode-life code and tests contain cooling and other constants; they are implementation context, not engineering evidence.
- repository security/authorization documents are largely placeholders, while the implementation has coarse role permissions; MRC-specific permissions remain undecided.
- existing `AuditLog` is generic and commits independently; production MRC requires atomic decision/audit publication and richer reproducibility data.
- generic machine/electrode database documents are placeholders and do not define an authoritative configuration master.

Documents 111, 112, and 113 are mutually aligned; these remaining risks concern unmodified implementation or placeholder documentation.

## 22. Design conclusion

The deterministic MRC architecture, safety model, traceability boundary, conceptual contracts, and implementation constraints are sufficiently specified for reviewed, threshold-free scaffolding. Production readiness evaluation remains blocked until the Engineering Rule Registry exists and applicable MRC rules acquire qualifying evidence.

**MRC DESIGN GO — architecture design only; engineering thresholds remain blocked.**
