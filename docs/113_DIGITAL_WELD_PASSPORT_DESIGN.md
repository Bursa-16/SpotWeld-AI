# 113 — Digital Weld Passport Design

**Document ID:** SDS-113  
**Status:** Design only — architecture-ready subject to Section 23 blockers  
**Authoritative parents:** [Engineering Rule Registry Design](111_ENGINEERING_RULE_REGISTRY_DESIGN.md), [Machine Readiness Check Design](112_MACHINE_READINESS_CHECK_DESIGN.md)  
**Scope:** Central traceable engineering record for a weld point or weld operation; no production implementation

## 1. Purpose and system boundary

The Digital Weld Passport (DWP) is the versioned, auditable engineering record that explains what a weld point was designed to be, what equipment and process context applied, what was actually observed, what deterministic engineering systems concluded, what quality evidence exists, and what humans authorized.

DWP is not a report, a flat mutable row, a rule engine, an MRC evaluator, a model registry, or an unlimited controller time-series store. It links those authoritative systems through immutable version references and sufficient snapshots for historical reconstruction.

```text
Weld identity and revision
  → design/material/stack snapshot
    → equipment/electrode snapshot
      → recipe revision
        → actual-cycle evidence references
          → MRC assessment reference
            → rule/evidence evaluation references
              → quality and model-result references
                → approvals/dispositions
                  → immutable DWP revision and audit trail
```

Safety invariants:

- DWP never creates thresholds or independently evaluates Engineering Rule Registry rules.
- DWP never recalculates or rewrites an MRC state.
- `UNRESOLVED`, `DATA_INSUFFICIENT`, `NOT_EVALUATED`, `ENGINEERING_REVIEW_REQUIRED`, and `MANUAL_REVIEW_REQUIRED` remain explicit.
- Missing information never becomes `PASS`, `READY`, `VALIDATED`, `APPROVED`, or production release.
- Human disposition is separate from deterministic engineering truth.
- AI/model output is advisory evidence and cannot replace deterministic engineering or quality truth.
- Exported files are generated views, never the system of record.

## 2. Repository baseline and discovered components

No dedicated DWP entity, service, endpoint, frontend feature, migration, or test exists.

Existing implementation context:

| Component | Existing capability | DWP limitation |
|---|---|---|
| `Project` | project code/name, customer, vehicle platform, status | no immutable project revision reference |
| `WeldPoint` | point, part/revision, station, robot, gun, operation, criticality, analysis input/result, approval status | mutable current row; not a complete passport |
| `WeldPointRevision` | immutable-looking numbered JSON snapshots with actor/reason/time | snapshot schema and integrity/version semantics are not formalized |
| `Approval` | type, approver text, status, note, time | approver is not a durable user/version reference; approval scope is ambiguous |
| `TestResult` | arbitrary test type, numeric value/unit, acceptance status, note, creator/time | no criterion/rule/evidence version, method, specimen, correction, or attachment lineage |
| `AuditLog` | actor, action, entity, ID, JSON detail, timestamp | generic and non-atomic with several domain writes; no before/after hashes |
| Analysis/rule/model outputs | analysis results, model selection, risk/failure outputs, explanations | several prototypes lack production provenance and must not become engineering truth |
| JWT/RBAC | coarse project/weld/approval/test permissions | no DWP-specific separation of duties |
| Integration architecture | planned REST, Excel/CSV, OPC-UA, MQTT, MES/SCADA, controller data | no implemented provenance/high-volume storage contract |

Repository-supported quality concepts are generic test results plus peel, chisel, macro section, nugget measurement, and failure classification references. Tensile shear, cross tension, UT, and visual inspection are valid design candidates but are not implemented as typed concepts and are `PROPOSED`. Image processing is explicitly out of scope; an external evidence-file reference may be stored, but DWP performs no image analysis. NCR/CAPA/8D links are not present and are `PROPOSED` external references.

## 3. Relationship to the Engineering Rule Registry

Document 111 remains the single owner of rule ID, version, evidence class, source, threshold/formula, operator, applicability, lifecycle, effective dates, units, and conflict policy.

DWP stores an immutable `RuleEvaluationReference` for every relevant evaluation:

- evaluation ID and immutable result revision;
- `rule_id` and exact rule revision/version/content hash;
- evidence reference IDs, revisions, exact source locations, and availability state;
- applicability-context snapshot/hash and applicability outcome;
- supplied and canonical values/units plus conversion trace references;
- deterministic result (`PASS`, `FAIL`, `UNRESOLVED`, `NOT_EVALUATED`, or review condition);
- reason codes, conflict references, evaluator/software version, and timestamp.

DWP may cache a signed/hashed display snapshot so history survives later registry changes, but the Registry remains the authoritative rule source. Cache content cannot be edited or used to create a new rule. An unresolved rule remains unresolved until a new Registry rule version is promoted through document 111; a new DWP revision is then required for reevaluation.

## 4. Relationship to MRC

Document 112 owns MRC check applicability/selection, observations, assessment evaluation, aggregation, READY prerequisites, and final state; document 111 retains ownership of engineering-rule applicability. DWP does not call Registry rules to reconstruct MRC.

`MrcAssessmentReference` contains:

- assessment ID and revision/content hash;
- exact final MRC state: `READY`, `NOT_READY`, `ENGINEERING_REVIEW_REQUIRED`, `MANUAL_REVIEW_REQUIRED`, or `NOT_EVALUATED`;
- assessment/evaluation timestamp;
- machine, gun, process, material/stack, schedule, and configuration snapshot references;
- prerequisite matrix, blocker/review summary, and unresolved/conflict summary;
- check/rule/evidence trace URI or immutable reference;
- MRC software/check-definition versions and integrity metadata.

DWP record existence and completeness are independent from MRC readiness. A DWP can be created and historically retained with any MRC state. Production release is blocked unless the release policy requires and observes a qualifying exact MRC assessment; this design assumes `READY` is required for automatic production release, while any concession policy remains a separate unresolved governance decision. DWP never changes a non-READY MRC result.

## 5. Multidimensional lifecycle and status model

A single `OK` or overloaded status is prohibited. Lifecycle, completeness, validation, approval, production use, MRC, rule compliance, and quality each have separate fields.

### 5.1 Record lifecycle

| State | Meaning | Entry/exit authority |
|---|---|---|
| `CREATED` | identity shell exists; required content not yet established | creator with `dwp:create` |
| `DRAFT` | editable working revision | authorized draft editor |
| `ENGINEERING_DEFINED` | required design, stack, equipment, recipe, and lineage fields are complete; not validation | derived completeness plus engineering submit authority |
| `VALIDATION_PENDING` | validation evidence collection is open | authorized engineering/quality transition |
| `VALIDATED` | revision-specific validation policy is satisfied; not approval or release | derived from source-backed criteria and quality evidence; authorized validation confirmation where required |
| `APPROVED` | revision-specific engineering approval is recorded | authorized approver; separation of duties applies |
| `PRODUCTION_ACTIVE` | approved revision is released for the governed production scope | authorized production-release approver after gates pass |
| `SUPERSEDED` | newer immutable revision replaces this revision | authorized revision/supersession workflow |
| `RETIRED` | no longer permitted for new production | authorized release owner |
| `ARCHIVED` | retained read-only under retention policy | records governance |

These labels provide workflow navigation, but authoritative truth remains in the dimensions below. `VALIDATED`, `APPROVED`, and `PRODUCTION_ACTIVE` require explicit policy gates; they must not be inferred solely from the lifecycle label.

### 5.2 Orthogonal status dimensions

| Dimension | Values | Derivation/authority |
|---|---|---|
| `completeness_status` | `INCOMPLETE`, `COMPLETE`, `DATA_INSUFFICIENT` | automatically derived from versioned required-field policy |
| `mrc_state` | document 112 states | immutable MRC reference only |
| `engineering_compliance_status` | `PASS`, `FAIL`, `UNRESOLVED`, `NOT_EVALUATED`, `ENGINEERING_REVIEW_REQUIRED`, `MANUAL_REVIEW_REQUIRED` | referenced deterministic Registry evaluations |
| `quality_validation_status` | `NOT_STARTED`, `PENDING`, `PASS`, `FAIL`, `DATA_INSUFFICIENT`, `NOT_EVALUATED`, `REVIEW_REQUIRED` | quality evidence against source-backed criteria |
| `approval_status` | `NOT_SUBMITTED`, `PENDING`, `APPROVED`, `REJECTED`, `WITHDRAWN` | authorized human workflow |
| `production_release_status` | `NOT_RELEASED`, `RELEASED`, `SUSPENDED`, `RETIRED` | authorized release workflow after deterministic gates |
| `workflow_disposition` | `NONE`, `RETURN_FOR_DATA`, `REQUEST_ENGINEERING_REVIEW`, `CONCESSION_REQUESTED`, `CONCESSION_GRANTED`, `REJECTED`, `CANCELLED` | authorized, append-only human action; never changes engineering truth |

### 5.3 Transition controls

- Draft edits require `dwp:draft-write` and are audited.
- Engineering definition/submission requires an engineering role and completeness evaluation.
- Validation confirmation requires authorized quality/engineering role and source-backed acceptance references.
- Approval and production release require distinct permissions; separation of duties is a policy decision that must be finalized.
- Superseding, suspension, retirement, and archival require reason, actor, timestamp, and prior/new revision links.
- Any material, recipe, equipment, rule, MRC, validation, or quality correction after approval creates a new revision; it never edits the approved revision.

## 6. Conceptual core data model

No SQL or ORM schema is created here.

| Entity | Responsibility and key fields | Relationships | Mutability |
|---|---|---|---|
| `DigitalWeldPassport` | stable passport ID, weld identity, current revision pointer | owns immutable revisions | identity stable; current pointer controlled |
| `DigitalWeldPassportRevision` | revision ID/no, lifecycle/status dimensions, prior/superseding IDs, change reason, content hash, created/sealed metadata | aggregates all snapshots/references | editable only as DRAFT; sealed revisions immutable |
| `WeldIdentitySnapshot` | project/program/platform/customer, part/revision, station, robot, gun, operation, weld-point code, criticality | one per revision | immutable snapshot |
| `StackDesignSnapshot` | ordered material layers, grade/subtype, thickness/unit, coating, adhesive/sealer, interface count, edge/pitch/shunt context, geometry references | revision design section | immutable; unknown fields explicit |
| `EquipmentSnapshot` | machine/control type, transformer/controller, gun/type/actuation, electrode identity/type/diameter/geometry, cooling context, configuration version | revision equipment section | immutable snapshot/reference bundle |
| `RecipeRevisionReference` | recipe ID/revision/hash; current, weld time, force, squeeze, hold, pulse, slope, control mode with units | revision references approved recipe version | immutable reference plus display snapshot |
| `ActualCycleEvidence` | cycle/batch ID, timestamp, values/units, alarms, controller outcome, provenance, raw-data URI/hash | zero-to-many per revision/production instance | append-only observed data |
| `MrcAssessmentReference` | fields in Section 4 | revision gate/reference | immutable |
| `RuleEvaluationReference` | fields in Section 3 | many per revision | immutable |
| `QualityEvidence` | test ID/type/method/specimen, values/units, failure classification, criterion/rule reference, result, attachments, actor/time | many per revision | append-only; correction supersedes |
| `ModelResultReference` | model/version/hash, dataset/version, applicability, inputs/outputs/units, confidence, explanation, warnings, review/correction | many per revision | immutable result; correction is separate review |
| `ApprovalRecord` | approval type/scope, decision, approver user/role/authority, comments, time, revision hash | many per revision | append-only; withdrawal is new event |
| `WorkflowDisposition` | reason/type, scope, conditions/expiry, authority, links; original truth snapshot | many per revision | append-only; does not mutate truth |
| `DwpAuditEvent` | actor/service, action, entity/version, before/after hashes, reason, time, correlation, software version | covers all DWP actions | append-only; finalization requires audit success |
| `ExternalEvidenceReference` | URI/object ID, version/hash, media/type, owner, retention/access classification | referenced by evidence sections | immutable version reference |

### 6.1 Section ownership, requiredness, and traceability

| Section | Source of truth | Required baseline | Versioning and traceability |
|---|---|---|---|
| Identity | Project/WeldPoint plus controlled master data | project, part/revision, operation, stable weld-point ID; other production identifiers policy-dependent | snapshot IDs and master versions |
| Stack/design | material/stack master or captured analysis input | ordered layers, material identity, thickness/unit; coating/adhesive when applicable | immutable layer-order snapshot and source refs |
| Equipment | machine/gun/electrode masters (not yet implemented) | machine, gun, electrode/configuration identity for production use | version refs plus critical display snapshot |
| Recipe | approved versioned recipe source (not yet implemented) | recipe ID/revision and all parameters required by that recipe schema | exact values/units/hash; no acceptable ranges in DWP |
| Actual process | controller/MES/SCADA or authenticated observation | policy-dependent; required for production instance evidence | immutable event/batch refs and raw-data hashes |
| MRC | document 112 subsystem | exact assessment reference when production release is requested | immutable ID/revision/state/hash |
| Rules/evidence | document 111 Registry/evaluation service | all applicable evaluation references | exact rule/evidence/applicability versions |
| Quality | Test/quality system | versioned validation plan determines required tests | test/method/criterion/evidence versions |
| AI/model | model execution/registry | optional unless approved workflow requires it | model/dataset/applicability/result versions |
| Governance | DWP workflow and identity provider | creator, revision reason, approvals/releases, timestamps, audit | append-only identities and events |

## 7. Snapshot versus reference strategy

| Data class | Strategy | Reason |
|---|---|---|
| Mutable project/material/machine/electrode masters | store immutable version reference and snapshot decision-critical fields | preserves history if masters change |
| Rule, evidence, MRC, recipe, model, and check definitions | reference immutable historical version/hash; cache signed display snapshot | authoritative owner remains external while DWP stays readable |
| Actual observations/cycle/test data | store immutable observed record or immutable raw-store reference with hash | these are event facts, not master data |
| High-volume curves/controller logs | external immutable object/time-series reference with schema/version, bounds, hash, retention, and access metadata | prevents DWP from becoming an unlimited time-series store |
| Approvals, dispositions, audit | store append-only in DWP governance record | preserves who decided what and why |
| Reports | reference generated artifact hash and source DWP revision | report is derived, never authoritative |

Critical snapshots include IDs and human-readable values so a historical record remains interpretable if a master service is unavailable. A reference without resolvable version/hash is `BROKEN_REFERENCE` and blocks the affected validation/release gate.

## 8. Revision model

### 8.1 Rules

- Passport ID is stable across the weld identity; each engineering change creates a monotonically versioned immutable revision.
- A DRAFT may be edited with field-level audit. Sealing computes a content hash and freezes it.
- Approved/production revisions are never patched. Corrections create a new revision with `supersedes_revision_id` and mandatory reason.
- Approval, validation, and production release apply only to one exact revision hash.
- Old revisions remain queryable and reproducible; deletion is prohibited except under an approved legal/privacy retention workflow that preserves tombstone audit metadata.
- Concurrent draft updates use optimistic versioning/ETags; conflicting updates do not silently merge.

### 8.2 Change examples

| Change | Required revision behavior |
|---|---|
| Material/part revision or stack order changes | new DWP revision, new stack snapshot, applicability/rule/MRC reevaluation references |
| Recipe parameter update | new recipe revision and DWP revision; prior recipe retained |
| Electrode or machine configuration change | new equipment snapshot and MRC reference; production release reevaluated |
| Engineering-rule revision | existing DWP unchanged; reevaluation creates new rule-evaluation and DWP revision |
| Validation result added | append evidence while validation is open; after seal/approval, create new revision |
| Quality evidence correction | superseding quality record plus new DWP revision if it affects sealed truth |
| Model update or human correction | new immutable model result/review; never overwrite original output |

## 9. Engineering truth versus workflow disposition

Each deterministic result is stored separately from workflow action:

```text
deterministic_result: FAIL | UNRESOLVED | DATA_INSUFFICIENT | ...
workflow_disposition: CONCESSION_REQUESTED | CONCESSION_GRANTED | ...
production_release_status: NOT_RELEASED | RELEASED | SUSPENDED | RETIRED
```

A failed MRC remains `NOT_READY`; an unresolved rule remains `UNRESOLVED`; a failed quality test remains `FAIL`. A manager or customer disposition records authorization, scope, expiry, rationale, and conditions but does not rewrite those fields.

Whether a concession can permit limited production is a governance decision not established by the repository. Until formally approved, non-READY MRC, required unresolved rule, required failed quality evidence, or insufficient required data blocks release. If a future concession policy is approved, release must still display the original blocking truth and concession prominently and immutably.

## 10. Quality and test traceability

`QualityEvidence` records:

- test ID/type and validation-plan requirement ID;
- specimen/part/weld/batch identity and sampling context;
- test method/procedure/version, equipment and calibration references;
- raw and normalized values with units and conversion trace;
- observations, nugget measurement, failure classification, attachments;
- exact source-backed acceptance rule/specification and evidence revision;
- deterministic acceptance result or unresolved/insufficient/review state;
- performer/reviewer identities, timestamps, correction/supersession links.

Repository status:

| Test concept | Status in repository/design |
|---|---|
| Peel, chisel, macro section, nugget measurement, failure classification | referenced; typed schemas/method governance still required |
| Tensile shear, cross tension, UT | `PROPOSED`; no current typed implementation |
| Visual inspection | `PROPOSED` manual observation only; no image-processing inference |
| External image/file reference | allowed as evidence reference; analysis remains out of scope |
| NCR/CAPA/8D | `PROPOSED` external-system link; no repository model found |

No test name implies acceptance. Acceptance criteria must resolve to an approved, applicable `SOURCE_BACKED` rule/specification. Otherwise the evidence is recorded with `UNRESOLVED`, `NOT_EVALUATED`, or review status.

## 11. Actual process and production traceability

### 11.1 Actual-cycle evidence

An actual-cycle record may contain actual current, force, weld time, voltage, resistance, energy, displacement, phase/pulse data, controller result, alarms, controller clock/time-zone, station/robot/gun, recipe revision, machine configuration, and provenance. Fields are optional unless a versioned capture/release policy requires them; absence of required fields becomes `DATA_INSUFFICIENT`.

Single-cycle evidence may be embedded as immutable structured data. High-volume resistance/force/current curves and production series remain in controller/MES/SCADA/object storage; DWP stores immutable references, hashes, schema versions, time ranges, sample counts, retention, and retrieval status. Aggregate records retain aggregation method/version, population/time window, exclusions, and raw-data references.

Existing dynamic-resistance and energy calculations are implementation context only. DWP may reference versioned results but does not treat current prototype outputs as source-backed quality truth.

### 11.2 Production identity boundary

Repository-supported fields: project/customer/platform, part/revision, station, robot, gun, operation, weld point, criticality, recipe/analysis context, and timestamps.

`PROPOSED` fields requiring integration/data ownership decisions: VIN/vehicle serial, part serial, batch/lot, shift, operator, controller cycle ID, line/body ID, and MES transaction ID. Their absence does not silently pass; the release policy declares which are required for each deployment.

## 12. AI and model governance

AI/model results are optional, versioned evidence. Each `ModelResultReference` records:

- model ID, semantic version, artifact hash, lifecycle/validation/approval status;
- training/calibration dataset ID/version where applicable;
- input snapshot, names/units, supported range, material/stack scope, extrapolation status;
- prediction/output and unit, confidence/uncertainty, explanation/contributions, warnings;
- execution/software version and timestamp;
- reviewer identity/status, human correction, reason, and superseding result link.

Low-confidence, unverified, unavailable, or out-of-scope results remain explicitly marked and cannot establish engineering compliance, quality PASS, MRC READY, approval, or release. Human correction is a separate review record; the original output remains immutable. Existing model-registry code is a prototype and does not by itself satisfy ADR-005 provenance requirements.

## 13. Insufficient and unresolved states

| Condition | DWP representation | Gate behavior |
|---|---|---|
| Missing required DWP field/evidence | `completeness_status=DATA_INSUFFICIENT` with reason codes | validation/approval/release blocked |
| Referenced evaluation has missing input | preserve `DATA_INSUFFICIENT` and `MANUAL_REVIEW_REQUIRED` | never convert to PASS |
| Required applicable rule unresolved | preserve rule/result `UNRESOLVED` and `ENGINEERING_REVIEW_REQUIRED` | compliance and release blocked |
| No applicable validated rule | preserve `NOT_EVALUATED` | never infer compliance |
| MRC review state | preserve exact MRC state/review summary | DWP may exist; release blocked by current policy |
| Quality criterion unavailable | quality `NOT_EVALUATED` or `UNRESOLVED` | quality validation/release blocked |
| Broken historical reference | `BROKEN_REFERENCE` plus affected status | affected gate blocked; repair creates audited reference correction/new revision |

Completing a document is not equivalent to satisfying engineering requirements.

## 14. Conceptual API contracts

Routes follow existing `/api/v1`, JSON/Pydantic, JWT, permission dependency, structured-error, and OpenAPI conventions. They are proposals only.

| Endpoint | Purpose / request | Response | Authorization, validation, fail-safe behavior |
|---|---|---|---|
| `POST /api/v1/dwp` | create passport/revision shell from weld-point identity | passport and draft revision IDs, missing-field report | `dwp:create`; duplicate identity policy and scope checks |
| `GET /api/v1/dwp/{id}` | retrieve passport/current or specified revision | revision snapshot, orthogonal statuses, references | `dwp:read`; no recomputation on read |
| `POST /api/v1/dwp/{id}/revisions` | clone selected revision into new DRAFT with reason | new revision and ETag | `dwp:revise`; prior revision remains immutable |
| `PATCH /api/v1/dwp/{id}/revisions/{rev}` | edit DRAFT sections with ETag | updated draft and completeness report | `dwp:draft-write`; sealed revision rejected |
| `PUT /api/v1/dwp/{id}/revisions/{rev}/mrc-reference` | attach exact immutable MRC reference | validated reference snapshot | `dwp:evidence-attach`; never recalculates MRC |
| `PUT /api/v1/dwp/{id}/revisions/{rev}/recipe-reference` | attach exact recipe revision | validated reference/snapshot | version/hash/unit checks; broken reference rejected |
| `POST /api/v1/dwp/{id}/revisions/{rev}/quality-evidence` | attach/supersede quality result | immutable quality record and status impact | `dwp:quality-write`; criterion lineage required for PASS |
| `POST /api/v1/dwp/{id}/revisions/{rev}/model-results` | attach immutable model execution | model result/reference | `dwp:model-attach`; applicability/validation state explicit |
| `POST /api/v1/dwp/{id}/revisions/{rev}/submit` | seal engineering definition/validation request | hash, completeness and blockers | `dwp:submit`; incomplete data blocks transition |
| `POST /api/v1/dwp/{id}/revisions/{rev}/approvals` | record scoped approval/rejection/withdrawal | append-only approval plus unchanged engineering truth | `dwp:approve`; identity/authority/separation checks |
| `POST /api/v1/dwp/{id}/revisions/{rev}/release` | release exact approved revision | release record/status | `dwp:release`; all policy gates and audit write must succeed |
| `POST /api/v1/dwp/{id}/revisions/{rev}/supersede` | link replacement revision | supersession event | `dwp:supersede`; mandatory reason/new revision |
| `GET /api/v1/dwp/{id}/audit` | retrieve ordered audit/integrity trail | paginated events | `dwp:audit-read`; access itself audited where required |

HTTP success never implies engineering PASS or production release. Idempotency keys protect create, attach, approve, release, and supersede operations. Persistence or audit failure prevents publication of state transitions.

## 15. Authorization model

DWP reuses the existing JWT/RBAC architecture and adds proposed granular permissions:

- `dwp:read`, `dwp:create`, `dwp:draft-write`, `dwp:revise`
- `dwp:evidence-attach`, `dwp:quality-write`, `dwp:model-attach`
- `dwp:submit`, `dwp:engineering-approve`, `dwp:production-release`
- `dwp:supersede`, `dwp:audit-read`

Role mapping is not silently assumed. Proposed intent: Process/Manufacturing Engineers define/revise; Quality Engineers attach/review quality evidence; authorized engineering approvers approve engineering revisions; separately delegated release authorities release production; Operators/Maintenance may contribute observations but not approve; Read Only/Customer access is scope-limited. System Admin manages access but does not automatically possess engineering approval authority.

Authorization also enforces project/customer/site scope, evidence sensitivity, delegated authority, and separation of duties. The current coarse permissions and free-text approver field are insufficient for production DWP.

## 16. Audit and traceability model

Every material event records:

- passport/revision/entity IDs and content hashes;
- actor/service identity, role, delegated authority, tenant/project scope;
- action, reason, old/new value or before/after hashes;
- UTC timestamp plus source time-zone/clock context where relevant;
- rule/evidence/MRC/recipe/material/equipment/model/quality reference versions;
- approval/disposition scope and original deterministic truth;
- correlation/idempotency IDs and software/API/build versions;
- attachment/object hashes, retention, and access classification.

Draft edits may retain field-level changes. Sealed revisions use append-only correction/supersession events. Decision publication and audit persistence must be atomic or equivalently fail-safe; an audit-write failure cannot produce a successful approval/release response.

## 17. Failure modes

| Failure | Detection | DWP state/result | Approval/release | User behavior | Audit behavior |
|---|---|---|---|---|---|
| Referenced MRC missing/broken | reference/version/hash validation | incomplete/broken reference | blocked | attach valid immutable assessment | failed-link event |
| MRC not READY | pinned MRC state | state preserved visibly | release blocked under current policy | resolve MRC/new DWP revision | state/reference snapshot |
| Required rule unresolved | rule evaluation reference | `UNRESOLVED` / engineering review | blocked | obtain evidence and reevaluate | rule/evidence/blocker trace |
| Required quality evidence missing | validation-plan completeness | `DATA_INSUFFICIENT` | blocked | attach required evidence | missing requirement IDs |
| Invalid material/stack reference | referential/schema/layer validation | incomplete/manual review | blocked | correct via new/draft revision | raw ref and errors |
| Missing recipe revision | required-reference validation | incomplete | blocked | attach approved version | missing-reference event |
| Stale machine configuration | versioned freshness/applicability policy | manual review | blocked | attach current snapshot/MRC | versions and policy |
| Broken evidence reference | hash/retrieval check | broken reference/review | affected gate blocked | restore or supersede reference | failure and repair events |
| Model unavailable | registry/execution reference check | model unavailable | not automatically blocking unless policy-required; never PASS | continue without advisory output or review | model/status trace |
| Model out of scope | applicability check | `OUT_OF_SCOPE` | cannot support gates | select applicable model or omit | applicability snapshot |
| Persistence failure | transaction outcome | no authoritative transition | blocked | safe retry | operational incident/idempotency trace |
| Audit-write failure | atomic audit outcome | transition unpublished | blocked | retry/escalate | external operational alert if primary audit unavailable |
| Unauthorized revision/action | permission/scope check | unchanged | blocked | return forbidden | denied-action security event |
| Conflicting revisions | ETag/current-revision check | conflict | blocked | reconcile by explicit new revision | competing versions/actors |
| Incomplete passport | completeness evaluator | `INCOMPLETE`/`DATA_INSUFFICIENT` | blocked | show exact missing requirements | completeness version/reasons |
| Unsupported unit | dimension/conversion validation | data invalid/manual review | affected gate blocked | supply supported explicit unit | raw unit, expected dimension, converter version |

## 18. Historical reproducibility

An approved or production-used revision retains or immutably references:

- DWP ID/revision/hash and lifecycle/status dimensions;
- project, platform/program, part/revision, weld identity, station/robot/gun/operation/criticality snapshots;
- material layers, order, grades, thickness/units, coating/adhesive and geometry context;
- machine/controller/transformer/gun/electrode/configuration versions;
- recipe ID/revision/hash and parameter values/units;
- actual-cycle/batch data or immutable raw-data references;
- exact MRC assessment/revision/state/hash;
- exact rule/evaluation/evidence/applicability/conflict versions;
- quality results, methods, criteria, attachments, corrections;
- model/dataset/software versions, outputs, applicability, explanations, reviews;
- approvals, dispositions, releases, supersession links, actors, reasons, timestamps;
- DWP evaluator/API/build, unit-conversion catalog, schema, and audit versions.

Reconstruction must not depend on mutable “current” master records. If external retention expires, the DWP must retain a policy-approved immutable snapshot sufficient for the record’s legal/engineering purpose.

## 19. Reporting boundary

DWP is the source record. PDF, DOCX, Excel, dashboards, and API summaries are generated views of one exact DWP revision.

Each export records DWP ID/revision/hash, generation time, template/version, generator/software version, locale/unit presentation, included/omitted sections, classification, and artifact hash. Regeneration may change presentation but not historical source truth. Imported/exported reports cannot overwrite DWP, Registry, MRC, quality, or model truth.

## 20. Acceptance criteria for future implementation

- Every passport has a unique stable weld identity and immutable revision IDs/hashes.
- Approved/sealed historical revisions cannot be destructively overwritten.
- Every production revision references an exact immutable MRC assessment and preserves its state.
- Rule evaluations retain exact rule/evidence versions and applicability snapshot.
- Recipe identity, revision, values, and units are traceable.
- Actual-cycle evidence records provenance or immutable raw-data references.
- Quality evidence records method, criterion/rule lineage, values/units, actors, and correction history.
- Model outputs retain model/dataset/version/applicability/confidence/explanation lineage.
- Engineering truth and workflow disposition are separate and independently queryable.
- Insufficient, unresolved, review, not-evaluated, failure, and out-of-scope states are preserved.
- Historical reconstruction succeeds without mutable-current lookups.
- Audit trail captures who changed what, why, when, and under which software/version context.
- Authorization and project/customer scope are enforced on every operation.
- No hard-coded threshold exists in DWP.
- DWP never duplicates or recalculates Registry or MRC logic.
- Reports are derived from an exact DWP revision and are never authoritative inputs.
- Persistence/audit failures cannot falsely publish approval or release.

## 21. Implementation boundaries

Future implementation must not:

- duplicate Engineering Rule Registry thresholds, applicability, evidence, or evaluation logic;
- duplicate MRC checks, aggregation, or READY logic;
- hard-code engineering or quality thresholds;
- infer PASS, READY, VALIDATED, APPROVED, or release from missing data;
- overwrite historical revisions or deterministic results;
- merge human disposition into engineering/quality/MRC truth;
- treat AI/model output as authoritative compliance;
- use exported reports as the system of record;
- lose rule, version, evidence, recipe, model, quality, MRC, or configuration lineage;
- store unlimited raw controller time-series inside the passport aggregate;
- use current prototype constants/results as source-backed evidence.

## 22. Consistency findings

### 22.1 Alignment

- Document 111 remains the sole rule/evidence authority; unresolved rules are never PASS.
- Document 112 remains the sole MRC authority; DWP references its immutable result and never converts non-READY to READY.
- The authoritative master index’s layered architecture is preserved: domain truth is independent of API/persistence details.
- Existing revision, approval, test, audit, model, and API conventions are extended conceptually rather than treated as production-complete.

### 22.2 Contradictions and risks elsewhere (not modified)

- Existing `WeldPoint` is mutable and its `approval_status` can be changed by adding a free-text approval; this is insufficient for immutable, revision-specific DWP truth and separation of duties.
- Existing revision snapshots capture only prior weld-point JSON and do not pin rule, MRC, evidence, recipe, model, quality-method, machine, or software versions.
- Existing test results accept arbitrary `acceptance_status` without a source-backed acceptance criterion or rule/evidence trace.
- Test creation and audit creation use separate commits; audit failure can occur after the test write, contradicting atomic publication required for DWP.
- Existing AuditLog lacks before/after values/hashes, revision scope, correlation, and software/version context.
- Current project delete behavior and cascade relationships require retention review before DWP use; an authoritative passport must not disappear through ordinary project deletion.
- Current role permissions and free-text approver identity do not provide DWP separation of duties or durable approval authority.
- Current model registry/code contains prototype validation/provenance semantics and must not be treated as a production model registry.
- Repository traceability/security/machine/electrode documents are partially placeholders; ownership and retention contracts remain undecided.

Documents 111, 112, and 113 are mutually aligned; no production artifact is modified by this design suite.

## 23. Implementation readiness

### A. Architecture-ready items

- Stable passport/revision aggregate, orthogonal status model, reference/snapshot strategy, truth/disposition separation, conceptual API, audit requirements, MRC/Registry boundaries, and report boundary.

### B. Data-model blockers

- Identity uniqueness scope, master-data version IDs, recipe aggregate, equipment/configuration master, validation-plan schema, reference hashes, attachment metadata, correction rules, retention/tombstone policy, and atomic audit design.

### C. Evidence blockers

- MRC’s 16 baseline items remain unresolved; quality acceptance criteria require source-backed rules/specifications; current prototype rule/model values are not authoritative.

### D. Authorization decisions

- DWP permission-to-role mapping, project/customer/site scope, engineering versus release authority, separation of duties, concession authority, evidence visibility, and audit access.

### E. API decisions

- Final resource naming, identity conflict policy, ETags/idempotency, draft sealing, asynchronous controller ingestion, bulk evidence, pagination, error schema, and reference-repair workflow.

### F. Storage decisions

- Immutable object storage/time-series ownership, hashes/signatures, retention, archival, legal hold, controller/MES provenance, attachment malware controls, and disaster recovery.

### G. Safe to implement now

- Threshold-free identifiers/status/reason types, immutable revision mechanics, reference envelopes, snapshot/hash contracts, unit/provenance metadata, authorization hooks, audit event schema, and tests using non-engineering fixtures.

### H. Must remain blocked

- Production release automation, source-backed compliance assertions, quality acceptance PASS, MRC-dependent release, concessions, and any engineering threshold until governing evidence/policies and production registries exist.

Readiness distinction:

- **DWP architecture readiness:** GO for reviewed threshold-free implementation design.
- **Engineering-rule readiness:** NO-GO until applicable Registry evidence is promoted.
- **Production-release readiness:** NO-GO until MRC, quality, authorization, retention, atomic audit, and release policies are implemented and validated.

## 24. Design conclusion

The DWP architecture is sufficiently specified as an immutable, versioned integration record without duplicating Registry, MRC, quality, model, or raw-data ownership. It is ready for design review and threshold-free scaffolding only; it is not authorization to implement or release production engineering decisions.

**DWP DESIGN GO — architecture design only; engineering-rule and production-release gates remain blocked.**
