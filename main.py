
import asyncio
import logging
import os
import uuid
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
from utils.session_storage import (
    STORAGE_ROOT,
    cleanup_loop,
    current_session_id,
    get_session_folder,
    validate_session_id,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
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
    session_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str


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
    session_id = request.session_id or str(uuid.uuid4())

    try:
        validate_session_id(session_id)
        get_session_folder(session_id)

        token = current_session_id.set(session_id)
        try:
            initial_state = {
                "messages": [HumanMessage(content=request.question)],
                "route_response": "",
            }

            # result = await data_agent.ainvoke(initial_state)
            result = await data_agent.ainvoke(initial_state,
                                              config={
                                                  "configurable": {
                                                      "thread_id": session_id
                                                    }
                                                },
                                            )
            answer = extract_answer(result.get("messages", []))

            if not answer:
                logger.warning("Agent returned no extractable answer")
                answer = (
                    "The agent completed but returned no readable answer. "
                    "Please check the backend logs."
                )

            return ChatResponse(answer=answer, session_id=session_id)
        finally:
            current_session_id.reset(token)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Ola Data Agent request failed")
        raise HTTPException(
            status_code=500,
            detail="The agent could not process your request. Check backend logs.",
        )


@app.get("/files/{session_id}")
def list_session_files(session_id: str):
    try:
        folder = get_session_folder(validate_session_id(session_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    files = []
    for path in folder.rglob("*"):
        if path.is_file() and path.name != ".activity":
            files.append({
                "name": path.name,
                "path": path.relative_to(folder).as_posix(),
                "download_url": f"/files/{session_id}/download/"
                                f"{path.relative_to(folder).as_posix()}",
            })

    return {"session_id": session_id, "files": files}


@app.get("/files/{session_id}/download/{file_path:path}")
def download_session_file(session_id: str, file_path: str):
    try:
        folder = get_session_folder(validate_session_id(session_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    requested = (folder / file_path).resolve()

    if folder.resolve() not in requested.parents:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not requested.is_file() or requested.name == ".activity":
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(requested),
        filename=requested.name,
    )