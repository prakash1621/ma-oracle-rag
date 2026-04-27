from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nl2sql.app.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    ensure_default_admin,
)
from nl2sql.app.config import get_settings
from nl2sql.app.database import DatabaseClient
from nl2sql.app.dependencies import get_current_user
from nl2sql.app.llm import SQLGenerator
from nl2sql.app.memory import count_memories, create_agent_memory
from nl2sql.app.models import ChatRequest, ChatResponse, HealthResponse, UnifiedRequest, UnifiedResponse
from nl2sql.app.pipeline import NL2SQLPipeline
from nl2sql.app.schema import load_database_schema
from nl2sql.app.security import SQLValidator
from nl2sql.app.seed_memory import seed_agent_memory

from src.contracts import QueryRequest, QueryResponse as RAGQueryResponse
from src.pipeline import RAGPipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    logger = logging.getLogger(__name__)
    settings = get_settings()

    # NL2SQL pipeline — requires local SQLite DB (may not exist in cloud deployment)
    try:
        database = DatabaseClient(settings.db_path)
        schema = load_database_schema(settings.db_path)
        agent_memory = create_agent_memory(settings)
        await seed_agent_memory(agent_memory)

        app.state.settings = settings
        app.state.database = database
        app.state.agent_memory = agent_memory
        app.state.pipeline = NL2SQLPipeline(
            settings=settings,
            database=database,
            sql_generator=SQLGenerator(settings=settings, schema=schema),
            sql_validator=SQLValidator(schema=schema, database=database),
            agent_memory=agent_memory,
        )
    except Exception as exc:
        logger.warning("NL2SQL pipeline init skipped (no local DB): %s", exc)
        app.state.settings = settings
        app.state.database = None
        app.state.agent_memory = None
        app.state.pipeline = None

    app.state.rag_pipeline = RAGPipeline(use_mocks=_should_use_mocks())
    ensure_default_admin()
    yield


def _should_use_mocks() -> bool:
    """Auto-detect: use real modules if Person 2/3/4 code exists, otherwise mocks."""
    try:
        import src.retrieval.pinecone_retriever  # noqa: F401
        import src.knowledge_graph.query  # noqa: F401
        import src.contradiction.detector  # noqa: F401
        return False  # All real modules found — use them
    except ImportError:
        return True  # Some modules missing — use mocks


app = FastAPI(title="NL2SQL API", lifespan=lifespan)

# CORS — allow frontend on Vercel to call Railway backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static asset directory for CSS and JS
app.mount("/static", StaticFiles(directory="nl2sql/static"), name="static")


@app.get("/")
async def serve_ui():
    """Redirect to login if not authenticated, otherwise serve main UI."""
    return FileResponse("nl2sql/static/login.html")


@app.get("/app")
async def serve_app():
    """Serve the main application UI (after login)."""
    return FileResponse("nl2sql/static/index.html")


# ─── Auth endpoints ──────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@app.post("/api/auth/login")
async def login(payload: LoginRequest):
    user = authenticate_user(payload.username, payload.password)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access = create_access_token({"sub": user["username"], "role": user["role"]})
    refresh = create_refresh_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": access, "refresh_token": refresh, "role": user["role"]}


@app.post("/api/auth/refresh")
async def refresh(payload: RefreshRequest):
    data = decode_token(payload.refresh_token, expected_type="refresh")
    if not data:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    access = create_access_token({"sub": data["sub"], "role": data["role"]})
    return {"access_token": access}


# ─── User management (admin only) ────────────────────────────

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


@app.get("/api/users")
async def list_users(user: dict = Depends(get_current_user)):
    from nl2sql.app.auth import _load_users
    users = _load_users()
    return [{"username": k, "role": v.get("role", "viewer")} for k, v in users.items()]


@app.post("/api/users")
async def create_user(payload: CreateUserRequest, user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    from nl2sql.app.auth import _load_users, _save_users, hash_password
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if payload.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'viewer'")
    users = _load_users()
    if payload.username in users:
        raise HTTPException(status_code=409, detail="User already exists")
    users[payload.username] = {
        "password_hash": hash_password(payload.password),
        "role": payload.role,
    }
    _save_users(users)
    return {"username": payload.username, "role": payload.role}


@app.delete("/api/users/{username}")
async def delete_user(username: str, user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    from nl2sql.app.auth import _load_users, _save_users
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if username == user.get("username"):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    users = _load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found")
    del users[username]
    _save_users(users)
    return {"deleted": username}


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    database_status = "connected" if request.app.state.database.check_connection() else "disconnected"
    return HealthResponse(
        status="ok",
        database=database_status,
        agent_memory_items=count_memories(request.app.state.agent_memory),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    return await request.app.state.pipeline.run(payload.question)


@app.post("/query")
async def rag_query(payload: QueryRequest, request: Request, user: dict = Depends(get_current_user)):
    """Unified endpoint — routes question to the best data source automatically."""
    result = request.app.state.rag_pipeline.query(
        payload.question, payload.filters
    )
    response = {
        "answer": result.answer,
        "citations": [
            {
                "company_name": c.company_name,
                "filing_type": c.filing_type,
                "filing_date": c.filing_date,
                "source_text": c.source_text,
                "relevance_score": c.relevance_score,
            }
            for c in result.citations
        ],
        "route": result.route,
        "confidence": result.confidence,
    }
    if result.extras:
        response["extras"] = result.extras
    return response


@app.post("/ask", response_model=UnifiedResponse)
async def unified_ask(payload: UnifiedRequest, request: Request, user: dict = Depends(get_current_user)):
    """Smart unified endpoint — auto-detects whether to use SQL or RAG."""
    rag_result = request.app.state.rag_pipeline.query(
        payload.question, payload.filters
    )

    response = UnifiedResponse(
        answer=rag_result.answer,
        route=rag_result.route,
        confidence=rag_result.confidence,
        citations=[
            {
                "company_name": c.company_name,
                "filing_type": c.filing_type,
                "filing_date": c.filing_date,
                "source_text": c.source_text,
                "relevance_score": c.relevance_score,
            }
            for c in rag_result.citations
        ],
        extras=rag_result.extras or {},
    )

    # If routed to xbrl_financial, also include raw SQL table data
    if rag_result.route == "xbrl_financial" and rag_result.extras:
        response.sql_query = rag_result.extras.get("sql_query", "")
        response.columns = rag_result.extras.get("columns", [])
        rows = rag_result.extras.get("rows", [])
        # Convert dicts to lists for table rendering
        if rows and isinstance(rows[0], dict):
            cols = response.columns or list(rows[0].keys())
            response.columns = cols
            response.rows = [[r.get(c) for c in cols] for r in rows]
        else:
            response.rows = rows

    return response
