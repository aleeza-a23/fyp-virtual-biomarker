from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..security import verify_password, make_token
from ..deps import current_user, audit

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginBody(BaseModel):
    username: str
    password: str

def user_out(u: User):
    return {"id": u.id, "role": u.role, "name": u.full_name, "patient_code": u.patient_code}

@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    u = db.query(User).filter_by(username=body.username).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Wrong username or password")
    audit(db, u, "login")
    return {"token": make_token(u), **user_out(u)}

@router.get("/me")
def me(u: User = Depends(current_user)):
    return user_out(u)