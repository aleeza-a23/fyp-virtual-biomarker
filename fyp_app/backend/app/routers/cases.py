import random
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Patient, Case, Prediction, User, AuditLog
from ..deps import require, audit

router = APIRouter(tags=["cases"])
BIOMARKERS = [("PD-L1", "CD274"), ("Ki-67", "MKI67"), ("CD8", "CD8A/CD8B"), ("FOXP3", "FOXP3")]

def case_out(c: Case, db: Session):
    p = db.get(Patient, c.patient_id)
    preds = db.query(Prediction).filter_by(case_id=c.id).all()
    return {
        "id": c.id, "code": c.code, "patient": p.code, "cancer": c.cancer_type,
        "status": c.status, "analysed_at": c.analysed_at, "decision": c.decision,
        "comment": c.comment, "next_step": c.next_step,
        "predictions": [{"biomarker": x.biomarker, "gene": x.gene, "score": x.score,
                         "level": "High" if x.score >= 0.5 else "Low",
                         "is_demo": x.is_demo, "model_name": x.model_name} for x in preds],
    }

@router.get("/patients")
def patients(db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    out = []
    for p in db.query(Patient).order_by(Patient.registered_at.desc()).all():
        cs = db.query(Case).filter_by(patient_id=p.id).all()
        last = max((c.analysed_at for c in cs if c.analysed_at), default=None)
        out.append({"code": p.code, "age": p.age, "sex": p.sex, "registered_at": p.registered_at,
                    "cases": len(cs), "last_analysis": last})
    return out

class NewPatient(BaseModel):
    code: str
    age: int
    sex: str

@router.post("/patients")
def create_patient(body: NewPatient, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    if db.query(Patient).filter_by(code=body.code).first():
        raise HTTPException(400, "Patient code already exists")
    db.add(Patient(code=body.code, age=body.age, sex=body.sex))
    db.commit()
    audit(db, user, "create_patient", body.code)
    return {"ok": True}

@router.get("/cases")
def cases(db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    return [case_out(c, db) for c in db.query(Case).order_by(Case.created_at.desc()).all()]

@router.get("/cases/{cid}")
def one_case(cid: int, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    c = db.get(Case, cid)
    if not c:
        raise HTTPException(404, "Case not found")
    audit(db, user, "open_case", c.code)
    return case_out(c, db)

class NewCase(BaseModel):
    patient_code: str
    cancer_type: str

@router.post("/cases")
def create_case(body: NewCase, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    p = db.query(Patient).filter_by(code=body.patient_code).first()
    if not p:
        raise HTTPException(404, "Patient not found")
    n = db.query(Case).count() + 1
    c = Case(code=f"CASE-{n:04d}", patient_id=p.id, cancer_type=body.cancer_type)
    db.add(c); db.commit(); db.refresh(c)
    audit(db, user, "create_case", c.code)
    return case_out(c, db)

@router.post("/cases/{cid}/analyze")
def analyze(cid: int, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    """DEMO ONLY: random scores flagged is_demo=True. Replaced by the real model later."""
    c = db.get(Case, cid)
    if not c:
        raise HTTPException(404, "Case not found")
    db.query(Prediction).filter_by(case_id=cid).delete()
    rng = random.Random(cid)
    for name, gene in BIOMARKERS:
        db.add(Prediction(case_id=cid, biomarker=name, gene=gene, score=round(rng.random(), 2),
                          is_demo=True, model_name="demo"))
    c.status, c.analysed_at = "Awaiting review", datetime.utcnow()
    db.commit()
    audit(db, user, "run_demo_analysis", c.code)
    return case_out(c, db)

class SignOff(BaseModel):
    decision: str
    comment: str = ""
    next_step: str = ""

@router.post("/cases/{cid}/signoff")
def signoff(cid: int, body: SignOff, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    c = db.get(Case, cid)
    if not c:
        raise HTTPException(404, "Case not found")
    if body.decision not in ("Agree", "Modify", "Reject"):
        raise HTTPException(400, "Decision must be Agree, Modify or Reject")
    if body.decision != "Agree" and not body.comment.strip():
        raise HTTPException(400, "A comment is required when modifying or rejecting")
    c.decision, c.comment, c.next_step = body.decision, body.comment, body.next_step
    c.status, c.signed_by, c.signed_at = "Signed off", user.id, datetime.utcnow()
    db.commit()
    audit(db, user, "signoff", c.code)
    return case_out(c, db)

@router.get("/me/reports")
def my_reports(db: Session = Depends(get_db), user: User = Depends(require("patient"))):
    p = db.query(Patient).filter_by(code=user.patient_code).first()
    cs = db.query(Case).filter_by(patient_id=p.id, status="Signed off").all()
    return [case_out(c, db) for c in cs]       # patients only ever see signed-off reports

@router.get("/research/cohort")
def cohort(db: Session = Depends(get_db), user: User = Depends(require("researcher"))):
    rows = []
    for c in db.query(Case).all():
        p = db.get(Patient, c.patient_id)
        if not p.research_consent:
            continue
        for x in db.query(Prediction).filter_by(case_id=c.id).all():
            rows.append({"coded_id": f"C-{c.id:04d}", "cancer": c.cancer_type, "biomarker": x.biomarker,
                         "score": x.score, "is_demo": x.is_demo})
    audit(db, user, "view_cohort")
    return rows

@router.get("/audit")
def audit_log(db: Session = Depends(get_db), user: User = Depends(require("pathologist", "researcher"))):
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(200).all()
    return [{"time": r.timestamp, "user_id": r.user_id, "action": r.action, "target": r.target} for r in rows]