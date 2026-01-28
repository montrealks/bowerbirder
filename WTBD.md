# WTBD - Cross-Project Standardization

Standardize Gooser, Ducker, and Bowerbirder to use identical architecture, libraries, and API contracts.

## Workflow Rules

1. Each iteration tackles exactly 1 task
2. Check notes left by previous iteration before starting
3. Always run smoketest after each task
4. Perform full research for each task individually - no hallucinations, no laziness
5. Determine verification/backpressure tests before beginning each task
6. When refactoring code, apply sitewide using grep/glob/search agents
7. Complete 1 task → run smoketest → commit → mark complete → leave note
8. After large changes affecting many lines, run code simplification
9. Don't stop until WTBD is totally complete
10. Dispatch up to 20 Sonnet Task Agents as necessary for efficiency

---

## Tasks

### A. Pin Library Versions (All Projects)

Standardize requirements.txt across all three projects:

```
fastapi==0.109.0
uvicorn==0.27.0
redis==5.0.1
httpx==0.26.0
pillow==10.2.0
pydantic==2.5.3
pydantic-settings==2.1.0
python-multipart==0.0.6
```

- [x] A1. Update Gooser requirements.txt (keep project-specific deps like insightface, opencv)
- [x] A2. Update Ducker requirements.txt (keep project-specific deps)
- [x] A3. Update Bowerbirder requirements.txt (keep project-specific deps like fal-client)
- [x] A4. Verify all three projects build successfully with `docker compose build`

**Verification:** `docker compose build` succeeds for all three projects

---

### B. Standardize Config Constants (All Projects)

Add unified constants to each project's `config.py`:

```python
# Unified limits
MIN_IMAGES = 2
MAX_IMAGES = 20
MAX_IMAGE_SIZE_MB = 20
MAX_TOTAL_SIZE_MB = 250
OUTPUT_EXPIRY_MINUTES = 30
MAX_QUEUE_LENGTH = 10
```

- [ ] B1. Update Gooser config.py with unified constants
- [ ] B2. Update Ducker config.py with unified constants
- [ ] B3. Update Bowerbirder config.py with unified constants
- [ ] B4. Update each project's main.py to use constants from config.py (if hardcoded)
- [ ] B5. Update each project's worker.py to use OUTPUT_EXPIRY_MINUTES from config.py

**Verification:** Grep for hardcoded values (20, 250, etc.) - should only appear in config.py

---

### C. Add Queue Backpressure to Gooser

Gooser lacks queue length check. Add it to match Ducker/Bowerbirder pattern.

- [ ] C1. Research how Ducker/Bowerbirder implement queue backpressure in main.py
- [ ] C2. Add MAX_QUEUE_LENGTH check to Gooser's POST /jobs endpoint
- [ ] C3. Return 503 with appropriate error message when queue is full

**Verification:** Test by filling queue and confirming 503 response

---

### D. Rename Options Endpoints

Standardize the "list options" endpoint across all projects:

| Current | Target |
|---------|--------|
| Gooser: `/presets` | `/options` |
| Ducker: `/tracks` | `/options` |
| Bowerbirder: `/styles` | `/options` |

- [ ] D1. Rename Gooser `/presets` to `/options`, update response format
- [ ] D2. Rename Ducker `/tracks` to `/options`, update response format
- [ ] D3. Rename Bowerbirder `/styles` to `/options`, update response format
- [ ] D4. Update each frontend to call `/options` instead of old endpoint
- [ ] D5. Ensure response format is consistent: `[{"id": "...", "name": "..."}]`

**Verification:** `curl /options` returns same schema for all three projects

---

### E. Standardize Job Response Schema

Unify the job status response across all projects:

```python
class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    status_detail: Optional[str] = None
    output_url: Optional[str] = None  # was: result_url, video_url, image_url
    expires_at: Optional[str] = None
    error: Optional[str] = None
```

- [ ] E1. Update Gooser: rename `result_url` to `output_url` in job responses
- [ ] E2. Update Ducker: rename `video_url` to `output_url` in job responses
- [ ] E3. Update Bowerbirder: rename `image_url` to `output_url` in job responses
- [ ] E4. Update each frontend to read `output_url` instead of old field name
- [ ] E5. Ensure all projects return `status_detail` during processing

**Verification:** `curl /jobs/{id}` returns identical schema structure for all three

---

### F. Add /aspect-ratios to Gooser

Gooser is missing the `/aspect-ratios` endpoint that Ducker and Bowerbirder have.

- [ ] F1. Research Ducker/Bowerbirder aspect-ratios endpoint implementation
- [ ] F2. Add `GET /aspect-ratios` to Gooser main.py
- [ ] F3. Add ASPECT_RATIOS constant to Gooser config.py if missing
- [ ] F4. Update Gooser frontend to use aspect ratio selector (if applicable)

**Verification:** `curl /aspect-ratios` returns `["16:9", "1:1", "9:16"]` for all three

---

### G. Standardize Port Configuration

Align development and production ports:

| Project | Target Dev Port | Target Prod Port |
|---------|-----------------|------------------|
| Gooser | 8000 | 8000 |
| Ducker | 8001 | 8001 |
| Bowerbirder | 8002 | 8002 |

- [ ] G1. Update Ducker docker-compose.yml to use port 8001
- [ ] G2. Update Ducker docker-compose.prod.yml to use port 8001
- [ ] G3. Verify Bowerbirder already uses 8002 (confirm, no changes needed)
- [ ] G4. Update Ducker frontend API_URL to use correct port
- [ ] G5. Update any Caddy configs if needed

**Verification:** Each project runs on its designated port without conflict

---

### H. Create Shared API Contract Documentation

Document the standardized API contract for programmatic usage.

- [ ] H1. Create `API_CONTRACT.md` in each project with identical content
- [ ] H2. Document all endpoints, request/response schemas
- [ ] H3. Document error responses and status codes
- [ ] H4. Add examples for common workflows

**Verification:** Diff API_CONTRACT.md across projects - should be identical except project name

---

### I. Final Verification & Cleanup

- [ ] I1. Run all three projects simultaneously, verify no port conflicts
- [ ] I2. Test each API endpoint on all three projects
- [ ] I3. Verify frontends work correctly with API changes
- [ ] I4. Run code simplification on any files with large changes
- [ ] I5. Update each project's CLAUDE.md with new API documentation

**Verification:** Full end-to-end test of each application

---

## Progress

### Task A - Completed
- Standardized requirements.txt across all three projects
- Added missing pillow to Ducker
- Changed Bowerbirder from >= to == pinned versions
- All three projects build successfully
- Commits: Gooser 85b94c8, Ducker 69a0dab, Bowerbirder 247d105

---
