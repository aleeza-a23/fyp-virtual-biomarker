from datetime import datetime, timedelta, timezone
import bcrypt, jwt
from .config import SECRET, ALGO, TOKEN_MIN

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())

def make_token(user) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MIN)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, SECRET, algorithm=ALGO)

def read_token(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=[ALGO])