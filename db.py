"""SQLite 业务数据库层（SQLAlchemy 2.0）。

统一存放结构化业务数据，文件为 kb_store/app.db：
- users            用户与角色
- sessions         登录会话 token（持久化，服务重启不掉线）
- user_secrets     每个用户私有的 API 配置（Key 为 Fernet 密文）
- knowledge_bases  知识库元数据（按 user_id 隔离）
- conversations    对话会话（按 user_id 隔离）
- messages         会话消息（含检索引用片段）

安全约定：
- 数据库内不出现明文：密码为 PBKDF2 哈希（不可逆），API Key 为 Fernet 密文（可逆）。
- 首次启动自动从旧 JSON（users.json / api_config.json / registry.json）迁移，旧文件改名 .bak 保留。

向量数据仍由 ChromaDB 管理，不在本层。
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def uuid_hex() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    salt = Column(String(64), nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False, default="user")  # user | admin
    created_at = Column(String(32), nullable=False, default=now_str)


class SessionToken(Base):
    __tablename__ = "sessions"

    token = Column(String(128), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(Integer, nullable=False)
    created_at = Column(String(32), nullable=False, default=now_str)


class UserSecret(Base):
    __tablename__ = "user_secrets"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, default="")
    base_url = Column(String(500), nullable=False)
    api_key_enc = Column(Text, nullable=False)
    model = Column(String(200), nullable=False)
    created_at = Column(String(32), nullable=False, default=now_str)
    updated_at = Column(String(32), nullable=False, default=now_str)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False, default="")
    chunk_count = Column(Integer, nullable=False, default=0)
    created_at = Column(String(32), nullable=False, default=now_str)
    updated_at = Column(String(32), nullable=False, default=now_str)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kb_id = Column(String(32), nullable=False, default="")
    title = Column(String(120), nullable=False, default="新对话")
    created_at = Column(String(32), nullable=False, default=now_str)
    updated_at = Column(String(32), nullable=False, default=now_str)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String(16), nullable=False)  # user | assistant
    content = Column(Text, nullable=False, default="")
    chunks_json = Column(Text, nullable=False, default="[]")
    created_at = Column(String(32), nullable=False, default=now_str)


class Database:
    """数据库连接与事务管理。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_conn, _record):  # pragma: no cover
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self):
        """事务性会话：正常结束提交，异常回滚。"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _backup(path: Path) -> None:
    """把旧文件改名为 .bak 保留（不删除）。"""
    try:
        target = Path(str(path) + ".bak")
        if target.exists():
            target.unlink()
        path.rename(target)
    except OSError:
        pass


def migrate_legacy_json(db: Database, store_dir: str | Path, cipher) -> None:
    """把旧 JSON 数据一次性迁移到数据库；旧文件改名 .bak。

    幂等：对应目标表非空时跳过迁移，避免重复导入。
    """
    store_dir = Path(store_dir)

    # 1) users.json -> users（保留原 salt/password_hash，密码不变）
    users_file = store_dir / "users.json"
    if users_file.is_file():
        with db.session() as s:
            if s.query(User).count() == 0:
                try:
                    data = json.loads(users_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = {}
                for u in data.get("users", []):
                    username = str(u.get("username", "")).strip()
                    if not username:
                        continue
                    role = "admin" if u.get("role") == "admin" else "user"
                    s.add(
                        User(
                            username=username,
                            salt=str(u.get("salt", "")),
                            password_hash=str(u.get("password_hash", "")),
                            role=role,
                            created_at=str(u.get("created_at") or now_str()),
                        )
                    )
        _backup(users_file)

    # 2) api_config.json -> user_secrets（归属最早的 admin）
    api_file = store_dir / "api_config.json"
    if api_file.is_file():
        with db.session() as s:
            admin = s.query(User).filter(User.role == "admin").order_by(User.id).first()
            if admin and s.query(UserSecret).count() == 0:
                try:
                    data = json.loads(api_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = {}
                for p in data.get("providers", []):
                    raw_key = str(p.get("api_key", ""))
                    s.add(
                        UserSecret(
                            id=str(p.get("id") or uuid_hex()),
                            user_id=admin.id,
                            name=str(p.get("name", "")),
                            base_url=str(p.get("base_url", "")),
                            api_key_enc=cipher.encrypt(raw_key),
                            model=str(p.get("model", "")),
                            created_at=str(p.get("created_at") or now_str()),
                            updated_at=str(p.get("updated_at") or now_str()),
                        )
                    )
        _backup(api_file)

    # 3) registry.json -> knowledge_bases（归属最早的 admin）
    registry_file = store_dir / "registry.json"
    if registry_file.is_file():
        with db.session() as s:
            admin = s.query(User).filter(User.role == "admin").order_by(User.id).first()
            if admin and s.query(KnowledgeBase).count() == 0:
                try:
                    data = json.loads(registry_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = {}
                for kb in data.get("kbs", []):
                    s.add(
                        KnowledgeBase(
                            id=str(kb.get("id") or uuid_hex()),
                            user_id=admin.id,
                            name=str(kb.get("name", "")),
                            description=str(kb.get("description", "")),
                            chunk_count=int(kb.get("chunk_count") or 0),
                            created_at=str(kb.get("created_at") or now_str()),
                            updated_at=str(kb.get("updated_at") or now_str()),
                        )
                    )
        _backup(registry_file)
