"""FastAPI 后端服务：用户认证 + 私有知识库 CRUD + 会话持久化 + SSE 流式问答。

启动：
    python -m uvicorn server:app --host 127.0.0.1 --port 8000

鉴权与隔离：
    - 除 /api/health、/api/login、/api/register 外，所有 /api/* 都需登录态。
    - 知识库、API 配置、会话/消息均为「用户私有」，服务端强制按 user_id 过滤。
    - /api/admin/* 为管理员专属（用户管理、统计）。
    - 默认管理员由环境变量 APP_ADMIN_USER / APP_ADMIN_PASSWORD 指定（默认 admin / admin123）。

数据存储：
    - 结构化数据 -> SQLite（kb_store/app.db，经 SQLAlchemy）
    - 向量       -> ChromaDB（kb_store/chroma/）
    - 知识库原文 -> 文件（kb_store/data/*.txt）
    - 敏感密钥   -> Fernet 密文（主密钥在环境变量或 kb_store/secret.key）
"""

from __future__ import annotations

import json
import hashlib
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api_answerer import APIConfigStore, APIAnswerer
from auth import AuthError, AuthManager
from conversation_service import ConversationService
from crypto import SecretCipher
from db import (
    Conversation,
    Database,
    KnowledgeBase,
    Message,
    User,
    UserSecret,
    migrate_legacy_json,
)
from kb_service import KnowledgeBaseManager
from document_reader import MAX_UPLOAD_BYTES, decode_text, parse_document
from llm_answerer import GenerationConfig, LLMAnswerer, build_messages
from rag_pipeline import EvidencePipeline

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STORE_DIR = BASE_DIR / "kb_store"
DEFAULT_DATA_FILE = BASE_DIR / "data" / "sample.md"

app = FastAPI(title="知识库问答助手", version="3.0")

# 延迟初始化：首次访问时建库/加载，避免 import 时触发大模型加载
_db: Database | None = None
_cipher: SecretCipher | None = None
_auth: AuthManager | None = None
_manager: KnowledgeBaseManager | None = None
_api_store: APIConfigStore | None = None
_convs: ConversationService | None = None
_answerer: LLMAnswerer | None = None
_init_lock = threading.Lock()
_gen_lock = threading.Lock()  # 串行化本地 LLM 推理，避免并发 OOM
_seed_done = threading.Event()


def _init_core() -> None:
    """初始化数据库、加密器、各服务（幂等）。"""
    global _db, _cipher, _auth, _manager, _api_store, _convs
    with _init_lock:
        if _db is not None:
            return
        database = Database(STORE_DIR / "app.db")
        cipher = SecretCipher(STORE_DIR / "secret.key")
        migrate_legacy_json(database, STORE_DIR, cipher)
        _db = database
        _cipher = cipher
        _auth = AuthManager(database)
        _manager = KnowledgeBaseManager(database, STORE_DIR)
        _api_store = APIConfigStore(database, cipher)
        _convs = ConversationService(database)


def get_db() -> Database:
    _init_core()
    assert _db is not None
    return _db


def get_auth() -> AuthManager:
    _init_core()
    assert _auth is not None
    return _auth


def get_manager() -> KnowledgeBaseManager:
    _init_core()
    assert _manager is not None
    return _manager


def get_api_store() -> APIConfigStore:
    _init_core()
    assert _api_store is not None
    return _api_store


def get_conversations() -> ConversationService:
    _init_core()
    assert _convs is not None
    return _convs


def get_answerer() -> LLMAnswerer:
    """本地模型懒加载（构造开销大，首次使用时才初始化）。"""
    global _answerer
    with _init_lock:
        if _answerer is None:
            _answerer = LLMAnswerer()
    return _answerer


def _seed_default_kb() -> None:
    """后台播种：若管理员尚无知识库且存在示例资料，则建一个默认知识库。"""
    try:
        _init_core()
        database = get_db()
        if not DEFAULT_DATA_FILE.is_file():
            return
        with database.session() as s:
            admin = s.query(User).filter(User.role == "admin").order_by(User.id).first()
            if admin is None:
                return
            admin_id = admin.id
        manager = get_manager()
        if manager.list(admin_id):
            return
        text = manager._read_text(DEFAULT_DATA_FILE)
        manager.create(admin_id, "虚构研究所示例", "由 data/sample.md 自动导入，仅供演示", text)
    except Exception as exc:  # pragma: no cover
        print(f"[seed] 默认知识库初始化失败: {exc}")
    finally:
        _seed_done.set()


@app.on_event("startup")
def _on_startup() -> None:
    threading.Thread(target=_seed_default_kb, daemon=True).start()


# --------------------------------------------------------------------- #
# 鉴权依赖
# --------------------------------------------------------------------- #
def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    user = get_auth().get_user(authorization[7:].strip())
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="当前账号无此操作权限")
    return user


# --------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    password_confirm: str = Field(..., min_length=1, max_length=128)


class KBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    text: str = ""


class KBUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    text: str | None = None


class KBMerge(BaseModel):
    kb_ids: list[str] = Field(..., min_length=2)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    delete_sources: bool = False


class ChatRequest(BaseModel):
    kb_id: str
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = []
    top_k: int = 4
    temperature: float = 0.2
    max_new_tokens: int = 512
    provider: str = "local"  # "local" 本地模型 | "api" 云端 API
    provider_id: str | None = None  # provider=api 时指定使用哪个配置
    conversation_id: str | None = None
    pipeline: str = Field(default="controlled", pattern="^(controlled|legacy)$")


class ConversationCreate(BaseModel):
    kb_id: str = ""
    title: str = "新对话"


class ConversationRename(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


class APIProviderCreate(BaseModel):
    name: str = Field(default="", max_length=100)
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str = Field(..., min_length=1, max_length=500)
    model: str = Field(..., min_length=1, max_length=200)


class APIProviderUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)


class AdminCreateUser(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = "user"


class AdminResetPassword(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _decode_text(raw: bytes) -> str:
    return decode_text(raw)


# --------------------------------------------------------------------- #
# 认证接口
# --------------------------------------------------------------------- #
@app.post("/api/register")
def register(req: RegisterRequest):
    try:
        user = get_auth().create_user(
            req.username, req.password, req.password_confirm, role="user"
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = get_auth().authenticate(req.username, req.password)
    return {"token": token, "user": user}


@app.post("/api/login")
def login(req: LoginRequest):
    token = get_auth().authenticate(req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user = get_auth().get_user(token)
    return {"token": token, "user": user}


@app.post("/api/logout")
def logout(authorization: str | None = Header(default=None), user: dict = Depends(get_current_user)):
    if authorization and authorization.startswith("Bearer "):
        get_auth().logout(authorization[7:].strip())
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(get_current_user)):
    return {"user": user}


# --------------------------------------------------------------------- #
# 健康检查 / 统计
# --------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"status": "ok", "seeded": _seed_done.is_set()}


@app.get("/api/stats")
def stats(user: dict = Depends(get_current_user)):
    return {"stats": get_manager().stats(user["id"])}


# --------------------------------------------------------------------- #
# 知识库 CRUD（用户私有）
# --------------------------------------------------------------------- #
@app.get("/api/kbs")
def list_kbs(user: dict = Depends(get_current_user)):
    return {"kbs": get_manager().list(user["id"])}


@app.post("/api/kbs")
def create_kb(req: KBCreate, user: dict = Depends(get_current_user)):
    try:
        kb = get_manager().create(user["id"], req.name, req.description, req.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"kb": kb}


@app.post("/api/kbs/merge")
def merge_kbs(req: KBMerge, user: dict = Depends(get_current_user)):
    try:
        result = get_manager().merge(
            user["id"], req.kb_ids, req.name, req.description, req.delete_sources
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@app.post("/api/kbs/upload")
def upload_kb(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    description: str = Form(default=""),
    kb_id: str = Form(default=""),
    user: dict = Depends(get_current_user),
):
    """解析上传文件后创建或替换知识库；解析失败时不修改原库。"""
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    display_name = (name or "").strip() or (file.filename or "未命名知识库")
    try:
        parsed = parse_document(file.filename or "", raw)
        text = parsed.text
        if kb_id:
            kb = get_manager().update(
                user["id"],
                kb_id,
                name=(name.strip() if name.strip() else None),
                description=(description.strip() if description else None),
                text=text,
            )
        else:
            kb = get_manager().create(user["id"], display_name, description, text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"kb": kb, "filename": file.filename, "size": len(raw), "warnings": parsed.warnings}


@app.get("/api/kbs/{kb_id}")
def get_kb(kb_id: str, with_text: bool = False, user: dict = Depends(get_current_user)):
    kb = get_manager().get(user["id"], kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    has_text = bool(kb.get("text"))
    if not with_text:
        kb.pop("text", None)
    kb["has_text"] = has_text
    return {"kb": kb}


@app.put("/api/kbs/{kb_id}")
def update_kb(kb_id: str, req: KBUpdate, user: dict = Depends(get_current_user)):
    try:
        kb = get_manager().update(user["id"], kb_id, req.name, req.description, req.text)
    except KeyError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"kb": kb}


@app.delete("/api/kbs/{kb_id}")
def delete_kb(kb_id: str, user: dict = Depends(get_current_user)):
    try:
        get_manager().delete(user["id"], kb_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"ok": True}


# --------------------------------------------------------------------- #
# 会话（用户私有）
# --------------------------------------------------------------------- #
@app.get("/api/conversations")
def list_conversations(user: dict = Depends(get_current_user)):
    return {"conversations": get_conversations().list(user["id"])}


@app.post("/api/conversations")
def create_conversation(req: ConversationCreate, user: dict = Depends(get_current_user)):
    conv = get_conversations().create(user["id"], req.kb_id, req.title)
    return {"conversation": conv}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    conv = get_conversations().get(user["id"], conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"conversation": conv}


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str, req: ConversationRename, user: dict = Depends(get_current_user)
):
    try:
        conv = get_conversations().rename(user["id"], conversation_id, req.title)
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"conversation": conv}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    try:
        get_conversations().delete(user["id"], conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


# --------------------------------------------------------------------- #
# 聊天（SSE 流式 + 落库）
# --------------------------------------------------------------------- #
@app.post("/api/chat")
def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    manager = get_manager()
    if manager.get(user["id"], req.kb_id) is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    chunks = manager.query(user["id"], req.kb_id, req.question, top_k=req.top_k) if req.pipeline == "legacy" else []

    # 解析生成后端
    if req.provider == "api":
        provider = get_api_store().get(user["id"], req.provider_id or "")
        if provider is None:
            raise HTTPException(status_code=400, detail="请选择有效的 API 配置")
    else:
        provider = None  # 本地模型

    chunks_payload = [
        {"text": c.text, "score": c.score, "chunk_index": c.chunk_index} for c in chunks
    ]

    # 会话：未指定则新建，标题取问题前 30 字
    conv_service = get_conversations()
    conversation_id = req.conversation_id
    if not conversation_id:
        conversation_id = conv_service.create(
            user["id"], req.kb_id, title=(req.question[:30] or "新对话")
        )["id"]

    try:
        conv_service.add_message(user["id"], conversation_id, "user", req.question)
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")

    def generate():
        yield _sse(
            {
                "type": "meta",
                "conversation_id": conversation_id,
                "chunks": chunks_payload,
                "provider": req.provider,
            }
        )
        collected: list[str] = []
        try:
            if req.pipeline == "controlled":
                yield _sse({"type": "status", "message": "正在明确问题、检索并核验证据…"})
                catalog = manager.document_catalog(user["id"], req.kb_id)
                def search(document, question, top_k):
                    return manager.query_evidence(user["id"], document["kb_id"], document["document_id"], question, top_k)
                if provider is None:
                    with _gen_lock:
                        result = EvidencePipeline(get_answerer().complete_messages, search, req.top_k).run(
                            req.question, req.history, catalog)
                else:
                    api = APIAnswerer(provider, max_retries=0)
                    try:
                        result = EvidencePipeline(api.complete_messages, search, req.top_k).run(req.question, req.history, catalog)
                        result["trace"]["api_calls"] = api.call_log
                    finally:
                        api.close()
                cited = set(result["citations"])
                chunks_payload[:] = [{k: e[k] for k in ("text", "score", "chunk_index", "source_title", "kb_id")}
                    | {"evidence_id": e["id"], "document_id": e["document_id"],
                       "section_context": e.get("section_context", []), "dense_score": e.get("dense_score")}
                    for e in result["evidence"] if e["id"] in cited]
                trace_dir = STORE_DIR / "rag_traces" / str(user["id"])
                trace_dir.mkdir(parents=True, exist_ok=True)
                trace_id = hashlib.sha256((conversation_id + req.question + json.dumps(result["trace"], ensure_ascii=False)).encode("utf-8")).hexdigest()
                trace_path = trace_dir / f"{trace_id}.json"
                trace_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                yield _sse({"type": "meta", "conversation_id": conversation_id, "chunks": chunks_payload,
                    "provider": req.provider, "pipeline": req.pipeline, "answer_status": result["status"],
                    "model_calls": result["trace"]["model_calls"]})
                # 草稿核验前不输出；引用和正文从同一份已核验结果构造。
                collected.append(result["answer"])
                yield _sse({"type": "token", "content": result["answer"]})
            elif provider is None:
                answerer = get_answerer()
                config = GenerationConfig(
                    max_new_tokens=req.max_new_tokens,
                    temperature=req.temperature,
                )
                with _gen_lock:
                    for token in answerer.stream_answer(
                        req.question, chunks, req.history, config
                    ):
                        collected.append(token)
                        yield _sse({"type": "token", "content": token})
            else:
                api = APIAnswerer(provider)
                messages = build_messages(req.question, chunks, req.history)
                for token in api.stream_answer(
                    messages,
                    max_new_tokens=req.max_new_tokens,
                    temperature=req.temperature,
                ):
                    collected.append(token)
                    yield _sse({"type": "token", "content": token})
        except ValueError as exc:
            public_errors = {
                "原文与索引版本不一致，请重新保存知识库以重建索引",
                "旧索引无法与当前来源对应，请重新保存或融合原始知识库",
                "来源文档边界格式不合法",
            }
            message = str(exc) if str(exc) in public_errors else "问答数据校验失败，请检查知识库或模型配置。"
            yield _sse({"type": "error", "message": message})
        except Exception:  # pragma: no cover
            yield _sse({"type": "error", "message": "问答阶段调用失败，请检查模型服务或配置。"})
        finally:
            answer = "".join(collected)
            if answer:
                try:
                    conv_service.add_message(
                        user["id"], conversation_id, "assistant", answer, chunks_payload
                    )
                except Exception:  # pragma: no cover
                    pass
        yield _sse({"type": "done"})

    return StreamingResponse(generate(), media_type="text/event-stream")


# --------------------------------------------------------------------- #
# API 配置管理（用户私有）
# --------------------------------------------------------------------- #
@app.get("/api/llm/providers")
def list_providers(user: dict = Depends(get_current_user)):
    """返回当前用户脱敏后的 API 配置列表（不含完整 key）。"""
    return {"providers": get_api_store().list_public(user["id"])}


@app.post("/api/llm/providers")
def create_provider(req: APIProviderCreate, user: dict = Depends(get_current_user)):
    try:
        provider = get_api_store().create(
            user["id"], req.name, req.base_url, req.api_key, req.model
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"provider": provider.to_public_dict()}


@app.put("/api/llm/providers/{provider_id}")
def update_provider(provider_id: str, req: APIProviderUpdate, user: dict = Depends(get_current_user)):
    try:
        provider = get_api_store().update(
            user["id"],
            provider_id,
            name=req.name,
            base_url=req.base_url,
            api_key=req.api_key,
            model=req.model,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="API 配置不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"provider": provider.to_public_dict()}


@app.delete("/api/llm/providers/{provider_id}")
def delete_provider(provider_id: str, user: dict = Depends(get_current_user)):
    try:
        get_api_store().delete(user["id"], provider_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="API 配置不存在")
    return {"ok": True}


# --------------------------------------------------------------------- #
# 管理员接口（跨用户运维）
# --------------------------------------------------------------------- #
@app.get("/api/admin/users")
def admin_list_users(user: dict = Depends(require_admin)):
    return {"users": get_auth().list_users()}


@app.post("/api/admin/users")
def admin_create_user(req: AdminCreateUser, user: dict = Depends(require_admin)):
    try:
        created = get_auth().create_user(req.username, req.password, role=req.role)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"user": created}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    # 先逐个清理该用户知识库的向量数据，避免 DB 级联删除后残留孤儿向量
    try:
        manager = get_manager()
        for kb in manager.list(user_id):
            try:
                manager.delete(user_id, kb["id"])
            except KeyError:
                pass
    except Exception as exc:  # pragma: no cover
        print(f"[admin] 清理用户 {user_id} 的向量失败: {exc}")
    try:
        get_auth().delete_user(user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, req: AdminResetPassword, user: dict = Depends(require_admin)):
    try:
        get_auth().reset_password(user_id, req.password)
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.get("/api/admin/stats")
def admin_stats(user: dict = Depends(require_admin)):
    database = get_db()
    with database.session() as s:
        return {
            "stats": {
                "users": s.query(User).count(),
                "admins": s.query(User).filter(User.role == "admin").count(),
                "knowledge_bases": s.query(KnowledgeBase).count(),
                "conversations": s.query(Conversation).count(),
                "messages": s.query(Message).count(),
                "api_configs": s.query(UserSecret).count(),
            }
        }


# --------------------------------------------------------------------- #
# 静态前端
# --------------------------------------------------------------------- #
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
