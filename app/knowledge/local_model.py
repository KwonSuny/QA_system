from __future__ import annotations

import os
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT_NAMES = ("models", "model")

REMOTE_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
REMOTE_LLM_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

EMBEDDING_CANDIDATES = (
    "bge-small-zh-v1___5",
    "bge-small-zh-v1.5",
    "BAAI_bge-small-zh-v1.5",
    "embedding",
)

LLM_CANDIDATES = (
    "Qwen2___5-1___5B-Instruct",
    "Qwen2.5-1.5B-Instruct",
    "llm",
)


def resolve_embedding_model_path() -> str:
    return _resolve_model_path(
        env_var="LOCAL_EMBEDDING_MODEL",
        candidates=EMBEDDING_CANDIDATES,
        fallback=REMOTE_EMBEDDING_MODEL,
        keywords=("bge", "embed", "embedding"),
    )


def resolve_llm_model_path() -> str:
    return _resolve_model_path(
        env_var="LOCAL_LLM_MODEL",
        candidates=LLM_CANDIDATES,
        fallback=REMOTE_LLM_MODEL,
        keywords=("qwen", "instruct", "chat", "llm"),
    )


def _resolve_model_path(
    env_var: str,
    candidates: tuple[str, ...],
    fallback: str,
    keywords: tuple[str, ...],
) -> str:
    env_value = os.getenv(env_var)
    if env_value:
        return env_value

    for root in _model_roots():
        for candidate in candidates:
            path = root / candidate
            if _looks_like_huggingface_model(path):
                return str(path)

    discovered = _discover_model_dir(keywords)
    if discovered is not None:
        return str(discovered)

    return fallback


def _model_roots() -> list[Path]:
    return [WORKSPACE_ROOT / name for name in MODEL_ROOT_NAMES if (WORKSPACE_ROOT / name).is_dir()]


def _discover_model_dir(keywords: tuple[str, ...]) -> Path | None:
    for root in _model_roots():
        for path in root.rglob("config.json"):
            model_dir = path.parent
            if not _looks_like_huggingface_model(model_dir):
                continue
            normalized_name = model_dir.name.lower()
            if any(keyword in normalized_name for keyword in keywords):
                return model_dir
    return None


def _looks_like_huggingface_model(path: Path) -> bool:
    if not path.is_dir():
        return False
    has_config = (path / "config.json").is_file()
    has_tokenizer = any(
        (path / filename).is_file()
        for filename in ("tokenizer.json", "tokenizer_config.json", "vocab.txt", "vocab.json")
    )
    has_weights = any(
        next(path.glob(pattern), None) is not None
        for pattern in ("*.safetensors", "pytorch_model*.bin", "model*.bin")
    )
    return has_config and has_tokenizer and has_weights
