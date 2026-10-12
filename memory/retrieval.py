"""Deterministic lexical ranking and serialized output budgets."""
import json
import re

def rank(records, query):
    phrase = query.casefold()
    tokens = set(re.findall(r"\w+", phrase))
    scored = []
    for record in records:
        corpus = (record.content + " " + " ".join(record.tags)).casefold()
        phrase_match = int(phrase in corpus)
        matches = len(tokens & set(re.findall(r"\w+", corpus)))
        if phrase_match or matches:
            scored.append(((phrase_match, matches, record.updated_at, record.id), record))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored]

def bounded(records, limit, max_bytes):
    result = {"trust": "untrusted_memory_data", "memories": [], "truncated": False}
    for record in records:
        if len(result["memories"]) >= limit:
            result["truncated"] = True
            break
        result["memories"].append(record.to_dict())
        if len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > max_bytes:
            result["memories"].pop()
            result["truncated"] = True
            break
    return result
