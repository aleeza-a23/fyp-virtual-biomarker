from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import Base, engine
from . import models  # noqa: F401  (registers the tables)
from .routers import auth, cases, slides, reports

Base.metadata.create_all(engine)
app = FastAPI(title="SlideSense API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_methods=["*"], allow_headers=["*"],
)
for r in (auth, cases, slides, reports):
    app.include_router(r.router)

@app.get("/health")
def health():
    return {"status": "ok"}