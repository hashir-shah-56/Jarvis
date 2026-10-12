# Jarvis

Jarvis is a personal Windows AI desktop assistant project inspired by fictional
assistants such as JARVIS. Its long-term vision is to understand natural-language
instructions, plan bounded tasks, use approved tools, maintain memory, and later
support voice and screen understanding.

**Current version: 0.6.1. Current stage: JARVIS V1 — Stage 6: Bounded Planner & Controller.**
Stage 7 SQLite memory is implemented in the working tree, pending release verification.
The executable version has one canonical source: `core.__version__` in
`core/__init__.py`; application code retrieves it using `get_version()`.


> README.md is the single source of truth for Jarvis. Any implementation task that changes architecture, capabilities, permissions, dependencies, configuration, security behavior, project structure, setup, or supported functionality must update README.md and its changelog in the same task.

## Current capabilities

- Explicit, validated environment-based configuration using an immutable settings model.
- Safe creation of missing runtime directories; existing contents are preserved.
- Reusable JSON-line console and UTF-8 file logging with UTC timestamps, severity,
  component name, and message. Files are appended to, never truncated by startup.
- Quota-free startup, a development text CLI, and sanitized top-level error reporting.
- Provider-independent tool metadata, risk levels, execution results, and permission
  decision vocabulary. These models do not execute or authorize actions.
- Direct-call system, allowlisted application, bounded filesystem, and browser-opening tools.
- Local path and HTTP(S) URL validation, plus sanitized tool failures with stable error IDs.
- An explicit registry of 16 Stage 2 operations plus six Stage 7 memory operations, exact-name lookup, and detached
  JSON-compatible metadata listings.
- A standardized executor that validates structured arguments before invoking a
  registered tool and enforces the `ExecutionResult` return boundary.
- A security gateway using trusted registered risk, explicit policy denials, and
  expiring, single-use, exact-action confirmations for MEDIUM/HIGH operations.
- Sanitized security audit events separate from ordinary application/debug logs.
- A provider-independent AI boundary (`ai/`) with Gemini as the first provider.
  The model may answer conversationally or propose one registered tool call per response.
  All proposals are treated as untrusted input and must pass through Stage 4.
- Gemini integrated using the official `google-genai` SDK (`google-genai==2.28.0`).
  API credentials come only from the `GEMINI_API_KEY` environment variable.
  Manual structured function calling only; SDK automatic execution is disabled.
  All 22 tool declarations derive from `REGISTRY.list_metadata()` — no second list.
  Confirmation APIs (`confirm_execution`, `reject_confirmation`) are never exposed.
- Bounded tool-result sanitization: only JSON-compatible data from successful
  executions crosses the provider boundary; sensitive field names are stripped;
  a node/depth/item/byte budget prevents oversized provider inputs.
- Provider errors fail with stable identifiers; no API key, raw stack traces, or
  raw HTTP payloads are logged or returned. Opt-in development diagnostics expose
  only allowlisted exception categories, status codes, phases, and fixed reasons.
- An iterative controller bounds each task to 5 actions and 8 provider calls,
  detects identical repeated actions, and independently gates every action.
- Confirmation pauses the task; only trusted CLI approval resumes it. Rejection,
  expiry, denial, and failures terminate without automatic retries.
- Multiple proposals in one response execute none (`AI_MULTIPLE_TOOL_CALLS`).
  Confirmation IDs never enter Gemini context or CLI output.
- Tests using `unittest`, temporary directories, fixed system measurements, and mocked launches.
- Opt-in SQLite memory with explicit bounded retrieval and exact-action confirmation
  for every create/update/delete; no automatic storage or prompt injection.

In development mode, startup opens a text-only interactive CLI. Testing/production
mode still initializes and exits. Startup makes no provider request and invokes no
tool. `Status: Ready` means the foundation initialized successfully, not that API
credentials were verified remotely.

### Stage 2 tools

Every public tool operation returns the existing `ExecutionResult`. Corresponding
`<FUNCTION_NAME>_METADATA` constants live beside each implementation, using the
existing `ToolMetadata` and `RiskLevel` types. Stage 3 explicitly binds all 16
operations in `tools/registry.py`. Stage 4 makes the executor security-aware.
Direct primitives are internal/developer-only; all future controller/LLM execution
must go through the Stage 4 gateway, never a direct callable from the registry.

| Module | Operation | Risk | Behavior |
| --- | --- | --- | --- |
| `tools.system_tools` | `get_system_info()` | READ_ONLY | OS/release/version, architecture, Python version; no device/account identifiers |
| `tools.system_tools` | `get_cpu_info()` | READ_ONLY | Physical/logical CPU counts; unknown counts are `None` |
| `tools.system_tools` | `get_cpu_usage()` | READ_ONLY | Actual utilization over a blocking 0.1-second sample |
| `tools.system_tools` | `get_memory_info()` | READ_ONLY | Total/available/used physical bytes and utilization; used = total − available |
| `tools.system_tools` | `get_disk_info(path=PROJECT_ROOT)` | READ_ONLY | Total/used/free bytes and percent for one validated local path's volume |
| `tools.system_tools` | `list_processes(limit=100)` | READ_ONLY | Bounded PID/name summary only; inaccessible names are skipped |
| `tools.app_tools` | `open_application(alias)` | LOW | Request launch of a fixed allowlisted Windows application |
| `tools.app_tools` | `open_project_in_vscode(path)` | LOW | Open an existing directory in a new VS Code window with extensions disabled |
| `tools.file_tools` | `list_directory(path, limit=100)` | READ_ONLY | Immediate entries with file/directory/link types; no recursion |
| `tools.file_tools` | `find_files(root, pattern="*", limit=100, max_depth=5, max_entries=10000)` | READ_ONLY | Case-insensitive filename glob; no content reads or indexing |
| `tools.file_tools` | `open_path(path)` | LOW | Open a directory or allowlisted document/image using its Windows association |
| `tools.file_tools` | `create_directory(path)` | MEDIUM | Create one new directory; parent must exist |
| `tools.file_tools` | `rename_path(path, new_name)` | MEDIUM | Rename to a new sibling basename without overwrite |
| `tools.file_tools` | `move_path(source, destination)` | MEDIUM | Move to an exact new destination on the same volume, without overwrite |
| `tools.browser_tools` | `open_url(url)` | LOW | Request default-browser opening for a validated HTTP(S) URL |
| `tools.browser_tools` | `search_web(query)` | LOW | Encode a query into the central search URL, then use `open_url` |

Application aliases are `chrome`, `edge`, `vscode`, `notepad`, `calculator`, and
`file_explorer`. `config/tool_settings.py` centrally defines fixed installation
locations, filename extensions, search provider, and limits. Locations are derived
from the trusted local `ProgramFiles`, `ProgramFiles(x86)`, `LOCALAPPDATA`, and
`SystemRoot` environment variables. No caller can supply executable paths or flags;
there is no PATH/current-directory executable search. Missing apps return
`APP_NOT_FOUND`. VS Code uses `Code.exe` directly, avoiding the `code.cmd` batch shim.
Windows `os.startfile` performs native launch requests; VS Code arguments use
Windows argv quoting, not a command shell. Successful launch requests do not prove
application readiness, website loading, or command completion.

Directory/process result limits must be integers from 1–500. Process queries ask
only for PID/name and inspect at most 1,001 yielded process records; results do not
contain command lines, environments, handles, or process memory. OS process discovery
may internally enumerate more PIDs. Search has a maximum depth of 10 (depth 0 reads
only the root), and at most 10,000 examined entries. It skips symlinks/reparse points
and inaccessible/disappearing descendants. Results include `skipped`,
`limit_reached`, and, for searches, `depth_limited`/`scanned_entries`. Hitting a bound
means completeness is not guaranteed, even if the last match happened to hit the
limit exactly. Returned subsets are sorted, but enumeration order and concurrent
OS changes can affect which entries fit within a limit. Limits bound traversal
work, not wall-clock time of an individual OS call.

### Stage 3 registry and execution API

`tools.registry.REGISTRY` is a fixed allowlist created from explicit source-level
`RegisteredTool(ToolMetadata, callable)` bindings. It does not scan modules or the
filesystem, load plugins, import caller-supplied paths, or resolve arbitrary Python
functions. `ToolRegistry` construction rejects duplicate names with the fixed
`ValueError` identifier `DUPLICATE_TOOL_NAME`; empty/non-string registration names
and non-callable implementations use `INVALID_TOOL_REGISTRATION`. Construction is
for trusted Python setup/tests, not an execution request API. There is no runtime
registration method. Construction invokes no operations.

- `REGISTRY.get(name)` returns a `RegisteredTool` for an exact name, or `None` for
  unknown/malformed names. Names are case-sensitive and are never trimmed or expanded.
- `REGISTRY.contains(name)` checks exact membership and returns a boolean.
- `REGISTRY.list_metadata()` returns detached JSON-compatible dictionaries in
  registration order, containing `name`, `description`, `risk_level`, and
  `arguments_schema`, without callables or provider-specific objects.
- `tools.executor.execute_tool(tool_name, arguments)` accepts only a name and an
  argument mapping, returning `ExecutionResult`. Use `{}` for zero-argument calls.
  It now delegates to Stage 4 `request_execution`; sensitive actions do not run
  until separately confirmed through the trusted interface.

The registry snapshots metadata at construction and copies it on retrieval,
including nested schema dictionaries/lists. Its internal name mapping is read-only;
editing returned descriptions cannot change subsequent validation. This protects
the public API, not against trusted Python code deliberately modifying private state.

The gateway reuses Stage 3 preparation/invocation in `tools/_execution.py`: validate
the name, resolve the binding, validate and snapshot arguments, then (only after
authorization) invoke the binding and verify the `ExecutionResult` return type.
Existing Stage 2 input validation and `_safe_result` remain intact.
Underlying success/failure results pass through unchanged. Registry failures,
unexpected validation/invocation exceptions, and wrong return types produce a
generic sanitized `TOOL_EXECUTION_FAILED`; no exception text or object representation
is returned. Invalid request failures are:

| Error ID | Meaning |
| --- | --- |
| `INVALID_TOOL_NAME` | Name is not a nonempty string |
| `TOOL_NOT_FOUND` | No exact registered name matches |
| `INVALID_TOOL_ARGUMENTS` | Arguments violate the declared tool schema |

`tools/schema.py` implements only the standard-library JSON Schema subset used by
these tools: `object`, `properties`, `required`, `additionalProperties: false`,
`string`, `integer`, `minLength`, `maxLength`, `minimum`, `maximum`, `enum`, and
`default`. Missing required fields, extra/non-string keys, malformed top-level
payloads, wrong types, and out-of-range values fail before invocation. Values are
never coerced: `True`, `10.0`, and `"10"` are not integer arguments. Path arguments
at this boundary must be strings, although direct Stage 2 calls also accept `Path`.
Unsupported schema features fail closed as an internal execution failure, including
when attached to an omitted optional argument.

Schema defaults are descriptive annotations. Optional arguments stay omitted so
the existing Python function supplies its default (including the project-root disk
path); the executor neither duplicates defaults nor mutates caller mappings. Tests
verify that every declared schema default matches the implementation signature.

Read-only examples for a controlled Python caller:

```python
from tools.registry import REGISTRY
from tools.executor import execute_tool

available = REGISTRY.list_metadata()  # Can be serialized with json.dumps.
assert REGISTRY.contains("system.get_cpu_info")
result = execute_tool("system.get_cpu_info", {})
listing = execute_tool("file.list_directory", {"path": "data", "limit": 10})
```

### Stage 4 permission and confirmation API

`security.gateway.request_execution(tool_name, arguments)` is the authoritative
request boundary. `tools.executor.execute_tool` delegates to the same default
gateway, so existing higher-level callers cannot skip Stage 4. The request accepts
no confirmation flag, risk override, callable, or alternate registry. Schema
validation precedes policy evaluation; malformed requests create no confirmations.
Stage 2 semantic/path/URL checks still occur inside the tool at execution time.
For example, a structurally valid path may later fail a no-overwrite check.

`security.permissions.evaluate_permission(metadata, policy)` uses only trusted
registered `ToolMetadata`. READ_ONLY/LOW default to `ALLOW`; MEDIUM/HIGH always
require confirmation. Invalid metadata/risk, missing or invalid policy, unknown
decisions, and evaluation failures deny. `PermissionPolicy(denied_tools=frozenset(...))`
allows trusted setup to deny exact registered names across every risk level.
Policy is immutable and deny-only: there are no risk-downgrade environment settings.
`DENY` stops before execution or confirmation creation and records an audit event.

For MEDIUM/HIGH, a request returns `success=False`, `error_id="CONFIRMATION_REQUIRED"`,
and `data` containing `confirmation_id`, `tool_name`, trusted `description`,
`risk_level`, and `expires_in_seconds=300`. The description is deliberately only
tool-level; it does not describe the target path or expose raw arguments. Stage 6
retains a separate snapshot of schema-validated arguments for CLI review, showing
the exact target alongside this description before asking for approval.

Two separate trusted interface methods complete this flow:

- `confirm_execution(confirmation_id)` consumes the ID, checks expiry, re-evaluates
  policy, and attempts only the stored callable with the stored arguments. It cannot
  accept a different tool, arguments, or an approval boolean.
- `reject_confirmation(confirmation_id)` discards the pending action, records its
  rejection, and returns a successful cancellation result without invoking a tool.

These APIs are **not registered tools and must never be exposed to an LLM**. The
future model may request an action; it may never authorize its own action. Stage 4
has no GUI confirmation dialog or user authentication: confirmation is currently a
programmatic boundary reserved for trusted interface/controller infrastructure;
the Stage 6 CLI calls it only after explicit terminal approval.
Receiving an ID in a model response must not cause automatic confirmation.

Pending requests are private to one gateway/process. Each stores the resolved tool
binding, an immutable JSON snapshot of schema-validated arguments (including nested
objects), and a monotonic expiry deadline. Caller mutations and returned display
data cannot change the pending action. Non-JSON Python values are rejected by the
schema validator. IDs use `secrets.token_urlsafe(32)` (256 bits of randomness), not
caller input, counters, timestamps, or object identities. Treat them as capability-like
references and do not log or persist them unnecessarily.

The fixed TTL is **300 seconds**, expiring at the deadline. A lock protects all
pending-state transitions; removal occurs before confirmation execution or rejection,
so concurrent replay cannot execute twice. Authorization is consumed even if the
tool, policy recheck, clock, or audit later fails. Tools run outside the state lock.
Retries require a new request and approval. At most 128 confirmations are retained;
new sensitive requests purge expired entries before checking capacity. There is no
background cleanup: unused expired arguments may remain in bounded memory until a
new sensitive request, an attempt to use/reject that ID, or process exit. Restarting
loses pending requests; nothing is stored in SQLite or on disk.

| Stage 4 error ID | Meaning |
| --- | --- |
| `PERMISSION_DENIED` | Policy denies or cannot establish authorization |
| `CONFIRMATION_REQUIRED` | Pending exact action needs trusted user confirmation |
| `CONFIRMATION_NOT_FOUND` | Unknown, malformed, consumed, rejected, or previously purged ID |
| `CONFIRMATION_EXPIRED` | An existing pending ID expired and has now been removed |
| `CONFIRMATION_UNAVAILABLE` | Pending capacity or ID-collision retry limit reached |
| `SECURITY_AUDIT_FAILED` | Audit recording failed; check action state before retrying |

Consumed and rejected IDs have no retained tombstones; they deliberately share the
not-found outcome. Unexpected ordinary failures retain sanitized
`TOOL_EXECUTION_FAILED`. No raw exception text or returned-object representation is
exposed by the gateway.

Programmatic request and cancellation example (does not create the directory):

```python
from security.gateway import request_execution, reject_confirmation

pending = request_execution("file.create_directory", {"path": "data/example"})
if pending.error_id == "CONFIRMATION_REQUIRED":
    cancelled = reject_confirmation(pending.data["confirmation_id"])
```

Only after a real user approval may trusted interface code call
`security.gateway.confirm_execution(id)`. No approval is inferred from the example.
For isolated trusted setup/tests, `SecurityGateway(registry=..., policy=..., audit=...,
clock=...)` provides independent state; its constructor dependencies are never request
payload fields. A custom gateway's IDs must be confirmed/rejected on that same instance.

### Security audit trail

`security/audit.py` records fixed events for allowed/denied/invalid requests,
confirmation required/accepted/rejected/expired/invalid, and authorized execution
attempted/completed/failed. Records contain a UTC timestamp, event, trusted tool
name/risk, decision, and allowlisted error ID. Unknown request names, argument values,
paths, URLs, queries, file contents, secrets, exception text, result messages/data,
and confirmation IDs are omitted. This is separate from `jarvis.log` and DEBUG filtering.

The default gateway keeps the latest **1,000 events in memory**, reviewable through
`security.audit.get_audit_records()` as detached JSON-compatible dictionaries.
Records are lost at process exit. Trusted setup may opt into append-only JSONL:

```python
from pathlib import Path
from security.audit import AuditTrail
from security.gateway import SecurityGateway

# Trusted configuration only; parent directory must already exist.
audit = AuditTrail(Path("logs/security-audit.jsonl"))
secure = SecurityGateway(audit=audit)
```

Construction/import opens no files. Each event is recorded under a lock and an
optional file append is flushed/closed before returning. File failures never emit
raw paths or exceptions. Failure to record a decision/attempt prevents execution;
failure to record completion occurs after the tool may already have acted and returns
`SECURITY_AUDIT_FAILED`. The confirmation remains consumed; inspect actual state
before requesting a retry. The in-memory event is retained even when file append fails.

Audit is not tamper-resistant, crash-proof, cryptographically signed, or remotely
stored. A local process/user can modify files or Python state. The memory history
is bounded, but optional JSONL files have no automatic rotation/retention and do
not have cross-process locking; trusted setup must manage their storage/lifecycle.

## Explicitly unimplemented

There is no unrestricted autonomous agent, GUI confirmation dialog,
desktop UI, or packaging. There is
no generic shell/PowerShell/CMD execution, `eval`/`exec`, arbitrary executable input,
file/directory deletion, software-installation tool, shutdown/restart, registry or
service manipulation, privilege escalation, credential/cookie extraction, messaging,
financial action, mouse/keyboard/screen control, browser automation/scraping, voice,
or wake word.

MEDIUM/HIGH-risk actions require programmatic trusted confirmation through the
supported gateway. The model may never authorize its own action. Stage 6 adds the
bounded planner/controller and CLI; Stage 7 adds bounded, user-approved SQLite memory.

## Stage 7 — user-controlled SQLite memory

The model proposes structured actions; trusted code validates, authorizes and
executes them. Memory adds six tools to the same registry and Stage 4 gateway.
No maintenance, SQL, Python, shell, database path, approval flag, or provenance
override is exposed to the model. HIGH already requires confirmation in Stage 4;
no permission policy was weakened or replaced.

| Tool | Risk | Behavior |
| --- | --- | --- |
| `memory.list` | READ_ONLY | Bounded active records, newest first; optional category filter |
| `memory.get` | READ_ONLY | One active record by opaque ID |
| `memory.search` | READ_ONLY | Deterministic lexical relevance, category filter and result limit |
| `memory.create` | MEDIUM | Store the exact reviewed content/category only after approval |
| `memory.update` | MEDIUM | Confirmed full replacement of one record's editable fields |
| `memory.delete` | HIGH | Confirmed deletion of one exact record, never a query or bulk operation |

### Architecture and database

`memory/models.py` defines JSON-only records; `validation.py` validates and
normalizes input; `database.py` owns SQLite connections, transactions and schema;
`repository.py` implements fixed-query CRUD and trusted expiration maintenance;
`retrieval.py` ranks and bounds returned data. `tools/memory_tools.py` supplies the
registry bindings. `main.py` initializes and installs the repository during
development startup. Imports, repository construction, and tool registration do
not open a database. Testing/production startup remains initialize-and-exit.

The deterministic filename is **`memory.sqlite3` inside `JARVIS_DATA_DIR`**
(default `F:\Work\Jarvis\data\memory.sqlite3`). Configure the application data
directory in the trusted environment before startup; it is never a tool argument.
Runtime directory creation is the existing trusted startup responsibility.
Initialization creates an empty schema, not a conversation record. Corruption or
schema errors leave the file in place and disable memory while other CLI tools
remain available. Ordinary repository operations require an existing database and
never create a replacement file if it disappears.

Schema version 1 has two tables:

| Table | Columns |
| --- | --- |
| `memories` | `id` (opaque 128-bit random ID, primary key), `category`, `content`, `created_at`, `updated_at`, nullable `expires_at`, `source`, `tags` (JSON text array) |
| `schema_migrations` | `version` (primary key), `applied_at` (UTC) |

Categories are `preference`, `fact`, `project`, `instruction`, and `note`.
Provenance is always application-assigned `user_approved`; it does not assert that
a claim is true or let the model claim consent. Timestamps are normalized to UTC
with microseconds; expiration input must include a timezone. Indexes support
recency and expiration. All SQL statements are application-owned; values are bound
parameters. Each operation uses and closes its own connection. Writes use
`BEGIN IMMEDIATE`, so capacity checks and mutations share the same lock/transaction.
SQLite uses WAL, `synchronous=FULL`, a five-second busy timeout, and read
transactions with `query_only=ON`. There are no automatic destructive retries.

Only trusted initialization may migrate schemas. Version 1 initializes an empty
database atomically; unknown/future versions or incompatible schemas fail closed.
Future releases must add fixed numbered migrations and compatibility tests, with
a backup before migration; they must never reset an existing database on error.

### Consent and exact-action review

Nothing automatically stores conversation text, results, system observations,
discovered paths, inferred personal data, or model suggestions. Every mutation
requires the existing expiring, single-use confirmation. The CLI displays the
operation, exact JSON fields, category, ID (when applicable), and risk, and defaults
to rejection. A model suggestion or an assertion of approval is not consent.

Updates require the current `updated_at` as `expected_updated_at`, plus the full
replacement content/category; omitted tags/expiration become empty. Deletes require
the ID, expected version, category, and exact `expected_content`. The repository
checks them atomically at execution. If another action changes the record after
review, the approved mutation fails with `MEMORY_CONFLICT`; it does not overwrite
or delete the newer record. A user must select an unambiguous record when search
finds multiple matches. The adapter asks for selection, the CLI warns on review,
and no query/category-only or bulk deletion is accepted.

Example: ask "Remember that I prefer concise technical explanations", review the
`memory.create` fields and approve. After restart, ask Jarvis to search its stored
communication preferences. To change or forget one, first retrieve/select the
record; review and approve the resulting update/delete. Answer `n` to leave data
unchanged. Existing `exit`, `quit`, EOF, and interrupt handling remain available.

### Limits and lexical search

| Setting or constraint | Default | Allowed range |
| --- | --- | --- |
| `JARVIS_MEMORY_MAX_RECORDS` | 1,000 | 1–10,000 total records, including expired records |
| `JARVIS_MEMORY_MAX_RESULTS` | 10 | 1–50 per retrieval |
| `JARVIS_MEMORY_MAX_RESULT_BYTES` | 8,192 | 512–12,000 serialized JSON bytes |
| Content | Up to 1,024 characters | Nonempty text; control/invisible format characters rejected |
| Search query | Up to 256 characters | Nonempty lexical text |
| Tags | Up to eight tags | 32 characters each; comma-separated input at most 256 characters |

Requested tool limits cannot exceed trusted limits. Results are safely serialized,
clearly labeled `untrusted_memory_data`, and marked `truncated` when records are
omitted for count/byte bounds. A very small byte budget can omit even a single
large record; increase the trusted budget to inspect it. Existing Stage 6 result,
feedback and context bounds still apply as an additional boundary. The unchanged
controller limits remain five actions and eight provider calls per task.

Search uses case-folded exact phrase matches first, matched whole-token count
second, updated timestamp third, and ID as a deterministic tie-breaker. It filters
categories/expiration and examines no more than the configured record cap. Queries
are never interpreted as SQL, wildcard expressions, or executable instructions.
This is lexical search, not semantic understanding; there are no embeddings, FTS
dependency, vector store, or second provider. If the database exceeds a newly
lowered capacity setting, retrieval fails visibly instead of silently ranking only
part of it.

Retrieval is explicit through tools. There is no automatic injection into prompts.
Even the `instruction` category remains untrusted reference data; it cannot add
registered tools or change permissions, approvals, or budgets. Model compliance
with prose is not the security boundary: every proposed action still crosses the
fixed registry, schema validator, controller, and gateway.

### Privacy, retention, and backup

Conservative detection rejects obvious credential patterns (private keys, known
API-token prefixes, bearer credentials, password/key assignments, credential URLs)
and the configured Gemini key. Regex detection cannot recognize all secrets or
sensitive personal information; do not approve their storage. Content and search
queries are not logged. Diagnostics/audit contain only fixed events and IDs of
error categories, never stored record contents or confirmation capabilities.

The database is local plaintext protected by the OS/account's filesystem access;
this is not encryption or a sandbox against other trusted local Python programs.
Use a private data directory. Explicitly retrieved content is sent to Gemini as
bounded tool-result data, subject to that provider's processing policies.

Expired records are excluded from ordinary reads without mutation. Trusted setup
may call `MemoryRepository.cleanup_expired()` to remove expired rows; it is not a
model tool and is not run automatically. Deleted records disappear immediately
from ordinary queries. **SQLite deletion is not forensic-grade secure erasure**:
historical pages, WAL/journal files, filesystem snapshots, and backups can retain
data. No unrestricted database reset or automatic bulk deletion tool exists.

Back up with SQLite's backup API using trusted code, or stop all Jarvis processes
and copy the complete consistent database state. Do not copy only the main file
from a live WAL database and assume it is complete. Protect backups like the
original, and account for deleted/expired content retained in older backups.

Stable errors include `MEMORY_DATABASE_UNAVAILABLE`, `MEMORY_DATABASE_CORRUPT`,
`MEMORY_INVALID_RECORD`, `MEMORY_RECORD_NOT_FOUND`, `MEMORY_CONFLICT`,
`MEMORY_CAPACITY_EXCEEDED`, `MEMORY_STORAGE_FAILED`, `MEMORY_SCHEMA_UNSUPPORTED`,
and `SECRET_DETECTED`. Messages do not reveal SQLite internals or record contents.

### Stage 7 testing and release gate

The initial working tree reported v0.6.1 but already had unfinished memory code:
279 baseline tests ran with seven failures and one error from obsolete 16-tool
expectations. All original tool assertions are retained; registry-size and binding
expectations now include the six memory tools. New tests use temporary databases
and never initialize or modify the developer's real memory database.

Both required full-suite commands pass **317 tests** (279 existing plus 38 new):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -W error -m unittest discover -s tests -v
```

Coverage includes persistence, schema versions, CRUD, fixed-query safety, limits,
ranking, expiration, concurrent capacity/initialization, rollback, corruption,
consent/rejection/expiry/replay, stale approvals, credential rejection, untrusted
retrieval, bounded context, and real SDK continuation without network access.
Live create/restart/recall/update/delete/reject and Calculator/CPU verification is
a separate release gate. If Gemini is unavailable, report that gate as blocked
and keep `core.__version__` at **0.6.1**; do not claim v0.7.0 released.

Live verification on **2026-10-08** used the actual development CLI and Gemini,
with a separate database under `data/stage7-verification-20261008`:

| Check | Result |
| --- | --- |
| Startup | Passed: v0.6.1, 22 tools, security active |
| Create with approval | Passed: zero rows before approval, exact category/content afterward, normal Gemini continuation |
| Complete exit and restart | Passed: first process exited with code 0; fresh process retrieved the exact preference |
| Update with approval | Passed: original value unchanged while pending; replacement verified in SQLite and a separate live retrieval |
| Delete with HIGH confirmation | Passed: exact ID/category/content/version reviewed; deletion executed and zero rows verified |
| Post-delete retrieval | Three retrieval calls completed with the empty database; final response was blocked by Gemini HTTP 429 `RESOURCE_EXHAUSTED` |
| Reject a separate creation | Live check blocked by provider rate limit; covered by offline CLI/gateway tests |
| Calculator and CPU | Stage 7 live checks blocked by provider rate limit; existing automated regression coverage passes |

Live requests stopped at the rate limit. The verification database was left empty,
and the CLI exited cleanly. The model initially asked for conversational selection
before proposing deletion; selecting the exact returned record then produced the
trusted HIGH confirmation. Natural-language wording can vary, so verification
checks actual gateway execution and database state rather than trusting prose.
**Stage 7 is implemented but not released.** Finish the remaining live checks after
quota is available before promoting the canonical version to v0.7.0.

## Architecture

Current startup:

```text
main.py -> configuration -> runtime directories -> logging -> banner
  |-- development -> interface/cli.py -> text turns -> exit/quit/EOF -> shutdown
  `-- testing/production -> shutdown
```

Stage 6 active task path:

```text
User text
    ↓
Brain.run_turn() -> Controller (isolated state, counters, fingerprints)
    ↓
Iterative Planner -> Provider abstraction (ai/base.py)
    ↓
Gemini provider (ai/gemini.py)
    ↓
Text ─────────────────────────────→ TaskResult (COMPLETED)

OR

Structured function-call proposal
    ↓
Jarvis validation (ai/validation.py)
    ↓
Stage 4 Security Gateway (security/gateway.py)
    ↓
ALLOW (READ_ONLY / LOW)
    ↓
Internal tool invocation → Stage 2 validation → ExecutionResult
    ↓
Bounded sanitized result (ai/sanitize.py)
    ↓
Planner -> Gemini next action OR final text
    ↑         bounded iterative loop; no recursion or retries
Controller checks action/provider limits and repeated actions every step

REQUIRE_CONFIRMATION (MEDIUM / HIGH)
    ↓
TaskResult (WAITING_FOR_CONFIRMATION)
    Stage 4 ID retained privately in the controller — never in model context
    CLI reviews exact arguments -> y/yes -> confirm_turn(turn_id) -> Stage 4
    Successful confirmation -> same turn resumes with unchanged counters
    No / expiry / denial / failure -> task terminates

DENY
    ↓
TaskResult (DENIED) — no retry, no model workaround
```

Security-aware tool path (`execute_tool` delegates to this gateway):

```text
Controlled trusted caller -> Security Gateway -> Registry + Schema Validation
                         -> Permission Engine
                            |-- DENY -> sanitized failure + audit
                            |-- ALLOW -----------------------------+
                            `-- REQUIRE_CONFIRMATION               |
                                -> stored exact action             |
                                -> trusted confirmation -----------+
                                                                   v
                                                   Internal tool invocation
                                                   -> Stage 2 validation
                                                   -> ExecutionResult + audit
```

Developer-only primitive path (never a controller/LLM entry point):

```text
Controlled Python caller -> specific tool -> input checks -> bounded operation
                        -> sanitized ExecutionResult
```

The error wrapper in `tools/_support.py` sanitizes results and emits debug events;
it is neither a dispatcher nor a permission check. Importing tools performs no
launches or filesystem modifications.

The AI may propose structured intent and tool calls. The Jarvis security layer —
not the model — resolves approved tools, enforces permission decisions, validates
inputs, and executes only authorized actions. The model must never receive
unrestricted OS access or an unrestricted PowerShell execution path.


`ToolMetadata` describes a unique name, description, `RiskLevel`, and argument schema.
Stage 3 enforces registry uniqueness and the supported schema subset at dispatch.
Metadata itself has no execution or authorization behavior. `RegisteredTool` binds
metadata to an implementation separately. `ExecutionResult` contains `success`, a human-readable `message`, optional
structured `data`, and optional `error_id`. Models use type hints; they are not
runtime security validators. Data/schema mappings should hold JSON-compatible
values; frozen dataclasses do not make nested mappings immutable.

## Security and permissions

Stage 2 implements input validation in `security/validator.py`; Stage 3 adds schema
validation before dispatch. Stage 4 evaluates and enforces permission decisions in
`security/permissions.py` and `security/gateway.py`, with trusted deny-only policy in
`security/policies.py`. The registry remains an allowlist/resolver; metadata itself
does not authorize. Stage 5 routes every model proposal through this gateway.

Current input safeguards and limits:

- Relative tool paths resolve against the project root. Parent traversal (`..`),
  UNC/network/device paths, drive-relative paths, Windows reserved names, alternate
  data streams, control characters, and trailing dots/spaces in names are rejected.
  Mapped network/unknown Windows drive types are rejected before traversal.
- Every existing path component is inspected for symlinks and Windows reparse
  points before canonical resolution. Junctions and cloud placeholders may therefore
  be rejected. Searches never intentionally follow such entries.
- Creation requires an existing parent. Rename accepts one basename. Move accepts
  an exact new destination (not an existing destination folder), rejects moving a
  directory into itself or moving a drive root, and rejects cross-volume moves.
  Rename/move use Windows no-replacement `os.rename`, including collision races;
  they fail on other platforms rather than using POSIX replacement semantics.
  Case-only renames to an existing spelling are rejected as collisions. Directories
  are renamed as entries, without reading or copying their descendants.
- `open_path` allows only directories and `.txt`, `.pdf`, `.png`, `.jpg`, `.jpeg`,
  `.gif`, `.bmp` files. Executables, scripts, shortcuts, URLs, HTML, SVG, and other
  extensions are rejected. This extension policy is not malware/content analysis;
  opening a document invokes the user's existing Windows association.
- URL parsing permits HTTP/HTTPS only, validates host/port syntax, rejects embedded
  credentials and ambiguous whitespace/backslashes, and limits URLs to 8,192
  characters. Search queries are limited to 2,000 characters and encoded as a single
  parameter for Google (central default). No DNS lookup, request, redirect validation,
  destination reputation check, or private-network restriction is performed. Local
  hosts are allowed. Browser opening leaves navigation to the user's browser.
- VS Code opening passes a directory plus fixed launch flags, with extensions
  disabled. Jarvis does not invoke project scripts or servers. Existing editor
  workspace trust/settings and any application startup behavior remain outside
  Jarvis's control; this is not an editor sandbox.

These are input checks plus programmatic authorization, not a complete OS sandbox
or a claim of production security. There is no filesystem allowlist or handle-based
race-proof validation. Stage 4 does not eliminate filesystem TOCTOU races.
Prevalidation cannot stop a different process replacing a parent with a reparse
point between checks and execution. Use only trusted local trees, installations,
environment variables, and associations under direct developer control.

Ongoing security requirements for future integrations:

- No unrestricted arbitrary commands; use approved structured tools and least privilege.
- Validate canonical paths before filesystem modifications, including symlinks and
  validation/execution races; validate URLs and redirects before network actions.
- Preserve exact-action confirmation and sanitized decision/action audit records;
  require trusted user-interface review before approving sensitive proposals.
- Fail closed when authorization or validation is absent or uncertain.
- Keep secrets in environment variables; never hard-code credentials or give an
  LLM authority to approve its own requests.

| Risk | Enforced gateway default |
| --- | --- |
| `READ_ONLY` | ALLOW, subject to validation and explicit denials |
| `LOW` | ALLOW, subject to validation and explicit denials |
| `MEDIUM` | REQUIRE_CONFIRMATION, unless denied |
| `HIGH` | REQUIRE_CONFIRMATION, unless denied; never automatic |

`PermissionDecision` retains `ALLOW`, `REQUIRE_CONFIRMATION`, and `DENY` in
`agent/permissions.py`. Stage 4 independently enforces them; all future controller
execution must use the gateway. Python module privacy is not a security sandbox:
trusted local code can still import direct tools or change private state.

Application logs are not security audit logs. Startup logs fixed lifecycle/error
messages; tools log only their operation name and completion/error identifier at
DEBUG level. The executor logs only fixed completion/rejection events and stable
dispatcher error IDs, never caller-provided tool names or underlying result data.
They never log paths, URLs, search queries, file contents, process names,
environment dumps, or raw exception details. The JSON formatter omits
exception tracebacks and arbitrary record extras. It does not redact secrets from
message text: future callers must sanitize messages and result data before logging
or displaying them. A sanitized `STARTUP_FAILED` message intentionally omits the
underlying exception and paths. Tool failures likewise return fixed safe messages
with identifiers such as `INVALID_PATH`, `PATH_NOT_FOUND`, `NOT_A_DIRECTORY`,
`DESTINATION_EXISTS`, `ACCESS_DENIED`, `UNSAFE_PATH`, `UNSUPPORTED_FILE_TYPE`,
`INVALID_URL`, `UNSUPPORTED_URL_SCHEME`, `APP_NOT_ALLOWED`, `APP_NOT_FOUND`,
`CROSS_DEVICE_MOVE`, `PROCESS_QUERY_FAILED`, and `TOOL_EXECUTION_FAILED`.

For development-only Gemini diagnosis, set `$env:JARVIS_PROVIDER_DIAGNOSTICS='1'`
before running `main.py`. This emits `provider_failure` metadata for
`initial_proposal`, `tool_continuation`, or the Stage 5 `final_response` phase.
It records only allowlisted exception classes/API categories, numeric HTTP status,
and fixed reason codes (including `unsupported_content_role`); unknown details
are withheld. It never emits raw exceptions, prompts, responses, tool arguments,
results, paths, URLs, queries, credentials, headers, or confirmation IDs.
Diagnostics are disabled unless explicitly enabled and are always suppressed in
`testing` and `production`. Remove the variable to disable them. No retries are added.

Gemini function feedback is a `Content(role="user")` containing a typed
`Part(function_response=FunctionResponse(...))`, immediately after the preserved
model function call. The name and optional call ID match that call. Stage 6
reconstructs all call/result pairs in order, retaining original thought signatures;
it uses `AUTO` for further steps, while Stage 5 `finish()` uses `NONE`.
The SDK serializes these objects. Offline wire regressions enforce valid roles,
matching names/IDs, binary signatures, and sanitized bounded feedback through Stage 4.

Runtime locations are trusted local configuration, not a sandbox or path allowlist.
Directories are created only when missing; a file occupying a directory path causes
failure without overwrite. Logging requires write access to `jarvis.log`. There is
no automatic log rotation, retention, or runtime cleanup in Stage 1.

## Project structure

```text
Jarvis/
|-- main.py
|-- README.md
|-- requirements.txt
|-- .env.example
|-- .gitignore
|-- core/
|   |-- __init__.py       # Canonical version and accessor
|   |-- logging.py        # Logging setup, formatter, lifecycle
|   |-- models.py         # RiskLevel and ExecutionResult
|   `-- runtime.py        # Directory initialization
|-- config/
|   |-- __init__.py
|   |-- settings.py       # Settings + GeminiSettings; DEFAULT_GEMINI_MODEL
|   |-- agent_settings.py # Trusted action/provider/context/pending limits
|   `-- tool_settings.py  # Trusted aliases, search provider, extensions, limits
|-- agent/
|   |-- __init__.py
|   |-- brain.py          # Bounded task API + Stage 5 compatibility API
|   |-- planner.py        # Iterative next-step decisions; no execution authority
|   |-- controller.py     # State machine, limits, progress and confirmation lifecycle
|   |-- models.py         # TurnStatus, TaskResult, ActionReview
|   `-- permissions.py
|-- ai/
|   |-- __init__.py       # Provider-independent AI contracts; no I/O on import
|   |-- base.py           # Provider and ProviderTurn protocols
|   |-- context.py        # Accumulated feedback bounds
|   |-- models.py         # AssistantText, ToolCallProposal, ProviderError, TurnResult
|   |-- gemini.py         # Official google-genai adapter; SDK objects stay here
|   |-- sanitize.py       # Bounded JSON-only tool feedback for provider input
|   `-- validation.py     # Untrusted provider output shape validation
|-- interface/
|   |-- __init__.py
|   `-- cli.py            # Trusted text interaction and exact-action confirmation
|-- tools/
|   |-- __init__.py
|   |-- base.py           # ToolMetadata
|   |-- _support.py       # Error/metadata helpers, no dispatcher
|   |-- registry.py       # Explicit 22-tool allowlist and detached descriptions
|   |-- schema.py         # Contract validation; defaults left to Python
|   |-- _execution.py     # Internal preparation and sanitized invocation
|   |-- executor.py       # Compatibility API delegates to security gateway
|   |-- system_tools.py
|   |-- app_tools.py
|   |-- file_tools.py
|   |-- browser_tools.py
|   `-- memory_tools.py   # Six gateway-controlled memory operations
|-- memory/
|   |-- __init__.py
|   |-- database.py       # Fixed SQLite schema, transactions and initialization
|   |-- models.py
|   |-- validation.py
|   |-- repository.py
|   `-- retrieval.py
|-- security/
|   |-- __init__.py
|   |-- validator.py
|   |-- permissions.py    # Fail-closed evaluation of registered metadata
|   |-- gateway.py        # Authoritative gateway and trusted confirmations
|   |-- audit.py          # Bounded security records; optional JSONL output
|   `-- policies.py
|-- data/                 # Tracked .gitkeep; runtime contents ignored
|-- logs/                 # Tracked .gitkeep; runtime contents ignored
`-- tests/
    |-- __init__.py
    |-- test_foundation.py
    |-- test_logging.py
    |-- test_main.py
    |-- test_system_tools.py
    |-- test_app_tools.py
    |-- test_file_tools.py
    |-- test_browser_tools.py
    |-- test_tool_contracts.py
    |-- test_tool_registry.py
    |-- test_tool_executor.py
    |-- test_permissions.py
    |-- test_security_gateway.py
    |-- test_security_audit.py
    |-- test_ai_brain.py    # Offline single-turn tests through real Stage 4
    |-- test_ai_sanitize.py # Sanitizer bounds, secret exclusion, no mutation
    |-- test_gemini.py      # Stage 5 adapter; SDK pin, declarations, wire test
    |-- test_controller.py  # Multi-step state, limits, pause/resume, expiry and races
    |-- test_cli.py         # Mocked input/output, defaults, interruption and privacy
    `-- test_gemini_tasks.py # Bounded SDK task context and mock transport
```

## Setup and running (Windows PowerShell)

Use Windows 11, Python 3.11 or newer, Git, and optionally Visual Studio Code.
Python 3.14.3 on Windows is the development verification environment; Python 3.11
syntax is checked, but a separate 3.11 runtime has not been tested here.

Third-party dependencies (both pinned in `requirements.txt`):

- **`psutil==7.2.2`** — reliable CPU utilization, physical memory, and bounded
  process summaries. See the [psutil documentation](https://psutil.readthedocs.io/stable/)
  and [pinned release](https://pypi.org/project/psutil/7.2.2/).
- **`google-genai==2.28.0`** — official Google Gen AI Python SDK. Used with manual
  structured function calling only; SDK automatic execution is explicitly disabled.
  See [google-genai on PyPI](https://pypi.org/project/google-genai/2.28.0/).
  `google-genai 2.28.0` imports a deprecated `_UnionGenericAlias` alias on Python 3.14;
  `ai/gemini.py` scopes the suppression of this exact upstream warning at import time.
  No LangChain, LlamaIndex, AutoGen, or other agent framework is added.

Open the repository folder in VS Code and open its PowerShell terminal. For a fresh
checkout, create a virtual environment; reuse an existing `.venv` if already present:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If activation is restricted, use the interpreter directly without changing your
PowerShell execution policy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Expected banner:

```text
JARVIS
Version: <current version from core.__version__>
Environment: development
Status: Ready
AI: Gemini (Configured)
Tools: 22
Security: Active
Type exit or quit to leave.
You >
```

JSON lifecycle logs appear on stderr and in `logs/jarvis.log` by default. Success
exits with code `0`; startup failure returns `1`; interruption returns `130`.
On startup failure, check the configuration values, whether directory paths are
occupied by files, and write permissions on configured directories and the log file.

### Configuration

| Environment variable | Default | Accepted values / meaning |
| --- | --- | --- |
| `JARVIS_ENV` | `development` | `development`, `testing`, or `production` |
| `JARVIS_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `JARVIS_DATA_DIR` | `data` | Nonempty runtime data directory path |
| `JARVIS_LOG_DIR` | `logs` | Nonempty log directory path |
| `GEMINI_API_KEY` | _(none)_ | Required for Stage 5 AI; never logged or committed |
| `JARVIS_GEMINI_MODEL` | `gemini-3.8-flash` | Model matching `gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,119}` |
| `JARVIS_AI_TIMEOUT_SECONDS` | `30` | Integer 1–120; provider network timeout |

Environment and level values ignore case and surrounding whitespace. Path values
are trimmed and support `~` expansion. Relative paths are resolved against the
project root regardless of the process working directory; absolute paths are
supported. Invalid values cause startup failure. Loading settings alone does not
create directories.

The CLI checks environment configuration locally at startup without an API request.
It prints `AI: Not configured` plus setup guidance when missing or invalid.
`GEMINI_API_KEY` is never logged. Each provider session loads it when requested.
Startup does not consume Gemini
API quota. Missing or blank `GEMINI_API_KEY` produces `AI_NOT_CONFIGURED` at
request time, not at startup. A malformed key, model, or timeout produces
`AI_INVALID_CONFIGURATION`.

`.env.example` is a reference, not an automatically loaded file. Set variables in
PowerShell; no dotenv dependency or real `.env` file is needed:

```powershell
$env:JARVIS_ENV = "development"
$env:JARVIS_LOG_LEVEL = "DEBUG"
$env:JARVIS_DATA_DIR = "data"
$env:JARVIS_LOG_DIR = "logs"
.\.venv\Scripts\python.exe main.py
```

Stage 5 credentials come only from `GEMINI_API_KEY`. `.env` files are ignored by
Git; `.env.example` is retained. Default
runtime content is ignored; custom runtime locations within the repository need
their own ignore entries before committing.

### Running tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -W error -m unittest discover -s tests -v
```

Tests cover defaults, environment overrides, invalid settings, safe/idempotent
directory creation, version retrieval, risk/result/tool/permission models, logging
fields and lifecycle, startup, interrupts, and sanitized failures. Stage 2 adds
system measurements, launch allowlists, URL/query validation, metadata completeness,
correct risks/schemas, bounded traversal, no-overwrite moves (including a collision
race), symlink/reparse rejection, and sanitized operational errors. Filesystem tests
use temporary directories. App/association/browser launch boundaries are mocked;
system measurements are mocked where machine values would make assertions unstable.
Tests do not launch real apps, execute commands, access external services, or require
API keys/admin privileges. The optional real-symlink test skips if Windows does not
allow unprivileged symlink creation; reparse simulation tests always run.

Stage 3 tests cover all 16 exact bindings, duplicate rejection, deterministic JSON
metadata, defensive copies, schema/signature default consistency, valid and omitted
arguments, all declared type/length/numeric/enum bounds, boolean rejection, missing
and extra arguments, malformed payloads, and unchanged caller mappings. They also
cover non-invocation on rejection, correct argument forwarding, result identity,
sanitized internal failures and wrong return types, sanitized logs, and continued
Stage 2 validation. Stage 4 adapts sensitive-operation assertions to confirm through
the gateway and replaces the former no-permissions expectation with enforced risk
decisions. Source checks prohibit dynamic resolution/OS access in the dispatcher
modules, verify explicit bindings, and
include all new production modules in Python 3.11 syntax checks.

Stage 4 adds policy allow/confirm/deny tests, invalid metadata/policy rejection,
schema-before-policy ordering, caller override rejection, unpredictable IDs, exact
stored binding/arguments, nested-copy isolation, TTL boundaries with a mocked clock,
single-use success/failure, rejection, independent requests, concurrent confirmation
and rejection races, bounded pending storage, and clock/entropy/audit failures.
Audit tests check event order/fields, sensitive-value exclusion from memory and JSONL,
append behavior, bounded detached history, and concurrent writes. Each test constructs
isolated gateway state; no real applications, browser pages, external services, API
keys, or administrator privileges are required. Temporary directories hold file tests.

Future modules can use `core.logging.get_logger("component")` after the entry point
initializes logging. Importing modules does not initialize directories, logs, or tools.

### Optional developer-only Stage 2 primitive verification

After installing requirements, start the project's Python interpreter:

```powershell
.\.venv\Scripts\python.exe
```

Read-only examples (enter these at the Python prompt):

```python
from tools.system_tools import get_system_info, get_cpu_usage, get_memory_info, get_disk_info, list_processes
from tools.file_tools import list_directory
print(get_system_info())
print(get_cpu_usage())
print(get_memory_info())
print(get_disk_info())
print(list_processes(limit=5))
print(list_directory("data", limit=10))
```

Optional launch checks below open real applications; run each only when wanted.
They are not part of automated verification:

```python
from tools.app_tools import open_application, open_project_in_vscode
from tools.browser_tools import open_url, search_web
print(open_application("notepad"))
print(open_url("https://example.com"))
print(search_web("Python pathlib documentation"))
print(open_project_in_vscode("."))
```

Direct imports are for primitive development/tests only. All supported higher-level
execution uses `execute_tool` or `request_execution`, enforcing Stage 4. Natural
language is available through the CLI and Stage 6 Python API below. Inspect `result.success`,
`result.message`, `result.data`, and `result.error_id` rather than parsing log text.

### Stage 6 task API and limits

`Brain(provider).run_turn(text)` returns an immutable `TaskResult` containing
`status`, `text`, `error_id`, `failure_kind`, `provider_calls`, `tool_actions`, and
`completed_actions`. When paused, it also returns an opaque `turn_id` (hidden from
repr) and an immutable `ActionReview`: trusted tool name, description, risk, and
exact schema-validated arguments serialized as JSON. No Stage 4 ID is returned.
`brain.confirm_turn(turn_id)` and `brain.reject_turn(turn_id)` are trusted UI APIs,
not tools. `brain.close()` cancels pending confirmations and releases their sessions.
There is no `confirmed=True` request field or generic resume-from-model-text API.

The planner asks for the next decision through `TaskProvider.task(text)`, whose
session exposes `propose()` and `advance(feedback)`. The controller owns the loop
and calls `security.gateway.request_execution()` for each accepted new action.
The planner has no execution or permission authority, and neither it nor the
controller imports Gemini types. Gemini retains signed call content inside its
session and uses manual function declarations with automatic SDK execution disabled.
The system instruction asks for one action per response; code rejects batches.

All Stage 6 limits are trusted source constants in `config/agent_settings.py`.
They cannot be overridden by a request, provider output, or environment variable:

| Limit | Value | Behavior |
| --- | --- | --- |
| Tool actions per turn | 5 | Counts gateway requests, including a pending action once; confirmation does not count it twice |
| Provider calls per turn | 8 | Counts attempts before calling the planner, including failures; independent defensive ceiling |
| Pending turns per Brain | 32 | Capacity exhaustion cancels the new pending action and closes its session |
| Pending-turn TTL | 300 seconds | Monotonic deadline measured before the pending action's gateway request |
| Accumulated feedback | 32,768 JSON bytes | Replace oldest result data with null and set `truncated=true` until it fits |
| Model content context | 262,144 bytes | Bound serialized request contents and retained signed call history; stop on excess |

The action ceiling stops immediately after the fifth successful action, without
an extra model call or sixth action. `completed_actions` reports completed work.
The 8-call ceiling independently protects the provider boundary and leaves room
above the normal one-decision-per-action pattern; malformed/no-progress responses
already terminate on the first occurrence. There are no automatic provider or tool
retries. Stage 5's network timeout and all per-result limits remain unchanged.

Repeated-action detection hashes the exact tool name plus sorted, compact JSON of
schema-validated arguments using SHA-256. Omitted schema defaults are filled only
for this fingerprint, not the execution request. Any identical action seen earlier
in the same turn is blocked with `REPEATED_ACTION`, including nonconsecutive repeats.
This deliberately conservative policy does not try to infer meaningful progress
from model text. Equivalent path spellings without identical validated JSON may
have different fingerprints; the action ceiling still applies.

Explicit states are `RUNNING`, `WAITING_FOR_CONFIRMATION`, `COMPLETED`, `DENIED`,
`FAILED`, `ACTION_LIMIT_REACHED`, `PROVIDER_LIMIT_REACHED`, and `CANCELLED`.
Running may pause or terminate. Waiting may resume after successful Stage 4
confirmation, or terminate after rejection, expiry, denial or failure. Terminal
states cannot resume. Invalid transitions fail closed (`CONTROLLER_STATE_FAILED`).
Failures distinguish provider, invalid model response, invalid tool proposal,
permission denial, tool execution, confirmation expiry, repeated action, limits,
and controller state. They contain stable identifiers without raw exceptions.

On confirmation-required, no later action or provider call runs. The controller
privately retains the Stage 4 ID, exact review snapshot, planner session, counters,
and fingerprints. CLI approval consumes the turn handle atomically and calls
`confirm_execution()`; Stage 4 still checks its own expiry/policy and executes only
the stored action. Only successful sanitized data is then sent to the planner.
Rejection calls `reject_confirmation()` and terminates; expiry never regenerates
authorization. Failure may follow an action that partially happened: inspect actual
state before submitting a new request.

Turn handles use `secrets.token_urlsafe(24)` (192 random bits, 32 characters), are
distinct from Stage 4 IDs, and rotate at each new pause. A handle alone does not
approve anything; only the trusted confirmation API can approve. Never send it to
the provider. Atomic removal prevents replay and concurrent double approval.
One Brain serializes calls under a lock, including synchronous provider waits;
separate turns have isolated state. There is no user/account authentication or
sandbox against trusted Python code invoking APIs directly.

Expired entries are purged on new turns and checked on confirmation/rejection;
`close()` releases all remaining entries. There is no background cleanup, so expired
data may remain in bounded memory until the next operation or process exit. A new
pause gets a fresh TTL but retains the original task budgets. Restarting loses all
state. Cleanup never invokes a tool, and conversations are not persisted.

Accumulated feedback preserves each action's success/truncation markers while
discarding oldest payloads. Tool names remain in the adapter's original signed
calls. Raw results, messages, failed results, and confirmation IDs never become
feedback. Current user text, bounded feedback and signed calls are the only task
history. Provider text is untrusted; deterministic status and counts remain the
authority for whether work completed.

Controller logs only fixed lifecycle/proposal/completion/pause/resume/failure/limit
events. The CLI may display exact arguments for user review, but never logs them.
It escapes terminal controls and redacts the configured API key from output.
Stage 4 remains the sole authorization and security-audit authority.

### Development CLI and manual verification

No new dependency is required. `main.py` composes the existing startup foundation,
Brain and Gemini provider; `interface/cli.py` owns input/output and confirmation.
Default `JARVIS_ENV=development` enters the CLI even without a key, displaying local
setup guidance. Testing/production retain initialize-and-exit behavior.
Configuration status is a local check, not a remote credential validation.

```powershell
cd F:\Work\Jarvis
$env:JARVIS_ENV = "development"
$env:GEMINI_API_KEY = "<developer supplies locally>"
.\.venv\Scripts\python.exe main.py
```

After automated tests pass, these optional live checks consume API quota. Run
individually; the calculator example opens a real application:

```text
You > Hello Jarvis
You > What is my current CPU usage?
You > Check my CPU and memory usage and tell me how my system is doing.
You > Open calculator.
You > Create the directory data/stage6-approved-test using file.create_directory.
Proceed? [y/N] > y
You > Create the directory data/stage6-rejected-test using file.create_directory.
Proceed? [y/N] > n
You > exit
```

Use fresh names within the project's test `data` folder, with its existing parent.
Verify no directory appears before approval and the rejected directory never
appears. Existing paths are never overwritten. The CLI shows the tool, risk,
description and exact JSON arguments before asking; inspect them before approval.
Only case-insensitive `y` and `yes`, trimmed of surrounding whitespace, approve.
Blank, `n`, and all other responses reject. Approval input never goes to Gemini.
`exit` or `quit` exits at the main prompt; at a confirmation prompt either rejects.
EOF exits cleanly; Ctrl+C cancels pending work and returns code 130. An OS action
already in progress cannot be rolled back by interruption. There is no shell syntax.

Automated CLI tests mock input/output, provider and launches; SDK task tests use
real serialization with an in-memory HTTP transport. Controller tests cover
sequential execution, budgets, repetitive/no-progress providers, confirmation
pause/resume, policy recheck, expiry, rejection, replay/races, isolated turns,
capacity/cleanup, immutable review state, privacy and context bounds. The original
216 tests retain their assertions; single-action tests explicitly call the retained
`run_single_turn()` API, and startup tests mock the newly introduced CLI boundary.
No live Gemini verification is part of automated tests. Stage 6 added no voice, persistent memory,
GUI, browser automation, or unrestricted autonomous execution is introduced.

### Retained Stage 5 single-action API

`Brain(provider).run_single_turn(user_text)` returns the original provider-independent `TurnResult`:
`text`, `error_id`, `tool_succeeded` (None before execution), `confirmation`, and
application-only `trusted_confirmation`. `confirmation_required` is a property.
Successful execution remains visible through `tool_succeeded=True` even when final
wording fails; Jarvis never retries that action automatically.

`ai.base.Provider.turn(text)` opens a context-managed `ProviderTurn`. Its
`propose()` returns `AssistantText`, `ToolCallProposal(tool_name, arguments)`, or
`ProviderError(error_id)`. `finish(sanitized_result)` is called only after a
successful automatically allowed action. `GeminiProvider()` implements this
interface and creates/closes one SDK client per turn. Core agent code imports no
Gemini SDK types. There is no automatic cross-turn conversation history or storage.

`build_tool_declarations()` translates exactly `REGISTRY.list_metadata()` into
22 `FunctionDeclaration` objects: exact names, trusted descriptions, and detached
`parameters_json_schema`. No raw callable or confirmation/rejection API is passed
to the SDK. Each request uses `AutomaticFunctionCallingConfig(disable=True)`;
the first request uses mode `AUTO`, the final wording request uses `NONE`.
Multiple structured calls execute none (`AI_MULTIPLE_TOOL_CALLS`). A final proposal
is rejected (`AI_ACTION_LIMIT`). Arbitrary prose is never interpreted as a call.
Registry/schema checks, Stage 4 permissions, and Stage 2 validation still apply.

The central default is `config.settings.DEFAULT_GEMINI_MODEL`, currently
`gemini-3.8-flash`, whose [official model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
lists function-calling support. The adapter follows the official SDK's
[manual function-calling interface](https://googleapis.github.io/python-genai/#manually-declare-and-invoke-a-function-for-function-calling).
Model configuration is syntax-validated locally; model availability, account access,
and quota are determined by Google at request time. Credentials are explicitly
passed from `GEMINI_API_KEY`; there is no fallback to `GOOGLE_API_KEY` or cloud
credentials. The Developer API endpoint is fixed in the adapter.

Only a successful tool's data crosses back into the provider. The JSON envelope
contains `success`, `data`, and `truncated`; original messages and error data are
omitted. Limits: **16,384 encoded JSON bytes**, depth **6**, **50** items per
container, **256** visited nodes, and **1,024** characters per string. Unsupported
objects/nonfinite numbers become null; sensitive key names are omitted. Any loss
sets `truncated=true`. If the encoded envelope still exceeds the byte bound, data
is replaced with null. The original `ExecutionResult` is never mutated.
This is a structural sanitizer, not general secret discovery: filenames and process
names may contain private text and are sent to Google when relevant to an allowed
request. The configured API key is additionally blocked/redacted by the adapter.

User input and assistant text are limited to **16,000 characters**; proposal
arguments to **16,384 JSON bytes**, depth **6**, **50** items per container and
**256** nodes. At most one candidate with **64** parts is accepted. SDK generation
uses **4,096 output tokens**; retained original model content is at most **65,536
bytes**. Signed function-call content and provider call IDs stay inside the
adapter for the immediate follow-up and are cleared on exit. Provider call IDs
are distinct from Stage 4 confirmation IDs.

For confirmation, the brain returns trusted metadata in `ConfirmationRequired`
and the real ID only in `TrustedConfirmation.confirmation_id`, excluded from repr.
It does not call `finish()` or send pending data to Gemini. Treat the full
`TurnResult` as application state: do not serialize it wholesale into a prompt or
log. Callers of this compatibility API must retain the ID and show the exact requested target before
explicit approval. This API adds no confirmation UI and never infers approval from
text. Denials and failures stop deterministically with no provider workaround.

Provider error identifiers:

| ID | Meaning |
| --- | --- |
| `AI_NOT_CONFIGURED` | Missing/blank API key |
| `AI_INVALID_CONFIGURATION` | Malformed key, model, or timeout |
| `AI_AUTH_FAILED` | Authentication rejected |
| `AI_RATE_LIMITED` | Provider rate limit |
| `AI_TIMEOUT` | Network timeout |
| `AI_NETWORK_ERROR` | Connection/transport failure |
| `AI_PROVIDER_ERROR` | Other SDK/provider failure |
| `AI_INVALID_RESPONSE` | Empty, malformed, blocked, or oversized response |
| `AI_MULTIPLE_TOOL_CALLS` | More than one structured action; none executed |
| `AI_ACTION_LIMIT` | Attempted second action or repeated turn operation |
| `AI_INVALID_INPUT` | Invalid/oversized text or unsafe provider input |

Timeout defaults to 30 seconds per network request, configurable from 1–120;
SDK retry attempts are fixed to 1 (no retries). This bounds network waits, not a
hard total wall-clock deadline across two requests, local tools, and OS scheduling.
AI debug logs contain only fixed request-start/completion, proposal and error events.
No prompts, responses, arguments, paths, URLs, keys, exceptions, or confirmation IDs
are logged by the AI layer. Ordinary conversation creates no security audit events.
Do not enable external SDK/HTTP wire tracing with credentials in a live session.

Offline tests use fake providers with real isolated Stage 4 gateways and mocked
tool implementations, plus real SDK types and an in-memory HTTP mock transport.
They exercise conversation, all risk levels (HIGH via trusted test metadata),
denials, invalid proposals, multiple actions, injection attempts, confirmation-ID
isolation, secret handling, configuration, failures, and result limits. No live
key, quota, network or external application is required. Python 3.14 triggers one
known upstream SDK import deprecation; only that exact warning in `google.genai.types`
is filtered during import. All other warnings remain subject to `-W error`.

### Optional Stage 5 Python verification

Automated verification does not use a real Gemini key. To opt into live requests,
set your own key locally, then open the interpreter:

```powershell
$env:GEMINI_API_KEY = "<developer supplies locally>"
# Optional: set JARVIS_GEMINI_MODEL to another compatible model.
.\.venv\Scripts\python.exe
```

Run these individually at the Python prompt. Each call consumes provider quota;
the LOW example opens a real application if proposed and allowed:

```python
from agent.brain import Brain
from ai.gemini import GeminiProvider
brain = Brain(GeminiProvider())

print(brain.run_single_turn("What is a CPU?").text)  # Conversational; no tool needed.
print(brain.run_single_turn("Use system.get_cpu_info to report my CPU core counts.").text)
print(brain.run_single_turn("Open Notepad using app.open_application.").text)  # LOW launch.
pending = brain.run_single_turn("Use file.create_directory to create data/stage5-example.")
print(pending.text, pending.confirmation_required)  # MEDIUM: must stop for approval.
```

Model choices are nondeterministic: inspect `error_id`, `tool_succeeded`, and
`confirmation_required`; a conversational answer alone does not prove execution.
The MEDIUM example does not create the directory until a separate trusted approval.
You may discard its pending state without executing it:

```python
from security.gateway import reject_confirmation
if pending.confirmation_required:
    reject_confirmation(pending.trusted_confirmation.confirmation_id)
```

No live Gemini verification was performed during Stage 5 implementation. Existing
filesystem race, local-Python trust, audit durability, and target-review limitations
still apply. The system instruction guides language behavior but cannot guarantee
truthful prose; deterministic gateway results remain authoritative. There is no
unrestricted autonomous agent, persistent memory, desktop UI, or background agent.

## V1 development roadmap

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Foundation, configuration, logging, models, tests | Implemented |
| 2 | Windows/system/application/file/browser tool implementations | Implemented |
| 3 | Tool registry and standardized execution | Implemented |
| 4 | Permission and security engine | Implemented |
| 5 | LLM provider integration and structured tool calling | Implemented |
| 6 | Planner/controller, bounded multi-step execution and development CLI | Implemented |
| 7 | SQLite memory | Implemented — release verification pending |
| 8 | Basic desktop interface | Planned |
| 9 | Testing, failure recovery, security hardening | Planned |
| 10 | Windows packaging and normal desktop usage | Planned |

Stage 6 stops at bounded in-memory task execution and a text development CLI.
Stage 7 persistent memory is implemented; its release requires automated and live verification.
Each stage requires its own scope and approval.

Future versions may add speech-to-text, text-to-speech, a wake word, screen
understanding, deeper Windows integration, local AI, reusable workflows, and
carefully bounded autonomous tasks.

## Changelog

### Unreleased — Stage 7 SQLite memory (2026-10-08)

- Added persistent, opt-in memory with six narrow registered operations and the
  existing MEDIUM/HIGH exact-action confirmation flow.
- Added fixed-query SQLite storage, atomic capacity enforcement, stale-record
  protection, schema version checks, explicit retention maintenance, lexical
  ranking and bounded untrusted retrieval. No dependencies or Stage 8 work added.
- Added secret-pattern checks, fixed safe errors, CLI consent guidance, and
  temporary-database regression coverage. Both suites pass 317 tests.
- Canonical version remains v0.6.1 until required live verification succeeds.
- Live creation, restart persistence, update/retrieval and confirmed deletion
  passed on 2026-10-08. HTTP 429 blocked the remaining rejection and Calculator/CPU
  live checks. The isolated verification database is empty; release is withheld.

### 0.6.1 — 2026-10-08

- Reproduced `google.genai.errors.ClientError`, HTTP 400 `INVALID_ARGUMENT`,
  during `tool_continuation`, after one successful Stage 4 action. The provider
  rejected the content role. Changed function-response content from `tool` to
  `user` in both Stage 6 `advance()` and Stage 5 `finish()`; the earlier adapter
  already contained this defect, and Stage 6 repeated it.
- Preserved typed SDK parts, original signed model content, function names/IDs,
  chronological history, manual execution, all controller limits, and sanitization.
- Added opt-in development-only provider metadata diagnostics and five offline
  regressions, including real SDK transport serialization through Stage 4.
  All three continuation regressions fail with the original roles.
- Both full test commands pass 279 tests (274 existing plus five new tests).
- Confirmed multiple sequential actions through the security gateway and real SDK
  continuation, including sequential READ_ONLY tool calls in the transport trace
  (`system.get_cpu_usage` followed by `system.get_memory_info`).
- Validated all security boundaries, offline fake providers, and exact-action
  confirmation gating prior to release promotion.

### 0.6.0 — 2026-10-06

- Added an iterative planner and deterministic controller with isolated state,
  action/provider budgets, canonical repeated-action detection, and no tool retries.
- Added confirmation pause/resume, single-use opaque turn handles, rejection,
  expiry, bounded synchronized pending storage, and context cleanup.
- Kept every action and confirmation behind Stage 4; no changes to tool authorization.
- Added bounded accumulated feedback and multi-step Gemini sessions preserving signed
  function-call content, with automatic SDK execution still disabled.
- Added a standard-library development CLI with explicit exact-action approval,
  default rejection, safe output, exit/quit, Ctrl+C and EOF handling.
- Retained Stage 5 behavior under `Brain.run_single_turn()` and added offline
  controller, CLI, context, replay, failure, concurrency and SDK-transport tests.
- Added no dependencies, persistent memory, voice, GUI, or shell capabilities.

### 0.5.0 — 2026-10-05

- Added provider-independent text/proposal/error contracts and an ephemeral turn API.
- Integrated `google-genai==2.28.0` using registry-derived function declarations,
  explicit automatic-calling disablement, bounded network timeouts, and no retries.
- Added a single-turn brain that executes only through Stage 4 and stops on
  confirmation, denial, invalid input, or multiple proposed actions.
- Isolated confirmation IDs in trusted application state; no model confirmation tools.
- Added bounded JSON feedback, sanitized errors and fixed operational log events.
- Added offline fake-provider, SDK mock-transport, injection, configuration, secret,
  confirmation-isolation and result-bound regression tests.
- Retained quota-free startup; no autonomous planner, persistent memory, or desktop UI.

### 0.4.0 — 2026-10-05

- Added fail-closed permission evaluation using registered metadata and immutable deny-only policy.
- Made `execute_tool` delegate to the authoritative security gateway; reused Stage 3
  lookup, schema validation, and sanitized invocation in an internal module.
- Added exact-action confirmations with 256-bit random IDs, immutable JSON argument
  snapshots, a fixed 300-second monotonic TTL, rejection, and atomic single-use consumption.
- Bounded pending storage, expired-entry cleanup, and isolated thread-safe gateway construction.
- Added structured security audit records with bounded memory history and optional
  append-only JSONL, excluding arguments, secrets, and confirmation IDs.
- Added stable permission/confirmation/audit errors and fail-closed pre-execution audit handling.
- Added policy, confirmation, concurrency, audit-redaction, and security regression tests;
  retained Stage 1–3 tests with necessary permission-contract updates.
- Preserved all Stage 2 primitives and checks; documented TOCTOU, local-code trust,
  audit durability/tampering, and tool-level confirmation-display limitations.
- Added no dependencies, LLM/API integration, autonomous behavior, or GUI confirmation dialog.

### 0.3.0 — 2026-10-05

- Explicitly registered all 16 existing Stage 2 operations with duplicate rejection.
- Added exact-name lookup, membership checks, and detached JSON-compatible metadata.
- Added standard-library schema validation without coercion or caller mutation;
  omitted optional arguments retain existing Python defaults.
- Added `execute_tool` with sanitized failures and defensive `ExecutionResult` checking.
- Added `INVALID_TOOL_NAME`, `TOOL_NOT_FOUND`, and `INVALID_TOOL_ARGUMENTS` request
  error IDs; unexpected failures reuse `TOOL_EXECUTION_FAILED`.
- Added registry/executor tests, source-level resolution checks, and default consistency checks.
- Preserved Stage 1/2 safeguards, tool implementations, and regression tests.
- Updated current architecture, API documentation, structure, and roadmap; added no dependencies.
- Kept authorization/confirmation, LLM/API integration, and autonomous execution unimplemented.

### 0.2.0 — 2026-10-02

- Added 16 deterministic direct-call tools using the existing metadata/risk/result models.
- Added reliable system measurements with the sole dependency `psutil==7.2.2`.
- Added fixed application aliases and VS Code project opening through native Windows launches.
- Added bounded filesystem listing/search and conservative associated-file opening.
- Added single-directory creation and same-volume, no-overwrite Windows rename/move primitives.
- Added local path/reparse validation, HTTP(S) validation, and encoded browser search opening.
- Added sanitized tool error handling and debug events without argument data.
- Added mocked launch, temporary filesystem, system, metadata, and regression tests.
- Updated setup, tool contracts, validation limits, manual checks, and Stage 2 roadmap status.
- Kept registry/dispatcher, active permissions, AI, and autonomous execution unimplemented.

### 0.1.0 — 2026-10-02

- Established Stage 1 project structure and canonical version source.
- Added validated environment configuration and non-destructive runtime directory setup.
- Added reusable console/file JSON logging and clean startup/shutdown handling.
- Defined provider-independent risk, tool metadata, execution result, and permission models.
- Documented future controller/security boundaries without implementing automation.
- Added isolated standard-library tests, environment example, and Python/Windows ignore rules.
- Established this README as the authoritative project specification and roadmap.
