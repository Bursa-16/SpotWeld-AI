# Evidence Verification Authority Policy

**Document ID:** SDS-115
**Title:** Evidence Verification Authority Policy
**Version:** 0.1 Draft
**Formal Status:** APPROVED
**Canonical Path:** `docs/115_EVIDENCE_VERIFICATION_AUTHORITY_POLICY.md`
**Accountable Human Owner:** İlhan Çekiç
**Owner Role:** Security/Governance Owner
**Document Approval Model:** SOLO_PROJECT_OWNER_APPROVAL
**Required Formal Document Approver:** Project Owner / Accountable Human Owner
**Optional Advisory Review Roles:** Architecture, Security, Data Owner
**Approval State:** APPROVED / RECORDED
**Fresh Reviewed Normative Content Reference:** `866782f98b3f868fceb688186fadfd670ad8b390:docs/115_EVIDENCE_VERIFICATION_AUTHORITY_POLICY.md`
**Review Reference Identifies Normative Content:** YES
**Future Metadata-Transition Commit Is Review Reference:** NO
**Owner Assignment Grants Approval:** NO
**IN_REVIEW Transition Grants Approval:** NO
**Document Owner Self-Approval Permitted:** YES, for this solo-project document
governance profile after a fresh review-content reference is established.
**Runtime Verification Authority Granted:** NO
**Runtime Separation-of-Duties Bypass:** NO
**Supersedes:** None

## 1. Purpose

This policy defines the governance authority required to submit and to review
or verify an exact Engineering Rule Registry evidence revision. It refines the
authority prerequisite established by SDS-111 and SDS-114. It does not modify
those documents and grants no engineering or implementation authority while
its formal status remains `DRAFT` or `IN_REVIEW`.

This document is policy only. It creates no database schema, migration, source
code, API, frontend behavior, engineering threshold, rule promotion, rule
enablement, or rule activation.

## 2. Normative language

The terms **must**, **must not**, **required**, and **prohibited** are normative.
The terms **may** and **future** identify permitted or deferred possibilities
and do not grant authority.

For this policy:

- **EvidenceReference revision** means one exact immutable Registry evidence
  revision, never a mutable or latest lookup.
- **submitter** means the durable human User who creates or submits that exact
  evidence revision.
- **verifier** means the durable human User making the authoritative
  verification decision.
- **delegation** means an explicit, scoped, effective-dated grant of the
  governed capability to a durable human User.
- **decision chain** means the pinned evidence revision, verification decision,
  authority snapshot, idempotency receipt, and governed audit lineage associated
  with one governed verification action and its append-only corrections.

## 3. Policy scope and capability boundary

SDS-115 governs only:

1. evidence submission; and
2. evidence review and verification.

Role eligibility and capability authority remain distinct. This policy does
not merge evidence submission with evidence review or verification.

The following capabilities and workflows are explicitly deferred:

- a separate evidence approval workflow;
- a formal evidence rejection lifecycle;
- `SOURCE_BACKED` promotion;
- rule enablement;
- rule activation;
- rule lifecycle authority beyond submission and verification;
- governed applicability resolution;
- governed comparison or evaluation orchestration; and
- rule-evaluation persistence.

## 4. Authority subject and assignment

1. A role provides eligibility only. Role membership alone does not grant
   engineering-review or evidence-verification authority.
2. Authoritative verification requires an explicit scoped delegation to a
   durable human `User` identity.
3. The verifier's durable User identity must be resolved and preserved. A
   display name, email string, token subject, role name, or transient session
   identity is not sufficient by itself.
4. `System Admin`, wildcard permission, or another administrative role does not
   constitute engineering-review authority.
5. A service, system, automated agent, or AI identity must not make an
   authoritative human evidence-verification decision.
6. Automated systems may support non-authoritative validation or workflow only
   when a future implementation contract permits it; they must not be recorded
   as the human verifier.

## 5. Authority scope

The only authority-scope dimensions approved by this policy are:

- customer;
- project;
- site; and
- machine.

Every verification request must be matched explicitly against the verifier's
effective delegated scope and the governed resource context.

- Scope matching is fail-closed.
- No implicit global wildcard exists.
- Ambiguous scope inheritance fails closed.
- An unsupported scope dimension fails closed.
- A missing governed resource scope fails closed.
- A scope match must not be inferred from role, administrative access, object
  visibility, or possession of a document.

This policy does not approve rule family, EngineeringRule identity,
EngineeringRuleRevision identity, evidence class, evidence source type,
applicability domain, organization, or global authority as additional
delegation-scope dimensions.

## 6. Delegation lifecycle

A verification delegation must be:

- explicit;
- granted to one durable human User;
- limited to the governed capability and approved resource scope;
- effective-dated;
- expiring;
- revocable; and
- non-redelegable.

A delegation is invalid when it is:

- not yet effective;
- expired;
- revoked;
- malformed;
- ambiguous;
- outside the requested resource scope; or
- missing any required capability, scope, identity, or effective-time data.

The delegate must not re-delegate the capability. A new grant requires a new
authorized delegation action and its own governed history.

## 7. Separation of duties

1. The creator or submitter of an EvidenceReference revision must not verify
   that same evidence revision.
2. The separation check must use durable identities and the exact pinned
   evidence revision. Display-name comparison is insufficient.
3. Missing or ambiguous separation proof fails closed.
4. Administrative status creates no separation-of-duties bypass.
5. A verifier must not later use the same governed decision chain to exercise
   `SOURCE_BACKED` promotion or rule-activation authority.
6. Promotion and activation remain deferred. This clause preserves their
   future separation boundary and does not design or authorize either workflow.

## 8. Verification decision semantics

`VERIFIED` is the only successful authoritative outcome approved by SDS-115.

An incomplete, unsuccessful, unauthorized, invalid, or otherwise nonqualifying
attempt:

- leaves the evidence unverified;
- may record a reason or rationale;
- must not be represented as successful; and
- must not create a formal `REJECTED`, `NEEDS_CORRECTION`, or `WITHDRAWN`
  evidence state.

Those additional outcome names are not part of this policy. A future approved
policy is required before any of them can acquire formal meaning.

Verification is the sole authoritative decision defined in this stage. No
separate evidence-approval decision or approval workflow is defined.

## 9. Exact evidence-revision pinning

Every authoritative verification decision must reference exactly one immutable
EvidenceReference revision by its durable identity and revision.

The decision must not depend on:

- latest evidence;
- current evidence;
- a mutable pointer without a pinned revision; or
- a query whose result may change during historical reconstruction.

Historical reconstruction must resolve the exact pinned EvidenceReference
revision and the decision-time authority evidence. A newer evidence revision
must not change the meaning or result of a prior verification decision.

## 10. Immutability and append-only correction

Historical EvidenceReference rows and verification decisions are immutable.
No evidence content or authoritative decision may be corrected in place.

### 10.1 Decision-only correction

When the evidence content remains unchanged but a verification decision needs
correction:

1. create a new append-only verification decision;
2. link or supersede the prior verification decision;
3. preserve the prior decision unchanged; and
4. preserve the reason and complete governed lineage for the correction.

### 10.2 Evidence-content correction

When evidence content needs correction:

1. create a new EvidenceReference revision;
2. link it to the prior evidence revision using the governed supersession
   contract;
3. preserve the prior evidence revision unchanged; and
4. create a new verification decision pinned to the new evidence revision.

A verification decision for an earlier revision must never be transferred,
copied as authority, or silently treated as verification of a later revision.

## 11. Decision-time authority snapshot

Every successful authoritative verification decision must durably preserve or
immutably reference a decision-time authority snapshot containing:

- durable human User identity;
- role snapshot;
- capability exercised;
- authority scope;
- delegation identity or durable reference;
- authority source;
- delegation effective interval;
- policy identifier and version;
- decision timestamp;
- correlation identity; and
- versioned integrity metadata.

The snapshot must prove the authority used for that exact decision as of the
decision time. A later role, scope, delegation, or policy change must not alter
the historical snapshot.

The exact SQL shape, persistence table layout, serialization, canonicalization,
integrity algorithm, and hash implementation are deferred implementation
details. They must not weaken or omit the normative snapshot content.

## 12. Deny-by-default policy

Verification must be denied when authority evidence is:

- missing;
- unknown;
- malformed;
- ambiguous;
- expired;
- revoked;
- outside its effective interval;
- scope mismatched;
- based only on role membership;
- based only on `System Admin` or wildcard permission; or
- missing required separation-of-duties proof.

Unsupported actor, capability, scope, delegation, policy version, or snapshot
data also fails closed. There is no fail-open, assumed-authority, inferred
authority, or administrative-default path.

## 13. Denial audit

Every governed verification authorization denial must generate an auditable
denial record. The record must retain sufficient actor, attempted capability,
resource scope, correlation, policy-version, time, and reason information for
security and governance review, subject to the approved visibility policy.

A denied request must not:

- create a successful verification decision;
- alter an EvidenceReference revision;
- grant, extend, or imply authority; or
- partially publish governed state.

## 14. No administrative or emergency bypass

No engineering-verification bypass exists for:

- `System Admin`;
- wildcard permission;
- emergency administrator; or
- an implicit elevated role.

Possession of administrative access may permit system administration under a
separate policy, but it does not satisfy SDS-115 verification authority.

Any future emergency engineering authority requires a separate formally
approved policy. Until then, an emergency request follows the same fail-closed
delegation, scope, separation, and audit rules as every other request.

## 15. Idempotency and transaction boundary

A future verification implementation must atomically coordinate:

- the persistent idempotency receipt;
- the immutable verification decision;
- the governed audit event; and
- the resulting governed state.

The following invariants apply:

- an identical replay must not create a duplicate verification decision;
- reuse of an idempotency identity with a conflicting request fails closed;
- an in-progress or incomplete command must not appear successful;
- partial authoritative publication is prohibited; and
- transaction ownership remains with the governed unit-of-work architecture.

The policy requires these properties but does not implement them.

## 16. Visibility

1. Evidence and verification visibility follows the governed customer,
   project, site, and machine resource scope.
2. Governed audit visibility requires explicit governance or audit authority.
3. Evidence visibility does not imply verification authority.
4. Audit visibility does not imply engineering authority.
5. Wildcard administration does not create unrestricted engineering authority.
6. Missing or ambiguous visibility scope fails closed.

API, query, filtering, field-level disclosure, and storage enforcement are
deferred implementation details.

## 17. Approval requirements and current state

Formal `APPROVED` status under the `SOLO_PROJECT_OWNER_APPROVAL` profile requires
one explicit approval from the Project Owner / Accountable Human Owner for the
exact current document version and fresh immutable review-content reference.
The approval must record:

- durable approver identity;
- approval role;
- UTC approval timestamp;
- exact approved document version; and
- durable approval evidence or reference.

Architecture, Security, and Data Owner may provide optional advisory reviews,
but they are not mandatory formal document-approval gates for SDS-115.
Document-owner self-approval is permitted for this solo-project profile.

Until the required owner approval exists for the fresh review cycle, SDS-115
remains `DRAFT` or `IN_REVIEW`, grants no implementation authority, and does
not unlock
`EVIDENCE_VERIFICATION_AUTHORITY_FOUNDATION`.

### 17.1 Approval record

| Role | Status | Durable Approver Identity | UTC Approval Timestamp | Approved Version | Approval Evidence / Reference |
|---|---|---|---|---|---|
| Project Owner / Accountable Human Owner | APPROVED / RECORDED | İlhan Çekiç | 2026-08-26T11:11:37.788Z | 0.1 Draft | `path=docs/approvals/SDS_115_PROJECT_OWNER_APPROVAL_0_1_DRAFT.md;sha256=9f4e8c84091c6bfd0565273210449d7721451ca19862c6298e7b1709bdbe1ef0` |
| Architecture advisory | HISTORICAL / SUPERSEDED — PRIOR REVIEW CYCLE | İlhan Çekiç | 2026-08-26T09:10:11.889Z | 0.1 Draft | Original evidence preserved at `b159cf1b493fcf740a6b3380143ade0d2224d05d:docs/approvals/SDS_115_ARCHITECTURE_APPROVAL_0_1_DRAFT.md`, SHA-256 `5d9df8f6f249f4348d0ac79922e434055de81e3a90fc1735a6adc0114cec0cab` |
| Security advisory | OPTIONAL / NOT RECORDED | NOT APPLICABLE | NOT APPLICABLE | NOT APPLICABLE | NOT APPLICABLE |
| Data Owner advisory | OPTIONAL / NOT RECORDED | NOT APPLICABLE | NOT APPLICABLE | NOT APPLICABLE | NOT APPLICABLE |

Only the Project Owner / Accountable Human Owner row records the formal
document approval for this review cycle. Advisory rows do not imply approval.

### 17.2 Recorded Project Owner approval metadata

- Approval role: Project Owner / Accountable Human Owner.
- Durable human approver identity: İlhan Çekiç.
- Approver role and authority: Security/Governance Owner; required formal
  document approver under `SOLO_PROJECT_OWNER_APPROVAL`.
- Decision: `APPROVE`.
- UTC decision timestamp: `2026-08-26T11:11:37.788Z`.
- Approved document version: `0.1 Draft`.
- Reviewed normative content reference:
  `866782f98b3f868fceb688186fadfd670ad8b390:docs/115_EVIDENCE_VERIFICATION_AUTHORITY_POLICY.md`.
- Durable approval evidence reference:
  `path=docs/approvals/SDS_115_PROJECT_OWNER_APPROVAL_0_1_DRAFT.md;sha256=9f4e8c84091c6bfd0565273210449d7721451ca19862c6298e7b1709bdbe1ef0`.
- This decision grants no runtime verification authority, Security bypass,
  implementation authority, or migration 0006 authority.
- SDS-115 is formally `APPROVED`; this status grants no implementation
  authority without the separate implementation-unlock gate.

### 17.3 Historical Architecture approval metadata

- Approval role: Architecture.
- Current status: `HISTORICAL / SUPERSEDED — PRIOR REVIEW CYCLE`.
- Durable human approver identity: İlhan Çekiç.
- Decision: `APPROVE`.
- UTC decision timestamp: `2026-08-26T09:10:11.889Z`.
- Approved document version: `0.1 Draft`.
- Reviewed normative content reference:
  `24fd85b6f16e961bf165d65b46b7555c715a57fd:docs/115_EVIDENCE_VERIFICATION_AUTHORITY_POLICY.md`.
- Original durable approval evidence is preserved at commit
  `b159cf1b493fcf740a6b3380143ade0d2224d05d`, path
  `docs/approvals/SDS_115_ARCHITECTURE_APPROVAL_0_1_DRAFT.md`, SHA-256
  `5d9df8f6f249f4348d0ac79922e434055de81e3a90fc1735a6adc0114cec0cab`.
- The original decision is not erased or falsified. It does not approve the
  normatively changed policy or the new review cycle.
- This historical Architecture approval granted no runtime verification,
  implementation, or migration 0006 authority.

### 17.4 Solo-project document-approval governance

- Required formal document approver: Project Owner / Accountable Human Owner.
- Accountable human owner: İlhan Çekiç.
- Owner role: Security/Governance Owner.
- One explicit owner `APPROVE` decision is sufficient after a fresh immutable
  review-content reference is established.
- Document-owner self-approval is permitted for this solo-project profile.
- AG-01 and AG-02 are superseded only for their three-distinct-human and
  owner-overlap requirements governing SDS-115 document approval.
- Runtime evidence-verification separation of duties and all runtime authority
  controls remain unchanged.

## 18. Implementation unlock gate

`EVIDENCE_VERIFICATION_AUTHORITY_FOUNDATION` may begin only after:

1. the SDS-115 policy text is complete;
2. an accountable durable human owner is assigned;
3. a fresh immutable review-content reference is established after this
   governance revision is committed;
4. the owner has explicitly approved that exact document version and review
   reference with a UTC timestamp and durable approval evidence;
5. SDS-115 is formally transitioned to `APPROVED` under SDS-100 governance;
   and
6. a separate implementation-unlock gate check explicitly authorizes the next
   implementation stage.

Until every condition is satisfied:

```text
IMPLEMENTATION_UNLOCKED = NO
MIGRATION_0006_ALLOWED = NO
EVIDENCE_VERIFICATION_AUTHORITY_FOUNDATION = BLOCKED
```

Committing this governance revision, assigning the accountable owner,
transitioning to `IN_REVIEW`, recording the review reference, or approving the
document does not by itself satisfy the separate implementation-unlock gate.

## 19. Explicit non-goals

SDS-115 does not authorize or implement:

- `SOURCE_BACKED` promotion;
- a separate approval workflow;
- a formal `REJECTED` lifecycle;
- rule enablement;
- rule activation;
- rule lifecycle-transition authority;
- governed applicability resolution;
- governed comparison orchestration;
- RuleEvaluation persistence;
- MRC publication;
- DWP publication;
- API authorization design;
- frontend behavior;
- engineering thresholds; or
- AI or system engineering authority.

It also does not define migration 0006 or any database, application, domain,
repository, service, API, or frontend implementation.

## 20. Traceability

SDS-115 refines the governance prerequisite for evidence verification. It does
not modify or supersede SDS-111, SDS-112, or SDS-114.

| Source | Relevant design basis | SDS-115 refinement |
|---|---|---|
| SDS-111, Sections 3.2 and 4 | Human review before `SOURCE_BACKED`; evidence verification in Registry lifecycle; immutable version history | Defines who may make the human verification decision and how authority fails closed |
| SDS-111, Sections 6 and 9–10 | Supersession, audit, traceability, and historical rule/evidence behavior | Requires exact revision pinning and append-only decision/evidence correction |
| SDS-114, Sections 4.5 and 5.2 | Frozen actor/authority metadata; evidence-review authority and promotion controls | Defines the decision-time authority snapshot while keeping promotion deferred |
| SDS-114, Sections 6 and 10.1–10.3 | `RuleEvidenceService`, atomic evidence verification, audit, idempotency, and historical reconstruction | Locks transaction, denial-audit, pinning, and append-only invariants |
| SDS-114, Sections 11.1–11.3 | Granular permissions, resource scope, explicit delegation, human/service separation, deny-by-default, and separation of duties | Resolves the evidence-verification authority policy decisions without designing APIs |

## 21. Owner-decision trace

| Decision | Policy representation |
|---|---|
| 01 | Role eligibility plus explicit user delegation: Section 4 |
| 02 | Submission and review/verification only: Section 3 |
| 03 | Durable human User only: Section 4 |
| 04 | Customer/project/site/machine fail-closed scope: Section 5 |
| 05 | Effective-dated, expiring, revocable, non-redelegable delegation: Section 6 |
| 06 | Submitter/verifier and future promotion/activation separation: Section 7 |
| 07 | Verification is the sole decision; approval deferred: Section 8 |
| 08 | `VERIFIED` is the only successful outcome: Section 8 |
| 09 | Append-only decision and evidence correction: Section 10 |
| 10 | Full decision-time authority snapshot: Section 11 |
| 11 | Audit every governed authorization denial: Section 13 |
| 12 | No administrative or emergency bypass: Section 14 |
| 13 | Scope-controlled evidence and explicit audit visibility: Section 16 |
| 14 | Security/Governance ownership and solo-project owner document approval: Section 17 |
| 15 | SDS number, status, location, and approval governance: metadata, Sections 17–18, and SDS-100 |

The Project Owner governance revision supersedes AG-01 and AG-02 only for
SDS-115 document approval. It does not supersede or weaken the runtime
separation rules represented in Sections 4–16.

## 22. Final policy state

```text
FORMAL_STATUS = APPROVED
APPROVAL_STATE = APPROVED / RECORDED
DOCUMENT_APPROVAL_MODEL = SOLO_PROJECT_OWNER_APPROVAL
REQUIRED_FORMAL_DOCUMENT_APPROVER = PROJECT OWNER / ACCOUNTABLE HUMAN OWNER
ACCOUNTABLE_HUMAN_OWNER = İLHAN ÇEKİÇ
REQUIRED_OWNER_APPROVAL = APPROVED / RECORDED
PRIOR_ARCHITECTURE_APPROVAL = HISTORICAL / SUPERSEDED — PRIOR REVIEW CYCLE
ARCHITECTURE_ADVISORY_REVIEW = OPTIONAL
SECURITY_ADVISORY_REVIEW = OPTIONAL
DATA_OWNER_ADVISORY_REVIEW = OPTIONAL
RUNTIME_SEPARATION_OF_DUTIES = PRESERVED
IMPLEMENTATION_UNLOCKED = NO
MIGRATION_0006_ALLOWED = NO
EVIDENCE_VERIFICATION_AUTHORITY_FOUNDATION = BLOCKED
SOURCE_BACKED_PROMOTION = DEFERRED
RULE_ENABLEMENT = DEFERRED
RULE_ACTIVATION = DEFERRED
GOVERNED_APPLICABILITY = DEFERRED
RULE_EVALUATION_PERSISTENCE = DEFERRED
```

---

End of Document
