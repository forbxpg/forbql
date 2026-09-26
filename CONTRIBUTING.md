# Contributing

## Set up

You need [uv](https://docs.astral.sh/uv/) and, for the local stand, Docker.

```bash
uv sync
uv run pre-commit install
```

`pre-commit install` sets up two hooks: lint and types before each commit, and a check
that the commit message follows [Conventional Commits](https://www.conventionalcommits.org/).

## Checks

All of these must pass; CI runs the same:

```bash
uv run ruff check . && uv run ruff format --check . && uv run basedpyright && uv run lint-imports && uv run pytest
```

Conventions: English everywhere, Google-style docstrings on every module, class and
function, `from __future__ import annotations` in every module, Python 3.12 as the floor.
Only names in `__all__` are public.

## Local stand

```bash
docker compose -f deploy/compose.yaml up -d
```

It starts the service store on `127.0.0.1:55432` and the demo bank on PostgreSQL
(`55433`) and MySQL (`53306`). For SQLite, build a file from the seed:
`sqlite3 bank.db < deploy/demo/sqlite.sql`. The demo role is `forbql_reader` with
password `forbql_reader`; it cannot read `passport` or the `secrets` table. It may read
two views: `account_totals`, which the demo profile lists, and `client_fingerprints`,
which no profile may list: its definition calls `md5` (`hex` on SQLite), outside the
function allowlist, and forbql refuses to open a session for a profile that lists it.

Check what holds before running anything — the role reads only, the listed views pass
the allowlist, the audit log is intact:

```bash
export FORBQL_DSN_BANK_POSTGRES=postgresql://forbql_reader:forbql_reader@127.0.0.1:55433/bank
uv run forbql doctor --policy deploy/demo/forbql.yaml --connection bank-postgres
```

Run a query through the whole pipeline — firewall, read-only engine, masking, audit:

```bash
export FORBQL_DSN_BANK_POSTGRES=postgresql://forbql_reader:forbql_reader@127.0.0.1:55433/bank
uv run forbql run "SELECT region, count(*) FROM clients GROUP BY region" \
  --policy deploy/demo/forbql.yaml --connection bank-postgres --profile analyst
uv run forbql audit verify forbql-audit.jsonl
```

A query the planner expects to cost `confirm_cost` or more (`explain` in the profile)
stops until it is confirmed with `--confirm`; from `block_cost` on it never runs.

The DSN variable is `FORBQL_DSN_` plus the connection name in upper case, with every
other character turned into `_`; `--dsn` overrides it. A profile that masks with `hash`
also needs `FORBQL_MASK_KEY` (32 bytes or more).

`.env.example` lists every variable with values for the stand. forbql never reads
`.env` by itself; copy the example and pass it explicitly:

```bash
cp .env.example .env
uv run --env-file .env forbql run "SELECT count(*) FROM accounts" \
  --connection bank-postgres --profile analyst
```

### The service store

The stand's store keeps forbql's own state: DSNs sealed with AES-256-GCM and the audit
chain. `forbql_owner` owns the `forbql` schema and runs migrations; `forbql_app`, the
runtime role, may add and remove connections and append audit records, never change
one. The live suite uses its own database, `forbql_test`, and empties it per test.

```bash
export FORBQL_STORE_OWNER_DSN=postgresql://forbql_owner:owner-local-only@127.0.0.1:55432/forbql
export FORBQL_STORE_DSN=postgresql://forbql_app:app-local-only@127.0.0.1:55432/forbql
export FORBQL_SECRET_KEY=$(uv run forbql store keygen)
uv run forbql store migrate
echo postgresql://forbql_reader:forbql_reader@127.0.0.1:55433/bank \
  | uv run forbql connection add bank-postgres --engine postgres
uv run forbql run "SELECT count(*) FROM accounts" \
  --policy deploy/demo/forbql.yaml --connection bank-postgres --profile analyst
uv run forbql audit verify
```

The DSN is read from standard input or a hidden prompt, never from the command line.
The tests expect no `FORBQL_*` variables in the shell that runs them.

The seeds are generated. After changing `deploy/demo/generate.py`, run
`uv run python deploy/demo/generate.py` and commit the result; a test fails otherwise.

## The attack corpus

`attacks/` holds one YAML file per attack class; `attacks/legitimate/` holds everyday
queries that must pass.

- Every attack runs against the firewall, which must reject it with the rule the case
  names.
- Attacks that list `effects` also run with the firewall off, straight into the database
  as `forbql_reader`, where each effect must hold: `denied`, `canary_unchanged`,
  `no_secrets`, `bounded`. An attack without `effects` is one the database lets through
  and only forbql stops, so there is nothing to check live; leaving `effects` empty says
  exactly that.

```bash
uv run pytest tests/unit/attacks                     # firewall side, no database
docker compose -f deploy/compose.yaml up -d --wait
uv run pytest -m integration                         # live side
```

To add an attack: pick the class file, add a case with `id`, `why`, `sql`, `rule`, and
`dialects` and `effects` where they apply. If the database cannot stop it yet on some
engine, say so in `pending` with the reason; the test then expects failure there and
fails the day it starts passing. A new firewall rule needs an attack that only it stops:
`tests/unit/attacks/test_every_rule_carries_weight.py` checks that.

## Commits and pull requests

Commit messages and PR titles follow Conventional Commits (`feat:`, `fix:`, `docs:`,
`test:`, `refactor:`, `build:`, `ci:`, `chore:`; `!` for breaking changes). The PR
title becomes the squashed commit, and the changelog is built from those.

## Security

Found a bypass? Do not open an issue: follow [SECURITY.md](SECURITY.md).