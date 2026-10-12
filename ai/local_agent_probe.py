"""Stage 8.4A: non-executing local model tool-proposal probe.

This module only proposes and validates tool calls. It never invokes a tool.
"""
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from ai.models import AssistantText, ProviderError, ToolCallProposal
from ai.validation import validate_response
from tools.registry import REGISTRY
from tools.schema import validate_arguments

MAX_RESPONSE_BYTES = 65536
LOCAL_URL = 'http://127.0.0.1:8080/v1/chat/completions'
STOP_WORDS = {
    'a', 'an', 'and', 'are', 'can', 'could', 'do', 'does', 'for', 'from', 'get',
    'have', 'i', 'in', 'is', 'it', 'me', 'my', 'of', 'on', 'please', 'show',
    'tell', 'the', 'to', 'what', 'whats', 'how', 'much', 'would', 'you', 'your',
    'called', 'about', 'check', 'current',
}

# Explicit synonyms make the smallest local model's candidate list more useful.
# Values are exact names from the trusted registry; this is retrieval only, not authorization.
ALIASES = (
    ({'cpu', 'processor', 'processorusage', 'cpuusage'}, {'system.get_cpu_usage', 'system.get_cpu_info'}),
    ({'ram', 'memory', 'mem', 'memoryusage'}, {'system.get_memory_info'}),
    ({'disk', 'storage', 'drive', 'space'}, {'system.get_disk_info'}),
    ({'system', 'computer', 'pc', 'machine', 'specs', 'specifications'}, {'system.get_system_info'}),
    ({'process', 'processes', 'task', 'tasks', 'running'}, {'system.list_processes'}),
    ({'folder', 'directory', 'mkdir'}, {'file.create_directory', 'file.list_directory'}),
    ({'list', 'contents', 'files', 'directory'}, {'file.list_directory'}),
    ({'find', 'locate', 'files'}, {'file.find_files', 'file.list_directory'}),
    ({'open', 'launch', 'start', 'application', 'app'}, {'app.open_application', 'file.open_path', 'browser.open_url'}),
    ({'rename'}, {'file.rename_path'}),
    ({'move'}, {'file.move_path'}),
    ({'url', 'website', 'browser', 'link'}, {'browser.open_url'}),
    ({'web', 'internet', 'online', 'search'}, {'browser.search_web'}),
    ({'saved', 'recall'}, {'memory.search', 'memory.list', 'memory.get'}),
    ({'remember', 'memory', 'save', 'note'}, {'memory.create', 'memory.search', 'memory.list'}),
)

# ---------------------------------------------------------------------------
# Special-location keywords that must never be resolved by the model.
# Trusted application code (e.g. os.path.expanduser / known-folder APIs) must
# resolve these, not a string produced by an LLM.
# ---------------------------------------------------------------------------
_SPECIAL_LOCATION_PATTERNS = (
    re.compile(r'\b(desktop)\b', re.IGNORECASE),
    re.compile(r'\b(downloads?)\b', re.IGNORECASE),
    re.compile(r'\b(documents?)\b', re.IGNORECASE),
    # Home-directory shorthands
    re.compile(r'(?:^|[\s\'"])~[/\\]'),
    re.compile(r'\bhome\s+(?:folder|directory)\b', re.IGNORECASE),
    re.compile(r'\bmy\s+home\b', re.IGNORECASE),
    # Explicit Windows user-profile variables
    re.compile(r'%USERPROFILE%', re.IGNORECASE),
    re.compile(r'%HOMEDRIVE%', re.IGNORECASE),
    re.compile(r'%HOMEPATH%', re.IGNORECASE),
)

# Filesystem-mutating path-argument tools. Special-location guard only fires when
# the user's request would route to one of these (read-only list/find are allowed).
_PATH_MUTATION_TOOLS = frozenset({
    'file.create_directory', 'file.rename_path', 'file.move_path', 'file.open_path',
    'app.open_project_in_vscode',
})


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r'[a-z0-9]+', text.lower()) if token not in STOP_WORDS}


def _broad_destructive_intent(text: str) -> bool:
    """Return True for clearly broad/destructive requests.

    Designed to be conservative: short-circuit before the model call only when
    the intent is unambiguously destructive. Benign educational questions that
    mention deletion or formatting are not blocked here.
    """
    lowered = text.lower()
    normalized = ' '.join(_tokens(text))
    patterns = (
        # Explicit multi-word destructive patterns
        r'\bdelete all\b',
        r'\bdelete everything\b',
        r'\berase all\b',
        r'\berase everything\b',
        r'\bremove all\b',
        r'\bremove everything\b',
        r'\bwipe (?:my )?(?:computer|pc|drive|disk|files|all)\b',
        r'\bformat (?:my )?(?:computer|pc|drive|disk)\b',
        r'\bdestroy (?:all|everything|my computer|my pc)\b',
        r'\bpurge all\b',
        r'\bnuke (?:my )?(?:computer|pc|drive|disk|files|all)\b',
    )
    if any(re.search(p, lowered) for p in patterns):
        return True
    # Token-level: delete/erase/remove + (all | everything) + (files | data | disk)
    destructive_verbs = normalized.split()
    has_destructive_verb = any(v in {'delete', 'erase', 'remove', 'wipe', 'purge', 'nuke'} for v in destructive_verbs)
    has_scope = any(v in {'all', 'everything', 'entire'} for v in destructive_verbs)
    has_target = any(v in {'files', 'data', 'disk', 'drive', 'computer', 'pc'} for v in destructive_verbs)
    return has_destructive_verb and has_scope and has_target


def _special_location_request(text: str, candidate_names: set[str]) -> bool:
    """Return True when the request references a special OS location AND would
    target a path-mutating tool.

    Read-only tools (list_directory, find_files) are exempt: those may
    legitimately receive 'Desktop' as an informational query. Mutation tools
    must never receive a model-invented path to a special system location.
    """
    if not candidate_names & _PATH_MUTATION_TOOLS:
        return False
    return any(pattern.search(text) for pattern in _SPECIAL_LOCATION_PATTERNS)


def _is_schema_as_arguments(arguments: object) -> bool:
    """Return True when the model returned a JSON Schema blob instead of values.

    The model sometimes copies the schema description into the arguments dict.
    A schema-shaped object contains keys like 'type', 'properties', 'required'
    or 'additionalProperties' at the top level — none of which are real argument
    names in any registered tool.
    """
    if not isinstance(arguments, dict):
        return False
    schema_keys = {'type', 'properties', 'required', 'additionalProperties', '$schema',
                   'definitions', 'allOf', 'anyOf', 'oneOf', 'not', 'description', 'enum'}
    # Heuristic: if any top-level key is a known schema keyword, treat the whole
    # object as schema-shaped. This is conservative — reject on detection.
    return bool(set(arguments) & schema_keys)


def _candidate_catalog(user_text: str) -> list[dict[str, object]]:
    """Return at most five plausible registered tools using conservative lexical retrieval."""
    metadata = REGISTRY.list_metadata()
    names = {item['name'] for item in metadata}
    query_tokens = _tokens(user_text)
    selected: set[str] = set()
    for alias_tokens, tool_names in ALIASES:
        if query_tokens & alias_tokens:
            selected.update(name for name in tool_names if name in names)

    scored: list[tuple[int, dict[str, object]]] = []
    for item in metadata:
        name = str(item['name'])
        searchable = _tokens(name.replace('.', ' ').replace('_', ' ')) | _tokens(str(item['description']))
        score = len(query_tokens & searchable)
        if name in selected:
            score += 3
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1]['name'])))
    # When a known intent alias fires, do not dilute the short list with unrelated
    # tools that happen to share generic words such as "create" or "search".
    if selected:
        ordered = [item for _, item in scored if item['name'] in selected]
        return ordered[:5]
    return [item for _, item in scored[:5]]


@dataclass(frozen=True)
class ProbeResult:
    response: object
    schema_valid: bool
    reason: str


def _no_tool(reason: str = 'NO_TOOL') -> ProbeResult:
    return ProbeResult(AssistantText('No tool proposed.'), True, reason)


def evaluate(raw: object) -> ProbeResult:
    """Validate JSON proposal and registered argument schema. NEVER execute.

    Accepted envelope:
        {"tool": "<name>" | null, "arguments": {<values>}}

    Rejected:
        - Any envelope with keys other than exactly {"tool", "arguments"}
        - tool != null but not a string
        - arguments containing JSON Schema keys (schema-as-arguments attack)
        - Unknown tool name (not in registry)
        - Arguments that fail the registered schema validation
        - null tool with non-empty or non-dict arguments
    """
    if type(raw) is not dict or set(raw) != {'tool', 'arguments'}:
        return ProbeResult(ProviderError('AI_INVALID_RESPONSE'), False, 'INVALID_ENVELOPE')
    name, args = raw['tool'], raw['arguments']
    if name is None:
        if type(args) is not dict or args:
            return ProbeResult(ProviderError('AI_INVALID_RESPONSE'), False, 'INVALID_TEXT_ENVELOPE')
        return _no_tool()
    # Reject schema blobs before further validation
    if _is_schema_as_arguments(args):
        return ProbeResult(ProviderError('AI_INVALID_RESPONSE'), False, 'SCHEMA_AS_ARGUMENTS')
    candidate = validate_response(ToolCallProposal(name, args))
    if not isinstance(candidate, ToolCallProposal):
        return ProbeResult(candidate, False, 'INVALID_PROPOSAL')
    metadata = next((m for m in REGISTRY.list_metadata() if m['name'] == candidate.tool_name), None)
    if metadata is None:
        return ProbeResult(candidate, False, 'UNKNOWN_TOOL')
    try:
        validate_arguments(candidate.arguments, metadata['arguments_schema'])
    except (ValueError, TypeError):
        return ProbeResult(candidate, False, 'INVALID_ARGUMENTS')
    return ProbeResult(candidate, True, 'VALID_PROPOSAL_NOT_EXECUTED')


def probe(user_text: str, *, url: str = LOCAL_URL, timeout: float = 60) -> ProbeResult:
    if type(user_text) is not str or not user_text.strip() or len(user_text) > 16000:
        raise ValueError('INVALID_INPUT')
    if url != LOCAL_URL:
        raise ValueError('INVALID_ENDPOINT')
    if type(timeout) not in (int, float) or not 1 <= timeout <= 120:
        raise ValueError('INVALID_TIMEOUT')

    # Conservative early rejection of clearly broad/destructive requests.
    # This is a probe safeguard, not a replacement for the trusted security gateway.
    if _broad_destructive_intent(user_text):
        return _no_tool('REJECTED_BROAD_DESTRUCTIVE_INTENT')

    catalog = _candidate_catalog(user_text)

    # Reject requests for special OS locations when the candidate set includes
    # path-mutating tools. The model must never invent a path to Desktop, Downloads,
    # Documents, home directory, or profile variables.
    candidate_names = {item['name'] for item in catalog}
    if _special_location_request(user_text, candidate_names):
        return _no_tool('SPECIAL_LOCATION_REQUIRES_TRUSTED_RESOLUTION')

    if not catalog:
        return _no_tool('NO_RELEVANT_TOOL_CANDIDATE')

    instruction = (
        'You are a strict tool-selection classifier for a DRY RUN. Nothing can execute. '
        'Return ONLY one JSON object with exactly these keys: "tool" and "arguments". '
        'Choose an exact tool name from the supplied short catalog, or null if none clearly fits. '
        '"arguments" means actual argument VALUES, never a JSON Schema. For a tool with no required '
        'inputs, return {}. Never invent a tool, never claim an action was performed, and do not use '
        'a tool for general knowledge questions. If unsure, return {"tool":null,"arguments":{}}. '
        'Examples: for CPU usage use {"tool":"system.get_cpu_usage","arguments":{}}; '
        'for a general-knowledge question use {"tool":null,"arguments":{}}. '
        'For path arguments, use only a path explicitly stated by the user; do not invent a location. '
        'Catalog schemas describe the allowed shape but must not be copied into arguments. Catalog: '
        + json.dumps(catalog, ensure_ascii=False, separators=(',', ':'))
    )
    payload = json.dumps({
        'messages': [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': user_text}],
        'temperature': 0,
        'max_tokens': 192,
        'response_format': {'type': 'json_object'},
        'chat_template_kwargs': {'enable_thinking': False},
    }, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(url, payload, {'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            return ProbeResult(ProviderError('AI_INVALID_RESPONSE'), False, 'RESPONSE_TOO_LARGE')
        envelope = json.loads(data)
        message = envelope['choices'][0]['message']['content']
        if type(message) is not str or len(message) > 16384:
            raise ValueError('INVALID_CONTENT')
        return evaluate(json.loads(message))
    except urllib.error.HTTPError as exc:
        # Do not log prompt/model data; status is enough to diagnose the server response.
        print(f'LOCAL AI HTTP ERROR {exc.code}')
        return ProbeResult(ProviderError('AI_NETWORK_ERROR'), False, f'HTTP_{exc.code}')
    except (urllib.error.URLError, TimeoutError, OSError):
        print('LOCAL AI CONNECTION ERROR: could not reach localhost llama-server')
        return ProbeResult(ProviderError('AI_NETWORK_ERROR'), False, 'LOCAL_SERVER_UNAVAILABLE')
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return ProbeResult(ProviderError('AI_INVALID_RESPONSE'), False, 'INVALID_MODEL_OUTPUT')
