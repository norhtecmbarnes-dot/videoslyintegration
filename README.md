# Videosly ↔ Ollama Bridge

A tiny FastAPI server that makes **Videosly** think it is talking to an OpenAI‑compatible endpoint while actually forwarding the request to a local **Ollama** model.

## Prerequisites
- Python 3.9+ installed.
- Ollama running locally (default `http://127.0.0.1:11434`).
- The JWT you provided (already baked into the bridge).

## Generating videos (optional)

If you have a video‑generation program that accepts a plain‑text prompt via a CLI (e.g., `ffmpeg‑video‑gen "<prompt>"`), you can extend the bridge with a tiny endpoint that forwards the LLM‑generated script to that program.

1. **Add a new FastAPI route** (see the code snippet below) that:
   - Calls the existing `/v1/chat/completions` endpoint internally to obtain a script.
   - Executes the external video‑generation binary with the script as an argument.
   - Returns the generated video file (or a URL) to the caller.

2. **Install the required binary** on the same machine where the bridge runs. The bridge will invoke it using `subprocess.run` with `shell=False` for safety.

```python
import subprocess
from fastapi import File, UploadFile

@app.post("/v1/generate-video")
async def generate_video(request: Request, authorization: str = Header(None)):
    # Re‑use the chat endpoint to get a script
    chat_resp = await chat_completions(request, authorization)
    script = chat_resp.body.decode().json()["choices"][0]["message"]["content"]

    # Call external video generator (replace `video-gen` with your actual command)
    result = subprocess.run(["video-gen", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail="Video generation failed")

    # Assuming the tool writes a file named `output.mp4` in the cwd
    return FileResponse("output.mp4", media_type="video/mp4")
```

3. **Expose it to Videosly** by configuring the platform to call `POST /v1/generate-video` instead of the plain chat endpoint.

> **Security note:** Only expose this endpoint on a trusted internal network. The bridge validates the JWT before invoking any external binary, preventing unauthenticated users from running arbitrary commands.


## Configuration (optional)
- **Port** – set the `PORT` environment variable before launching, e.g. `set PORT=4000`.
- **Ollama URL** – edit the `OLLAMA_URL` constant in `videosly_ollama_bridge.py` if Ollama runs elsewhere.
- **JWT secret** – the bridge now reads the token from the `VIDEOSLY_TOKEN` environment variable. Update this variable whenever the token is refreshed (every 60 days). The bridge will reject requests until the variable is set.

## How to point Videosly at the bridge
| Setting | Value |
|---------|-------|
| **Base URL** | `http://127.0.0.1:3000/v1` |
| **Authorization header** | `Bearer <your‑jwt‑token>` |
| **Endpoint** | `POST /chat/completions` (or add a `/completions` alias if needed) |

## Verify it works
```bash
curl -X POST http://127.0.0.1:3000/v1/chat/completions \
  -H "Authorization: Bearer <your‑jwt‑token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"llama2","messages":[{"role":"user","content":"Hello"}],"temperature":0.7,"max_tokens":128}'
```
You should receive an OpenAI‑style JSON payload containing Ollama’s response.

## Running as a background service (optional)
Create a Windows Service or use `nssm`/`sc` to run the same command automatically on boot. The same `uvicorn` command works; just point the service’s *binPath* to the `python.exe` inside the virtual‑env and pass the arguments.

---
**That’s it!** The bridge is now a single‑file, one‑command service that lets Videosly talk to your local Ollama model.
