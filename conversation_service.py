"""会话与消息持久化服务（按用户隔离）。

- conversations：每个用户可创建多个会话，各自绑定一个知识库。
- messages：会话内消息（user / assistant），assistant 消息携带检索引用片段。
- 所有读写强制按 user_id 过滤；越权访问一律视作「不存在」（返回 None / KeyError）。
"""

from __future__ import annotations

import json

from db import Conversation, Database, Message, now_str, uuid_hex

MAX_TITLE_LEN = 40


class ConversationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @staticmethod
    def _conv_dict(row: Conversation) -> dict:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "title": row.title,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _msg_dict(row: Message) -> dict:
        try:
            chunks = json.loads(row.chunks_json or "[]")
        except (json.JSONDecodeError, TypeError):
            chunks = []
        return {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "chunks": chunks if isinstance(chunks, list) else [],
            "created_at": row.created_at,
        }

    def _owned(self, session, user_id: int, conversation_id: str) -> Conversation | None:
        return (
            session.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .first()
        )

    # ------------------------------------------------------------------ #
    # 会话
    # ------------------------------------------------------------------ #
    def list(self, user_id: int) -> list[dict]:
        with self.db.session() as s:
            rows = (
                s.query(Conversation)
                .filter(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
                .all()
            )
            return [self._conv_dict(r) for r in rows]

    def create(self, user_id: int, kb_id: str = "", title: str = "新对话") -> dict:
        title = (title or "新对话").strip()[:MAX_TITLE_LEN] or "新对话"
        row = Conversation(
            id=uuid_hex(),
            user_id=user_id,
            kb_id=kb_id or "",
            title=title,
            created_at=now_str(),
            updated_at=now_str(),
        )
        with self.db.session() as s:
            s.add(row)
        return self._conv_dict(row)

    def get(self, user_id: int, conversation_id: str) -> dict | None:
        with self.db.session() as s:
            row = self._owned(s, user_id, conversation_id)
            if row is None:
                return None
            messages = (
                s.query(Message)
                .filter(Message.conversation_id == conversation_id)
                .order_by(Message.id)
                .all()
            )
            item = self._conv_dict(row)
            item["messages"] = [self._msg_dict(m) for m in messages]
            return item

    def rename(self, user_id: int, conversation_id: str, title: str) -> dict:
        title = (title or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        with self.db.session() as s:
            row = self._owned(s, user_id, conversation_id)
            if row is None:
                raise KeyError("会话不存在")
            row.title = title[:MAX_TITLE_LEN]
            row.updated_at = now_str()
            s.flush()
            return self._conv_dict(row)

    def delete(self, user_id: int, conversation_id: str) -> None:
        with self.db.session() as s:
            row = self._owned(s, user_id, conversation_id)
            if row is None:
                raise KeyError("会话不存在")
            s.delete(row)  # 级联删除消息

    # ------------------------------------------------------------------ #
    # 消息
    # ------------------------------------------------------------------ #
    def add_message(
        self,
        user_id: int,
        conversation_id: str,
        role: str,
        content: str,
        chunks: list | None = None,
    ) -> dict:
        with self.db.session() as s:
            conv = self._owned(s, user_id, conversation_id)
            if conv is None:
                raise KeyError("会话不存在")
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content or "",
                chunks_json=json.dumps(chunks or [], ensure_ascii=False),
                created_at=now_str(),
            )
            s.add(message)
            conv.updated_at = now_str()
            s.flush()
            return self._msg_dict(message)

    def count(self, user_id: int) -> int:
        with self.db.session() as s:
            return s.query(Conversation).filter(Conversation.user_id == user_id).count()
