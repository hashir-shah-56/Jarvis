"""Bounded multi-step SDK sessions using real serialization and offline transport."""

import json
import os
import unittest
from unittest.mock import patch

from ai.gemini import GeminiProvider
from ai.context import bound_feedback
from ai.models import AssistantText, ToolCallProposal
from config import agent_settings as limits
from google.genai import Client as SDKClient, types
import httpx
from tests.test_gemini import FAKE_KEY, call, response


class GeminiTaskTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_KEY}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        factory = patch("ai.gemini.genai.Client")
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.generate = self.factory.return_value.models.generate_content

    def test_task_multiple_actions_keep_signatures_and_manual_calling(self):
        first = call()
        first.thought_signature = b"first-signature"
        second = call("system.get_memory_info")
        second.thought_signature = b"second-signature"
        responses = [response(first), response(second), response(types.Part(text="done"))]
        self.generate.side_effect = responses
        feedback = {"success": True, "data": {"x": 1}, "truncated": False}
        with GeminiProvider().task("cpu and memory") as task:
            self.assertIsInstance(task.propose(), ToolCallProposal)
            self.assertIsInstance(task.advance([feedback]), ToolCallProposal)
            self.assertEqual(task.advance([feedback, feedback]), AssistantText("done"))
        self.assertEqual(self.generate.call_count, 3)
        contents = self.generate.call_args.kwargs["contents"]
        self.assertEqual(len(contents), 5)
        self.assertIs(contents[1], responses[0].candidates[0].content)
        self.assertIs(contents[3], responses[1].candidates[0].content)
        for request in self.generate.call_args_list:
            config = request.kwargs["config"]
            self.assertTrue(config.automatic_function_calling.disable)
            self.assertEqual(config.tool_config.function_calling_config.mode, "AUTO")
        self.assertEqual(task._history, [])

    def test_provider_call_limit_enforced_in_adapter_too(self):
        self.generate.return_value = response(call())
        with GeminiProvider().task("request") as task:
            task.propose()
            with patch.object(limits, "MAX_PROVIDER_CALLS_PER_TURN", 1):
                self.assertEqual(task.advance([{}]).error_id, "AI_PROVIDER_CALL_LIMIT")
        self.generate.assert_called_once()

    def test_no_advance_after_text_or_without_corresponding_result(self):
        self.generate.return_value = response(types.Part(text="done"))
        with GeminiProvider().task("hello") as task:
            task.propose()
            self.assertEqual(task.advance([]).error_id, "AI_INVALID_RESPONSE")
        self.generate.assert_called_once()

    def test_multiple_calls_are_still_invalid(self):
        self.generate.return_value = response(call(), call())
        with GeminiProvider().task("two") as task:
            self.assertEqual(task.propose().error_id, "AI_MULTIPLE_TOOL_CALLS")

    def test_full_context_budget_stops_before_network(self):
        self.generate.return_value = response(call())
        with GeminiProvider().task("hello") as task:
            task.propose()
            with patch.object(limits, "MAX_MODEL_CONTEXT_BYTES", 1):
                self.assertEqual(task.advance([{}]).error_id, "AI_CONTEXT_LIMIT")
        self.generate.assert_called_once()

    def test_older_feedback_payloads_drop_deterministically(self):
        feedback = [{"success": True, "data": {"text": "x" * 14000}, "truncated": False} for _ in range(4)]
        bounded = bound_feedback(feedback)
        self.assertLessEqual(len(json.dumps(bounded)), limits.MAX_FEEDBACK_BYTES)
        self.assertEqual([item["truncated"] for item in bounded], [True, True, False, False])
        self.assertTrue(all(item["data"] for item in feedback))

    def test_wire_requests_for_multiple_steps(self):
        seen = []
        responses = iter([response(call()), response(call("system.get_memory_info")), response(types.Part(text="done"))])
        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=next(responses).model_dump(mode="json", by_alias=True, exclude_none=True))
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            with SDKClient(api_key=FAKE_KEY, vertexai=False, enterprise=False, http_options=types.HttpOptions(httpx_client=transport)) as real:
                self.factory.side_effect = lambda **kwargs: real
                with GeminiProvider().task("cpu and memory") as task:
                    self.assertIsInstance(task.propose(), ToolCallProposal)
                    self.assertIsInstance(task.advance([{"success": True}]), ToolCallProposal)
                    self.assertEqual(task.advance([{"success": True}, {"success": True}]), AssistantText("done"))
        self.assertEqual([len(req["contents"]) for req in seen], [1, 3, 5])
        self.assertNotIn(FAKE_KEY, json.dumps(seen))
