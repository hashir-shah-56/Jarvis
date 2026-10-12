"""Real pinned SDK models/config/serialization, fake transport; no API quota."""

import json
import os
import unittest
from unittest.mock import Mock, patch

import httpx

from agent.brain import Brain
from ai.gemini import GeminiProvider, build_tool_declarations, parse_response
from google import genai
from google.genai import errors, types
from google.genai import Client as SDKClient
from ai.models import AssistantText, ProviderError, ToolCallProposal
from config.settings import DEFAULT_GEMINI_MODEL, ConfigurationError, load_gemini_settings
from tools.registry import REGISTRY

FAKE_KEY = "distinctive-fake-key-not-a-real-credential"


def response(*parts, finish="STOP"):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=list(parts)), finish_reason=finish,
    )])


def call(name="system.get_cpu_info", args=None):
    return types.Part(function_call=types.FunctionCall(name=name, args={} if args is None else args))


class ConfigurationTests(unittest.TestCase):
    def test_present_default_model_timeout_and_secret_repr(self):
        settings = load_gemini_settings({"GEMINI_API_KEY": FAKE_KEY})
        self.assertEqual(settings.api_key, FAKE_KEY)
        self.assertEqual(settings.model, DEFAULT_GEMINI_MODEL)
        self.assertEqual(settings.timeout_seconds, 30)
        self.assertNotIn(FAKE_KEY, repr(settings))

    def test_missing_and_blank_key(self):
        for value in ({}, {"GEMINI_API_KEY": ""}, {"GEMINI_API_KEY": " "}, {"GOOGLE_API_KEY": FAKE_KEY}):
            with self.assertRaisesRegex(ConfigurationError, "^AI_NOT_CONFIGURED$"):
                load_gemini_settings(value)

    def test_configured_model_and_timeout(self):
        settings = load_gemini_settings({"GEMINI_API_KEY": FAKE_KEY, "JARVIS_GEMINI_MODEL": "gemini-test-model", "JARVIS_AI_TIMEOUT_SECONDS": "15"})
        self.assertEqual(settings.model, "gemini-test-model")
        self.assertEqual(settings.timeout_seconds, 15)

    def test_invalid_configuration_has_fixed_error(self):
        for key, values in (
            ("JARVIS_GEMINI_MODEL", ("", " ", "secret/path", "other", None)),
            ("JARVIS_AI_TIMEOUT_SECONDS", ("", "0", "121", "nan", "1.5", None)),
            ("GEMINI_API_KEY", ("private key", " private", "private\n")),
        ):
            for value in values:
                with self.assertRaisesRegex(ConfigurationError, "^AI_INVALID_CONFIGURATION$"):
                    load_gemini_settings({"GEMINI_API_KEY": FAKE_KEY, key: value})


class GeminiTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_KEY}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self._factory_patcher = patch("ai.gemini.genai.Client")
        self.factory = self._factory_patcher.start()
        self.addCleanup(self._factory_patcher.stop)
        self.client = self.factory.return_value
        self.generate = self.client.models.generate_content

    def test_exact_sdk_pin(self):
        self.assertEqual(genai.__version__, "2.28.0")

    def test_declarations_exactly_match_registry_and_are_detached(self):
        declarations = build_tool_declarations()
        metadata = REGISTRY.list_metadata()
        self.assertEqual(len(declarations), 22)
        self.assertEqual(declarations, build_tool_declarations())
        for declaration, item in zip(declarations, metadata):
            self.assertEqual(declaration.name, item["name"])
            self.assertEqual(declaration.description, item["description"])
            self.assertEqual(declaration.parameters_json_schema, item["arguments_schema"])
            self.assertFalse(callable(declaration))
            self.assertNotIn("confirm", declaration.name)
            self.assertNotIn("reject", declaration.name)
        declarations[0].parameters_json_schema["additionalProperties"] = True
        self.assertEqual(metadata, REGISTRY.list_metadata())

    def test_text_and_structured_argument_parse(self):
        self.assertEqual(parse_response(response(types.Part(text="hello"))), AssistantText("hello"))
        proposal = parse_response(response(call("system.list_processes", {"limit": 3})))
        self.assertEqual(proposal, ToolCallProposal("system.list_processes", {"limit": 3}))
        self.assertIs(type(proposal.arguments["limit"]), int)

    def test_malformed_empty_blocked_and_nontext_responses(self):
        for item in (None, {}, types.GenerateContentResponse(), response(), response(types.Part(text="")),
                     response(types.Part(text="private"), finish="SAFETY"),
                     response(call(), finish="MAX_TOKENS"),
                     response(types.Part(function_call=types.FunctionCall(name="x"))),
                     response(types.Part(function_call=types.FunctionCall(name="x", args={}, will_continue=True))),
                     response(types.Part(inline_data=types.Blob(data=b"x", mime_type="image/png"))),
                     response(types.Part(text="thought only", thought=True))):
            self.assertEqual(parse_response(item), ProviderError("AI_INVALID_RESPONSE"))

    def test_multiple_calls_execute_none(self):
        self.generate.return_value = response(call(), call())
        with patch("security.gateway.request_execution") as execute:
            result = Brain(GeminiProvider()).run_single_turn("Do two actions")
        self.assertEqual(result.error_id, "AI_MULTIPLE_TOOL_CALLS")
        execute.assert_not_called()
        self.generate.assert_called_once()

    def test_multiple_candidates_fail_closed(self):
        item = response(call())
        item.candidates.append(item.candidates[0])
        self.assertEqual(parse_response(item), ProviderError("AI_INVALID_RESPONSE"))

    def test_lazy_client_missing_config_no_quota(self):
        provider = GeminiProvider()
        self.factory.assert_not_called()
        with patch.dict(os.environ, {}, clear=True):
            result = Brain(provider).run_single_turn("Hello")
        self.assertEqual(result.error_id, "AI_NOT_CONFIGURED")
        self.factory.assert_not_called()

    def test_manual_config_timeout_no_retry_and_client_cleanup(self):
        self.generate.return_value = response(types.Part(text="hello"))
        self.assertEqual(Brain(GeminiProvider()).run_single_turn("Hi").text, "hello")
        options = self.factory.call_args.kwargs
        self.assertEqual(options["api_key"], FAKE_KEY)
        self.assertFalse(options["vertexai"])
        self.assertFalse(options["enterprise"])
        self.assertEqual(options["http_options"].timeout, 30000)
        self.assertEqual(options["http_options"].retry_options.attempts, 1)
        config = self.generate.call_args.kwargs["config"]
        self.assertTrue(config.automatic_function_calling.disable)
        self.assertEqual(config.tool_config.function_calling_config.mode, "AUTO")
        self.assertEqual(len(config.tools[0].function_declarations), 22)
        self.assertNotIn(FAKE_KEY, config.model_dump_json())
        self.client.close.assert_called_once()

    def test_followup_retains_signature_call_id_and_disables_functions(self):
        part = call()
        part.thought_signature = b"opaque-signature"
        part.function_call.id = "provider-call-id"
        first = response(part)
        self.generate.side_effect = [first, response(types.Part(text="four cores"))]
        with GeminiProvider().turn("How many cores?") as turn:
            self.assertIsInstance(turn.propose(), ToolCallProposal)
            self.assertEqual(turn.finish({"success": True, "data": {"count": 4}, "truncated": False}), AssistantText("four cores"))
            self.assertEqual(turn.finish({}).error_id, "AI_ACTION_LIMIT")
            self.assertEqual(turn.propose().error_id, "AI_ACTION_LIMIT")
        kwargs = self.generate.call_args.kwargs
        self.assertIs(kwargs["contents"][1], first.candidates[0].content)
        self.assertEqual(kwargs["contents"][2].parts[0].function_response.id, "provider-call-id")
        self.assertEqual(kwargs["config"].tool_config.function_calling_config.mode, "NONE")
        self.assertTrue(kwargs["config"].automatic_function_calling.disable)
        self.assertEqual(self.generate.call_count, 2)
        self.assertIsNone(turn._content)
        self.assertEqual(turn._user_text, "")

    def test_final_call_is_rejected_by_adapter(self):
        self.generate.side_effect = [response(call()), response(call())]
        with GeminiProvider().turn("Hello") as turn:
            turn.propose()
            self.assertEqual(turn.finish({}).error_id, "AI_ACTION_LIMIT")

    def test_error_mapping_never_echoes_exception_payload(self):
        for exception, expected in (
            (errors.ClientError(401, {"message": FAKE_KEY}), "AI_AUTH_FAILED"),
            (errors.ClientError(403, {"message": FAKE_KEY}), "AI_AUTH_FAILED"),
            (errors.ClientError(400, {"error": {"message": FAKE_KEY, "details": [{"reason": "API_KEY_INVALID"}]}}), "AI_AUTH_FAILED"),
            (errors.ClientError(429, {"message": FAKE_KEY}), "AI_RATE_LIMITED"),
            (errors.ServerError(504, {"message": FAKE_KEY}), "AI_TIMEOUT"),
            (httpx.ReadTimeout(FAKE_KEY), "AI_TIMEOUT"),
            (httpx.ConnectError(FAKE_KEY), "AI_NETWORK_ERROR"),
            (RuntimeError(FAKE_KEY), "AI_PROVIDER_ERROR"),
        ):
            self.generate.side_effect = exception
            with self.assertLogs("jarvis.ai", level="DEBUG") as logs:
                result = Brain(GeminiProvider()).run_single_turn("Hello")
            self.assertEqual(result.error_id, expected)
            self.assertNotIn(FAKE_KEY, repr(result) + " ".join(logs.output))

    def test_key_cannot_enter_prompt_or_tool_arguments(self):
        result = Brain(GeminiProvider()).run_single_turn("Use " + FAKE_KEY)
        self.assertEqual(result.error_id, "AI_INVALID_INPUT")
        self.generate.assert_not_called()
        self.generate.return_value = response(call("browser.search_web", {"query": FAKE_KEY}))
        with patch("security.gateway.request_execution") as execute:
            self.assertEqual(Brain(GeminiProvider()).run_single_turn("hello").error_id, "AI_INVALID_RESPONSE")
        execute.assert_not_called()

    def test_key_redacted_from_text_and_feedback(self):
        self.generate.side_effect = [response(call()), response(types.Part(text="secret " + FAKE_KEY))]
        with GeminiProvider().turn("hello") as turn:
            turn.propose()
            final = turn.finish({"data": {"text": FAKE_KEY}})
        self.assertNotIn(FAKE_KEY, final.text)
        self.assertNotIn(FAKE_KEY, self.generate.call_args.kwargs["contents"][2].model_dump_json())

    def test_sdk_wire_serialization_with_mock_http_transport(self):
        # Exercise the real SDK's conversion and AFC path without sockets.
        # SDKClient retains the real constructor while the adapter factory is mocked.
        seen = []
        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=response(call()).model_dump(mode="json", by_alias=True, exclude_none=True))
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            with SDKClient(api_key=FAKE_KEY, vertexai=False, enterprise=False,
                           http_options=types.HttpOptions(httpx_client=transport)) as real:
                self.factory.side_effect = lambda **kwargs: real
                with GeminiProvider().turn("hello") as turn:
                    self.assertEqual(turn.propose(), ToolCallProposal("system.get_cpu_info", {}))
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(seen[0]["tools"][0]["functionDeclarations"]), 22)
        self.assertNotIn(FAKE_KEY, json.dumps(seen))
