"""Central trusted defaults for Stage 2, not caller-provided execution config."""

# Each pair names a trusted installation-root environment variable and a fixed
# relative executable. Never search PATH or the working directory for programs.
APPLICATION_LOCATIONS = {
    "chrome": (
        ("ProgramFiles", "Google/Chrome/Application/chrome.exe"),
        ("ProgramFiles(x86)", "Google/Chrome/Application/chrome.exe"),
        ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
    ),
    "edge": (
        ("ProgramFiles(x86)", "Microsoft/Edge/Application/msedge.exe"),
        ("ProgramFiles", "Microsoft/Edge/Application/msedge.exe"),
    ),
    "vscode": (
        ("LOCALAPPDATA", "Programs/Microsoft VS Code/Code.exe"),
        ("ProgramFiles", "Microsoft VS Code/Code.exe"),
    ),
    "notepad": (("SystemRoot", "System32/notepad.exe"),),
    "calculator": (("SystemRoot", "System32/calc.exe"),),
    "file_explorer": (("SystemRoot", "explorer.exe"),),
}

SEARCH_URL = "https://www.google.com/search"
OPEN_FILE_EXTENSIONS = frozenset({".txt", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp"})
MAX_RESULTS = 500
DEFAULT_RESULTS = 100
MAX_SEARCH_ENTRIES = 10_000
MAX_SEARCH_DEPTH = 10
