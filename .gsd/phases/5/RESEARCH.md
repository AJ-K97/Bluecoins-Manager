# Research Phase 5: Centralized Persistence

## Current State
- **Database**: PostgreSQL 16 (Docker container `bluecoins_db`)
- **Data**: Populated (65 transactions, 4 accounts)
- **Persistence**: Docker volume `db_data`
- **Network**: Port 5432 exposed

## Objective
Enable robust, multi-machine access to this single database instance.

## Risks & Mitigation
- **Risk**: Schema changes break existing data.
  - **Mitigation**: Implement **Alembic** for schema migrations.
- **Risk**: Container failure loses data (unlikely with volume, but possible).
  - **Mitigation**: Create `backup.sh` script using `pg_dump`.
- **Risk**: Remote connection fails due to config.
  - **Mitigation**: Document LAN access steps and verify `listen_addresses`.

## Plan Strategy
1. **Plan 5.1**: Initialize Alembic and baseline the current schema.
2. **Plan 5.2**: Create backup scripts and remote access documentation.
