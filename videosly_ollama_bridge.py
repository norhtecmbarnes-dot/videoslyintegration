#!/usr/bin/env python3
"""Videosly ↔ Ollama bridge

- Listens on http://127.0.0.1:3000 (default, configurable via PORT env var)
- Exposes an OpenAI‑compatible endpoint used by Videosly:
      POST /v1/chat/completions
- Validates the JWT you supplied (HS256, token itself is the secret).
- Translates the request payload to Ollama's `/api/chat` format.
- Returns an OpenAI‑style JSON response (or streams SSE when `stream:true`).

Run with:
    uvicorn videosly_ollama_bridge:app --host 0.0.0.0 --port 3000
"""

import os
import time
from typing import Any, Dict

import jwt
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

# ----------------------------------------------------------------------
# Configuration – edit only if your Ollama instance runs elsewhere.
# ----------------------------------------------------------------------
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"  # Ollama chat endpoint
VIDEOSLY_AUDIENCE = "https://api.videosly.ai/v1"
# The JWT you posted is used as the secret key (HS256). In production you would
# store the secret securely elsewhere.
# Token secret is read from the environment variable VIDEOSLY_TOKEN.
# This allows you to rotate the token without restarting the server.
# If the variable is not set, the server will refuse all requests.
if not TOKEN_SECRET:
    raise RuntimeError("VIDEOSLY_TOKEN environment variable not set; the bridge cannot verify JWTs.")

# ----------------------------------------------------------------------
# Helper: verify incoming JWT (HS256, token itself is the secret).
# ----------------------------------------------------------------------
def verify_jwt(auth_header: str | None) -> None:
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = auth_header.split(" ", 1)[1]
    try:
        jwt.decode(
            token,
            TOKEN_SECRET,
            algorithms=["HS256"],
            audience=VIDEOSLY_AUDIENCE,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

# ----------------------------------------------------------------------
# Core endpoint – OpenAI‑compatible chat completion.
# ----------------------------------------------------------------------
@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: str = Header(None)):
    # 1️⃣ Authenticate
    verify_jwt(authorization)

    # 2️⃣ Parse request body
    body: Dict[str, Any] = await request.json()
    model = body.get("model", "llama2")
    messages = body.get("messages", [])
    temperature = body.get("temperature", 0.8)
    max_tokens = body.get("max_tokens", 512)
    stream = bool(body.get("stream", False))

    # 3️⃣ Build Ollama payload
    ollama_payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
        "max_gen_len": max_tokens,
    }

    # 4️⃣ Call Ollama
    async with httpx.AsyncClient() as client:
        try:
            ollama_resp = await client.post(OLLAMA_URL, json=ollama_payload, timeout=60.0)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc

    # 5️⃣ Streaming case – forward raw SSE directly
    if stream:
        return StreamingResponse(ollama_resp.aiter_raw(), media_type="text/event-stream")

    # 6️⃣ Convert Ollama JSON to OpenAI‑compatible JSON
    ollama_data = ollama_resp.json()
    openai_resp = {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "usage": {
            "prompt_tokens": ollama_data.get("prompt_eval_count", 0),
            "completion_tokens": ollama_data.get("eval_count", 0),
            "total_tokens": ollama_data.get("prompt_eval_count", 0) + ollama_data.get("eval_count", 0),
        },
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": ollama_data.get("message", {}).get("content", ""),
                },
                "finish_reason": "stop",
            }
        ],
    }
    return JSONResponse(openai_resp)

# ----------------------------------------------------------------------
# Optional health‑check endpoint (useful for Docker / CI).
# ----------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}

# End of file
