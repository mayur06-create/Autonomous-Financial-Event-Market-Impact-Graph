"""Config: real environment variables win, then a .env file in the project root."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MARKETAUX_URL = "https://api.marketaux.com/v1/news/all"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _load_dotenv() -> None:
    p = BASE_DIR / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


# Functions (not constants) so tests / the UI can change env vars at runtime.
def marketaux_key() -> str:
    return os.getenv("MARKETAUX_API_KEY", "")


def gemini_key() -> str:
    return os.getenv("GEMINI_API_KEY", "")


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


def db_path() -> Path:
    return Path(os.getenv("NEWSGRAPH_DB", BASE_DIR / "data" / "knowledge_base.db"))
