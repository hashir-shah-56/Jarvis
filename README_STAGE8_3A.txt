JARVIS Stage 8.3A — LOCAL CHAT BENCHMARK (EXPERIMENTAL)

This patch adds an isolated, chat-only local model client. It does not modify
main.py, desktop UI, Gemini, Controller, Gateway, or persistent memory.
It does not implement automatic fallback or any local tool calling.

Requirements: llama.cpp llama-server Windows executable and a GGUF model
(download these separately from trusted official sources).

Example PowerShell workflow:
  cd F:\Work\Jarvis
  # Extract this ZIP here.
  # Launch llama-server in a SECOND PowerShell window, for example:
  & "F:\Models\llama-server.exe" -m "F:\Models\model.gguf" --host 127.0.0.1 --port 8080 -c 2048 -t 2
  # In the JARVIS PowerShell window:
  .\.venv\Scripts\python.exe -m unittest tests.test_local_chat -v
  .\.venv\Scripts\python.exe -m scripts.local_chat_benchmark

Use a small Q4 GGUF model (~0.6B-1.7B parameters) on the current 8GB laptop.
Set JARVIS_LOCAL_MODEL if your server requires a specific model identifier.
Default local endpoint: http://127.0.0.1:8080/v1/chat/completions

Security: endpoint hardcoded to IPv4 loopback; proxies disabled; bounded
request/response; plain text only; no tool proposal interpretation.
Do not expose llama-server to the LAN or public Internet.

Stage 8.2 UI should be installed and tested separately. Do not bump version.
