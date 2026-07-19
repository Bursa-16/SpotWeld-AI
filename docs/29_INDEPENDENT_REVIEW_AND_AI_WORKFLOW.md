# Independent Review and AI Workflow

## 1. Roles

### ChatGPT
- planning and architecture integration
- file-level implementation specification
- code/patch preparation
- acceptance criteria
- review consolidation

### Claude
- implementation review
- code-level correctness check
- refactoring suggestions
- test/build verification
- changed-file and regression analysis

### Blackbox
- independent verification
- architecture audit
- CI/security/DevOps review
- second opinion

Blackbox is not the primary remediation agent when its terminal/tool context is unstable.

## 2. Mandatory workflow

```text
Plan
  → Implement
    → Local verification
      → Claude code review
        → Independent Blackbox audit
          → Fix verified issues
            → CI green
              → Commit / push / release
```

## 3. Evidence hierarchy

Highest confidence:
1. reproducible command output
2. automated test result
3. CI result
4. direct code inspection
5. architecture inference
6. documentation claim

Documentation alone cannot establish that a feature works.

## 4. Review classifications

Every review finding must be marked as one of:

```text
VERIFIED_DEFECT
VERIFIED_PASS
ARCHITECTURE_RISK
IMPROVEMENT
UNVERIFIED_ASSUMPTION
OUT_OF_SCOPE
```

## 5. Required review output

- changed files
- exact defects and severity
- evidence or command output
- root cause
- recommended correction
- regression risk
- remaining unknowns
- release readiness

## 6. Claude review gate

Claude must verify:
- requested scope only
- no image-processing features introduced
- no fabricated standard/model claims
- domain boundaries preserved
- tests correspond to real behavior
- README and docs match code
- PowerShell-compatible command usage on Windows
- no secret committed

## 7. Blackbox review gate

Blackbox should be asked to perform review-only tasks when tool execution is unstable:
- architecture review
- security audit
- DevOps/CI audit
- OEM commercial-readiness review
- ASPICE-style traceability review

## 8. Approval rule

A finding becomes an implementation task only when:
- verified by code or execution, or
- accepted explicitly as an architectural improvement.

Conflicting AI findings are resolved by evidence, not model confidence or writing quality.
