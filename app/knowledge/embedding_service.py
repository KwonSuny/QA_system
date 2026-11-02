"""用户私有的在线嵌入配置及 OpenAI 兼容适配器。"""

from __future__ import annotations

import hashlib
import json
import math

import httpx
from openai import OpenAI

from app.llm.api_answerer import mask_key, validate_embedding_endpoint, _validate_model
from app.core.db import EmbeddingProfile, KnowledgeBase, KnowledgeIndex, uuid_hex


class EmbeddingStore:
    def __init__(self, db, cipher):
        self.db, self.cipher = db, cipher

    def _view(self, row, private=False):
        data = {key: getattr(row, key) for key in ("id", "name", "base_url", "model", "dimensions", "batch_size")}
        key = self.cipher.decrypt(row.api_key_enc)
        data["api_key" if private else "api_key_masked"] = key if private else mask_key(key)
        return data

    def list(self, user_id):
        with self.db.session() as session:
            return [self._view(r) for r in session.query(EmbeddingProfile).filter_by(user_id=user_id).all()]

    def get(self, user_id, profile_id):
        with self.db.session() as session:
            row = session.query(EmbeddingProfile).filter_by(id=profile_id, user_id=user_id).first()
            if row is None:
                raise ValueError("嵌入配置不存在或无权访问")
            return self._view(row, private=True)

    def create(self, user_id, name, base_url, api_key, model, dimensions=None, batch_size=10):
        base_url = validate_embedding_endpoint(base_url)
        model = _validate_model(model)
        if not api_key.strip() or (dimensions is not None and not 1 <= dimensions <= 8192) or not 1 <= batch_size <= 128:
            raise ValueError("请填写密钥，维度需为1至8192，批量大小需为1至128")
        row = EmbeddingProfile(id=uuid_hex(), user_id=user_id, name=name.strip() or model,
                               base_url=base_url, api_key_enc=self.cipher.encrypt(api_key.strip()), model=model,
                               dimensions=dimensions, batch_size=batch_size)
        with self.db.session() as session:
            session.add(row)
            session.flush()
            return self._view(row)

    def rotate_key(self, user_id, profile_id, api_key):
        if not api_key.strip():
            raise ValueError("密钥不能为空")
        with self.db.session() as session:
            row = session.query(EmbeddingProfile).filter_by(id=profile_id, user_id=user_id).first()
            if row is None:
                raise KeyError("嵌入配置不存在")
            row.api_key_enc = self.cipher.encrypt(api_key.strip())

    def delete(self, user_id, profile_id):
        with self.db.session() as session:
            row = session.query(EmbeddingProfile).filter_by(id=profile_id, user_id=user_id).first()
            if row is None:
                raise KeyError("嵌入配置不存在")
            used = session.query(KnowledgeIndex).join(KnowledgeBase).filter(
                KnowledgeBase.user_id == user_id, KnowledgeIndex.profile_id == profile_id).first()
            if used:
                raise ValueError("配置仍被当前或保留的历史索引使用，请保留以便恢复")
            session.delete(row)


def embedding_fingerprint(config):
    public = {k: config.get(k) for k in ("provider", "base_url", "model", "dimensions", "pooling")}
    return hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class RemoteEmbeddingModel:
    def __init__(self, config):
        self.config = config

    def encode(self, values):
        texts = [values] if isinstance(values, str) else list(values)
        if not texts:
            return []
        if any(not isinstance(t, str) or not t.strip() or len(t) > 32000 for t in texts):
            raise ValueError("嵌入输入必须为非空文本，单项不能超过32000字符")
        url = validate_embedding_endpoint(self.config["base_url"], resolve=True)
        vectors, dimension = [], self.config.get("dimensions")
        # 不透传代理环境变量，不跟随跳转，避免密钥或正文被转发到其他地址。
        with OpenAI(api_key=self.config["api_key"], base_url=url, timeout=30, max_retries=0,
                    http_client=httpx.Client(follow_redirects=False, trust_env=False, timeout=30)) as client:
            for start in range(0, len(texts), self.config["batch_size"]):
                batch = texts[start:start + self.config["batch_size"]]
                options = {"dimensions": dimension} if self.config.get("dimensions") is not None else {}
                try:
                    result = client.embeddings.create(model=self.config["model"], input=batch,
                                                      encoding_format="float", **options)
                    rows = sorted(result.data, key=lambda row: row.index)
                    if [row.index for row in rows] != list(range(len(batch))):
                        raise ValueError("嵌入结果数量或索引不匹配")
                    for row in rows:
                        vector = list(row.embedding)
                        dimension = dimension or len(vector)
                        if (not vector or len(vector) != dimension
                                or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)
                                or not any(vector)):
                            raise ValueError("嵌入向量维度或数值异常")
                        vectors.append(vector)
                except Exception:
                    raise ValueError("在线嵌入调用失败或响应不合法，请检查配置、配额及输入限制") from None
        return vectors
