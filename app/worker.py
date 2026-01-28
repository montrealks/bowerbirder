"""Bowerbirder worker - processes collage generation jobs from Redis queue"""
from app.settings import settings
import os
import io
import json
import signal
import time
import base64
import shutil
import threading
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import redis
import fal_client
from PIL import Image, ImageOps

# Allow large images
Image.MAX_IMAGE_PIXELS = 178956970

from app.config import STYLE_PRESETS, OPTIMIZE_MAX_SIZE, OPTIMIZE_QUALITY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown_event = threading.Event()


def _signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, initiating graceful shutdown...")
    _shutdown_event.set()


redis_client = redis.from_url(settings.redis_url)

OUTPUT_DIR = settings.output_dir
IMAGE_EXPIRY_MINUTES = settings.image_expiry_minutes
API_BASE_URL = settings.api_base_url


def update_job_status(job_id: str, status: str, **extra):
    """Update job status in Redis"""
    job_data = redis_client.get(f"job:{job_id}")
    if not job_data:
        return

    job = json.loads(job_data)
    job["status"] = status
    job.update(extra)
    redis_client.set(f"job:{job_id}", json.dumps(job))


def optimize_image(image_data: bytes) -> bytes:
    """Optimize image for API submission.

    - Apply EXIF orientation (fix rotated phone photos)
    - Resize longest edge to 768px
    - Convert to JPEG at 85% quality
    - Strip metadata
    """
    img = Image.open(io.BytesIO(image_data))

    # Apply EXIF orientation - fixes rotated phone photos
    img = ImageOps.exif_transpose(img)

    # Convert to RGB if necessary (handles PNG with alpha, etc.)
    if img.mode in ('RGBA', 'P', 'LA', 'L'):
        # Create white background for transparent images
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        else:
            img = img.convert('RGB')

    # Resize to max longest edge
    max_size = OPTIMIZE_MAX_SIZE
    ratio = max_size / max(img.size)
    if ratio < 1:
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Save as JPEG with quality setting
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=OPTIMIZE_QUALITY, optimize=True)
    return buffer.getvalue()


def decode_base64_image(data_url: str) -> bytes:
    """Decode base64 data URL to bytes"""
    # Handle data URL format: data:image/jpeg;base64,/9j/4AAQ...
    if data_url.startswith('data:'):
        # Split off the header
        header, base64_data = data_url.split(',', 1)
    else:
        base64_data = data_url

    return base64.b64decode(base64_data)


def upload_to_fal(image_bytes: bytes) -> str:
    """Upload image bytes to fal.ai and return the URL"""
    url = fal_client.upload(image_bytes, content_type="image/jpeg")
    return url


def process_job(job_id: str):
    """Process a single job"""
    logger.info(f"[{job_id}] Processing job started")

    job_data = redis_client.get(f"job:{job_id}")
    if not job_data:
        logger.warning(f"[{job_id}] Job not found in Redis")
        return

    job = json.loads(job_data)
    update_job_status(job_id, "processing", status_detail="Optimizing images...")
    image_dir = job.get("image_dir")

    try:
        # Load and optimize images
        image_paths = job.get("image_paths", [])
        optimized_images = []

        for i, path in enumerate(image_paths):
            update_job_status(job_id, "processing",
                              status_detail=f"Optimizing image {i+1}/{len(image_paths)}...")

            with open(path, "r") as f:
                data_url = f.read()

            raw_bytes = decode_base64_image(data_url)
            optimized_bytes = optimize_image(raw_bytes)
            optimized_images.append(optimized_bytes)

            logger.info(f"[{job_id}] Optimized image {i+1}: "
                        f"{len(raw_bytes) // 1024}KB -> {len(optimized_bytes) // 1024}KB")

        # Upload to fal.ai
        update_job_status(job_id, "processing", status_detail="Uploading images...")
        image_urls = []

        for i, img_bytes in enumerate(optimized_images):
            update_job_status(job_id, "processing",
                              status_detail=f"Uploading image {i+1}/{len(optimized_images)}...")
            url = upload_to_fal(img_bytes)
            image_urls.append(url)
            logger.info(f"[{job_id}] Uploaded image {i+1}: {url[:60]}...")

        # Get style prompt
        style_key = job.get("style", "fridge")
        style = STYLE_PRESETS.get(style_key, STYLE_PRESETS["fridge"])
        prompt = style["prompt"]

        # Call fal.ai API
        update_job_status(job_id, "processing", status_detail="Generating collage...")
        logger.info(f"[{job_id}] Calling fal.ai with {len(image_urls)} images, style: {style_key}")

        result = fal_client.subscribe(
            "fal-ai/nano-banana-pro/edit",
            arguments={
                "prompt": prompt,
                "image_urls": image_urls,
                "resolution": "2K",
                "aspect_ratio": job.get("aspect_ratio", "16:9"),
                "output_format": "png",
                "num_images": 1
            }
        )

        # Get result image URL
        images = result.get("images", [])
        if not images:
            raise Exception("No images returned from fal.ai")

        result_url = images[0]["url"]
        logger.info(f"[{job_id}] Got result from fal.ai: {result_url[:60]}...")

        # Download result image
        update_job_status(job_id, "processing", status_detail="Downloading result...")
        import httpx
        with httpx.Client(timeout=60.0) as client:
            response = client.get(result_url)
            response.raise_for_status()
            result_bytes = response.content

        # Save to output directory
        output_path = os.path.join(OUTPUT_DIR, f"{job_id}.png")
        with open(output_path, "wb") as f:
            f.write(result_bytes)

        logger.info(f"[{job_id}] Saved result to {output_path} ({len(result_bytes) // 1024}KB)")

        # Update job status
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=IMAGE_EXPIRY_MINUTES)
        expires_at_iso = expires_at.isoformat().replace("+00:00", "Z")
        image_url = f"{API_BASE_URL}/output/{job_id}.png"

        update_job_status(
            job_id,
            "completed",
            image_url=image_url,
            expires_at=expires_at_iso,
            status_detail=None
        )

        logger.info(f"[{job_id}] Job completed successfully - {image_url}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[{job_id}] Job failed: {error_msg}")
        update_job_status(job_id, "failed", error=error_msg, status_detail=None)

    finally:
        # Clean up image directory
        if image_dir:
            shutil.rmtree(image_dir, ignore_errors=True)


def cleanup_expired_images():
    """Delete images older than IMAGE_EXPIRY_MINUTES and their Redis keys"""
    try:
        now = time.time()
        expiry_seconds = IMAGE_EXPIRY_MINUTES * 60
        output_path = Path(OUTPUT_DIR)

        if not output_path.exists():
            return

        deleted_count = 0
        for image_file in output_path.glob("*.png"):
            file_age = now - image_file.stat().st_mtime
            if file_age > expiry_seconds:
                job_id = image_file.stem
                image_file.unlink()
                redis_client.delete(f"job:{job_id}")
                deleted_count += 1
                logger.info(f"Cleaned up expired image: {image_file.name} (age: {int(file_age/60)}m)")

        if deleted_count > 0:
            logger.info(f"Cleanup complete: deleted {deleted_count} expired image(s)")

    except Exception as e:
        logger.error(f"Cleanup error: {e}")


def cleanup_worker():
    """Background thread that periodically cleans up expired images"""
    while not _shutdown_event.is_set():
        _shutdown_event.wait(timeout=60)
        if not _shutdown_event.is_set():
            cleanup_expired_images()


def main():
    """Main worker loop with graceful shutdown support."""
    logger.info("Bowerbirder Worker Started")
    logger.info(f"Output dir: {OUTPUT_DIR}")
    logger.info(f"Image expiry: {IMAGE_EXPIRY_MINUTES} minutes")

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    logger.info("Cleanup thread started (checks every 60s)")

    while not _shutdown_event.is_set():
        try:
            result = redis_client.brpop("job_queue", timeout=5)

            if result and not _shutdown_event.is_set():
                _, job_id = result
                job_id = job_id.decode() if isinstance(job_id, bytes) else job_id
                logger.info(f"[{job_id}] Starting job")
                process_job(job_id)
                logger.info(f"[{job_id}] Job completed")

        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}")
            if not _shutdown_event.is_set():
                time.sleep(5)
        except Exception as e:
            logger.error(f"Worker error: {e}")
            if not _shutdown_event.is_set():
                time.sleep(1)

    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    main()
