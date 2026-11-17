import io, math, shutil, uuid
from functools import lru_cache
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Response
from sqlalchemy.orm import Session
from tiffslide import TiffSlide
from ..config import SLIDES
from ..database import get_db
from ..models import Slide, Case, User
from ..deps import require, audit

router = APIRouter(tags=["slides"])
TILE = 256

@lru_cache(maxsize=8)
def open_slide(path: str):
    return TiffSlide(path)

@router.post("/cases/{cid}/slides")
def upload(cid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
           user: User = Depends(require("pathologist"))):
    c = db.get(Case, cid)
    if not c:
        raise HTTPException(404, "Case not found")
    ext = Path(file.filename).suffix.lower()
    if ext not in {".svs", ".tif", ".tiff"}:
        raise HTTPException(400, "Unsupported file type. Use .svs, .tif or .tiff")
    SLIDES.mkdir(parents=True, exist_ok=True)
    dest = SLIDES / f"{uuid.uuid4().hex}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        w, h = TiffSlide(str(dest)).dimensions
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Could not read this slide file")
    s = Slide(case_id=cid, filename=file.filename, path=str(dest), width=w, height=h)
    db.add(s); db.commit(); db.refresh(s)
    audit(db, user, "upload_slide", c.code)
    return {"id": s.id, "width": w, "height": h}

@router.get("/cases/{cid}/slides")
def list_slides(cid: int, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    return [{"id": s.id, "filename": s.filename, "width": s.width, "height": s.height}
            for s in db.query(Slide).filter_by(case_id=cid).all()]

@router.get("/slides/{sid}/info")
def info(sid: int, db: Session = Depends(get_db), user: User = Depends(require("pathologist"))):
    s = db.get(Slide, sid)
    if not s:
        raise HTTPException(404, "Slide not found")
    return {"width": s.width, "height": s.height, "tile": TILE,
            "max_level": math.ceil(math.log2(max(s.width, s.height)))}

@router.get("/slides/{sid}/tile/{level}/{x}/{y}")
def tile(sid: int, level: int, x: int, y: int, db: Session = Depends(get_db),
         user: User = Depends(require("pathologist"))):
    s = db.get(Slide, sid)
    if not s:
        raise HTTPException(404, "Slide not found")
    sl = open_slide(s.path)
    w, h = sl.dimensions
    scale = 2 ** (math.ceil(math.log2(max(w, h))) - level)
    x0, y0 = x * TILE * scale, y * TILE * scale
    if x0 >= w or y0 >= h:
        raise HTTPException(404, "Tile outside slide")
    lv = sl.get_best_level_for_downsample(scale)
    ds = sl.level_downsamples[lv]
    rw, rh = min(TILE * scale, w - x0), min(TILE * scale, h - y0)
    img = sl.read_region((x0, y0), lv, (max(1, round(rw / ds)), max(1, round(rh / ds)))).convert("RGB")
    img = img.resize((max(1, round(rw / scale)), max(1, round(rh / scale))))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg")