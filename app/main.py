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

from app.config import (
    STYLE_PRESETS, ASPECT_RATIOS, MIN_IMAGES, MAX_IMAGES,
    MAX_IMAGE_SIZE_MB, MAX_TOTAL_SIZE_MB, OUTPUT_EXPIRY_MINUTES, MAX_QUEUE_LENGTH
)
from app.ratelimit import check_rate_limit, get_trusted_client_ip

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

# Rate limiting (anonymous expensive /jobs endpoint)
RATE_LIMIT_ENABLED = settings.rate_limit_enabled
RATE_LIMIT_PER_MINUTE = settings.rate_limit_per_minute
RATE_LIMIT_PER_HOUR = settings.rate_limit_per_hour
RATE_LIMIT_PER_DAY = settings.rate_limit_per_day


def get_client_ip(request: Request) -> str:
    """Return the real, non-spoofable client IP.

    Uses the trusted X-Real-IP / CF-Connecting-IP header set by the Caddy
    edge from Cloudflare's verified Cf-Connecting-Ip. Raw X-Forwarded-For
    is client-spoofable and is no longer trusted.
    """
    return get_trusted_client_ip(request)


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
    output_url: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/options")
def list_options():
    """List available style presets"""
    return [
        {"id": key, "name": preset["name"]}
        for key, preset in STYLE_PRESETS.items()
    ]


@app.get("/aspect-ratios")
def list_aspect_ratios():
    """List available output aspect ratios"""
    return {"aspect_ratios": ASPECT_RATIOS}


@app.post("/jobs", response_model=JobResponse)
def create_job(request: JobRequest, http_request: Request):
    """Create a new collage generation job"""
    # Per-IP rate limiting on this anonymous, expensive endpoint so cost
    # cannot be amplified. Uses the trusted real client IP.
    if RATE_LIMIT_ENABLED:
        client_ip = get_client_ip(http_request)
        rl = check_rate_limit(
            redis_client,
            client_ip,
            prefix="bowerbirder",
            per_minute=RATE_LIMIT_PER_MINUTE,
            per_hour=RATE_LIMIT_PER_HOUR,
            per_day=RATE_LIMIT_PER_DAY,
        )
        if not rl.allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({rl.limit} per {rl.scope}). Retry in {rl.retry_after}s.",
                headers={"Retry-After": str(rl.retry_after)},
            )

    # Check queue backpressure
    queue_length = redis_client.llen("bowerbirder_job_queue")
    if queue_length >= MAX_QUEUE_LENGTH:
        raise HTTPException(
            status_code=503,
            detail=f"Server busy ({queue_length} jobs queued). Try again later."
        )

    if len(request.images) < MIN_IMAGES:
        raise HTTPException(status_code=400, detail=f"At least {MIN_IMAGES} images required")

    if len(request.images) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_IMAGES} images allowed")

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
    redis_client.lpush("bowerbirder_job_queue", job_id)

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
        response.output_url = job.get("output_url")
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
