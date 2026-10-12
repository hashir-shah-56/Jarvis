"""Real SDK wire regression for the live INVALID_ARGUMENT continuation failure."""

import base64
import json
import os
import unittest
from unittest.mock import Mock, patch

import httpx

from agent.brain import Brain
from ai.gemini import GeminiProvider, _diagnose
from core.models import ExecutionResult
from google.genai import Client, errors, types
from security.gateway import SecurityGateway
from tools.registry import REGISTRY, RegisteredTool, ToolRegistry
from tests.test_gemini import FAKE_KEY, call, response


class ContinuationRegressionTests(unittest.TestCase):
    def exercise(self, proposals, *, single=False):
        seen = []
        operations = {}
        entries = []
        for metadata in REGISTRY.list_metadata():
            operation = Mock(return_value=ExecutionResult(True, "ok", {
                "value": 42, "confirmation_id": "private-confirmation",
                "api_key": FAKE_KEY, "large": "x" * 2000,
            }))
            operations[metadata["name"]] = operation
            entries.append(RegisteredTool(REGISTRY.get(metadata["name"]).metadata, operation))
        gateway = SecurityGateway(registry=ToolRegistry(entries))
        for index, part in enumerate(proposals):
            part.function_call.id = f"call-{index}"
            part.thought_signature = bytes([255, 0, 128, index])
        responses = iter([response(part) for part in proposals] + [response(types.Part(text="done"))])

        def handler(request):
            payload = json.loads(request.content)
            seen.append(payload)
            # Reproduce the actual server validation: SDK types alone accept tool.
            if any(content["role"] not in {"user", "model"} for content in payload["contents"]):
                return httpx.Response(400, json={"error": {
                    "code": 400, "status": "INVALID_ARGUMENT",
                    "message": "Role is not supported; use user or model.",
                }})
            return httpx.Response(200, json=next(responses).model_dump(mode="json", by_alias=True, exclude_none=True))

        with patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_KEY}, clear=True):
            with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
                with Client(api_key=FAKE_KEY, vertexai=False, enterprise=False,
                            http_options=types.HttpOptions(httpx_client=transport)) as client:
                    with patch("ai.gemini.genai.Client", return_value=client), patch("security.gateway._DEFAULT_GATEWAY", gateway):
                        brain = Brain(GeminiProvider())
                        try:
                            result = brain.run_single_turn("request") if single else brain.run_turn("request")
                        finally:
                            brain.close()
        self.assertIsNone(result.error_id)
        self.assertEqual(result.text, "done")
        if not single:
            self.assertEqual(result.completed_actions, len(proposals))
        self.assertEqual(len(seen), len(proposals) + 1)
        for index, part in enumerate(proposals):
            operations[part.function_call.name].assert_called_once_with(**part.function_call.args)
            model, feedback = seen[-1]["contents"][1 + index * 2:3 + index * 2]
            self.assertEqual(model["role"], "model")
            self.assertEqual(feedback["role"], "user")
            model_part = model["parts"][0]
            self.assertEqual(base64.urlsafe_b64decode(model_part["thoughtSignature"]), part.thought_signature)
            returned = feedback["parts"][0]["functionResponse"]
            self.assertEqual(returned["name"], model_part["functionCall"]["name"])
            self.assertEqual(returned["id"], model_part["functionCall"]["id"])
            self.assertIsInstance(returned["response"], dict)
            self.assertTrue(returned["response"]["success"])
            self.assertTrue(returned["response"]["truncated"])
        wire = json.dumps(seen)
        self.assertNotIn("private-confirmation", wire)
        self.assertNotIn(FAKE_KEY, wire)
        self.assertNotIn("x" * 1025, wire)
        self.assertEqual(seen[-1]["toolConfig"]["functionCallingConfig"]["mode"], "NONE" if single else "AUTO")

    def test_low_action_through_gateway_and_real_sdk_continuation(self):
        self.exercise([call("app.open_application", {"alias": "calculator"})])

    def test_two_read_only_actions_through_gateway_and_real_sdk(self):
        self.exercise([call("system.get_cpu_usage"), call("system.get_memory_info")])

    def test_stage5_final_response_uses_valid_role(self):
        self.exercise([call("app.open_application", {"alias": "calculator"})], single=True)

    def test_diagnostics_opt_in_and_production_suppression(self):
        exception = errors.ClientError(400, {"error": {
            "status": "INVALID_ARGUMENT", "message": "Role is not supported " + FAKE_KEY,
        }})
        for environment, enabled in [("production", "1"), ("testing", "1"), ("development", "0")]:
            with patch.dict(os.environ, {"JARVIS_ENV": environment, "JARVIS_PROVIDER_DIAGNOSTICS": enabled}, clear=True):
                with self.assertNoLogs("jarvis.ai.gemini"):
                    _diagnose(exception, "tool_continuation")

    def test_diagnostics_use_only_fixed_metadata_and_reasons(self):
        private = "key user prompt https://private/path C:/private search confirmation-id"
        for phase in ("initial_proposal", "tool_continuation", "final_response"):
            with patch.dict(os.environ, {"JARVIS_ENV": "development", "JARVIS_PROVIDER_DIAGNOSTICS": "1"}, clear=True):
                exception = errors.ClientError(400, {"error": {
                    "status": "INVALID_ARGUMENT", "message": "Role is not supported " + private,
                }})
                with self.assertLogs("jarvis.ai.gemini") as logs:
                    _diagnose(exception, phase)
                    _diagnose(RuntimeError(private), phase)
                self.assertIn("reason=unsupported_content_role", logs.output[0])
                self.assertIn("exception=ClientError status=400 category=INVALID_ARGUMENT", logs.output[0])
                self.assertIn("phase=" + phase, logs.output[0])
                self.assertNotIn(private, " ".join(logs.output))
                self.assertIn("reason=details_withheld", logs.output[1])
