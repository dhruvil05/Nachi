# Nachi

An adaptive Socratic tutor for self-learners, built as a network of A2A agents on
[nexus-a2a](https://github.com/dhruvil05/nexus-a2a). Named after Nachiketa, the boy in
the Katha Upanishad who kept questioning Yama until he got real answers.

Nachi has a second job: it is nexus-a2a's first real user. Every agent runs as its own
service on its own port or machine, so the library is tested on a real network. Library
problems found along the way are logged in [FINDINGS.md](FINDINGS.md).

**Status:** Phase 0 (foundation). See the design doc for the full plan.

## Layout

```
src/nachi/
  core/         config + topology loader, identity (auth, trust), LLM layer, schemas, serve
  agents/       one package per agent; each runs alone: python -m nachi.agents.<name>
  learner/      learner data model (SQLAlchemy)
curriculum/     intro Python concepts and grading rubrics
migrations/     Alembic migrations for the learner tables
topologies/     where each service runs (T0 one process, T1 ports, T2 containers, T3 servers)
tests/          support fixtures, unit and contract tests
```

## Setup

Nachi expects the nexus-a2a checkout next to it (`../nexus-a2a`).

```bash
uv sync                  # uses the local ../nexus-a2a checkout
uv sync --no-sources     # uses the published nexus-a2a release from PyPI instead
```

Generate local service keys (one API key per service, written to `secrets/`, never committed):

```bash
uv run python scripts/gen_keys.py topologies/t1-ports.toml
```

Run the placeholder agent on its own port (setup T1):

```bash
uv run python -m nachi.agents.echo --topology topologies/t1-ports.toml
```

Check it with nexus-a2a's own conformance tool, as the `probe` service:

```bash
uv run python scripts/verify_agent.py topologies/t1-ports.toml echo
```

## Tests

```bash
uv run pytest                     # unit + contract tests
uv run pytest -m "not contract"   # unit tests only
```

CI never calls a real model: tests use `nachi.core.llm.fake.FakeLLM`.

## Rules for working on Nachi

- **Public nexus-a2a API only.** Import from `nexus_a2a` itself, never from its
  submodules or private names. `tests/unit/test_public_api.py` enforces this. If Nachi
  needs something that is not exported, that is a finding: log it in `FINDINGS.md`.
- **Real security everywhere.** Never pass `allow_insecure=True`, even locally.
- **Agents find each other by skill and topology, never by hard-coded URL.**
