"""Iterative language decisions; no execution, authorization, or retries."""

from contextlib import ExitStack

from ai.base import TaskProvider
from ai.context import bound_feedback
from ai.models import ProviderError
from ai.sanitize import sanitize_result
from ai.validation import validate_response


class Planner:
    def __init__(self, provider: TaskProvider, user_text: str):
        self._provider = provider
        self._user_text = user_text
        self._stack = ExitStack()
        self._session = None
        self._feedback = []
        self._started = False
        self._closed = False

    def next_step(self):
        if self._closed:
            return ProviderError("AI_INVALID_RESPONSE")
        try:
            if self._session is None:
                self._session = self._stack.enter_context(self._provider.task(self._user_text))
            if not self._started:
                self._started = True
                return validate_response(self._session.propose())
            return validate_response(self._session.advance(bound_feedback(self._feedback)))
        except TimeoutError:
            return ProviderError("AI_TIMEOUT")
        except Exception:
            return ProviderError("AI_PROVIDER_ERROR")

    def observe(self, result):
        self._feedback = bound_feedback([*self._feedback, sanitize_result(result)])

    def close(self):
        self._closed = True
        try:
            self._stack.close()
        except Exception:
            pass
        self._session = None
        self._feedback.clear()
        self._user_text = ""
