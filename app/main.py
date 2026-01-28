"""Bowerbirder API - Photo collage generator using fal.ai"""
from app.settings import settings
import uuid
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
import redis

from app.config import STYLE_PRESETS, ASPECT_RATIOS, MIN_IMAGES, MAX_IMAGES

app = FastAPI(title="Bowerbirder API")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "https://bowerbirder.pressive.in",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis connection
redis_client = redis.from_url(settings.redis_url)

# Config
ENVIRONMENT = settings.environment
OUTPUT_DIR = settings.output_dir
IMAGE_EXPIRY_MINUTES = settings.image_expiry_minutes
API_ALLOWED_IPS = settings.allowed_ips_list
JOB_IMAGES_DIR = settings.job_images_dir
MAX_QUEUED_JOBS = 10


def get_client_ip(request: Request) -> str:
    """Extract client IP, handling X-Forwarded-For for reverse proxies"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Middleware to restrict API access by IP in production mode"""

    async def dispatch(self, request: Request, call_next):
        if ENVIRONMENT == "local":
            return await call_next(request)

        if API_ALLOWED_IPS:
            client_ip = get_client_ip(request)
            if client_ip not in API_ALLOWED_IPS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Access denied for IP: {client_ip}"}
                )

        return await call_next(request)


app.add_middleware(IPWhitelistMiddleware)


class JobRequest(BaseModel):
    images: list[str] = Field(..., min_length=MIN_IMAGES, max_length=MAX_IMAGES)
    style: str = "fridge"
    aspect_ratio: str = "16:9"


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobStatus(BaseModel):
    job_id: str
    status: str
    status_detail: Optional[str] = None
    image_url: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/styles")
def list_styles():
    """List available style presets"""
    return {
        "styles": [
            {"id": key, "name": preset["name"]}
            for key, preset in STYLE_PRESETS.items()
        ]
    }


@app.get("/aspect-ratios")
def list_aspect_ratios():
    """List available output aspect ratios"""
    return {"aspect_ratios": ASPECT_RATIOS}


@app.post("/jobs", response_model=JobResponse)
def create_job(request: JobRequest):
    """Create a new collage generation job"""
    # Check queue backpressure
    queue_length = redis_client.llen("job_queue")
    if queue_length >= MAX_QUEUED_JOBS:
        raise HTTPException(
            status_code=503,
            detail=f"Server busy ({queue_length} jobs queued). Try again later."
        )

    if len(request.images) < MIN_IMAGES:
        raise HTTPException(status_code=400, detail=f"At least {MIN_IMAGES} images required")

    if len(request.images) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_IMAGES} images allowed")

    MAX_IMAGE_SIZE_MB = 20
    MAX_TOTAL_SIZE_MB = 100
    MAX_IMAGE_SIZE = MAX_IMAGE_SIZE_MB * 1024 * 1024
    MAX_TOTAL_SIZE = MAX_TOTAL_SIZE_MB * 1024 * 1024
    total_size = 0

    for i, img in enumerate(request.images):
        img_size = len(img)
        if img_size > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Image {i+1} too large ({img_size // 1024 // 1024}MB). Max: {MAX_IMAGE_SIZE_MB}MB"
            )
        total_size += img_size

    if total_size > MAX_TOTAL_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Total request too large ({total_size // 1024 // 1024}MB). Max: {MAX_TOTAL_SIZE_MB}MB"
        )

    if request.style not in STYLE_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid style. Available: {list(STYLE_PRESETS.keys())}"
        )

    if request.aspect_ratio not in ASPECT_RATIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid aspect ratio. Available: {ASPECT_RATIOS}"
        )

    job_id = str(uuid.uuid4())

    # Save images to disk instead of storing in Redis
    image_dir = os.path.join(JOB_IMAGES_DIR, job_id)
    os.makedirs(image_dir, exist_ok=True)
    image_paths = []

    try:
        for i, img in enumerate(request.images):
            path = os.path.join(image_dir, f"img_{i:03d}.dat")
            with open(path, "w") as f:
                f.write(img)
            image_paths.append(path)
    except Exception as e:
        shutil.rmtree(image_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to save images: {e}")

    job_data = {
        "job_id": job_id,
        "status": "queued",
        "image_paths": image_paths,
        "image_dir": image_dir,
        "style": request.style,
        "aspect_ratio": request.aspect_ratio,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    job_ttl_seconds = IMAGE_EXPIRY_MINUTES * 2 * 60
    redis_client.setex(f"job:{job_id}", job_ttl_seconds, json.dumps(job_data))
    redis_client.lpush("job_queue", job_id)

    return JobResponse(job_id=job_id, status="queued")


@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job_status(job_id: str):
    """Get the status of a job"""
    job_data = redis_client.get(f"job:{job_id}")
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(job_data)

    response = JobStatus(
        job_id=job["job_id"],
        status=job["status"],
        status_detail=job.get("status_detail"),
    )

    if job["status"] == "completed":
        response.image_url = job.get("image_url")
        response.expires_at = job.get("expires_at")
    elif job["status"] == "failed":
        response.error = job.get("error")

    return response


# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
