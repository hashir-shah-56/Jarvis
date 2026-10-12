"""Opt-in, chat-only local model adapter. Never interprets model text as tool calls."""
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from ai.models import AssistantText, ProviderError, MAX_TEXT_CHARS

_ALLOWED = frozenset({'127.0.0.1', 'localhost'})

@dataclass(frozen=True)
class LocalChatConfig:
    model: str = 'local'
    port: int = 8080
    timeout: int = 90


def load_local_config(environ=None):
    values = os.environ if environ is None else environ
    model = values.get('JARVIS_LOCAL_MODEL', 'local')
    port = values.get('JARVIS_LOCAL_PORT', '8080')
    timeout = values.get('JARVIS_LOCAL_TIMEOUT', '90')
    if not isinstance(model, str) or not model or len(model) > 128 or any(ord(c) < 32 for c in model):
        raise ValueError('Invalid local model')
    if not port.isascii() or not port.isdecimal() or not 1024 <= int(port) <= 65535:
        raise ValueError('Invalid local port')
    if not timeout.isascii() or not timeout.isdecimal() or not 1 <= int(timeout) <= 180:
        raise ValueError('Invalid local timeout')
    return LocalChatConfig(model, int(port), int(timeout))


class LocalChatProvider:
    """Only generates plain text. No tool schema, no trusted action pathway."""
    def __init__(self, config=None):
        self.config = config if config is not None else load_local_config()

    def chat(self, prompt):
        if type(prompt) is not str or not prompt.strip() or len(prompt) > MAX_TEXT_CHARS:
            return ProviderError('AI_INVALID_INPUT')
        body = json.dumps({
            'model': self.config.model,
            'messages': [
                {'role': 'system', 'content': 'You are Jarvis. Respond conversationally. You cannot run tools or operate this computer. Do not claim to have performed actions.'},
                {'role': 'user', 'content': prompt},
            ],
            'stream': False,
            'max_tokens': 384,
            'temperature': 0.4,
        }).encode('utf-8')
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.config.port}/v1/chat/completions',
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            # Explicitly disable system proxy configuration; loopback only.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=self.config.timeout) as response:
                if response.status != 200:
                    return ProviderError('AI_PROVIDER_ERROR')
                raw = response.read(131073)
            if len(raw) > 131072:
                return ProviderError('AI_INVALID_RESPONSE')
            payload = json.loads(raw)
            content = payload['choices'][0]['message']['content']
            if type(content) is not str or not content.strip() or len(content) > MAX_TEXT_CHARS:
                return ProviderError('AI_INVALID_RESPONSE')
            return AssistantText(content)
        except (urllib.error.URLError, TimeoutError, OSError):
            return ProviderError('AI_NETWORK_ERROR')
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return ProviderError('AI_INVALID_RESPONSE')
