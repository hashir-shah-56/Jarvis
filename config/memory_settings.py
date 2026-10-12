"""Trusted memory limits; no tool can override storage or retrieval budgets."""
import os
from dataclasses import dataclass
from config.settings import ConfigurationError

@dataclass(frozen=True)
class MemorySettings:
    max_records: int = 1000
    max_results: int = 10
    max_result_bytes: int = 8192

    def __post_init__(self):
        for value, low, high in ((self.max_records, 1, 10000), (self.max_results, 1, 50),
                                 (self.max_result_bytes, 512, 12000)):
            if type(value) is not int or not low <= value <= high:
                raise ConfigurationError("MEMORY_INVALID_CONFIGURATION")

def load_memory_settings(environ=None):
    values = os.environ if environ is None else environ
    try:
        return MemorySettings(*(int(values.get(name, default)) for name, default in (
            ("JARVIS_MEMORY_MAX_RECORDS", "1000"), ("JARVIS_MEMORY_MAX_RESULTS", "10"),
            ("JARVIS_MEMORY_MAX_RESULT_BYTES", "8192"))))
    except (TypeError, ValueError):
        raise ConfigurationError("MEMORY_INVALID_CONFIGURATION") from None
