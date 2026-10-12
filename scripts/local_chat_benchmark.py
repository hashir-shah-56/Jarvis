"""Run: python -m scripts.local_chat_benchmark"""
import time
from ai.local_chat import LocalChatProvider
from ai.models import AssistantText


def main():
    provider = LocalChatProvider()
    print('Chat-only local benchmark. No Gemini calls and no system tools.')
    for prompt in ('Reply with exactly: Ready', 'Explain RAM in two sentences.'):
        start = time.perf_counter()
        result = provider.chat(prompt)
        elapsed = time.perf_counter() - start
        if isinstance(result, AssistantText):
            print(f'{elapsed:.1f}s | {result.text[:300]}')
        else:
            print(f'{elapsed:.1f}s | ERROR: {result.error_id}')
            break


if __name__ == '__main__':
    main()
