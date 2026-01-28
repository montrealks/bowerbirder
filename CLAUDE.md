# CLAUDE.md - Bowerbirder

## Overview

Bowerbirder is an AI-powered photo collage generator. Users upload 2-6 photos, select a style preset, choose an aspect ratio, and the app generates a styled collage using fal.ai's Nano Banana Pro API.

Named after the bowerbird - nature's collage artist that collects and arranges colorful objects into elaborate displays.

## Tech Stack

- **Backend**: FastAPI (Python 3.11)
- **Frontend**: SvelteKit 5 with Uppy for file uploads
- **Queue**: Redis for job processing
- **AI**: fal.ai Nano Banana Pro (`fal-ai/nano-banana-pro/edit`)
- **Image Processing**: Pillow (PIL) for optimization before API calls

## Project Template

This project is based on **Ducker** (`~/Projects/ducker`). Copy the following from Ducker as starting points:
- `docker-compose.yml` / `docker-compose.prod.yml`
- `Dockerfile`
- `frontend/` directory structure (SvelteKit 5)
- Redis job queue pattern

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   FastAPI   │────▶│    Redis    │
│  (SvelteKit)│     │    (API)    │     │   (Queue)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │   Worker    │
                                        │  (fal.ai)   │
                                        └─────────────┘
```

**Flow:**
1. User uploads 2-6 images via Uppy
2. User selects style preset (Fridge, Scrapbook, Clean)
3. User selects aspect ratio (16:9, 1:1, 9:16)
4. Frontend sends images + options to FastAPI
5. FastAPI creates job in Redis queue
6. Worker picks up job, optimizes images, calls fal.ai API
7. Worker stores result, updates job status
8. Frontend polls for completion, displays result

## API Specification

### Nano Banana Pro Edit API

**Endpoint:** `fal-ai/nano-banana-pro/edit`

**Request:**
```json
{
  "prompt": "Arrange these photos as if pinned with colorful magnets on a teal refrigerator door...",
  "image_urls": [
    "https://...",
    "https://..."
  ],
  "resolution": "2K",
  "aspect_ratio": "16:9",
  "output_format": "png",
  "num_images": 1
}
```

**Response:**
```json
{
  "images": [
    {
      "url": "https://storage.googleapis.com/.../result.png",
      "width": 2048,
      "height": 1152,
      "content_type": "image/png",
      "file_size": 1234567
    }
  ],
  "description": "..."
}
```

**Cost:** $0.15 per generation

**Documentation:** https://fal.ai/models/fal-ai/nano-banana-pro/edit/api

## Configuration

### Style Presets

```python
STYLE_PRESETS = {
    "fridge": {
        "name": "On the Fridge",
        "prompt": "Arrange these photos as if pinned with colorful magnets on a teal refrigerator door, slightly tilted and overlapping naturally, casual family photo display"
    },
    "scrapbook": {
        "name": "Old Scrapbook",
        "prompt": "Arrange these photos on a vintage scrapbook page with aged cream paper texture, washi tape, corner stickers, and nostalgic decorations"
    },
    "clean": {
        "name": "Clean",
        "prompt": "Arrange these photos in a clean, modern gallery layout on a pure white background with subtle drop shadows, balanced spacing"
    }
}
```

### Output Dimensions

Based on aspect ratio with 2K (2048px) longest edge:
- **Landscape (16:9)**: 2048 × 1152
- **Square (1:1)**: 2048 × 2048
- **Portrait (9:16)**: 1152 × 2048

### Limits

| Limit | Value |
|-------|-------|
| Min images | 2 |
| Max images | 6 |
| Max image size | 20MB per image |
| Max total payload | 100MB |
| Result expiry | 30 minutes |

## Image Optimization (Critical)

**Before sending to fal.ai, aggressively optimize images using Pillow:**

1. **Resize**: Longest edge to 768px (maintains aspect ratio)
2. **Format**: JPEG at 85% quality
3. **Strip metadata**: Remove EXIF data to reduce size

```python
from PIL import Image
import io

def optimize_image(image_data: bytes) -> bytes:
    """Optimize image for API submission."""
    img = Image.open(io.BytesIO(image_data))

    # Convert to RGB if necessary (handles PNG with alpha, etc.)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    # Resize to max 768px longest edge
    max_size = 768
    ratio = max_size / max(img.size)
    if ratio < 1:
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Save as JPEG 85% quality
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85, optimize=True)
    return buffer.getvalue()
```

**Why optimize:**
- Faster uploads to fal.ai
- Lower bandwidth costs
- AI doesn't need high-res to understand content
- Typical optimized image: 50-100KB (vs 2-5MB original)

## Project Structure

```
bowerbirder/
├── app/
│   ├── main.py           # FastAPI server
│   ├── worker.py         # Job processor (image optimization + fal.ai)
│   └── config.py         # Style presets, limits, constants
├── frontend/
│   ├── src/
│   │   └── routes/
│   │       ├── +layout.svelte
│   │       └── +page.svelte   # Main UI
│   ├── static/
│   ├── package.json
│   └── svelte.config.js
├── output/               # Generated collages (served statically)
├── docker-compose.yml    # Development config
├── docker-compose.prod.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

## Development

### Local Setup

```bash
# Start all services
docker compose up -d

# Frontend dev server (with hot reload)
cd frontend && npm run dev
```

### Code Changes Without Rebuild

- `app/main.py` - Auto-reloads via uvicorn
- `app/worker.py` - Requires: `docker compose restart worker`
- `app/config.py` - Requires: `docker compose restart worker`

### Testing

```bash
# Health check
curl http://localhost:8000/health

# List style presets
curl http://localhost:8000/styles

# List aspect ratios
curl http://localhost:8000/aspect-ratios
```

## API Endpoints (FastAPI)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/styles` | List available style presets |
| GET | `/aspect-ratios` | List available aspect ratios |
| POST | `/jobs` | Create new collage job |
| GET | `/jobs/{job_id}` | Get job status |

### POST /jobs

**Request:**
```json
{
  "images": ["data:image/jpeg;base64,...", "data:image/jpeg;base64,..."],
  "style": "fridge",
  "aspect_ratio": "16:9"
}
```

**Response:**
```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

### GET /jobs/{job_id}

**Response (processing):**
```json
{
  "job_id": "uuid",
  "status": "processing",
  "status_detail": "Generating collage..."
}
```

**Response (completed):**
```json
{
  "job_id": "uuid",
  "status": "completed",
  "image_url": "http://localhost:8000/output/uuid.png",
  "expires_at": "2026-01-28T15:30:00Z"
}
```

## Frontend UI

Based on Ducker's UI with these changes:

### Section 1: Add Photos
- Uppy dashboard (same as Ducker)
- Min 2, max 6 images
- Show capacity bar

### Section 2: Choose Style
- Simple button grid (like Ducker's track selector)
- 3 options: "On the Fridge", "Old Scrapbook", "Clean"

### Section 3: Aspect Ratio
- Same aspect ratio picker as Ducker
- 3 options with icons: Landscape (16:9), Square (1:1), Portrait (9:16)

### Generate Button
- "Generate Collage (X photos)"
- Shows status during processing
- Disabled if < 2 images

### Result
- Display generated collage image
- Download button
- Expiry timer (30 minutes)
- Clear button

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FAL_KEY` | fal.ai API key | - |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |
| `ENVIRONMENT` | `local` or `production` | `local` |
| `API_BASE_URL` | URL for result links | `http://localhost:8000` |
| `IMAGE_EXPIRY_MINUTES` | Result cleanup time | `30` |
| `API_ALLOWED_IPS` | IP whitelist (production) | - |

## Deployment

### VPS (bowerbirder.pressive.in)

Follow same pattern as Ducker:

```bash
# Sync files
rsync -avz app/ docker-compose.yml docker-compose.prod.yml vps:bowerbirder/
rsync -avz frontend/src/ vps:bowerbirder/frontend/src/

# Rebuild and restart
ssh vps "cd bowerbirder && docker compose -f docker-compose.prod.yml down && docker compose -f docker-compose.prod.yml up -d --build"
```

## Implementation Checklist

### Phase 1: Project Setup
- [ ] Copy Ducker's docker-compose.yml and adapt
- [ ] Copy Ducker's Dockerfile and adapt
- [ ] Create requirements.txt (fastapi, redis, pillow, fal-client, httpx)
- [ ] Create .env.example
- [ ] Copy frontend structure from Ducker

### Phase 2: Backend
- [ ] Create app/config.py with style presets and constants
- [ ] Create app/main.py with FastAPI endpoints
- [ ] Create app/worker.py with image optimization and fal.ai integration
- [ ] Test API locally

### Phase 3: Frontend
- [ ] Adapt +page.svelte for collage UI
- [ ] Update section 2 from tracks to styles
- [ ] Change image limit from 20 to 6
- [ ] Update generate button text
- [ ] Display image result instead of video

### Phase 4: Testing & Polish
- [ ] Test full flow locally
- [ ] Test with various image sizes and counts
- [ ] Verify image optimization is working
- [ ] Test all 3 style presets
- [ ] Test all 3 aspect ratios

### Phase 5: Deployment
- [ ] Set up bowerbirder.pressive.in
- [ ] Deploy to VPS
- [ ] Configure Caddy reverse proxy
- [ ] Test production

## Future Enhancements (Not for V1)

- Visual preview cards for style presets
- Custom prompt input (advanced mode)
- More style presets
- Integration back into Route1Views Media Studio V2

## Related Projects

- **Ducker** (`~/Projects/ducker`) - Ken Burns video generator (template for this project)
- **Gooser** (`~/Projects/gooser`) - Group photo compositor
- **Route1Views Media Studio V2** - Where this will eventually integrate
