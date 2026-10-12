"""Stage 8.3B chat-only provider selection; never exposes tools or agent controller."""
from __future__ import annotations
import os
from ai.local_chat import LocalChatProvider
from ai.models import AssistantText, ProviderError, MAX_TEXT_CHARS

MODES = ('local', 'gemini', 'auto')
FALLBACK_ERRORS = frozenset({'AI_RATE_LIMITED', 'AI_TIMEOUT', 'AI_NETWORK_ERROR', 'AI_PROVIDER_ERROR'})

class GeminiChatOnly:
    """Separate plain-text Gemini endpoint; no tool declarations or function calls."""
    def chat(self, prompt):
        if type(prompt) is not str or not prompt.strip() or len(prompt) > 4096:
            return ProviderError('AI_INVALID_INPUT')
        key = os.environ.get('GEMINI_API_KEY', '')
        if not key:
            return ProviderError('AI_NOT_CONFIGURED')
        try:
            from google import genai
            from google.genai import types
            model = os.environ.get('JARVIS_GEMINI_MODEL', 'gemini-2.5-flash')
            with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000, retry_options=types.HttpRetryOptions(attempts=1))) as client:
                response = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction='You are Jarvis in chat-only mode. You cannot use tools, access the computer, or save memories. Never claim actions were performed.',
                        max_output_tokens=512, candidate_count=1,
                    ),
                )
            value = response.text
            if type(value) is not str or not value.strip() or len(value) > MAX_TEXT_CHARS:
                return ProviderError('AI_INVALID_RESPONSE')
            return AssistantText(value.replace(key, '[redacted]'))
        except Exception as exc:
            # Do not log exceptions: provider messages may contain sensitive content.
            status = getattr(exc, 'code', None)
            if status is None:
                status = getattr(exc, 'status_code', None)
            try: status = int(status)
            except (ValueError, TypeError): status = None
            if status == 429: return ProviderError('AI_RATE_LIMITED')
            if status in (408, 504): return ProviderError('AI_TIMEOUT')
            if status in (500, 502, 503): return ProviderError('AI_PROVIDER_ERROR')
            if status in (401, 403): return ProviderError('AI_AUTH_FAILED')
            if isinstance(exc, (TimeoutError, ConnectionError)): return ProviderError('AI_NETWORK_ERROR')
            return ProviderError('AI_PROVIDER_ERROR')

class HybridChat:
    def __init__(self, local=None, cloud=None):
        self.local = local if local is not None else LocalChatProvider()
        self.cloud = cloud if cloud is not None else GeminiChatOnly()

    def chat(self, prompt, mode='local'):
        if mode not in MODES or type(prompt) is not str or not prompt.strip() or len(prompt) > 4096:
            return ProviderError('AI_INVALID_INPUT'), 'none', False
        if mode == 'local': return self.local.chat(prompt), 'local', False
        cloud_result = self.cloud.chat(prompt)
        if mode == 'auto' and isinstance(cloud_result, ProviderError) and cloud_result.error_id in FALLBACK_ERRORS:
            return self.local.chat(prompt), 'local', True
        return cloud_result, 'gemini', False
