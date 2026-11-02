from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine
import models  # noqa: F401 - ensure table registered
from auth import router as auth_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Milestone 2 - Auth & Security")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.get("/")
def root():
    return {"status": "ok", "service": "auth"}
