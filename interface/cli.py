"""Trusted terminal confirmation UI. No shell syntax or execution authority in prose."""

import os

from config.settings import ConfigurationError, load_gemini_settings
from tools.registry import REGISTRY


def _display(text):
    # Do not allow model text or paths to inject terminal controls or print the key.
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        text = text.replace(key, "[redacted]")
    return "".join(char if char.isprintable() or char == "\n" else "?" for char in text)


def run_cli(brain, *, read=None, write=None):
    read = input if read is None else read
    write = print if write is None else write

    def say(text):
        write(_display(text))

    try:
        try:
            load_gemini_settings()
            configured = True
            say("AI: Gemini (Configured)")
        except ConfigurationError:
            configured = False
            say("AI: Not configured. Set GEMINI_API_KEY and check model/timeout configuration.")
        say(f"Tools: {len(REGISTRY.list_metadata())}\nSecurity: Active\nType exit or quit to leave.")
        while True:
            text = read("You > ")
            if text.strip().lower() in {"exit", "quit"}:
                break
            if not text.strip():
                continue
            if not configured:
                say("Jarvis > AI is not configured. Set GEMINI_API_KEY in PowerShell and restart.")
                continue
            result = brain.run_turn(text)
            while result.confirmation_required:
                review = result.confirmation
                say("Jarvis > This action requires confirmation.")
                say(f"Action: {review.tool_name}\nDescription: {review.description}\nRisk: {review.risk.upper()}\nArguments: {review.arguments_json}")
                if review.tool_name in {"memory.create", "memory.update", "memory.delete"}:
                    say("Memory consent: approve only the exact record and fields above. "
                        "Updates replace all fields; omitted tags and expiration are cleared. "
                        "If the intended record is ambiguous, answer no and select a record first.")
                answer = read("Proceed? [y/N] > ").strip().lower()
                result = brain.confirm_turn(result.turn_id) if answer in {"y", "yes"} else brain.reject_turn(result.turn_id)
            say("Jarvis > " + result.text)
            if result.error_id:
                say(f"Status: {result.error_id}; completed actions: {result.completed_actions}")
        say("Jarvis > Goodbye.")
        return 0
    except EOFError:
        say("Jarvis > Goodbye.")
        return 0
    except KeyboardInterrupt:
        say("Jarvis > Interrupted. Pending actions cancelled; check any action already in progress.")
        return 130
    except Exception:
        say("Jarvis > The session stopped (CLI_FAILED). Check action state before retrying.")
        return 1
    finally:
        brain.close()
