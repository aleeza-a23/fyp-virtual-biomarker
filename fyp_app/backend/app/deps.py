import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .database import get_db
from .models import User, AuditLog
from .security import read_token

bearer = HTTPBearer()

def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    try:
        data = read_token(cred.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active:
        raise HTTPException(401, "Unknown user")
    return user

def require(*roles):
    def check(user: User = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Not allowed for your role")
        return user
    return check

def audit(db: Session, user, action: str, target: str = ""):
    db.add(AuditLog(user_id=user.id if user else None, action=action, target=target))
    db.commit()