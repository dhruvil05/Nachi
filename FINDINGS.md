# nexus-a2a findings

Problems Nachi ran into while using nexus-a2a: bugs, missing hooks, and confusing docs
or errors. Each entry gets an upstream issue, then a fix and release; the Nachi
workaround is deleted when the fix ships.

| # | Date | Kind | Version | Status |
|---|---|---|---|---|
| 1 | 2026-11-13 | Doc bug | 2.1.0 | Open |
| 2 | 2026-11-13 | Confusing API | 2.1.0 | Open |
| 3 | 2026-11-13 | Confusing error | 2.1.0 | Open |
| 4 | 2026-11-13 | Missing packaging | 2.1.0 | Open |
| 5 | 2026-11-13 | Confusing API | 2.1.0 | Open |
| 6 | 2026-11-13 | Missing feature | 2.1.0 | Open |

## 1. README still shows `AuthManager(allow_unregistered=True)`

- **Where:** README.md line 648, "Authentication" → the "Auth fails closed" note.
- **Symptom:** the snippet `AuthManager(allow_unregistered=True)  # old behaviour, dev only`
  raises `TypeError` since 2.0 (`security/auth.py` refuses the argument). Anyone copying
  it gets a crash.
- **Fix:** replace it with `AuthManager(default=AgentCredentialConfig(scheme=AuthScheme.NONE))`,
  as MIGRATING.md already says.
- **Nachi workaround:** none needed; Nachi registers every caller explicitly.

## 2. `RetryConfig(max_retries=0)` sends nothing and reports "unreachable: unknown"

- **Where:** `transport/http_client.py`, `RetryConfig` and the RPC loop.
- **Symptom:** `max_retries` is documented as "maximum number of attempts (including the
  first)", so `0` runs the loop zero times. The client then raises
  `AgentUnreachableError("... is unreachable: unknown")` without making any request. The
  name reads as "retries after the first", so `0` looks like "no retries".
- **Found by:** every Nachi contract test failed with "unreachable: unknown" until the
  helper switched to `max_retries=1`.
- **Fix options:** rename to `max_attempts` (keep `max_retries` as a deprecated alias with
  the old meaning), or reject values below 1 with a clear `ValueError`.
- **Nachi workaround:** `tests/support/agents.py` uses `RetryConfig(max_retries=1)`.

## 3. A refused credential surfaces as `AgentUnreachableError`

- **Where:** `transport/http_client.py`, the 4xx branch of the RPC loop.
- **Symptom:** a 401 or 403 from the server becomes
  `AgentUnreachableError("... is unreachable: HTTP 401 (client error)")`. Callers cannot
  tell "my key was refused" or "the trust rule denied this skill" from "the agent is
  down" without matching on the message text, and the word "unreachable" is misleading.
- **Fix:** raise a dedicated subclass, e.g. `AgentRefusedError(TransportError)` carrying
  `status_code`, for 401/403 (and 413/429), keeping it a `TransportError` for
  compatibility.
- **Nachi workaround:** contract tests match `"401"` / `"403"` in the message.

## 4. No `py.typed` marker, so users get no types

- **Where:** the `nexus_a2a` package.
- **Symptom:** the library passes `mypy --strict` itself (1.9 changelog), but ships no
  `py.typed`. Downstream mypy reports `import-untyped` and treats every nexus-a2a name
  as `Any`, losing all that typing work.
- **Fix:** add an empty `nexus_a2a/py.typed` and include it in the wheel; add the
  `Typing :: Typed` classifier.
- **Nachi workaround:** a mypy override in `pyproject.toml` with
  `follow_untyped_imports = true`, to be removed once the marker ships.

## 5. A structured result streams as an unlabelled text chunk

- **Where:** `message/stream` for a non-streaming agent (`A2AServer`, SSE path).
- **Symptom:** when a non-streaming agent returns a `dict`, the stream delivers it as one
  `artifact_chunk` whose `content` is the JSON text. A client cannot tell "the agent
  streamed this text" from "this is the structured result" without trying to parse
  every chunk. Nachi's web page showed the Diagnostician's raw placement JSON as if it
  were feedback.
- **Fix:** label chunks with their part type (e.g. `"type": "json"` and the content as an
  object), or send a structured result as an `artifact_complete` event instead of a chunk.
- **Nachi workaround:** `gateway/service.py` drops chunks that parse as a JSON object or
  array (`_is_structured`) and reads results from the settled task.

## 6. No durable task store without Redis or Postgres

- **Where:** `nexus_a2a.storage`.
- **Symptom:** the only stores that survive a restart need an external server. Local
  development and single-machine setups (and machines without Docker) cannot test
  "a paused multi-turn task survives a restart" at all.
- **Fix:** ship a SQLite store. Nachi's `src/nachi/core/store.py` (about 90 lines, public
  `AbstractTaskStore` only, the whole `Task` as JSON like `PostgresTaskStore`) can be
  upstreamed as-is.
- **Nachi workaround:** `SqliteTaskStore`, used by every Nachi agent by default.
