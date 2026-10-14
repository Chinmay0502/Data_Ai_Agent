
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

load_dotenv()

from agents.data_agent import data_agent
from utils.etl_tools import (
    DATA_ROOT,
    EXTRACT_DIR,
    TRANSFORM_DIR,
    cleanup_old_files,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup_loop():
    """Check for expired temporary files once per minute."""
    while True:
        try:
            cleanup_old_files()
        except Exception:
            logger.exception("Temporary-file cleanup failed")

        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    TRANSFORM_DIR.mkdir(parents=True, exist_ok=True)

    cleanup_task = asyncio.create_task(cleanup_loop())

    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Ola Data Agent API", lifespan=lifespan)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    answer: str


def extract_answer(messages) -> str:
    for item in reversed(messages or []):
        if getattr(item, "type", None) == "ai":
            content = getattr(item, "content", "")

            if isinstance(content, str) and content.strip():
                return content.strip()

            if isinstance(content, list):
                text_parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("text")
                ]
                if text_parts:
                    return "\n".join(text_parts).strip()

        if isinstance(item, dict):
            answer = extract_answer(item.get("messages", []))
            if answer:
                return answer

    return ""


@app.get("/health")
def health():
    return {"status": "ok", "service": "Ola_Data_Agent"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        initial_state = {
            "messages": [HumanMessage(content=request.question)],
            "route_response": "",
        }

        result = await data_agent.ainvoke(initial_state)
        answer = extract_answer(result.get("messages", []))

        if not answer:
            logger.warning("Agent returned no extractable answer")
            answer = (
                "The agent completed but returned no readable answer. "
                "Please check the backend logs."
            )

        return ChatResponse(answer=answer)

    except Exception:
        logger.exception("Ola Data Agent request failed")
        raise HTTPException(
            status_code=500,
            detail=(
                "The agent could not process your request. "
                "Check backend logs."
            ),
        )


@app.get("/files")
def list_files():
    files = []

    for folder in (EXTRACT_DIR, TRANSFORM_DIR):
        if not folder.exists():
            continue

        for path in folder.rglob("*"):
            if path.is_file() and path.name != ".activity":
                relative_path = path.relative_to(DATA_ROOT).as_posix()

                files.append({
                    "name": path.name,
                    "path": relative_path,
                    "download_url": f"/files/download/{relative_path}",
                })

    return {"files": files}


@app.get("/files/download/{file_path:path}")
def download_file(file_path: str):
    requested = (DATA_ROOT / file_path).resolve()
    root = DATA_ROOT.resolve()

    if requested != root and root not in requested.parents:
        raise HTTPException(
            status_code=400,
            detail="Invalid file path",
        )

    allowed_folders = {
        EXTRACT_DIR.resolve(),
        TRANSFORM_DIR.resolve(),
    }

    if not any(
        requested == folder or folder in requested.parents
        for folder in allowed_folders
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid file location",
        )

    if not requested.is_file() or requested.name == ".activity":
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(requested),
        filename=requested.name,
    )