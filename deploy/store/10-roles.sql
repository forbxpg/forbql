-- Roles of the service store, for this stand only; passwords are local.
-- forbql_owner owns the schema and runs migrations; forbql_app, the runtime role, gets
-- rows only, as the migrations grant them. forbql_test is the live suite's own store.
CREATE ROLE forbql_owner LOGIN PASSWORD 'owner-local-only';
CREATE ROLE forbql_app LOGIN PASSWORD 'app-local-only';
CREATE DATABASE forbql_test;

\connect forbql
REVOKE ALL ON DATABASE forbql FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE forbql TO forbql_owner, forbql_app;
CREATE SCHEMA forbql AUTHORIZATION forbql_owner;

\connect forbql_test
REVOKE ALL ON DATABASE forbql_test FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE forbql_test TO forbql_owner, forbql_app;
CREATE SCHEMA forbql AUTHORIZATION forbql_owner;
