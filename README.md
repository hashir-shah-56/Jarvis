# Jarvis

Jarvis is a personal Windows AI desktop assistant project inspired by fictional
assistants such as JARVIS. Its long-term vision is to understand natural-language
instructions, plan bounded tasks, use approved tools, maintain memory, and later
support voice and screen understanding.

**Current version: 0.2.0. Current stage: JARVIS V1 — Stage 2: Deterministic Tools.**
The executable version has one canonical source: `core.__version__` in
`core/__init__.py`; application code retrieves it using `get_version()`.

> README.md is the single source of truth for Jarvis. Any implementation task that changes architecture, capabilities, permissions, dependencies, configuration, security behavior, project structure, setup, or supported functionality must update README.md and its changelog in the same task.

## Current capabilities

- Explicit, validated environment-based configuration using an immutable settings model.
- Safe creation of missing runtime directories; existing contents are preserved.
- Reusable JSON-line console and UTF-8 file logging with UTC timestamps, severity,
  component name, and message. Files are appended to, never truncated by startup.
- Startup banner, immediate clean shutdown, and sanitized top-level error reporting.
- Provider-independent tool metadata, risk levels, execution results, and permission
  decision vocabulary. These models do not execute or authorize actions.
- Direct-call system, allowlisted application, bounded filesystem, and browser-opening tools.
- Local path and HTTP(S) URL validation, plus sanitized tool failures with stable error IDs.
- Tests using `unittest`, temporary directories, fixed system measurements, and mocked launches.

The application still starts, reports readiness, and exits. It does not invoke tools.
There is no interactive assistant loop.
`Status: Ready` means the foundation initialized successfully.

### Stage 2 tools

Every public tool operation returns the existing `ExecutionResult`. Corresponding
`<FUNCTION_NAME>_METADATA` constants live beside each implementation, using the
existing `ToolMetadata` and `RiskLevel` types. There is no registry or dispatcher.
These are deterministic primitives invoked directly by controlled Python code/tests.

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

## Explicitly unimplemented

There is still no LLM/API integration, AI reasoning, tool registry/dispatcher,
autonomous controller, active permission engine, or autonomous execution. There is
no generic shell/PowerShell/CMD execution, `eval`/`exec`, arbitrary executable input,
file/directory deletion, software-installation tool, shutdown/restart, registry or
service manipulation, privilege escalation, credential/cookie extraction, messaging,
financial action, mouse/keyboard/screen control, browser automation/scraping, voice,
wake word, persistent memory/database, desktop UI, or packaging.

MEDIUM-risk filesystem primitives are not available to an AI because no AI execution
path exists. They do not prompt for confirmation; they are for direct controlled
invocation/tests only. Stage 4 permission enforcement has not been implemented.

## Architecture

Current startup:

```text
main.py -> configuration -> runtime directories -> logging -> banner -> shutdown
```

Current direct tool path:

```text
Controlled Python caller -> specific tool -> input checks -> bounded operation
                        -> sanitized ExecutionResult
```

The error wrapper in `tools/_support.py` sanitizes results and emits debug events;
it is neither a dispatcher nor a permission check. Importing tools performs no
launches or filesystem modifications.

Planned execution architecture (not active yet):

```text
User -> Interface -> AI Brain -> Planner -> Agent Controller
     -> Permission Engine -> Security Validator -> Approved Tool
     -> Result -> Agent -> User
```

The AI may propose structured intent and tool calls. A controller independent of
the LLM must resolve approved tools, enforce permission decisions, validate inputs,
and execute only authorized actions. An LLM must never receive unrestricted OS
access or an unrestricted PowerShell execution path.

`ToolMetadata` describes a unique name, description, `RiskLevel`, and argument schema
(intended as JSON Schema). Registry uniqueness and schema validation are future
work. `ExecutionResult` contains `success`, a human-readable `message`, optional
structured `data`, and optional `error_id`. Models use type hints; they are not
runtime security validators. Data/schema mappings should hold JSON-compatible
values; frozen dataclasses do not make nested mappings immutable.

## Security and permissions

Stage 2 implements input validation in `security/validator.py`. The policy module
still documents future requirements; no authorization decisions are enforced.

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

These are input checks, not Stage 4-grade sandbox security. There is no filesystem
allowlist, confirmation flow, handle-based race-proof validation, or full audit log.
Prevalidation cannot stop a different process replacing a parent with a reparse
point between checks and execution. Use only trusted local trees, installations,
environment variables, and associations under direct developer control.

Future requirements:

- No unrestricted arbitrary commands; use approved structured tools and least privilege.
- Validate canonical paths before filesystem modifications, including symlinks and
  validation/execution races; validate URLs and redirects before network actions.
- Require explicit confirmation for destructive or sensitive operations, tied to
  the exact action. Maintain sanitized audit logs of decisions and actions.
- Fail closed when authorization or validation is absent or uncertain.
- Keep secrets in environment variables; never hard-code credentials or give an
  LLM authority to approve its own requests.

| Risk | Planned default behavior |
| --- | --- |
| `READ_ONLY` | Normally automatic, subject to validation and policy |
| `LOW` | Normally automatic, subject to validation and policy |
| `MEDIUM` | May require confirmation depending on future configuration |
| `HIGH` | Explicit user confirmation required |

`PermissionDecision` defines `ALLOW`, `REQUIRE_CONFIRMATION`, and `DENY` only.
No evaluator, confirmation setting, or enforcement exists yet. The future
controller must enforce permission decisions, independently of the LLM.

Application logs are not security audit logs. Startup logs fixed lifecycle/error
messages; tools log only their operation name and completion/error identifier at
DEBUG level. They never log paths, URLs, search queries, file contents, process names,
environment dumps, or raw exception details. The JSON formatter omits
exception tracebacks and arbitrary record extras. It does not redact secrets from
message text: future callers must sanitize messages and result data before logging
or displaying them. A sanitized `STARTUP_FAILED` message intentionally omits the
underlying exception and paths. Tool failures likewise return fixed safe messages
with identifiers such as `INVALID_PATH`, `PATH_NOT_FOUND`, `NOT_A_DIRECTORY`,
`DESTINATION_EXISTS`, `ACCESS_DENIED`, `UNSAFE_PATH`, `UNSUPPORTED_FILE_TYPE`,
`INVALID_URL`, `UNSUPPORTED_URL_SCHEME`, `APP_NOT_ALLOWED`, `APP_NOT_FOUND`,
`CROSS_DEVICE_MOVE`, `PROCESS_QUERY_FAILED`, and `TOOL_EXECUTION_FAILED`.

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
|   |-- logging.py       # Logging setup, formatter, lifecycle
|   |-- models.py        # RiskLevel and ExecutionResult
|   `-- runtime.py       # Directory initialization
|-- config/
|   |-- __init__.py
|   |-- settings.py
|   `-- tool_settings.py  # Trusted aliases, search provider, extensions, limits
|-- agent/
|   |-- __init__.py
|   |-- brain.py
|   |-- planner.py
|   |-- controller.py
|   `-- permissions.py
|-- tools/
|   |-- __init__.py
|   |-- base.py           # ToolMetadata
|   |-- _support.py       # Error/metadata helpers, no dispatcher
|   |-- system_tools.py
|   |-- app_tools.py
|   |-- file_tools.py
|   `-- browser_tools.py
|-- memory/
|   |-- __init__.py
|   `-- database.py
|-- security/
|   |-- __init__.py
|   |-- validator.py
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
    `-- test_tool_contracts.py
```

## Setup and running (Windows PowerShell)

Use Windows 11, Python 3.11 or newer, Git, and optionally Visual Studio Code.
Python 3.14.3 on Windows is the development verification environment; Python 3.11
syntax is checked, but a separate 3.11 runtime has not been tested here.

The only third-party dependency is **`psutil==7.2.2`**, pinned for reliable CPU
utilization, physical memory, and process measurements (also used for disk usage).
This replaces the need for shell commands or custom native bindings for those
measurements. See the [psutil documentation](https://psutil.readthedocs.io/stable/)
and [pinned release](https://pypi.org/project/psutil/7.2.2/). No Playwright, LLM SDK,
voice package, GUI framework, or Windows automation dependency is added.

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

Environment and level values ignore case and surrounding whitespace. Path values
are trimmed and support `~` expansion. Relative paths are resolved against the
project root regardless of the process working directory; absolute paths are
supported. Invalid values cause startup failure. Loading settings alone does not
create directories.

`.env.example` is a reference, not an automatically loaded file. Set variables in
PowerShell; no dotenv dependency or real `.env` file is needed:

```powershell
$env:JARVIS_ENV = "development"
$env:JARVIS_LOG_LEVEL = "DEBUG"
$env:JARVIS_DATA_DIR = "data"
$env:JARVIS_LOG_DIR = "logs"
.\.venv\Scripts\python.exe main.py
```

No secret settings are needed in Stage 2. Future secrets must come from environment
variables. `.env` files are ignored by Git; `.env.example` is retained. Default
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

Future modules can use `core.logging.get_logger("component")` after the entry point
initializes logging. Importing modules does not initialize directories, logs, or tools.

### Optional manual Stage 2 verification

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

For direct primitive use, import functions from their specific modules; there is
no text-command endpoint or generic execution API. Inspect `result.success`,
`result.message`, `result.data`, and `result.error_id` rather than parsing log text.

## V1 development roadmap

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Foundation, configuration, logging, models, tests | Implemented |
| 2 | Windows/system/application/file/browser tool implementations | Implemented |
| 3 | Tool registry and standardized execution | Planned |
| 4 | Permission and security engine | Planned |
| 5 | LLM provider integration and structured tool calling | Planned |
| 6 | Planner/controller and bounded multi-step execution | Planned |
| 7 | SQLite memory | Planned |
| 8 | Basic desktop interface | Planned |
| 9 | Testing, failure recovery, security hardening | Planned |
| 10 | Windows packaging and normal desktop usage | Planned |

Stages 2–3 must not expose tools to an LLM or autonomous controller before the
permission/security boundaries are implemented. Each stage requires its own scope
and approval. Stage 2 stops at direct-call primitives; Stage 3 has not started.

Future versions may add speech-to-text, text-to-speech, a wake word, screen
understanding, deeper Windows integration, local AI, reusable workflows, and
carefully bounded autonomous tasks.

## Changelog

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
