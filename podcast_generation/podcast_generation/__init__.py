"""Multi-agent pipeline that turns books into podcast episodes.

Importing the package loads `.env` (see `settings`), so submodules can read
environment variables without calling `load_dotenv()` themselves.
"""
from . import settings as settings  # noqa: F401  (side effect: loads .env)
