# Domain Model

## Main aggregates
- Project
- WeldPoint
- WeldPointRevision
- Approval
- TestResult
- Rule
- EngineeringModel
- AnalysisRun
- FailureProbabilityResult

## Important invariants
- Layer count must match 2T/3T/4T.
- Thickness and parameter units must be explicit.
- Revision snapshots are immutable.
- Approved records require traceable analysis and test context.
- Experimental models cannot silently override OEM/customer rules.
