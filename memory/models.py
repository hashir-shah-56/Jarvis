"""JSON-only records; sensitive contents are excluded from repr."""
from dataclasses import asdict, dataclass
from enum import Enum

SCHEMA_VERSION = 1
MAX_CONTENT_CHARS = 1024
MAX_TAGS_STRING_CHARS = 256
MAX_SEARCH_QUERY_CHARS = 256
MAX_RESULTS_LIMIT = 50
DEFAULT_LIST_LIMIT = 10
DEFAULT_SEARCH_LIMIT = 10

class MemoryCategory(str, Enum):
    PREFERENCE = "preference"
    FACT = "fact"
    PROJECT = "project"
    INSTRUCTION = "instruction"
    NOTE = "note"

class MemorySource(str, Enum):
    USER_APPROVED = "user_approved"

@dataclass(frozen=True, repr=False)
class MemoryRecord:
    id: str
    category: str
    content: str
    created_at: str
    updated_at: str
    expires_at: str | None
    source: str
    tags: tuple[str, ...]

    def to_dict(self):
        result = asdict(self)
        result["tags"] = list(self.tags)
        return result
