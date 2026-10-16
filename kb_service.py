"""多知识库管理服务层（按用户隔离）。

职责：知识库的创建、修改、删除、检索、融合，以及向量化与持久化。

- 元数据入库：知识库的名称/简介/片段数存 SQLite 的 knowledge_bases 表，按 ``user_id`` 隔离；
  向量存 ChromaDB（单 collection + ``kb_id`` 过滤），原文存 ``data/{kb_id}.txt``。
- 越权防护：所有读写方法都要求 user_id，先校验归属再操作；查不到一律当作不存在。
- 原子性：更新/创建时先完成「切分 + 向量化」，成功后才落库与写文件，
  向量化失败不会破坏已有数据。
- 确定性 chunk id：``kb_id + 索引 + 内容哈希``，配合 upsert 避免重复入库导致的堆积。
- 编码兼容：读取文本时优先 UTF-8，失败回退 GBK，兼容中文 Windows 常见文件。
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import chromadb

from db import Database, KnowledgeBase
from local_model import resolve_embedding_model_path
from local_rag_engine import LocalEmbeddingModel, _pick_device
from rag_pipeline import document_fingerprint, heading_contexts, hybrid_order, merge_documents, normalize, source_documents

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover
    RecursiveCharacterTextSplitter = None


COLLECTION_PREFIX = "kb_chunks"


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    score: float
    kb_id: str
    chunk_index: int
    source_title: str = ""
    document_id: str = "D1"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_collection_name(embedding_model_name: str) -> str:
    digest = hashlib.sha1(embedding_model_name.encode("utf-8")).hexdigest()[:8]
    return f"{COLLECTION_PREFIX}_{digest}"


class KnowledgeBaseManager:
    def __init__(
        self,
        db: Database,
        store_dir: str | Path,
        embedding_model_name: str | None = None,
        device: str | None = None,
        chunk_size: int = 260,
        chunk_overlap: int = 60,
    ) -> None:
        self.db = db
        self.store_dir = Path(store_dir)
        self.data_dir = self.store_dir / "data"
        self.chroma_dir = self.store_dir / "chroma"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)

        self.embedding_model_name = embedding_model_name or resolve_embedding_model_path()
        self.device = device or _pick_device()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.collection_name = _safe_collection_name(self.embedding_model_name)
        self.db_client = chromadb.PersistentClient(path=str(self.chroma_dir))
        self.collection = self.db_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedding_model: LocalEmbeddingModel | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _embedder(self) -> LocalEmbeddingModel:
        if self._embedding_model is None:
            with self._lock:
                if self._embedding_model is None:
                    self._embedding_model = LocalEmbeddingModel(self.embedding_model_name, device=self.device)
        return self._embedding_model

    def _read_text(self, path: Path) -> str:
        raw = path.read_bytes()
        for encoding in ("utf-8", "gbk", "utf-16"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def _split_text(self, text: str) -> list[str]:
        if RecursiveCharacterTextSplitter is not None:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=["\n\n", "\n", "。", "！", "？", "；", "，", " "],
            )
            return [c.strip() for c in splitter.split_text(text) if c.strip()]
        chunks: list[str] = []
        current = ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(current) + len(line) <= self.chunk_size:
                current = f"{current}\n{line}".strip()
            else:
                if current:
                    chunks.append(current)
                current = line
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _chunk_id(kb_id: str, index: int, chunk: str) -> str:
        digest = hashlib.sha1(f"{kb_id}:{index}:{chunk}".encode("utf-8")).hexdigest()
        return f"{kb_id}_{digest[:20]}"

    def _ingest(self, kb_id: str, text: str, user_id: int, title: str = "") -> int:
        chunks, origins = [], []
        for document in source_documents(text, title or kb_id):
            document_chunks = self._split_text(document["text"])
            fingerprint = document_fingerprint(document["text"])
            for chunk, sections in zip(document_chunks, heading_contexts(document["text"], document_chunks)):
                chunks.append(chunk)
                origins.append({**document, "document_sha256": fingerprint, "section_context": sections})
        if not chunks:
            self.collection.delete(where={"kb_id": kb_id})
            return 0

        embeddings = self._embedder().encode(chunks)
        ids = [self._chunk_id(kb_id, i, c) for i, c in enumerate(chunks)]
        metadatas = [
            {"kb_id": kb_id, "user_id": user_id, "chunk": i,
             "document_id": origins[i]["document_id"], "source_title": origins[i]["title"],
             "document_sha256": origins[i]["document_sha256"],
             "section_context": json.dumps(origins[i]["section_context"], ensure_ascii=False)}
            for i in range(len(chunks))
        ]

        self.collection.delete(where={"kb_id": kb_id})
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )
        return len(chunks)

    def _kb_file(self, kb_id: str) -> Path:
        return self.data_dir / f"{kb_id}.txt"

    @staticmethod
    def _row_to_dict(row: KnowledgeBase) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "chunk_count": row.chunk_count,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "owner_id": row.user_id,
        }

    def _owned_row(self, session, user_id: int, kb_id: str) -> KnowledgeBase | None:
        return (
            session.query(KnowledgeBase)
            .filter(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user_id)
            .first()
        )

    # ------------------------------------------------------------------ #
    # 对外 API（全部按 user_id 隔离）
    # ------------------------------------------------------------------ #
    def list(self, user_id: int) -> list[dict]:
        with self.db.session() as s:
            rows = (
                s.query(KnowledgeBase)
                .filter(KnowledgeBase.user_id == user_id)
                .order_by(KnowledgeBase.updated_at.desc())
                .all()
            )
            return [self._row_to_dict(r) for r in rows]

    def get(self, user_id: int, kb_id: str) -> dict | None:
        with self.db.session() as s:
            row = self._owned_row(s, user_id, kb_id)
            if row is None:
                return None
            item = self._row_to_dict(row)
        path = self._kb_file(kb_id)
        item["text"] = self._read_text(path) if path.is_file() else ""
        return item

    def create(self, user_id: int, name: str, description: str = "", text: str = "") -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("知识库名称不能为空")
        kb_id = uuid.uuid4().hex
        # 重活（切分 + 向量化）在数据库事务之外完成，避免长时间持锁
        chunk_count = self._ingest(kb_id, text, user_id, name)
        self._kb_file(kb_id).write_text(text, encoding="utf-8")
        now = _now()
        row = KnowledgeBase(
            id=kb_id,
            user_id=user_id,
            name=name,
            description=(description or "").strip(),
            chunk_count=chunk_count,
            created_at=now,
            updated_at=now,
        )
        with self.db.session() as s:
            s.add(row)
        return self._row_to_dict(row)

    def update(
        self,
        user_id: int,
        kb_id: str,
        name: str | None = None,
        description: str | None = None,
        text: str | None = None,
    ) -> dict:
        # 1) 先校验归属（短事务）
        with self.db.session() as s:
            owned = self._owned_row(s, user_id, kb_id)
            if owned is None:
                raise KeyError(f"知识库不存在: {kb_id}")
            old_name = owned.name
        # 2) 事务外完成向量化与文件写入
        chunk_count = None
        if text is not None:
            chunk_count = self._ingest(kb_id, text, user_id, name or old_name)
            self._kb_file(kb_id).write_text(text, encoding="utf-8")
        # 3) 更新元数据（短事务）
        with self.db.session() as s:
            row = self._owned_row(s, user_id, kb_id)
            if row is None:
                raise KeyError(f"知识库不存在: {kb_id}")
            if name is not None and name.strip():
                row.name = name.strip()
            if description is not None:
                row.description = description.strip()
            if chunk_count is not None:
                row.chunk_count = chunk_count
            row.updated_at = _now()
            s.flush()
            return self._row_to_dict(row)

    def delete(self, user_id: int, kb_id: str) -> None:
        with self.db.session() as s:
            row = self._owned_row(s, user_id, kb_id)
            if row is None:
                raise KeyError(f"知识库不存在: {kb_id}")
            s.delete(row)
        self.collection.delete(where={"kb_id": kb_id})
        path = self._kb_file(kb_id)
        if path.is_file():
            path.unlink()

    def merge(
        self,
        user_id: int,
        kb_ids: list[str],
        new_name: str,
        description: str = "",
        delete_sources: bool = False,
    ) -> dict:
        """把多个知识库正文合并为一个新知识库（仅限本人所有）。"""
        ordered = [k for k in dict.fromkeys(kb_ids or []) if k]
        if len(ordered) < 2:
            raise ValueError("至少选择两个知识库进行融合")
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("融合后的知识库名称不能为空")

        with self.db.session() as s:
            rows = (
                s.query(KnowledgeBase)
                .filter(KnowledgeBase.user_id == user_id, KnowledgeBase.id.in_(ordered))
                .all()
            )
            found = {r.id: r.name for r in rows}
            if any(k not in found for k in ordered):
                raise KeyError("包含不存在或无权访问的知识库")

        parts = []
        for kb_id in ordered:
            path = self._kb_file(kb_id)
            text = self._read_text(path) if path.is_file() else ""
            if text.strip():
                parts.extend(source_documents(text, found[kb_id]))
        merged_text = merge_documents(parts)

        new_kb = self.create(user_id, new_name, description, merged_text)

        if delete_sources:
            for kb_id in ordered:
                try:
                    self.delete(user_id, kb_id)
                except KeyError:
                    pass
        return {"kb": new_kb, "merged_from": [found[k] for k in ordered]}

    def query(self, user_id: int, kb_id: str, question: str, top_k: int = 4) -> list[RetrievedChunk]:
        # 归属校验：非本人知识库直接返回空
        with self.db.session() as s:
            if self._owned_row(s, user_id, kb_id) is None:
                return []
        count = self.collection.count()
        if count == 0:
            return []
        n_results = min(max(top_k, 1), count)
        query_embedding = self._embedder().encode(question)[0]
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"kb_id": kb_id},
            include=["documents", "metadatas", "distances"],
        )
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            chunks.append(
                RetrievedChunk(
                    text=document,
                    score=round(1.0 - float(distance), 4),
                    kb_id=str((metadata or {}).get("kb_id", "")),
                    chunk_index=int((metadata or {}).get("chunk", 0)),
                )
            )
        return chunks

    def document_catalog(self, user_id: int, kb_id: str) -> list[dict]:
        kb = self.get(user_id, kb_id)
        if kb is None:
            return []
        return [{"source_id": f"{kb_id}/{d['document_id']}", "kb_id": kb_id,
                 "document_id": d["document_id"], "title": d["title"],
                 "document_sha256": document_fingerprint(d["text"]),
                 "opening": d["text"].strip()[:240]}
                for d in source_documents(kb["text"], kb["name"])]

    def query_evidence(self, user_id: int, kb_id: str, document_id: str,
                       question: str, top_k: int = 4) -> list[dict]:
        catalog = {d["document_id"]: d for d in self.document_catalog(user_id, kb_id)}
        if document_id not in catalog:
            return []
        # 包括旧索引的D1回退；所有候选仍限定于已校验归属的知识库。
        found = self.collection.get(where={"kb_id": kb_id}, include=["documents", "metadatas"])
        rows = []
        for rid, text, metadata in zip(found["ids"], found["documents"], found["metadatas"]):
            metadata = metadata or {}
            if metadata.get("document_id", "D1") != document_id:
                continue
            rows.append({"id": rid, "text": text, "chunk_index": int(metadata.get("chunk", 0)),
                         "kb_id": kb_id, "document_id": document_id,
                         "document_sha256": metadata.get("document_sha256"),
                         "section_context": json.loads(metadata.get("section_context", "[]")),
                         "source_title": catalog[document_id]["title"]})
        if not rows:
            return []
        current_hash = catalog[document_id]["document_sha256"]
        if all(r["document_sha256"] for r in rows):
            if any(r["document_sha256"] != current_hash for r in rows):
                raise ValueError("原文与索引版本不一致，请重新保存知识库以重建索引")
        else:
            kb = self.get(user_id, kb_id)
            document = next(d for d in source_documents(kb["text"], kb["name"])
                            if d["document_id"] == document_id)
            ordered = sorted(rows, key=lambda r: r["chunk_index"])
            expected = self._split_text(document["text"])
            if [normalize(r["text"]) for r in ordered] != [normalize(c) for c in expected]:
                raise ValueError("旧索引无法与当前来源对应，请重新保存或融合原始知识库")
            for row, sections in zip(ordered, heading_contexts(document["text"], expected)):
                row["document_sha256"], row["section_context"] = current_hash, sections
        embedding = self._embedder().encode(question)[0]
        # 有文档元数据的新索引在向量召回时就过滤；旧索引只有一个D1文档。
        has_document_metadata = all((m or {}).get("document_id") for m in found["metadatas"])
        where = {"$and": [{"kb_id": kb_id}, {"document_id": document_id}]} if has_document_metadata else {"kb_id": kb_id}
        dense = self.collection.query(query_embeddings=[embedding], n_results=min(max(top_k*4, 12), len(rows)),
                                      where=where, include=["distances"])
        dense_ids = dense["ids"][0]
        similarities = {rid: 1-float(distance) for rid, distance in zip(dense_ids, dense["distances"][0])}
        ranked = hybrid_order(rows, question, dense_ids)[:max(1, top_k)]
        return [{**row, "score": round(similarities.get(row["id"], 0.0), 4),
                 "dense_score": similarities.get(row["id"]), "retrieval_method": "bm25+vector_rrf"}
                for row in ranked]

    def stats(self, user_id: int) -> dict:
        with self.db.session() as s:
            rows = s.query(KnowledgeBase).filter(KnowledgeBase.user_id == user_id).all()
            kb_count = len(rows)
            chunk_count = sum(int(r.chunk_count or 0) for r in rows)
        return {
            "kb_count": kb_count,
            "chunk_count": chunk_count,
            "embedding_model": self.embedding_model_name,
            "device": self.device,
        }
