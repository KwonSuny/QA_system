"""用户认证与会话管理（基于 SQLite）。

安全设计：
- 密码：PBKDF2-SHA256 + 每用户随机盐，20 万次迭代，单向哈希不可逆。
- 会话：登录后生成 256 位随机 token，持久化到 sessions 表（服务重启不掉线），12 小时过期。
- 角色：admin（可跨用户运维）/ user（仅管理自己的资源）。
- 数据库中绝不存明文密码。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time

from db import Database, SessionToken, User, now_str

SESSION_TTL = 12 * 3600
MIN_PASSWORD_LEN = 6
MIN_USERNAME_LEN = 2
MAX_USERNAME_LEN = 32
ROLES = ("user", "admin")


class AuthError(ValueError):
    """认证/注册相关的业务错误，供上层转换为 400。"""


class AuthManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_default_admin()

    # ------------------------------------------------------------------ #
    # 密码
    # ------------------------------------------------------------------ #
    @staticmethod
    def _hash(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
        ).hex()

    def _ensure_default_admin(self) -> None:
        """保证系统至少存在一个管理员账号。"""
        with self.db.session() as s:
            if s.query(User).filter(User.role == "admin").first() is not None:
                return
            username = (os.getenv("APP_ADMIN_USER") or "admin").strip() or "admin"
            password = os.getenv("APP_ADMIN_PASSWORD") or "admin123"
            if s.query(User).filter(User.username == username).first() is not None:
                return
            salt = secrets.token_hex(16)
            s.add(
                User(
                    username=username,
                    salt=salt,
                    password_hash=self._hash(password, salt),
                    role="admin",
                    created_at=now_str(),
                )
            )
            print(
                f"[auth] 已创建默认管理员账号 '{username}'。"
                "若使用默认密码，请尽快通过环境变量 APP_ADMIN_PASSWORD 修改。"
            )

    # ------------------------------------------------------------------ #
    # 用户管理
    # ------------------------------------------------------------------ #
    def create_user(
        self,
        username: str,
        password: str,
        password_confirm: str | None = None,
        role: str = "user",
    ) -> dict:
        """创建用户。password_confirm 非 None 时校验两次密码一致（注册场景）。"""
        username = (username or "").strip()
        if not username:
            raise AuthError("用户名不能为空")
        if not (MIN_USERNAME_LEN <= len(username) <= MAX_USERNAME_LEN):
            raise AuthError(f"用户名长度需在 {MIN_USERNAME_LEN}-{MAX_USERNAME_LEN} 个字符之间")
        if not password or len(password) < MIN_PASSWORD_LEN:
            raise AuthError(f"密码长度不能少于 {MIN_PASSWORD_LEN} 位")
        if password_confirm is not None and password != password_confirm:
            raise AuthError("两次输入的密码不一致")
        if role not in ROLES:
            role = "user"

        with self.db.session() as s:
            if s.query(User).filter(User.username == username).first() is not None:
                raise AuthError("用户名已存在")
            salt = secrets.token_hex(16)
            user = User(
                username=username,
                salt=salt,
                password_hash=self._hash(password, salt),
                role=role,
                created_at=now_str(),
            )
            s.add(user)
            s.flush()
            return {"id": user.id, "username": user.username, "role": user.role}

    def list_users(self) -> list[dict]:
        with self.db.session() as s:
            return [
                {"id": u.id, "username": u.username, "role": u.role, "created_at": u.created_at}
                for u in s.query(User).order_by(User.id).all()
            ]

    def delete_user(self, user_id: int) -> None:
        with self.db.session() as s:
            user = s.get(User, user_id)
            if user is None:
                raise KeyError("用户不存在")
            if user.role == "admin":
                remaining = (
                    s.query(User)
                    .filter(User.role == "admin", User.id != user_id)
                    .count()
                )
                if remaining == 0:
                    raise AuthError("不能删除唯一的管理员账号")
            s.delete(user)  # 外键级联删除其会话/配置/知识库/对话

    def reset_password(self, user_id: int, new_password: str) -> None:
        if not new_password or len(new_password) < MIN_PASSWORD_LEN:
            raise AuthError(f"密码长度不能少于 {MIN_PASSWORD_LEN} 位")
        with self.db.session() as s:
            user = s.get(User, user_id)
            if user is None:
                raise KeyError("用户不存在")
            salt = secrets.token_hex(16)
            user.salt = salt
            user.password_hash = self._hash(new_password, salt)
            # 重置密码后强制该用户所有会话失效
            s.query(SessionToken).filter(SessionToken.user_id == user_id).delete()

    # ------------------------------------------------------------------ #
    # 认证与会话
    # ------------------------------------------------------------------ #
    def authenticate(self, username: str, password: str) -> str | None:
        with self.db.session() as s:
            user = s.query(User).filter(User.username == (username or "").strip()).first()
            if user is None:
                return None
            if self._hash(password or "", user.salt) != user.password_hash:
                return None
            token = secrets.token_hex(32)
            s.add(
                SessionToken(
                    token=token,
                    user_id=user.id,
                    expires_at=int(time.time()) + SESSION_TTL,
                    created_at=now_str(),
                )
            )
            return token

    def get_user(self, token: str) -> dict | None:
        if not token:
            return None
        with self.db.session() as s:
            sess = s.get(SessionToken, token)
            if sess is None:
                return None
            if sess.expires_at < time.time():
                s.delete(sess)
                return None
            user = s.get(User, sess.user_id)
            if user is None:
                return None
            return {"id": user.id, "username": user.username, "role": user.role}

    def logout(self, token: str) -> None:
        if not token:
            return
        with self.db.session() as s:
            s.query(SessionToken).filter(SessionToken.token == token).delete()
