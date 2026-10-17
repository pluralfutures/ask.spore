#!/bin/sh
# Dev only: create the login role the API uses (DATABASE_URL). It is not the table
# owner and has no BYPASSRLS, so row-level security applies to every API query.
# Alembic revision 0001 grants its privileges; on other environments the role is
# created by the migration (NOLOGIN) and given LOGIN and a password by the operator.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE askspore_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
  PASSWORD '${APP_DB_PASSWORD}';
SQL
