from datetime import datetime, timedelta
from app.database import Base, engine, SessionLocal
from app import models as m
from app.security import hash_password

Base.metadata.create_all(engine)
db = SessionLocal()
if not db.query(m.User).first():
    db.add_all([
        m.User(username="dr.demo", password_hash=hash_password("demo-password"), role="pathologist", full_name="Dr. Demo"),
        m.User(username="res.demo", password_hash=hash_password("demo-password"), role="researcher", full_name="Researcher Demo"),
        m.User(username="p.demo", password_hash=hash_password("demo-password"), role="patient", full_name="Patient Demo", patient_code="P-0142"),
    ])
    now = datetime.utcnow()
    for i, (code, age, sex, consent) in enumerate([("P-0142", 62, "Female", True), ("P-0143", 55, "Female", True), ("P-0144", 67, "Male", False)]):
        db.add(m.Patient(code=code, age=age, sex=sex, research_consent=consent, registered_at=now - timedelta(days=10 - i * 3)))
    db.commit()
    for i, (pc, cancer) in enumerate([("P-0142", "Lung adenocarcinoma"), ("P-0143", "Breast"), ("P-0144", "Colon")], 1):
        p = db.query(m.Patient).filter_by(code=pc).first()
        db.add(m.Case(code=f"CASE-{i:04d}", patient_id=p.id, cancer_type=cancer))
    db.commit()
    print("Seeded demo users, patients and cases")
else:
    print("Database already has data, nothing changed")