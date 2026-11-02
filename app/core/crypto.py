"""对称加密工具：用于加密存储 API Key 等敏感配置。

主密钥来源（按优先级）：
1. 环境变量 APP_SECRET_KEY（任意字符串，会被派生为合法 Fernet 密钥）
2. 本地文件 kb_store/secret.key（首次运行自动生成）

设计要点：
- 采用 Fernet（AES-128-CBC 加密 + HMAC-SHA256 完整性认证），可逆，用于需要还原的密钥。
- 与用户密码的 PBKDF2 单向哈希严格区分：后者不可逆，仅用于校验。
- 主密钥绝不写入数据库、绝不提交到 Git（kb_store/ 已被 .gitignore 忽略）。
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def _normalize_key(raw: bytes) -> bytes:
    """把任意字节串规范化为合法的 Fernet 密钥（44 字符 urlsafe-base64）。"""
    candidate = (raw or b"").strip()
    if candidate:
        try:
            Fernet(candidate)  # 已是合法密钥则直接使用
            return candidate
        except (ValueError, TypeError):
            pass
    digest = hashlib.sha256(candidate or b"kb-qa-default-key").digest()
    return base64.urlsafe_b64encode(digest)


class SecretCipher:
    """基于 Fernet 的对称加解密器。"""

    def __init__(self, key_path: str | Path) -> None:
        self.key_path = Path(key_path)
        self._fernet = Fernet(self._resolve_key())

    def _resolve_key(self) -> bytes:
        env_key = os.getenv("APP_SECRET_KEY")
        if env_key:
            return _normalize_key(env_key.encode("utf-8"))
        if self.key_path.is_file():
            return _normalize_key(self.key_path.read_bytes())
        key = Fernet.generate_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def encrypt(self, plain: str | None) -> str:
        return self._fernet.encrypt((plain or "").encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str | None) -> str:
        if not token:
            return ""
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            return ""
