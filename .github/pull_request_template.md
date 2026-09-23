## What and why

## Checklist

- [ ] The title follows Conventional Commits (`feat: …`, `fix: …`).
- [ ] Tests cover the change; a new firewall rule has an attack case that only it stops.
- [ ] `uv run ruff check . && uv run basedpyright && uv run lint-imports && uv run pytest` passes.
- [ ] Not a security bypass report: those go through [SECURITY.md](../SECURITY.md).
