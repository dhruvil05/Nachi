# Nachi

An adaptive Socratic tutor for self-learners, built as a network of A2A agents on
[nexus-a2a](https://github.com/dhruvil05/nexus-a2a). Named after Nachiketa, the boy in
the Katha Upanishad who kept questioning Yama until he got real answers.

Nachi has a second job: it is nexus-a2a's first real user. Every agent runs as its own
service on its own port or machine, so the library is tested on a real network. Library
problems found along the way are logged in [FINDINGS.md](FINDINGS.md).

**Status:** Phase 1 (MVP agents on T0/T1). Intro Python, English, one learner at a time.

## How it works

```
browser ──HTTP──▶ gateway ──A2A──▶ Diagnostician   placement check (multi-turn)
                     │      ──A2A──▶ Socratic Tutor ──A2A──▶ Grader
                     │                               └─A2A──▶ Explainer
                     │      ──A2A──▶ Review Scheduler (SM-2)
                     └── learner DB (students, mastery, attempts, cards, sessions)
```

| Service | Port (T1) | Skill | What it does |
|---|---|---|---|
| gateway | 8000 | | Web page + API; the only thing learners talk to |
| diagnostician | 8101 | `diagnose` | Binary-searches the curriculum with multiple-choice probes |
| tutor | 8102 | `tutor` | Guiding questions, hints, re-teaching; streams feedback |
| explainer | 8103 | `explain` | Short explanation, optionally aimed at a misconception |
| quizmaker | 8104 | `quiz` | Questions of one type about one concept |
| grader | 8105 | `grade` | Exact grading for objective answers, rubric + LLM otherwise |
| scheduler | 8106 | `schedule_review` | SM-2 spaced repetition, no LLM |

Every call between services is authenticated with the caller's own API key and checked
against the trust rules in `src/nachi/core/identity.py`. Multi-turn agents keep all state
in the task history and their tasks in a SQLite store, so restarting an agent mid-session
loses nothing.

## Setup

Nachi expects the nexus-a2a checkout next to it (`../nexus-a2a`).

```bash
uv sync                  # uses the local ../nexus-a2a checkout
uv sync --no-sources     # uses the published nexus-a2a release from PyPI instead
uv run python scripts/gen_keys.py topologies/t1-ports.toml   # one API key per service
```

## Run it (setup T1: every service its own process)

```bash
NACHI_LLM=demo uv run python scripts/run_t1.py    # no API key, canned content
uv run python scripts/run_t1.py                   # real Claude (needs ANTHROPIC_API_KEY)
```

Open http://127.0.0.1:8000. With `NACHI_LLM=demo`, the right multiple-choice answer is
always the concept's title (option A) and every other answer is `demo`.

Any service can also run alone, e.g. `uv run python -m nachi.agents.tutor --topology
topologies/t1-ports.toml`. Stop one while `run_t1.py` is running and the rest keep going,
which is how to try the fault scenarios by hand.

Models: the Tutor uses Claude Sonnet 5.5 (with server-side refusal fallbacks); everything
else uses Claude Haiku 5.5. Override with `NACHI_MODEL_DEEP` / `NACHI_MODEL_FAST`.

## Tests

```bash
uv run pytest                                          # everything (no API calls)
uv run pytest -m "not contract and not flow and not fault"   # unit only
uv run pytest -m "flow or fault"                       # whole network, restarts
uv run python evals/run_grader_eval.py                 # real-model grader eval (costs money)
```

CI never calls a real model: tests use a scripted `FakeLLM` or the deterministic `DemoLLM`.

## Rules for working on Nachi

- **Public nexus-a2a API only.** Import from `nexus_a2a` itself, never from its
  submodules or private names. `tests/unit/test_public_api.py` enforces this. If Nachi
  needs something that is not exported, that is a finding: log it in `FINDINGS.md`.
- **Real security everywhere.** Never pass `allow_insecure=True`, even locally.
- **Agents find each other by skill and topology, never by hard-coded URL.**
- **Learners never see answers.** Agents put answers in JSON; the gateway forwards only
  the agent's text and the public form of a question.
