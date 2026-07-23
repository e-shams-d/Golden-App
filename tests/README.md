# Cross-application tests

Application-local unit tests live next to their source. This directory is reserved for
tests that cross a deployment boundary or verify a repository-wide contract.

- `contract/`: OpenAPI, generated-client, error-envelope, and catalogue compatibility
- `integration/`: PostgreSQL/Redis/storage integration behavior
- `e2e/`: browser and complete workflow tests
- `security/`: RBAC, ownership, privacy, and abuse-case tests
- `fixtures/`: synthetic-only fixtures; no real trader, bank, or personal data
