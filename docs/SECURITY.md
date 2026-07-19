# Security and Authorization v0.8

## Token model
- Access token: 30 minutes
- Refresh token: 7 days
- HS256 JWT
- BCrypt password hashing

## Role model
Permissions are enforced at FastAPI dependency level.

## Audit
Login, user creation and test result creation generate audit records.

## Production requirements
- Replace JWT_SECRET_KEY
- Replace default admin password
- Use HTTPS
- Restrict CORS origins
- Configure secure secret management
