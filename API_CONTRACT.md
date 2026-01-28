# Unified API Contract

This document describes the standardized API contract shared across Gooser, Ducker, and Bowerbirder.

## Base Configuration

| Project | Dev Port | Prod Port |
|---------|----------|-----------|
| Gooser | 8000 | 8000 |
| Ducker | 8001 | 8001 |
| Bowerbirder | 8002 | 8002 |

## Endpoints

### GET /health

Health check endpoint.

**Response:**
```json
{"status": "ok"}
```

### GET /options

List available options/presets for the service.

**Response:**
```json
[
  {"id": "option_id", "name": "Display Name"},
  ...
]
```

### GET /aspect-ratios

List available output aspect ratios.

**Response:**
```json
{"aspect_ratios": ["16:9", "1:1", "9:16"]}
```

### POST /jobs

Create a new processing job.

**Request:** (varies by project, but always includes `images` array)
```json
{
  "images": ["data:image/jpeg;base64,...", ...],
  "option_id": "selected_option",
  "aspect_ratio": "16:9"
}
```

**Response:**
```json
{"job_id": "uuid-string"}
```

**Error Responses:**
- `400` - Invalid request (missing images, invalid options)
- `413` - Payload too large
- `503` - Server busy (queue full)

### GET /jobs/{job_id}

Get job status and result.

**Response (queued/processing):**
```json
{
  "job_id": "uuid-string",
  "status": "processing",
  "status_detail": "Uploading images...",
  "output_url": null,
  "expires_at": null,
  "error": null
}
```

**Response (completed):**
```json
{
  "job_id": "uuid-string",
  "status": "completed",
  "status_detail": null,
  "output_url": "https://example.com/output/uuid.png",
  "expires_at": "2026-01-28T12:30:00Z",
  "error": null
}
```

**Response (failed):**
```json
{
  "job_id": "uuid-string",
  "status": "failed",
  "status_detail": null,
  "output_url": null,
  "expires_at": null,
  "error": "Error message describing what went wrong"
}
```

## Job Status Values

| Status | Description |
|--------|-------------|
| `queued` | Job is waiting in queue |
| `processing` | Job is being processed |
| `completed` | Job finished successfully |
| `failed` | Job failed with error |

## Unified Constants

All projects use these limits (defined in `app/config.py`):

```python
MIN_IMAGES = 2
MAX_IMAGES = 20
MAX_IMAGE_SIZE_MB = 20
MAX_TOTAL_SIZE_MB = 250
OUTPUT_EXPIRY_MINUTES = 30
MAX_QUEUE_LENGTH = 10
```

## Error Response Format

All error responses follow this format:

```json
{
  "detail": "Human-readable error message"
}
```

## CORS

All projects accept requests from:
- `http://localhost:5173` (SvelteKit dev)
- `http://localhost:5174` (SvelteKit dev alternate)
- `http://localhost:3000` (alternative dev)
- Project-specific production domains

## Authentication

Currently none. IP whitelisting available via `API_ALLOWED_IPS` environment variable in production.
