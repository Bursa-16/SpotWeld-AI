# 100 - Software Design Specification (SDS) Master Index

**Project:** SpotWeld-AI
**Document ID:** SDS-100
**Version:** 1.1-draft
**Status:** DRAFT
**Document owner:** Project Owner
**Repository:** `D:\SpotWeld-AI`

## 1. Purpose and authority

This file is the sole authoritative index and allocator for the SpotWeld-AI
Software Design Specification namespace. It defines document identity,
location, status, ownership, approval requirements, and supersession history.

The file `docs/100_SDS_MASTER_INDEX.md` is a non-authoritative legacy pointer.
It cannot allocate numbers, change status, record approval, or supersede an
entry in this index.

## 2. SDS namespace

- Governed SDS identifiers use the `SDS-NNN` form and are registered below.
- Numeric filename prefixes are not SDS identifiers unless this index contains
  a matching registration.
- The legacy `00` through `63` documentation prefixes are outside the SDS
  namespace. Their duplicate numbers do not reserve or alter SDS identifiers.
- Every SDS identifier belongs to exactly one registered governed document.
- An allocated SDS identifier is permanent and is never reused, including
  after its document is superseded or retired.

## 3. Allocation and location rules

1. The next allocation uses the next sequential unused SDS number unless this
   index contains an explicitly approved reserved range or number.
2. Allocation occurs before document creation. A number is allocated only when
   this index contains a `RESERVED / NOT YET CREATED` entry with its title,
   intended path, owner, status, and approval requirements.
3. A filename alone does not allocate or reserve an SDS number.
4. Governed SDS documents other than this master index are stored under
   `docs/` using the form `NNN_UPPER_SNAKE_CASE_TITLE.md`.
5. A reserved entry changes to `EXISTING` only after the exact registered file
   is created through an approved change.
6. Registration and allocation do not constitute document approval or grant
   implementation authority.

## 4. Formal document status model

| Status | Meaning | Implementation authority |
|---|---|---|
| `DRAFT` | Reserved or authored content that has not completed formal review | None |
| `IN_REVIEW` | Version submitted for its required formal approvals | None |
| `APPROVED` | Exact version has all required approval records | Only the authority expressly stated by the approved document |
| `SUPERSEDED` | Preserved historical document replaced by an identified approved document/version | None for new work |
| `RETIRED` | Preserved historical document withdrawn without a replacement | None |

Labels such as `Design Only`, `Implementation Planning Only`, `Proposed`,
`Revised`, `Future`, and `Approved Semantic Baseline` describe scope or context.
They are not formal document statuses.

## 5. Status transitions and approval records

- The document owner may submit a `DRAFT` version for `IN_REVIEW`.
- The authoritative index records every status transition.
- A document becomes `APPROVED` only when every required approval role has
  approved the exact document version.
- `SUPERSEDED` and `RETIRED` transitions require the same approval roles as
  approval unless an approved document-specific rule states otherwise.
- Each approval record must contain the durable approver identity, approval
  role, exact document ID and version, UTC timestamp, decision, and durable
  approval-evidence reference.
- Missing ownership or missing approval evidence keeps a document fail-closed
  in `DRAFT` or `IN_REVIEW` and grants no implementation authority.
- Approval records must not name an unverified or placeholder human approver.

The default required approval roles for this governed SDS series are
Architecture, Security, and Data Owner. An exception requires an explicit,
approved entry in this index; silence is not an exception.

### 5.1 SDS-115 solo-project document-approval exception

SDS-115 uses the `SOLO_PROJECT_OWNER_APPROVAL` document-governance profile:

- Required formal document approver: Project Owner / Accountable Human Owner.
- Accountable human owner: İlhan Çekiç.
- Owner role: Security/Governance Owner.
- One explicit owner `APPROVE` decision for the exact reviewed version and
  immutable review-content reference is sufficient for formal SDS-115 document
  approval.
- Document-owner self-approval is permitted for this solo-project profile.
- Architecture, Security, and Data Owner reviews are optional advisory reviews,
  not mandatory formal document-approval gates for SDS-115.
- AG-01 and AG-02 are superseded only where they required three distinct humans
  or prohibited owner overlap for SDS-115 document approval.
- This exception grants no runtime verification authority and does not weaken
  runtime human-only verification, scoped delegation, deny-by-default behavior,
  creator/submitter-versus-verifier separation, no-admin-bypass, append-only
  decisions, auditability, or authority-snapshot requirements.
- A normative SDS-115 governance change returns the document to `DRAFT`,
  invalidates prior content-specific approvals for the new review cycle, and
  requires a fresh immutable review-content reference before `IN_REVIEW`.

## 6. Supersession and retirement

- Superseded and retired documents remain registered at their historical IDs
  and paths.
- Supersession records the replacement document ID and effective approval
  record. The replacement receives its own permanent SDS number.
- Historical IDs, versions, approval records, and paths are never silently
  deleted, reassigned, or reused.

## 7. Canonical SDS registry

`PENDING` means that the formal approval record required by this governance
contract has not been recorded. Existing semantic-baseline references do not
change that approval state.

| ID | Title | Path | Status | File state | Owner | Required approvals | Approval state | Supersedes |
|---|---|---|---|---|---|---|---|---|
| SDS-100 | Software Design Specification Master Index | `100_SDS_MASTER_INDEX.md` | DRAFT | EXISTING | Project Owner | Architecture, Security, Data Owner | PENDING | None |
| SDS-101 | System Context | `docs/101_SYSTEM_CONTEXT.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-102 | Domain Architecture | `docs/102_DOMAIN_ARCHITECTURE.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-103 | Rule Engine Design | `docs/103_RULE_ENGINE_DESIGN.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-104 | Model Registry | `docs/104_MODEL_REGISTRY.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-105 | Phase 1 Execution Plan | `docs/105_PHASE1_EXECUTION_PLAN.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-106 | API Contract | `docs/106_API_CONTRACT.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-107 | Database Blueprint | `docs/107_DATABASE_BLUEPRINT.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-108 | Automotive Compliance Roadmap | `docs/108_AUTOMOTIVE_COMPLIANCE.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-109 | AI Review Workflow | `docs/109_AI_REVIEW_WORKFLOW.md` | DRAFT | EXISTING / LEGACY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-110 | Recommendation Engine | `docs/110_RECOMMENDATION_ENGINE.md` | DRAFT | RESERVED / NOT YET CREATED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-111 | Engineering Rule Registry Design | `docs/111_ENGINEERING_RULE_REGISTRY_DESIGN.md` | IN_REVIEW | EXISTING / FORMALLY REGISTERED | Engineering Team - accountable owner assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-112 | Machine Readiness Check Design | `docs/112_MACHINE_READINESS_CHECK_DESIGN.md` | DRAFT | EXISTING / FORMALLY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-113 | Digital Weld Passport Design | `docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md` | DRAFT | EXISTING / FORMALLY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-114 | Registry + MRC + DWP Implementation Architecture Plan | `docs/114_REGISTRY_MRC_DWP_IMPLEMENTATION_PLAN.md` | DRAFT | EXISTING / FORMALLY REGISTERED | Assignment pending | Architecture, Security, Data Owner | PENDING | None |
| SDS-115 | Evidence Verification Authority Policy | `docs/115_EVIDENCE_VERIFICATION_AUTHORITY_POLICY.md` | DRAFT | FILE PRESENT / DRAFT | İlhan Çekiç (Security/Governance Owner) | Project Owner / Accountable Human Owner | PENDING | None |

### 7.1 SDS-115 review metadata

- Version: `0.1 Draft`.
- Formal status: `DRAFT` because the document-approval governance changed.
- Document-approval model: `SOLO_PROJECT_OWNER_APPROVAL`.
- Required formal document approver: Project Owner / Accountable Human Owner.
- Accountable human owner: İlhan Çekiç.
- Owner role: Security/Governance Owner.
- Fresh review-content reference: `PENDING` until the governance revision is
  committed; the future reference must identify that exact committed policy.
- Required owner approval: `PENDING`.
- Document-owner self-approval: permitted for this solo-project profile after
  the fresh review-content reference is established.
- Prior Architecture approval status:
  `HISTORICAL / SUPERSEDED — PRIOR REVIEW CYCLE`.
- Architecture approver: İlhan Çekiç.
- Architecture approval role: Architecture.
- Architecture approval UTC timestamp: `2026-08-26T09:10:11.889Z`.
- Architecture approved version: `0.1 Draft`.
- Prior Architecture reviewed normative content reference:
  `24fd85b6f16e961bf165d65b46b7555c715a57fd:docs/115_EVIDENCE_VERIFICATION_AUTHORITY_POLICY.md`.
- Prior Architecture evidence is preserved at commit
  `b159cf1b493fcf740a6b3380143ade0d2224d05d`, path
  `docs/approvals/SDS_115_ARCHITECTURE_APPROVAL_0_1_DRAFT.md`, SHA-256
  `5d9df8f6f249f4348d0ac79922e434055de81e3a90fc1735a6adc0114cec0cab`.
- Architecture, Security, and Data Owner advisory reviews: optional and not
  formal SDS-115 document-approval gates.
- Runtime verification separation of duties: unchanged and mandatory.
- `IMPLEMENTATION_UNLOCKED = NO`.
- `MIGRATION_0006_ALLOWED = NO`.

## 8. Reconciliation record

- The prior SDS-100 subject labels for SDS-103 through SDS-109 conflicted with
  the files present in the repository. The canonical registry now uses the
  existing document titles and paths.
- SDS-110 remains allocated to Recommendation Engine and is explicitly
  reserved; its absence does not make the number reusable.
- SDS-111 through SDS-114 are formally registered without changing their file
  contents or implying formal approval.
- SDS-115 is registered for the Evidence Verification Authority Policy. Its
  file is present in `DRAFT` state following a normative document-governance
  revision. File presence and owner assignment do not approve that policy.
- The legacy duplicate prefixes `00` through `30` remain outside the governed
  SDS namespace and do not affect this registry.

## 9. Architecture rules

- Domain code must not depend on FastAPI.
- Domain code must not depend on SQLAlchemy.
- Domain code must not depend on environment variables.
- Engineering evidence, production authority, and implementation permission
  are granted only by the applicable approved governed documents and gates,
  never by a filename, draft status, code constant, or index reservation.

---

End of Document
