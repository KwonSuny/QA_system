from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import chromadb
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

from local_model import resolve_embedding_model_path

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - used only when langchain is absent.
    RecursiveCharacterTextSplitter = None


DEFAULT_EMBEDDING_MODEL = resolve_embedding_model_path()


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    score: float
    source: str


@dataclass
class LocalRagConfig:
    data_file: str = str(Path(__file__).resolve().parent / "data" / "aidata.txt")
    db_path: str = "./knowledge_base"
    collection_name: str | None = None
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL
    chunk_size: int = 260
    chunk_overlap: int = 60
    top_k: int = 4
    device: str | None = None


def _pick_device(preferred: str | None = None) -> str:
    if preferred:
        return preferred
    return "cuda" if torch.cuda.is_available() else "cpu"


def _safe_collection_name(model_name: str) -> str:
    digest = hashlib.sha1(model_name.encode("utf-8")).hexdigest()[:10]
    return f"txt_docs_local_{digest}"


def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    masked_hidden = last_hidden_state * mask
    token_counts = mask.sum(dim=1).clamp(min=1e-9)
    return masked_hidden.sum(dim=1) / token_counts


class LocalEmbeddingModel:
    def __init__(self, model_name: str, device: str | None = None) -> None:
        self.model_name = model_name
        self.device = _pick_device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(model_name, trust_remote_code=True)
        self.model.to(self.device)
        self.model.eval()

    @torch.inference_mode()
    def encode(self, texts: str | Iterable[str], batch_size: int = 16) -> list[list[float]]:
        if isinstance(texts, str):
            text_list = [texts]
        else:
            text_list = list(texts)

        embeddings: list[list[float]] = []
        for start in range(0, len(text_list), batch_size):
            batch_texts = text_list[start : start + batch_size]
            encoded = self.tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            output = self.model(**encoded)
            pooled = _mean_pool(output.last_hidden_state, encoded["attention_mask"])
            pooled = F.normalize(pooled, p=2, dim=1)
            embeddings.extend(pooled.cpu().float().tolist())
        return embeddings


class LocalKnowledgeBase:
    """Build and query a Chroma knowledge base with local pretrained embeddings."""

    def __init__(self, config: LocalRagConfig | None = None) -> None:
        self.config = config or LocalRagConfig()
        self.collection_name = self.config.collection_name or _safe_collection_name(
            self.config.embedding_model_name
        )
        self.db_client = chromadb.PersistentClient(path=self.config.db_path)
        self.collection = self.db_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self.embedding_model: LocalEmbeddingModel | None = None

    def _embedder(self) -> LocalEmbeddingModel:
        if self.embedding_model is None:
            self.embedding_model = LocalEmbeddingModel(
                self.config.embedding_model_name,
                device=self.config.device,
            )
        return self.embedding_model

    def ensure_loaded(self, file_path: str | None = None) -> int:
        if self.collection.count() == 0:
            return self.rebuild(file_path)
        return self.collection.count()

    def rebuild(self, file_path: str | None = None) -> int:
        target_file = file_path or self.config.data_file
        chunks = self._split_file(target_file)

        try:
            self.db_client.delete_collection(self.collection_name)
        except Exception:
            pass
        self.collection = self.db_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        if not chunks:
            return 0

        embeddings = self._embedder().encode(chunks)
        source = str(Path(target_file).resolve())
        ids = [self._chunk_id(source, index, chunk) for index, chunk in enumerate(chunks)]
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=[{"source": source, "chunk": index} for index in range(len(chunks))],
        )
        return len(chunks)

    def query(self, question: str, top_k: int | None = None) -> list[RetrievedChunk]:
        count = self.ensure_loaded()
        if count == 0:
            return []

        n_results = min(top_k or self.config.top_k, count)
        query_embedding = self._embedder().encode(question)[0]
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        chunks: list[RetrievedChunk] = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            score = max(0.0, 1.0 - float(distance))
            chunks.append(
                RetrievedChunk(
                    text=document,
                    score=score,
                    source=str((metadata or {}).get("source", "")),
                )
            )
        return chunks

    def _split_file(self, file_path: str) -> list[str]:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8")
        if RecursiveCharacterTextSplitter is not None:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                separators=["\n\n", "\n", "。", "！", "？", "；", "，", " "],
            )
            return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]
        return self._fallback_split(text)

    def _fallback_split(self, text: str) -> list[str]:
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) <= self.config.chunk_size:
                current = f"{current}\n{paragraph}".strip()
                continue
            if current:
                chunks.append(current)
            current = paragraph
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _chunk_id(source: str, index: int, chunk: str) -> str:
        digest = hashlib.sha1(f"{source}:{index}:{chunk}".encode("utf-8")).hexdigest()
        return f"local_txt_chunk_{digest[:24]}"
