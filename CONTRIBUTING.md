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
password `forbql_reader`; it cannot read `passport` or the `secrets` table.

The seeds are generated. After changing `deploy/demo/generate.py`, run
`uv run python deploy/demo/generate.py` and commit the result; a test fails otherwise.

## Commits and pull requests

Commit messages and PR titles follow Conventional Commits (`feat:`, `fix:`, `docs:`,
`test:`, `refactor:`, `build:`, `ci:`, `chore:`; `!` for breaking changes). The PR
title becomes the squashed commit, and the changelog is built from those.

## Security

Found a bypass? Do not open an issue: follow [SECURITY.md](SECURITY.md).
