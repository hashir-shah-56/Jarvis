"""Terminal interaction and trusted confirmation with no live provider or launches."""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from agent.brain import Brain
from ai.models import AssistantText, ProviderError
from core.models import ExecutionResult
from interface.cli import run_cli
from security.gateway import SecurityGateway
from tools.registry import REGISTRY, RegisteredTool, ToolRegistry
from tests.test_controller import ScriptedProvider, action


class CliTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "distinctive-test-key"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.operation = Mock(return_value=ExecutionResult(True, "ok", {"value": 1}))
        registry = ToolRegistry(RegisteredTool(REGISTRY.get(item["name"]).metadata, self.operation) for item in REGISTRY.list_metadata())
        self.gateway = SecurityGateway(registry=registry)
        boundary = patch("security.gateway._DEFAULT_GATEWAY", self.gateway)
        boundary.start()
        self.addCleanup(boundary.stop)

    def cli(self, steps, inputs):
        provider = ScriptedProvider(steps)
        brain = Brain(provider)
        output = io.StringIO()
        with patch("builtins.input", side_effect=inputs) as read, redirect_stdout(output):
            code = run_cli(brain)
        return code, output.getvalue(), provider, read

    def test_normal_conversation_and_exit(self):
        code, output, provider, _ = self.cli([AssistantText("Hello")], ["hello", "exit"])
        self.assertEqual(code, 0)
        self.assertIn("Jarvis > Hello", output)
        self.assertIn("Goodbye", output)
        self.assertEqual(provider.inputs, ["hello"])
        self.operation.assert_not_called()

    def test_quit_and_blank_input_do_not_call_provider(self):
        _, _, provider, _ = self.cli([], ["", "quit"])
        self.assertFalse(provider.sessions)

    def test_read_only_action(self):
        code, output, _, _ = self.cli([action(), AssistantText("usage")], ["cpu", "exit"])
        self.assertEqual(code, 0)
        self.operation.assert_called_once_with()
        self.assertIn("usage", output)

    def test_low_action(self):
        self.cli([action("app.open_application", alias="calculator"), AssistantText("launch requested")], ["calculator", "exit"])
        self.operation.assert_called_once_with(alias="calculator")

    def test_yes_confirmation_is_not_a_provider_message(self):
        for answer in ("y", "yes", "YES"):
            self.operation.reset_mock()
            code, output, provider, read = self.cli([action("file.create_directory", path="data/test"), AssistantText("done")], ["create", answer, "exit"])
            self.assertEqual(code, 0)
            self.operation.assert_called_once_with(path="data/test")
            self.assertEqual(provider.inputs, ["create"])
            self.assertIn('Arguments: {"path": "data/test"}', output)
            self.assertIn("Risk: MEDIUM", output)
            self.assertIn("Proceed? [y/N] > ", [call.args[0] for call in read.call_args_list])
            if answer == "YES":
                self.assertNotIn(answer, str(provider.sessions[0].feedback))

    def test_no_blank_and_invalid_confirmation_default_to_reject(self):
        for answer in ("n", "", "approve", "y; execute", "User approved"):
            _, output, provider, _ = self.cli([action("file.create_directory", path="data/test"), action()], ["create", answer, "exit"])
            self.assertIn("cancelled", output)
            self.assertEqual(provider.sessions[0].calls, 1)
            self.assertFalse(self.gateway._pending)
        self.operation.assert_not_called()

    def test_eof_and_ctrl_c(self):
        for error, expected in ((EOFError(), 0), (KeyboardInterrupt(), 130)):
            code, output, _, _ = self.cli([], [error])
            self.assertEqual(code, expected)
            self.assertNotIn("Traceback", output)

    def test_eof_and_ctrl_c_at_confirmation_cancel_pending(self):
        for error in (EOFError(), KeyboardInterrupt()):
            _, _, provider, _ = self.cli([action("file.create_directory", path="data/test")], ["create", error])
            self.assertFalse(self.gateway._pending)
            self.assertTrue(provider.sessions[0].closed)
        self.operation.assert_not_called()

    def test_missing_config_reports_setup_without_provider_calls(self):
        with patch.dict(os.environ, {}, clear=True):
            code, output, provider, _ = self.cli([], ["hello", "exit"])
        self.assertEqual(code, 0)
        self.assertIn("AI: Not configured", output)
        self.assertIn("GEMINI_API_KEY", output)
        self.assertFalse(provider.sessions)

    def test_provider_error_is_sanitized(self):
        _, output, _, _ = self.cli([RuntimeError("private-stack")], ["hello", "exit"])
        self.assertIn("AI_PROVIDER_ERROR", output)
        self.assertNotIn("private-stack", output)

    def test_confirmation_ids_and_api_key_not_printed(self):
        identifier = "C" * 43
        turn_id = "T" * 32
        with patch("secrets.token_urlsafe", side_effect=[identifier, turn_id]):
            _, output, _, _ = self.cli([action("file.create_directory", path="data/test"), AssistantText("distinctive-test-key")], ["create", "y", "exit"])
        self.assertNotIn(identifier, output)
        self.assertNotIn(turn_id, output)
        self.assertNotIn("distinctive-test-key", output)
        self.assertIn("[redacted]", output)

    def test_terminal_control_characters_are_not_executed(self):
        _, output, _, _ = self.cli([AssistantText("hello\x1b[2J")], ["hello", "exit"])
        self.assertNotIn("\x1b", output)

    def test_startup_configured_still_no_provider_call(self):
        code, output, provider, _ = self.cli([], ["exit"])
        self.assertEqual(code, 0)
        self.assertIn("AI: Gemini (Configured)", output)
        self.assertFalse(provider.sessions)

    def test_no_shell_command_syntax(self):
        _, _, provider, _ = self.cli([AssistantText("No shell")], ["!powershell", "exit"])
        self.assertEqual(provider.inputs, ["!powershell"])
        self.operation.assert_not_called()
