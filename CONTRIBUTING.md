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
uv run forbql schema sync bank-postgres --policy deploy/demo/forbql.yaml
uv run forbql knowledge sync bank-postgres deploy/demo/knowledge.yaml \
  --policy deploy/demo/forbql.yaml
uv run forbql knowledge search "сколько денег на счетах" --policy deploy/demo/forbql.yaml \
  --connection bank-postgres --profile analyst
uv run forbql run "SELECT count(*) FROM accounts" \
  --policy deploy/demo/forbql.yaml --connection bank-postgres --profile analyst
uv run forbql audit verify
```

The DSN is read from standard input or a hidden prompt, never from the command line.

To change the key, make a new one and seal every DSN again with it, then restart forbql
with the new key; until the restart, a session that opens a DSN is refused with both key
ids:

```bash
export FORBQL_OLD_SECRET_KEY=$FORBQL_SECRET_KEY
export FORBQL_SECRET_KEY=$(uv run forbql store keygen)
uv run forbql store rekey
```

With a store, a session sees only what is both in the database and in the schema the
operator synced last: `forbql schema sync` keeps a new version and prints what changed,
`forbql schema diff` shows what changed since, and a table or column added in between
stays unseen until the next sync. `forbql schema erd <connection> --profile <profile>`
prints a Mermaid diagram of what that profile sees (`--around <table>` for large
schemas).

`schema sync` also indexes the schema for search: one document per table and per column,
embedded locally by `Qwen/Qwen3-Embedding-0.6B-Q`, which the first sync downloads (about
1.1 GB, into fastembed's cache; `FASTEMBED_CACHE_PATH` moves it). Search fuses meaning and
words, and never ranks what the profile cannot see. `forbql knowledge reindex` embeds
everything again. The store needs pgvector, which only a superuser can create: the stand
does it; elsewhere run `CREATE EXTENSION vector;` in the store's database first. The
search bar — 95% of the questions in `tests/data/search` find every table they need —
is a live test.

A knowledge file (`deploy/demo/knowledge.yaml`) holds a connection's glossary and
examples, kept in git beside the policy. A term has a definition and, optionally, one
expression over one table (`status = 'open'`); an example is a question and a full query.
`forbql knowledge sync` loads the whole file or nothing: it checks every entry under every
profile against the synced schema, prints who sees what, and refuses an entry no profile
may see; entries gone from the file leave the store. Search shows a profile a term or an
example only if its SQL passes that profile's firewall and its text names no table or
column hidden from it. `schema sync` names entries that a schema change left unseen.

### The MCP server

`forbql mcp` serves one profile of one connection to an MCP client over stdio (it needs
the `mcp` extra). The agent gets four read-only tools — `search_schema`,
`describe_table`, `check_sql`, `run_sql` — plus `propose_example`, and three resources:
`forbql://erd`, `forbql://erd/{table}` and `forbql://glossary`. The server's instructions tell the
model the profile's rules and its tables; rows, comments, glossary text and examples
reach it inside an `<untrusted-data>` block. A result holds at most 200 rows (fewer if
the profile's `max_rows` is lower) and about 30 KB, and says what cut it. A query the
planner finds expensive runs only if the person at the client says yes; a client that
cannot ask means no. Every call, a search or a read included, leaves an audit record
naming its kind. The session opens on the first call: if it cannot, every call says
why, and the next call after the fix opens it without a restart.

Claude Code, from the stand above (`claude mcp add` stores the variables):

```bash
claude mcp add forbql-bank \
  -e FORBQL_STORE_DSN=$FORBQL_STORE_DSN -e FORBQL_SECRET_KEY=$FORBQL_SECRET_KEY \
  -- uv run --directory "$PWD" forbql mcp --policy "$PWD/deploy/demo/forbql.yaml" \
  --connection bank-postgres --profile analyst
```

Claude Desktop starts servers without your shell: give absolute paths, and an
absolute `FORBQL_AUDIT_LOG` if there is no store. The first search downloads the
embedding model; `forbql schema sync` or `forbql knowledge reindex` does it beforehand.

```json
{
  "mcpServers": {
    "forbql-bank": {
      "command": "/absolute/path/to/forbql/.venv/bin/forbql",
      "args": ["mcp", "--policy", "/absolute/path/to/forbql.yaml",
               "--connection", "bank-postgres", "--profile", "analyst"],
      "env": {"FORBQL_STORE_DSN": "postgresql://…", "FORBQL_SECRET_KEY": "…"}
    }
  }
}
```

Tokens let HTTP clients in. A token is
`fql_<id>_<secret>`; the store keeps its id and a hash of its secret, so it is printed
once. It expires (90 days by default, a year at most) and may do only what its grants
say: `connection:profile:capability[,capability]` with `schema.read`, `sql.check`,
`sql.run`, `knowledge.propose`.

```bash
uv run forbql token create agent --policy deploy/demo/forbql.yaml \
  --grant bank-postgres:analyst:schema.read,sql.check,sql.run
uv run forbql token list
uv run forbql token revoke <id>
```

`forbql mcp --http` serves the same profile over HTTP with those tokens (the store is
required: tokens live there). Every request is checked against the store, so a revoked
token stops at once; a token with no grant on this profile gets 403 and says so, any
other refusal is 401. A token's refusals are audited as `access.denied`; a token the
store does not know is only logged, so nobody without one can grow the audit chain.
Tools a token has no capability for are hidden (`search_schema` and `describe_table`
need `schema.read`, `check_sql` needs `sql.check`, `run_sql` needs `sql.run`,
`propose_example` needs `knowledge.propose`). Each
token may make 10 requests a second (20 at once) and run one query at a time. Plain
HTTP listens only on the loopback: elsewhere give `--tls-cert` and `--tls-key` with the
`--public-url https://…` clients use, or put a proxy that terminates TLS in front and
give its `--public-url`. `Host` and
`Origin` must match, bodies are capped at 1 MB, and a token in the URL is refused.
Over HTTP an expensive query is stopped rather than asked about, since the client may
be the agent's own code; `--ask-to-confirm` asks the person at the client instead.

```bash
uv run forbql mcp --http --policy deploy/demo/forbql.yaml \
  --connection bank-postgres --profile analyst --port 8765
claude mcp add --transport http forbql-bank http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer ${FORBQL_TOKEN}"
```

Keep the token in an environment variable: written into `.mcp.json` it ends up in git.
In docker publish the port on the loopback (`-p 127.0.0.1:8765:8765`); a plain
`-p 8765:8765` listens on every interface and passes the host firewall.

An agent that wrote a query worth keeping offers it with `propose_example`: a question
and its query, checked under the agent's profile and kept in the store until you decide,
at most 20 waiting per token (or per local user over stdio). Read each one in full
before approving: the question reaches every agent that searches, and a query can look
right and answer something else. `list` prints hidden characters escaped.

```bash
uv run forbql examples list
uv run forbql examples approve 1 --policy deploy/demo/forbql.yaml
uv run forbql examples reject 2 --policy deploy/demo/forbql.yaml
```

Approval checks the example again under its proposer's profile, then search shows it to
every profile that may see it; rejecting an approved one takes it back out. Both are
audited. `forbql knowledge sync` leaves approved examples in place and refuses a file
that repeats one.

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

The other side is what the firewall refuses that it should not.
[`attacks/legitimate/REPORT.md`](attacks/legitimate/REPORT.md) counts it over the demo
bank's queries and over Spider's, and a test fails when the report no longer matches the
firewall. After changing a rule or a legitimate corpus, regenerate it and read the diff:

```bash
uv run python tests/support/false_blocks.py
```

Hypothesis spoils corpus queries the ways parsers and databases disagree: comments,
quotes, dollar strings, escapes, case, odd whitespace. Whatever the firewall lets
through must pass its checks again unchanged, and the database's own planner must read
no table the profile does not see. Pull requests run a few hundred examples; the
nightly workflow runs twenty thousand, and every supported PostgreSQL and MySQL version
under the live suite. A nightly finding prints only its seed: replay it with
`HYPOTHESIS_PROFILE=nightly` and `--hypothesis-seed`, and add the query to the corpus
before fixing it.

## Commits and pull requests

Commit messages and PR titles follow Conventional Commits (`feat:`, `fix:`, `docs:`,
`test:`, `refactor:`, `build:`, `ci:`, `chore:`; `!` for breaking changes). The PR
title becomes the squashed commit, and the changelog is built from those.

## Security

Found a bypass? Do not open an issue: follow [SECURITY.md](SECURITY.md).