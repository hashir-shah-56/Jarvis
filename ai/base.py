"""A provider opens one ephemeral turn, with at most two language requests."""

from contextlib import AbstractContextManager
from typing import Protocol

from ai.models import ProviderResponse


class ProviderTurn(Protocol):
    def propose(self) -> ProviderResponse: ...

    def finish(self, result: dict[str, object]) -> ProviderResponse: ...


class Provider(Protocol):
    def turn(self, user_text: str) -> AbstractContextManager[ProviderTurn]: ...
