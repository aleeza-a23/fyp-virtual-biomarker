from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session
from ..config import REPORTS
from ..database import get_db
from ..models import Case, User
from ..deps import require, audit
from .cases import case_out

router = APIRouter(tags=["reports"])
DISCLAIMER = ("Research and decision-support tool only. Scores are predicted from H&E images using "
              "RNA-derived proxy labels, not direct protein measurements. Not validated for clinical use "
              "and not a substitute for pathologist judgment.")

@router.get("/cases/{cid}/report")
def report(cid: int, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    c = db.get(Case, cid)
    if not c:
        raise HTTPException(404, "Case not found")
    d = case_out(c, db)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{c.code}.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    def line(text, size=11, gap=18):
        nonlocal y
        pdf.setFont("Helvetica", size); pdf.drawString(50, y, text[:105]); y -= gap
    line("SlideSense analysis report", 16, 28)
    line(f"Case: {d['code']}   Patient: {d['patient']}   Cancer: {d['cancer']}")
    line(f"Status: {d['status']}   Decision: {d['decision'] or 'not signed off'}", gap=26)
    for p in d["predictions"]:
        src = "DEMO output" if p["is_demo"] else f"Model: {p['model_name']}"
        line(f"{p['biomarker']} ({p['gene']}): {p['level']}  score {p['score']:.2f}  [{src}]")
    y -= 10
    line("Pathologist comment: " + (d["comment"] or "none"))
    line("Next step: " + (d["next_step"] or "none"), gap=30)
    words, row = DISCLAIMER.split(), ""
    for w in words:
        if len(row) + len(w) > 95:
            line(row, 9, 13); row = ""
        row += w + " "
    line(row, 9, 13)
    pdf.save()
    audit(db, user, "export_report", c.code)
    return FileResponse(path, media_type="application/pdf", filename=f"{c.code}.pdf")