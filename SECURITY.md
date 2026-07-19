# Security Policy

## Supported version
Only the latest released version is actively maintained.

## Reporting
Report vulnerabilities privately to the repository owner. Do not publish
credentials, customer data, OEM standards, proprietary datasets, or exploit details.

## Required production controls
- Replace all default credentials.
- Use a secret manager for JWT and database credentials.
- Enforce HTTPS.
- Restrict CORS.
- Apply least-privilege database accounts.
- Back up PostgreSQL and verify restoration.
- Store customer/OEM files outside public repositories.
