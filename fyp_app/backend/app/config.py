from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STORAGE = BASE / "storage"
SLIDES = STORAGE / "slides"
REPORTS = STORAGE / "reports"
DB_URL = f"sqlite:///{(STORAGE / 'app.db').as_posix()}"
SECRET = "change-this-before-any-real-use"
ALGO = "HS256"
TOKEN_MIN = 480