# Jarvis

Jarvis is a personal Windows AI desktop assistant project inspired by fictional
assistants such as JARVIS. Its long-term vision is to understand natural-language
instructions, plan bounded tasks, use approved tools, maintain memory, and later
support voice and screen understanding.

**Current version: 0.1.0. Current stage: JARVIS V1 — Stage 1: Project Foundation.**
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
- Standard-library tests using temporary directories, with no external services.

Stage 1 starts, reports readiness, and exits. There is no interactive assistant loop.
`Status: Ready` means the foundation initialized successfully.

## Explicitly unimplemented

No LLM/API integration, AI reasoning, autonomous agent, shell executor, Windows
automation, application launching, file tools, browser automation, voice recognition,
text-to-speech, wake word, screen capture/vision, destructive file actions, software
installation, autonomous messaging, or financial actions exist. There is also no
tool registry/dispatcher, active permission/security engine, planner, persistent
memory/database, desktop interface, or packaging yet.

The only current runtime filesystem writes are directory creation and application
logs. Documentation-only modules reserve future boundaries without pretending to
implement them.

## Architecture

Current startup:

```text
main.py -> configuration -> runtime directories -> logging -> banner -> shutdown
```

Planned execution architecture (not active in Stage 1):

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

Stage 1 reduces exposure by having no tool execution path. The security modules
document requirements; they do not claim to enforce future tool safety.

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

Application logs are not security audit logs. Stage 1 logs only fixed lifecycle/error
messages, never environment dumps or raw exception details. The JSON formatter omits
exception tracebacks and arbitrary record extras. It does not redact secrets from
message text: future callers must sanitize messages and result data before logging
or displaying them. A sanitized `STARTUP_FAILED` message intentionally omits the
underlying exception and paths.

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
|   `-- settings.py
|-- agent/
|   |-- __init__.py
|   |-- brain.py
|   |-- planner.py
|   |-- controller.py
|   `-- permissions.py
|-- tools/
|   |-- __init__.py
|   |-- base.py           # ToolMetadata
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
    `-- test_main.py
```

## Setup and running (Windows PowerShell)

Use Python 3.11 or newer, Git, and optionally Visual Studio Code. Stage 1 has no
third-party dependencies; `requirements.txt` intentionally contains only a comment.
Python 3.14.3 is the development verification environment. No installation of
future SDKs or automation packages is needed.

Open the repository folder in VS Code and open its PowerShell terminal. For a fresh
checkout, create a virtual environment; reuse an existing `.venv` if already present:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python main.py
```

If activation is restricted, use the interpreter directly without changing your
PowerShell execution policy:

```powershell
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

No secret settings are needed in Stage 1. Future secrets must come from environment
variables. `.env` files are ignored by Git; `.env.example` is retained. Default
runtime content is ignored; custom runtime locations within the repository need
their own ignore entries before committing.

### Running tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover defaults, environment overrides, invalid settings, safe/idempotent
directory creation, version retrieval, risk/result/tool/permission models, logging
fields and lifecycle, startup, interrupts, and sanitized failures. Filesystem tests
use temporary directories. Tests do not execute system commands, access external
services, or require API keys.

Future modules can use `core.logging.get_logger("component")` after the entry point
initializes logging. Importing modules does not initialize directories, logs, or tools.

## V1 development roadmap

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Foundation, configuration, logging, models, tests | Implemented |
| 2 | Windows/system/application/file/browser tool implementations | Planned |
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
and approval; Stage 2 is not started as part of the foundation.

Future versions may add speech-to-text, text-to-speech, a wake word, screen
understanding, deeper Windows integration, local AI, reusable workflows, and
carefully bounded autonomous tasks.

## Changelog

### 0.1.0 — 2026-10-02

- Established Stage 1 project structure and canonical version source.
- Added validated environment configuration and non-destructive runtime directory setup.
- Added reusable console/file JSON logging and clean startup/shutdown handling.
- Defined provider-independent risk, tool metadata, execution result, and permission models.
- Documented future controller/security boundaries without implementing automation.
- Added isolated standard-library tests, environment example, and Python/Windows ignore rules.
- Established this README as the authoritative project specification and roadmap.
