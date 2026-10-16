"""云端大模型（OpenAI 兼容接口）流式生成 + 用户私有 API 配置管理。

安全设计：
- API Key 使用 Fernet 对称加密后存入 user_secrets 表，数据库中不出现明文。
- 所有配置操作强制按 user_id 过滤，用户之间互不可见（管理员亦不可见他人 Key）。
- 返回前端一律为脱敏视图（只保留首尾少量字符）。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from openai import OpenAI

from crypto import SecretCipher
from db import Database, UserSecret, now_str, uuid_hex


def mask_key(key: str) -> str:
    """把 API key 脱敏，仅保留首尾少量字符。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return key[:2] + "****"
    return key[:6] + "****" + key[-4:]


def _validate_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("base_url 不能为空")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url 必须为 http/https 协议")
    if not parsed.netloc:
        raise ValueError("base_url 格式不正确")
    return url.rstrip("/")


def _validate_model(model: str) -> str:
    model = (model or "").strip()
    if not model:
        raise ValueError("模型名不能为空")
    if len(model) > 200:
        raise ValueError("模型名过长")
    if any(ch in model for ch in "\r\n\t"):
        raise ValueError("模型名包含非法字符")
    return model


# ---------------------------------------------------------------------- #
# 数据模型
# ---------------------------------------------------------------------- #
@dataclass
class APIProvider:
    id: str
    name: str
    base_url: str
    api_key: str  # 明文，仅内存中使用，绝不返回前端
    model: str
    created_at: str = ""
    updated_at: str = ""

    def to_public_dict(self) -> dict:
        """返回给前端的脱敏视图，绝不包含完整 key。"""
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_masked": mask_key(self.api_key),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------- #
# 用户私有配置存储
# ---------------------------------------------------------------------- #
class APIConfigStore:
    """基于数据库的 API 配置持久化，全部按 user_id 隔离。"""

    def __init__(self, db: Database, cipher: SecretCipher) -> None:
        self.db = db
        self.cipher = cipher

    @staticmethod
    def _row_id(row: UserSecret) -> str:
        return row.id

    def _to_provider(self, row: UserSecret) -> APIProvider:
        return APIProvider(
            id=row.id,
            name=row.name,
            base_url=row.base_url,
            api_key=self.cipher.decrypt(row.api_key_enc),
            model=row.model,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _to_public(self, row: UserSecret) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "base_url": row.base_url,
            "model": row.model,
            "api_key_masked": mask_key(self.cipher.decrypt(row.api_key_enc)),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def list_public(self, user_id: int) -> list[dict]:
        with self.db.session() as s:
            rows = (
                s.query(UserSecret)
                .filter(UserSecret.user_id == user_id)
                .order_by(UserSecret.created_at)
                .all()
            )
            return [self._to_public(r) for r in rows]

    def get(self, user_id: int, provider_id: str) -> APIProvider | None:
        if not provider_id:
            return None
        with self.db.session() as s:
            row = (
                s.query(UserSecret)
                .filter(UserSecret.id == provider_id, UserSecret.user_id == user_id)
                .first()
            )
            return self._to_provider(row) if row else None

    def create(self, user_id: int, name: str, base_url: str, api_key: str, model: str) -> APIProvider:
        name = (name or "").strip() or "未命名"
        base_url = _validate_base_url(base_url)
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("API Key 不能为空")
        model = _validate_model(model)
        now = now_str()
        row = UserSecret(
            id=uuid_hex(),
            user_id=user_id,
            name=name,
            base_url=base_url,
            api_key_enc=self.cipher.encrypt(api_key),
            model=model,
            created_at=now,
            updated_at=now,
        )
        with self.db.session() as s:
            s.add(row)
        return self._to_provider(row)

    def update(
        self,
        user_id: int,
        provider_id: str,
        name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> APIProvider:
        with self.db.session() as s:
            row = (
                s.query(UserSecret)
                .filter(UserSecret.id == provider_id, UserSecret.user_id == user_id)
                .first()
            )
            if row is None:
                raise KeyError("API 配置不存在")
            if name is not None and name.strip():
                row.name = name.strip()
            if base_url is not None:
                row.base_url = _validate_base_url(base_url)
            if api_key is not None:
                candidate = (api_key or "").strip()
                # 前端未修改时可能传空或脱敏值（含 ****），此时保留原 key
                if candidate and "****" not in candidate:
                    row.api_key_enc = self.cipher.encrypt(candidate)
            if model is not None:
                row.model = _validate_model(model)
            row.updated_at = now_str()
            s.flush()
            return self._to_provider(row)

    def delete(self, user_id: int, provider_id: str) -> None:
        with self.db.session() as s:
            deleted = (
                s.query(UserSecret)
                .filter(UserSecret.id == provider_id, UserSecret.user_id == user_id)
                .delete()
            )
            if not deleted:
                raise KeyError("API 配置不存在")


# ---------------------------------------------------------------------- #
# 生成器
# ---------------------------------------------------------------------- #
class APIAnswerer:
    def __init__(self, provider: APIProvider, timeout: float = 120.0, max_retries: int = 1) -> None:
        self.provider = provider
        self.call_log: list[dict] = []
        self._client = OpenAI(
            api_key=provider.api_key,
            base_url=provider.base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def stream_answer(self, messages: list[dict], max_new_tokens: int = 512, temperature: float = 0.2):
        response = self._client.chat.completions.create(
            model=self.provider.model,
            messages=messages,
            stream=True,
            temperature=temperature,
            max_tokens=max_new_tokens,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    def complete_messages(self, messages: list[dict], max_new_tokens: int = 1536) -> str:
        options = {"extra_body": {"enable_thinking": False}} if self.provider.model.startswith("qwen3.8") else {}
        log = {"requested_model":self.provider.model,"model":None,"finish_reason":None,"usage":None,"status":"pending"}
        self.call_log.append(log)
        try:
            response = self._client.chat.completions.create(model=self.provider.model, messages=messages,
                temperature=0.0, max_tokens=max_new_tokens, stream=False, **options)
            log.update({"model":response.model,"finish_reason":response.choices[0].finish_reason if response.choices else None,
                        "usage":response.usage.model_dump(exclude_none=True) if response.usage else None,"status":"completed"})
            if not response.choices or response.choices[0].finish_reason == "length":
                raise RuntimeError("结构化回答为空或被截断")
            return response.choices[0].message.content or ""
        except Exception as exc:
            log.update({"status":"failed","error_type":type(exc).__name__})
            # 不向前端传播可能含端点、请求正文或凭据的供应商异常。
            raise RuntimeError(f"API阶段调用失败（{type(exc).__name__}）") from None

    def close(self) -> None:
        self._client.close()
