# Claude Phase Review Prompt

Use this prompt after adding the hierarchy and implementation documents to the repository.

```text
Repository:
https://github.com/Bursa-16/Spot-Welding-Parametre-Assistance

Act as a senior software architect and independent code reviewer.

Product boundary:
This product is only for resistance spot welding parameter analysis.
Do not propose or add image processing, OpenCV, camera inspection, YOLO, CNN, ResNet or weld-image classification.

First read these documents:
- docs/26_PROGRAM_HIERARCHY_AND_STRUCTURE.md
- docs/27_PHASED_IMPLEMENTATION_PLAN.md
- docs/28_ARCHITECTURE_DECISIONS_AND_BOUNDARIES.md
- docs/29_INDEPENDENT_REVIEW_AND_AI_WORKFLOW.md

Then compare those documents with the real repository.

Review objectives:
1. Verify whether the proposed hierarchy matches the existing source tree.
2. Identify contradictions between docs, README and code.
3. Validate the order and scope of Phase 1–4.
4. Check that Phase 1 contains every current release blocker.
5. Identify any missing critical file or test.
6. Check whether proposed DDD/repository/provider boundaries are justified.
7. Detect over-engineering or premature abstractions.
8. Confirm that image-processing scope is excluded everywhere.
9. Verify that model, rule and standards claims remain traceable and honest.
10. Produce a file-by-file implementation roadmap for Phase 1 only.

Do not modify code in this task.
Do not claim execution unless you actually run the command.
Do not trust README without source verification.

Classify every finding as:
- VERIFIED_DEFECT
- ARCHITECTURE_RISK
- IMPROVEMENT
- UNVERIFIED_ASSUMPTION
- OUT_OF_SCOPE

Output:
A. Overall assessment
B. Documentation-code alignment
C. Missing/incorrect hierarchy items
D. Phase plan corrections
E. Phase 1 file-by-file work list
F. Required tests and commands
G. Acceptance criteria
H. Release-readiness decision
```
