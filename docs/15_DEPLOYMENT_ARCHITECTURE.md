# Deployment Architecture

## Development
Docker Compose:
- frontend
- backend
- PostgreSQL

## Production
Recommended:
- Nginx or approved reverse proxy
- FastAPI workers
- PostgreSQL managed or on-premise
- encrypted backups
- central logging
- health checks
- customer-specific secret management

On-premise deployment is a first-class requirement.
