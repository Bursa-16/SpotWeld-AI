# Contributing

This is a proprietary engineering product. Contributions require authorization.

## Workflow
1. Create a feature branch from `develop`.
2. Keep domain calculations independent from API and UI layers.
3. Add or update automated tests.
4. Update affected documentation.
5. Open a pull request using the repository template.

## Commit format
- `feat: add failure probability calibration`
- `fix: correct force unit conversion`
- `test: add coated steel regression case`
- `docs: update API contract`

## Engineering rules
- Never invent missing OEM limits or model coefficients.
- Store units explicitly.
- Mark unvalidated models clearly.
- Do not place image-processing code in this repository.
- Any production recommendation must remain traceable to its source and model version.
