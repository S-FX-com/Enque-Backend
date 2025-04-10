from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.libs.email_sync import start_scheduler
from app.api.api import api_router
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup event
    start_scheduler()
    yield
    # Shutdown event

app = FastAPI(title="ObieDesk API", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.get_cors_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router)

@app.get("/")
def read_root():
    return {"message": "Welcome to ObieDesk API"}
