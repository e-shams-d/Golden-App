# Infrastructure baseline

This directory contains the M1 local/pilot topology. It is intentionally separate from
production approval and contains no real secrets, certificates, bank data, or trader
data.

## Layout

```text
compose/   explicit Compose entry points
docker/    pinned application and ingress Dockerfiles
nginx/     local reverse-proxy configuration
redis/     non-authoritative broker configuration
scripts/   provider-neutral verification commands
```

`compose.local.yml` publishes only Nginx on loopback port 8080. PostgreSQL and Redis
exist only on the internal data network. The backend and frontends exist only on the
internal application network.

For production, replace tag pins with reviewed multi-architecture digests, provide
external secret management, TLS, encrypted off-server backups, monitoring ownership,
and the approved private-storage adapter. The local bind mounts are not a production
storage design.
