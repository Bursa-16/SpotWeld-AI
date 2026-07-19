# Database Design

## Core tables
- users
- projects
- weld_points
- weld_point_revisions
- approvals
- test_results
- audit_logs

## Recommended extensions
- analysis_runs
- analysis_inputs
- analysis_outputs
- engineering_models
- model_versions
- rule_packages
- rule_versions
- failure_probability_results
- calibration_datasets

## Data retention
Engineering inputs, outputs, model version, and rule source should be retained
together so historical results remain reproducible.
