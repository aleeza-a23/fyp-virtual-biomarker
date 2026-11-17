from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String)                       # pathologist | researcher | patient
    full_name = Column(String, default="")
    patient_code = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)   # e.g. P-0142, no names stored
    age = Column(Integer)
    sex = Column(String)
    registered_at = Column(DateTime, default=datetime.utcnow)
    research_consent = Column(Boolean, default=False)

class Case(Base):
    __tablename__ = "cases"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    cancer_type = Column(String)
    status = Column(String, default="Awaiting analysis")
    created_at = Column(DateTime, default=datetime.utcnow)
    analysed_at = Column(DateTime, nullable=True)
    decision = Column(String, nullable=True)
    comment = Column(Text, nullable=True)
    next_step = Column(Text, nullable=True)
    signed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    signed_at = Column(DateTime, nullable=True)

class Slide(Base):
    __tablename__ = "slides"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"))
    filename = Column(String)
    path = Column(String)
    width = Column(Integer)
    height = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"))
    biomarker = Column(String)
    gene = Column(String)
    score = Column(Float)
    is_demo = Column(Boolean, default=True)
    model_name = Column(String, default="demo")
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String)
    target = Column(String, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)