"""离线 RAG 评测：校验标注、运行现有检索器、汇总检索及人工复核指标。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import statistics
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "evaluation" / "reasoning_development.json"
REVIEW_FIELDS = ("answer_correct", "supported_by_context", "refused")
API_KEY = os.getenv("DASHSCOPE_API_KEY")
BASE_URL = os.getenv("DASHSCOPE_BASE_URL")

def normalize(text: str) -> str:
    # 只去掉空白，避免 Windows 换行差异和切分后的 strip 影响证据定位。
    return "".join(text.split())


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_dataset(path: Path) -> tuple[dict, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not data.get("cases") or not data.get("sources"):
        raise ValueError("评测集需包含 schema_version=1、sources 和非空 cases")
    texts = {}
    for source_id, source in data["sources"].items():
        texts[source_id] = (path.parent / source["path"]).read_text(encoding="utf-8-sig")
        if digest(normalize(texts[source_id])) != source["text_sha256"]:
            raise ValueError(f"原文已变化，请重新核对标注和版本: {source_id}")
    seen = set()
    for case in data["cases"]:
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"题目 ID 为空或重复: {case_id}")
        seen.add(case_id)
        if case["source_id"] not in texts or not isinstance(case["answerable"], bool):
            raise ValueError(f"来源或 answerable 不合法: {case_id}")
        scope = case.get("retrieval_source_ids", [case["source_id"]])
        if (not isinstance(scope, list) or not scope or any(s not in texts for s in scope)
                or len(scope) != len(set(scope)) or case["source_id"] not in scope):
            raise ValueError(f"检索资料范围不合法: {case_id}")
        if not case.get("question", "").strip() or not case.get("reference_answer", "").strip():
            raise ValueError(f"问题和参考答案不能为空: {case_id}")
        if not case.get("category"):
            raise ValueError(f"category 不能为空: {case_id}")
        annotation_review = case.get("annotation_review")
        if annotation_review is not None:
            if (not isinstance(annotation_review, dict)
                    or (annotation_review.get("approved") is not None
                        and type(annotation_review["approved"]) is not bool)):
                raise ValueError(f"标注审核 approved 需为 true/false/null: {case_id}")
            approved = annotation_review.get("approved")
            if approved is not None and not str(annotation_review.get("reviewer") or "").strip():
                raise ValueError(f"填写标注审核时必须注明 reviewer: {case_id}")
            if ((case.get("annotation_status") == "human_reviewed"
                 or data.get("annotation_status") == "human_reviewed")
                    and (approved is not True or case.get("annotation_status") != "human_reviewed")):
                raise ValueError(f"人工审核状态与逐题确认不一致: {case_id}")
        evidence = case.get("evidence", [])
        if bool(evidence) != case["answerable"]:
            raise ValueError(f"可回答题必须有证据，不可回答题不能有答案证据: {case_id}")
        evidence_ids = set()
        for span in evidence:
            source_id = span.get("source_id", case["source_id"])
            if source_id not in scope:
                raise ValueError(f"证据来源不在检索范围内: {case_id}")
            source = normalize(texts[source_id])
            start, end = span["start"], span["end"]
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(source)
                    or source[start:end] != normalize(span["quote"])):
                raise ValueError(f"证据位置或摘录不匹配: {case_id}")
            if (source_id, start, end) in evidence_ids:
                raise ValueError(f"重复证据: {case_id}")
            evidence_ids.add((source_id, start, end))
        for message in case.get("history", []):
            if message.get("role") not in ("user", "assistant") or not isinstance(message.get("content"), str):
                raise ValueError(f"历史消息不合法: {case_id}")
    return data, texts


def locate_chunks(source_id: str, text: str, chunks: list[str]) -> list[dict]:
    source = normalize(text)
    result = []
    previous_start = -1
    for index, chunk in enumerate(chunks):
        normalized = normalize(chunk)
        start = source.find(normalized, previous_start + 1)
        if not normalized or start < 0:
            raise ValueError(f"切分片段无法定位到原文: {source_id}/{index}")
        previous_start = start
        result.append({"source_id": source_id, "chunk_index": index, "text": chunk,
                       "start": start, "end": start + len(normalized)})
    return result


def span_coverage(span: dict, chunks: list[dict]) -> float:
    intervals = sorted((max(span["start"], c["start"]), min(span["end"], c["end"]))
                       for c in chunks if c["end"] > span["start"] and c["start"] < span["end"]
                       and ("source_id" not in span or c["source_id"] == span["source_id"]))
    covered = 0
    cursor = span["start"]
    for start, end in intervals:
        covered += max(0, end - max(start, cursor))
        cursor = max(cursor, end)
    return covered / (span["end"] - span["start"])


def retrieval_metrics(case: dict, chunks: list[dict], ks: list[int], threshold: float = 0.9) -> dict:
    if not case["answerable"]:
        return {}
    evidence = [{**span, "source_id": span.get("source_id", case["source_id"])}
                for span in case["evidence"]]
    metrics = {}
    for k in ks:
        ranked = chunks[:k]
        # 一条片段覆盖某条证据的 90% 才视作相关，不以词面相似代替标注。
        rank = next((i for i, c in enumerate(ranked, 1)
                     if any(span_coverage(e, [c]) >= threshold for e in evidence)), None)
        recalls = [span_coverage(e, ranked) >= threshold for e in evidence]
        metrics[f"hit@{k}"] = float(rank is not None)
        metrics[f"mrr@{k}"] = 1.0 / rank if rank else 0.0
        metrics[f"evidence_recall@{k}"] = sum(recalls) / len(evidence)
        metrics[f"all_evidence@{k}"] = float(all(recalls))
    return metrics


def validate_prediction(case: dict, prediction: dict, texts: dict[str, str], depth: int) -> None:
    chunks = prediction.get("retrieved")
    if not isinstance(chunks, list):
        raise ValueError(f"缺少 retrieved 列表: {case['id']}")
    if type(prediction.get("retrieval_depth")) is not int or prediction["retrieval_depth"] < depth:
        raise ValueError(f"检索深度不足，不能计算 @{depth}: {case['id']}")
    if len(chunks) > prediction["retrieval_depth"]:
        raise ValueError(f"片段数超过声明的检索深度: {case['id']}")
    scope = case.get("retrieval_source_ids", [case["source_id"]])
    for chunk in chunks:
        source = normalize(texts[chunk["source_id"]]) if chunk.get("source_id") in scope else ""
        start, end = chunk.get("start"), chunk.get("end")
        if (chunk.get("source_id") not in scope
                or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(source)
                or source[start:end] != normalize(chunk.get("text", ""))):
            raise ValueError(f"检索片段不属于本题原文或位置不匹配: {case['id']}")
    review = prediction.get("review") or {}
    if not isinstance(review, dict):
        raise ValueError(f"review 必须是对象: {case['id']}")
    for field in REVIEW_FIELDS:
        if review.get(field) is not None and type(review[field]) is not bool:
            raise ValueError(f"复核字段 {field} 需为 true/false/null: {case['id']}")
    if any(review.get(f) is not None for f in REVIEW_FIELDS):
        if not isinstance(prediction.get("answer"), str) or not prediction["answer"].strip():
            raise ValueError(f"没有生成答案时不能填写回答评分: {case['id']}")
        if not str(review.get("reviewer") or "").strip():
            raise ValueError(f"填写评分时必须注明 reviewer: {case['id']}")
        context = prediction.get("answer_context")
        if not isinstance(context, list) or any(c not in chunks for c in context):
            raise ValueError(f"回答复核需提供实际用于生成的 answer_context: {case['id']}")
    if review.get("supported_by_context") is not None and review.get("refused") is not False:
        raise ValueError(f"证据支持指标仅用于已明确标记为非拒答的回答: {case['id']}")
    for field in ("retrieval_ms", "generation_ms", "first_token_ms"):
        value = prediction.get(field)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f"耗时需为非负有限数: {case['id']}/{field}")


def _review_rate(cases: list[dict], predictions: dict, field: str, answerable: bool | None = None) -> dict:
    eligible = [c for c in cases if answerable is None or c["answerable"] == answerable]
    if field == "supported_by_context":
        eligible = [c for c in eligible if (predictions[c["id"]].get("review") or {}).get("refused") is False]
    values = [(predictions[c["id"]].get("review") or {}).get(field) for c in eligible]
    reviewed = [v for v in values if v is not None]
    return {"value": statistics.mean(reviewed) if reviewed else None,
            "reviewed": len(reviewed), "eligible": len(eligible),
            "coverage": len(reviewed) / len(eligible) if eligible else None}


def _latencies(rows: list[dict], field: str) -> dict:
    values = sorted(p[field] for p in rows if p.get(field) is not None)
    return {"count": len(values), "p50": statistics.median(values) if values else None,
            "p95": values[math.ceil(len(values) * 0.95) - 1] if values else None}


def score_dataset(data: dict, texts: dict[str, str], run: dict, ks: list[int]) -> dict:
    ks = sorted(set(ks))
    if not ks or any(type(k) is not int or k < 1 for k in ks):
        raise ValueError("K 必须为正整数")
    if run.get("dataset_sha256") != digest(json.dumps(data, ensure_ascii=False, sort_keys=True)):
        raise ValueError("运行结果与评测集版本不匹配")
    rows = run.get("predictions", [])
    ids = [p["id"] for p in rows]
    expected = {c["id"] for c in data["cases"]}
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("运行结果必须恰好包含每道题一次，不能遗漏、重复或混入其他题目")
    predictions = {p["id"]: p for p in rows}
    details = []
    for case in data["cases"]:
        prediction = predictions[case["id"]]
        validate_prediction(case, prediction, texts, max(ks))
        details.append({"id": case["id"], "category": case["category"],
                        "answerable": case["answerable"], "question": case["question"],
                        "metrics": retrieval_metrics(case, prediction["retrieved"], ks)})

    def aggregate(items):
        answerable_rows = [d for d in items if d["answerable"]]
        names = [f"{metric}@{k}" for k in ks
                 for metric in ("hit", "mrr", "evidence_recall", "all_evidence")]
        return {"total": len(items), "answerable": len(answerable_rows),
                "metrics": {name: statistics.mean(d["metrics"][name] for d in answerable_rows)
                            if answerable_rows else None for name in names}}

    return {"dataset": data["name"], "annotation_status": data["annotation_status"],
            "scorer_sha256": digest(Path(__file__).read_text(encoding="utf-8-sig")),
            "run_config": run.get("config", {}), "retrieval": aggregate(details),
            "by_category": {category: aggregate([d for d in details if d["category"] == category])
                            for category in sorted({d["category"] for d in details})},
            "answer_review": {
                "answer_accuracy": _review_rate(data["cases"], predictions, "answer_correct"),
                "supported_answer_rate": _review_rate(data["cases"], predictions, "supported_by_context"),
                "unanswerable_refusal_rate": _review_rate(data["cases"], predictions, "refused", False),
                "false_refusal_rate": _review_rate(data["cases"], predictions, "refused", True)},
            "latency_ms": {f: _latencies(rows, f) for f in
                           ("retrieval_ms", "generation_ms", "first_token_ms")},
            "details": details}


def run_baseline(data: dict, texts: dict[str, str], args) -> dict:
    # 评测只能用现有本地权重；不下载模型，不初始化真实账号、密钥或业务数据库。
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    from db import Database, User
    from kb_service import KnowledgeBaseManager, RecursiveCharacterTextSplitter
    from local_model import resolve_embedding_model_path, resolve_llm_model_path

    model_path = resolve_embedding_model_path()
    if not Path(model_path).is_dir():
        raise ValueError("请先准备本地嵌入权重或设置 LOCAL_EMBEDDING_MODEL；评测禁止自动下载")
    llm = None
    if args.generate_local:
        from llm_answerer import GenerationConfig, LLMAnswerer
        llm_path = resolve_llm_model_path()
        if not Path(llm_path).is_dir():
            raise ValueError("请先准备本地生成权重或设置 LOCAL_LLM_MODEL")
        llm = LLMAnswerer(llm_path, device=args.device)

    predictions = []
    with tempfile.TemporaryDirectory(prefix="qasystem-eval-") as directory:
        db = Database(Path(directory) / "evaluation.db")
        manager = None
        try:
            with db.session() as session:
                user = User(username="evaluation", salt="unused", password_hash="unused", role="user")
                session.add(user)
                session.flush()
                user_id = user.id
            manager = KnowledgeBaseManager(db, directory, model_path, device=args.device,
                                           chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
            sources = {}
            started = time.perf_counter()
            for source_id, text in texts.items():
                chunks = locate_chunks(source_id, text, manager._split_text(text))
                kb = manager.create(user_id, source_id, text=text)
                sources[source_id] = {"kb_id": kb["id"], "chunks": chunks}
            indexing_ms = (time.perf_counter() - started) * 1000
            for i, case in enumerate(data["cases"], 1):
                # 保持当前线上行为：历史仅用于生成，检索不读取标注的 standalone_question。
                started = time.perf_counter()
                depth = max(max(args.ks), args.answer_top_k if llm else 0)
                scope = case.get("retrieval_source_ids", [case["source_id"]])
                candidates = []
                for source_id in scope:
                    source = sources[source_id]
                    found = manager.query(user_id, source["kb_id"], case["question"], depth)
                    candidates.extend((h, source["chunks"][h.chunk_index]) for h in found)
                candidates.sort(key=lambda pair: (-pair[0].score, pair[1]["source_id"], pair[0].chunk_index))
                candidates = candidates[:depth]
                hits = [hit for hit, _ in candidates]
                retrieval_ms = (time.perf_counter() - started) * 1000
                ranked = [{**chunk, "score": hit.score} for hit, chunk in candidates]
                prediction = {"id": case["id"], "retrieval_depth": depth, "retrieved": ranked,
                              "answer": None, "answer_context": None, "retrieval_ms": retrieval_ms,
                              "generation_ms": None, "first_token_ms": None,
                              "review": {"reviewer": None, "answer_correct": None,
                                         "supported_by_context": None, "refused": None, "notes": ""}}
                if llm is not None:
                    prediction["answer_context"] = ranked[:args.answer_top_k]
                    tokens = []
                    started = time.perf_counter()
                    for token in llm.stream_answer(case["question"], hits[:args.answer_top_k], case.get("history", []),
                                                  GenerationConfig(args.max_new_tokens, 0.0)):
                        if token and prediction["first_token_ms"] is None:
                            prediction["first_token_ms"] = (time.perf_counter() - started) * 1000
                        tokens.append(token)
                    prediction["answer"] = "".join(tokens)
                    prediction["generation_ms"] = (time.perf_counter() - started) * 1000
                predictions.append(prediction)
                print(f"[{i}/{len(data['cases'])}] {case['id']}", flush=True)
            config = {"engine": "KnowledgeBaseManager.query", "embedding_model": model_path,
                      "pooling": "mean (current implementation)", "device": manager.device,
                      "splitter": "recursive" if RecursiveCharacterTextSplitter else "fallback",
                      "chunk_size": args.chunk_size, "chunk_overlap": args.chunk_overlap,
                      "ks": args.ks, "generation": "local" if llm else "none",
                      "answer_top_k": args.answer_top_k if llm else None,
                      "llm_model": llm.model_name if llm else None,
                      "temperature": 0.0 if llm else None,
                      "max_new_tokens": args.max_new_tokens if llm else None,
                      "indexing_ms": indexing_ms,
                      "chunk_counts": {sid: len(s["chunks"]) for sid, s in sources.items()},
                      "retrieval_scope": "按每题允许的来源分别检索，再按当前余弦分数合并；仅离线评测支持多来源",
                      "package_versions": {name: importlib.metadata.version(name) for name in
                                           ("torch", "transformers", "chromadb", "sqlalchemy")},
                      "code_sha256": {name: digest((ROOT / name).read_text(encoding="utf-8-sig"))
                                      for name in ("kb_service.py", "local_rag_engine.py", "llm_answerer.py",
                                                   "rag_evaluation.py")},
                      "created_at": datetime.now().astimezone().isoformat()}
        finally:
            if manager is not None:
                # Windows 上先关闭 Chroma 句柄，否则临时目录无法删除。
                close = getattr(manager.db_client, "close", None)
                if close is not None:
                    close()
                else:
                    # 旧版客户端无 close；这里只停止本次独立临时目录对应的系统。
                    manager.db_client._system.stop()
            db.engine.dispose()
    return {"schema_version": 1,
            "dataset_sha256": digest(json.dumps(data, ensure_ascii=False, sort_keys=True)),
            "config": config, "predictions": predictions}


def prepare_api_replay(data: dict, texts: dict[str, str], baseline: dict,
                       source_path: Path, model: str) -> dict:
    """固定本地运行的证据和提示词版本，仅替换生成模型。"""
    if not isinstance(API_KEY, str) or not API_KEY.strip():
        raise ValueError("API_KEY 为空，请在运行进程中设置 DASHSCOPE_API_KEY")
    if not isinstance(BASE_URL, str) or not BASE_URL.strip():
        raise ValueError("BASE_URL 为空，请在运行进程中设置 DASHSCOPE_BASE_URL")
    if not model.strip():
        raise ValueError("API 模型名不能为空")
    config = baseline["config"]
    score_dataset(data, texts, baseline, config["ks"])
    prompt_hash = digest((ROOT / "llm_answerer.py").read_text(encoding="utf-8-sig"))
    if config.get("code_sha256", {}).get("llm_answerer.py") != prompt_hash:
        raise ValueError("公共提示词代码与本地运行版本不一致，不能进行同提示词对照")
    if config.get("generation") != "local":
        raise ValueError("API 对照需要已保存答案和实际上下文的本地生成结果")
    for row in baseline["predictions"]:
        context = row.get("answer_context")
        if (not isinstance(context, list) or any(c not in row["retrieved"] for c in context)
                or any(not isinstance(c.get("score"), (int, float))
                       or not math.isfinite(c["score"]) for c in context)
                or not isinstance(row.get("answer"), str) or not row["answer"].strip()):
            raise ValueError(f"本地答案或实际生成上下文缺失/不合法: {row['id']}")
    if config.get("temperature") != 0.0 or not isinstance(config.get("max_new_tokens"), int):
        raise ValueError("API 对照需要本地运行保存温度 0 和生成长度")
    run = copy.deepcopy(baseline)
    run["config"].update({
        "generation": "api", "llm_model": model, "enable_thinking": False,
        "enable_search": False, "tools_enabled": False,
        "source_predictions_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "source_predictions_path": str(source_path.resolve()), "source_config": copy.deepcopy(config),
        "created_at": datetime.now().astimezone().isoformat(),
        "replay_code_sha256": digest(Path(__file__).read_text(encoding="utf-8-sig")),
        "api_endpoint_sha256": digest(BASE_URL),
        "api_package_version": importlib.metadata.version("openai"),
        "api_timeout_seconds": 120, "api_max_retries": 1,
        "retrieval_timing_note": "沿用本地基线耗时，本轮未重新检索",
    })
    run["completed_ids"] = []
    for row in run["predictions"]:
        row.update({"answer": None, "generation_ms": None, "first_token_ms": None,
                    "review": {"reviewer": None, "answer_correct": None,
                               "supported_by_context": None, "refused": None, "notes": ""}})
    return run


def replay_messages(data: dict, run: dict) -> dict[str, list[dict]]:
    from llm_answerer import build_messages

    rows = {p["id"]: p for p in run["predictions"]}
    return {c["id"]: build_messages(c["question"],
            [SimpleNamespace(text=p["text"], score=p["score"]) for p in rows[c["id"]]["answer_context"]],
            c.get("history", [])) for c in data["cases"]}


def load_api_checkpoint(expected: dict, path: Path) -> dict:
    saved = json.loads(path.read_text(encoding="utf-8-sig"))
    wanted_config = {k: v for k, v in expected["config"].items() if k != "created_at"}
    saved_config = {k: v for k, v in saved.get("config", {}).items() if k != "created_at"}
    if saved_config != wanted_config or saved.get("dataset_sha256") != expected["dataset_sha256"]:
        raise ValueError("断点的模型、证据、端点或代码版本不一致，不能续跑")
    completed = saved.get("completed_ids", [])
    if (not isinstance(completed, list) or len(completed) != len(set(completed))
            or set(completed) - {p["id"] for p in expected["predictions"]}
            or len(saved.get("predictions", [])) != len(expected["predictions"])):
        raise ValueError("API 断点记录不完整")
    for old, new in zip(saved["predictions"], expected["predictions"]):
        for field in ("id", "retrieval_depth", "retrieved", "answer_context", "retrieval_ms"):
            if old.get(field) != new.get(field):
                raise ValueError("API 断点的检索证据发生变化")
        if old.get("messages") != new.get("messages") or old.get("messages_sha256") != new.get("messages_sha256"):
            raise ValueError("API 断点的提示词发生变化")
        if old["id"] in completed and (not isinstance(old.get("answer"), str) or not old["answer"].strip()):
            raise ValueError("API 断点的答案或提示词不完整")
    return saved


def save_api_checkpoint(path: Path, run: dict) -> None:
    # 完整写入后替换，避免中断时破坏上一份付费结果。
    temporary = path.with_suffix(".json.tmp")
    write_json(temporary, run)
    temporary.replace(path)


class APIGenerationError(RuntimeError):
    """仅输出脱敏的调用状态，不传播 SDK 异常中的地址或请求内容。"""


def run_api_replay(data: dict, texts: dict[str, str], baseline: dict, source_path: Path,
                   output: Path, model: str, resume: bool = False, client=None) -> dict:
    run = prepare_api_replay(data, texts, baseline, source_path, model)
    messages = replay_messages(data, run)
    for row in run["predictions"]:
        row["messages"] = messages[row["id"]]
        row["messages_sha256"] = digest(json.dumps(row["messages"], ensure_ascii=False, sort_keys=True))
    checkpoint = output / "predictions.partial.json"
    if resume:
        run = load_api_checkpoint(run, checkpoint)
        score_dataset(data, texts, run, run["config"]["ks"])
    elif output.exists() and any(output.iterdir()):
        raise ValueError("输出目录非空，请换一个目录，避免覆盖已有评测结果")
    owned_client = client is None
    if owned_client:
        from openai import OpenAI
        try:
            client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=120, max_retries=1)
        except Exception:
            raise APIGenerationError("API 客户端配置失败，请检查凭据和端点配置") from None
    try:
        save_api_checkpoint(checkpoint, run)
        for i, row in enumerate(run["predictions"], 1):
            if row["id"] in run["completed_ids"]:
                continue
            stream = None
            started = time.perf_counter()
            parts, usage, returned_model, finish_reason = [], None, None, None
            first_token_ms = None
            try:
                stream = client.chat.completions.create(
                    model=model, messages=row["messages"], stream=True,
                    temperature=run["config"]["temperature"], max_tokens=run["config"]["max_new_tokens"],
                    stream_options={"include_usage": True}, extra_body={"enable_thinking": False})
                for chunk in stream:
                    returned_model = getattr(chunk, "model", None) or returned_model
                    if getattr(chunk, "usage", None) is not None:
                        usage = chunk.usage.model_dump(exclude_none=True)
                    if chunk.choices:
                        choice = chunk.choices[0]
                        finish_reason = choice.finish_reason or finish_reason
                        content = getattr(choice.delta, "content", None)
                        if content:
                            if first_token_ms is None:
                                first_token_ms = (time.perf_counter() - started) * 1000
                            parts.append(content)
                answer = "".join(parts)
                if not answer.strip():
                    raise APIGenerationError("API 返回了空答案")
            except Exception as exc:
                # 不打印 str(exc)，供应商异常可能包含凭据、内部地址和请求正文。
                status = getattr(exc, "status_code", None)
                status_text = f"HTTP {status}" if type(status) is int else type(exc).__name__
                raise APIGenerationError(f"{row['id']} 调用失败（{status_text}）；已保存 "
                                         f"{len(run['completed_ids'])} 题，可用 --resume 续跑") from None
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            row.update({"answer": answer, "generation_ms": (time.perf_counter() - started) * 1000,
                        "first_token_ms": first_token_ms,
                        "api_response": {"model": returned_model, "finish_reason": finish_reason, "usage": usage}})
            run["completed_ids"].append(row["id"])
            save_api_checkpoint(checkpoint, run)
            print(f"[{i}/{len(run['predictions'])}] {row['id']} API 已保存", flush=True)
    finally:
        if owned_client:
            try:
                client.close()
            except Exception:
                pass
    return run


def run_controlled(data: dict, texts: dict[str, str], args, output: Path) -> dict:
    from api_answerer import APIAnswerer, APIProvider
    from db import Database, User
    from kb_service import KnowledgeBaseManager
    from rag_pipeline import EvidencePipeline, PIPELINE_VERSION

    if output.exists() and any(output.iterdir()) and not args.resume:
        raise ValueError("输出目录非空，受控评测不会覆盖历史基线")
    if not args.generate_local and (not isinstance(API_KEY, str) or not API_KEY.strip()
                                  or not isinstance(BASE_URL, str) or not BASE_URL.strip()):
        raise ValueError("受控API评测需要DASHSCOPE_API_KEY和DASHSCOPE_BASE_URL")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    api = None
    if args.generate_local:
        from llm_answerer import LLMAnswerer
        model = LLMAnswerer(device=args.device)
        complete = model.complete_messages
        model_name = model.model_name
    else:
        api = APIAnswerer(APIProvider("evaluation", "evaluation", BASE_URL, API_KEY, args.api_model), max_retries=0)
        complete = api.complete_messages
        model_name = args.api_model
    run = {"schema_version": 1, "dataset_sha256": digest(json.dumps(data, ensure_ascii=False, sort_keys=True)),
           "config": {"engine": PIPELINE_VERSION, "ks": args.ks, "generation": "controlled-local" if args.generate_local else "controlled-api",
              "llm_model": model_name, "answer_top_k": args.answer_top_k, "temperature": 0,
              "max_new_tokens": max(args.max_new_tokens, 1536), "api_max_retries": 0,
              "max_model_calls_per_case": 5, "chunk_size": args.chunk_size, "chunk_overlap": args.chunk_overlap,
              "api_endpoint_sha256": digest(BASE_URL) if api is not None else None,
              "retrieval_scope": "规划绑定来源，BM25+向量RRF；候选按必答项和轮次串联，非单query全局余弦排名",
              "code_sha256": {name: digest((ROOT/name).read_text(encoding="utf-8-sig")) for name in
                             ("rag_pipeline.py", "kb_service.py", "api_answerer.py", "rag_evaluation.py")},
              "created_at": datetime.now().astimezone().isoformat()}, "predictions": []}
    try:
        with tempfile.TemporaryDirectory(prefix="controlled-eval-", dir=ROOT/"kb_store") as directory:
            db = Database(Path(directory)/"evaluation.db")
            manager = KnowledgeBaseManager(db, Path(directory)/"store", device=args.device,
                                           chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
            try:
                with db.session() as session:
                    user = User(username="offline_evaluation", salt="unused", password_hash="unused", role="user")
                    session.add(user)
                    session.flush()
                    user_id = user.id
                catalog, source_lookup, chunks_lookup = [], {}, {}
                for sid, text in texts.items():
                    kb = manager.create(user_id, data["sources"][sid]["title"], text=text)
                    documents = manager.document_catalog(user_id, kb["id"])
                    for document in documents:
                        source_lookup[document["source_id"]] = sid
                    catalog.extend(documents)
                    chunks_lookup[sid] = locate_chunks(sid, text, manager._split_text(text))
                run["config"]["chunk_counts"] = {sid: len(c) for sid,c in chunks_lookup.items()}
                run["config"].update({"device": manager.device, "embedding_model": manager.embedding_model_name})
                checkpoint = output/"predictions.partial.json"
                if args.resume:
                    saved = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
                    current_config = {k:v for k,v in run["config"].items() if k != "created_at"}
                    saved_config = {k:v for k,v in saved.get("config",{}).items() if k != "created_at"}
                    if saved_config != current_config or saved.get("dataset_sha256") != run["dataset_sha256"]:
                        raise ValueError("受控评测断点的数据、模型、端点或代码版本不一致")
                    expected_ids = [c["id"] for c in data["cases"]]
                    done_ids = [p["id"] for p in saved.get("predictions",[])]
                    if done_ids != expected_ids[:len(done_ids)]:
                        raise ValueError("受控断点题目顺序或范围不合法")
                    for c,p in zip(data["cases"],saved["predictions"]):
                        validate_prediction(c,p,texts,max(args.ks))
                    run = saved
                    interrupted = run.pop("failure",None)
                    if interrupted:
                        run.setdefault("interrupted_api_calls",[]).extend(interrupted.get("api_calls",[]))
                done = len(run["predictions"])
                def search(document, question, top_k):
                    return manager.query_evidence(user_id, document["kb_id"], document["document_id"], question, top_k)
                for i, case in enumerate(data["cases"], 1):
                    if i <= done:
                        continue
                    allowed = set(case.get("retrieval_source_ids", [case["source_id"]]))
                    scoped_catalog = [d for d in catalog if source_lookup[d["source_id"]] in allowed]
                    started = time.perf_counter()
                    call_start = len(api.call_log) if api is not None else 0
                    try:
                        result = EvidencePipeline(complete, search, args.answer_top_k, max(args.max_new_tokens,1536)).run(
                            case["question"], case.get("history", []), scoped_catalog)
                    except Exception:
                        run["failure"] = {"case_id":case["id"], "api_calls":api.call_log[call_start:] if api is not None else []}
                        save_api_checkpoint(checkpoint,run)
                        raise
                    ranked = []
                    for evidence in result["evidence"]:
                        sid = source_lookup[evidence["source_key"]]
                        ranked.append({**chunks_lookup[sid][evidence["chunk_index"]], "score": evidence["score"],
                            "evidence_id": evidence["id"], "source_title": evidence["source_title"],
                            "retrieval_method": evidence["retrieval_method"], "fusion_score": evidence["fusion_score"]})
                    total_ms = (time.perf_counter()-started)*1000
                    retrieval_ms = sum(s.get("elapsed_ms",0) for s in result["trace"]["steps"] if s["stage"] == "retrieve")
                    run["predictions"].append({"id": case["id"], "retrieval_depth": max(max(args.ks),len(ranked)),
                        "retrieved": ranked, "answer_context": ranked, "answer": result["answer"],
                        "answer_status": result["status"], "claims": result["claims"], "pipeline_trace": result["trace"],
                        "api_calls": api.call_log[call_start:] if api is not None else [],
                        "pipeline_ms":total_ms,"retrieval_ms":retrieval_ms,"generation_ms":max(0,total_ms-retrieval_ms),"first_token_ms":total_ms,
                        "review": {"reviewer": None, "answer_correct": None, "supported_by_context": None, "refused": None, "notes": ""}})
                    save_api_checkpoint(checkpoint, run)
                    print(f"[{i}/{len(data['cases'])}] {case['id']} {result['status']} 调用{result['trace']['model_calls']}次",flush=True)
            finally:
                close = getattr(manager.db_client,"close",None)
                if close is not None: close()
                else: manager.db_client._system.stop()
                db.engine.dispose()
    finally:
        if api is not None: api.close()
    run.pop("failure",None)
    return run


def write_answers(output: Path, data: dict, run: dict, baseline: dict | None = None) -> None:
    rows = {p["id"]: p for p in run["predictions"]}
    old_rows = {p["id"]: p for p in baseline["predictions"]} if baseline else {}
    lines = [f"# {data['name']} · 回答审核", "",
             f"模型：{run['config'].get('llm_model')}；实际上下文 Top-{run['config'].get('answer_top_k')}。", "",
             "回答尚未人工评分。参考答案和标准证据只供审核，不发送给生成模型。", ""]
    if run["config"].get("generation","").startswith("controlled-"):
        lines += ["受控流程每个必答项分别检索，允许一次补检。上方Top-K指每项召回上限，实际完整上下文以逐题列表和轨迹为准。", ""]
    if baseline:
        lines += ["API 复用本地基线的检索排名、实际上下文、历史和公共提示词；思考模式关闭。", ""]
    for case in data["cases"]:
        row = rows[case["id"]]
        lines += [f"## {case['id']} · {case['category']}", "", f"**问题：** {case['question']}", ""]
        if case.get("history"):
            lines += ["**历史：**", ""]
            lines.extend(f"> {m['role']}：{m['content']}\n" for m in case["history"])
        lines += ["**参考答案：**", "", case["reference_answer"], ""]
        if row.get("answer_status"):
            lines += [f"流程状态：`{row['answer_status']}`；模型调用：`{row['pipeline_trace']['model_calls']}`次。", ""]
        if baseline:
            lines += ["**本地 1.5B 回答：**", "", old_rows[case["id"]]["answer"], ""]
        lines += ["**API 回答：**" if baseline else "**模型回答：**", "", row.get("answer") or "未生成", "",
                  "**实际生成上下文：**", ""]
        for i, chunk in enumerate(row.get("answer_context") or [], 1):
            lines += [f"{i}. 引用编号 `{chunk.get('evidence_id','—')}`；来源 `{chunk.get('source_title',chunk['source_id'])}`；片段 `{chunk.get('chunk_index')}`；"
                      f"区间 `{chunk['start']}:{chunk['end']}`；分数 `{chunk.get('score', 0):.4f}`", "",
                      chunk["text"], ""]
        response = row.get("api_response")
        if response:
            lines += [f"结束原因：`{response.get('finish_reason')}`；用量：`{response.get('usage')}`。", ""]
    output.mkdir(parents=True, exist_ok=True)
    (output / "answers.md").write_text("\n".join(lines), encoding="utf-8")


def write_report(output: Path, data: dict, report: dict) -> None:
    write_json(output / "report.json", report)
    config = report["run_config"]
    lines = [f"# {data['name']} · 评测报告", "",
             f"标注状态：{data['annotation_status']}。本报告不是公开数据集成绩。", "",
             f"标注说明：{data.get('annotation_notes', '').rstrip('。')}。统计仅反映当前评测语料。", "",
             f"原文分块数：{config.get('chunk_counts', {})}。K 接近分块总数时，召回分数会偏容易。", "",
             f"切分：{config.get('chunk_size')}/{config.get('chunk_overlap')}；"
             f"设备：{config.get('device')}；生成：{config.get('generation')}。", "",
             "## 检索指标", "", "只统计可回答题。Hit/MRR 以单片段覆盖证据至少 90% 为相关标准；",
             "Evidence Recall 按 Top-K 片段覆盖的不同原文证据计分，重叠区域只算一次。", "",
             "| 指标 | 值 |", "| --- | --- |"]
    for name, value in report["retrieval"]["metrics"].items():
        lines.append(f"| {name} | {value:.4f} |" if value is not None else f"| {name} | 未评测 |")
    lines += ["", "## 分类结果", "", "| 类别 | 可回答题数 | K | Hit | MRR | Evidence Recall | All Evidence |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for category, values in report["by_category"].items():
        for k in config.get("ks", [1]):
            cells = [values["metrics"].get(f"{name}@{k}") for name in
                     ("hit", "mrr", "evidence_recall", "all_evidence")]
            summary = " | ".join(f"{value:.3f}" if value is not None else "—" for value in cells)
            lines.append(f"| {category} | {values['answerable']} | {k} | {summary} |")
    lines += ["", "## 回答人工复核", "", "缺少复核的指标显示未评测，不按 0 分或满分处理。", "",
              "| 指标 | 值 | 已复核 / 应复核 |", "| --- | --- | --- |"]
    for name, result in report["answer_review"].items():
        value = f"{result['value']:.4f}" if result["value"] is not None else "未评测"
        lines.append(f"| {name} | {value} | {result['reviewed']} / {result['eligible']} |")
    lines += ["", "## 检索未覆盖完整证据的题目", ""]
    for k in config.get("ks", [1]):
        lines += [f"### K={k}", ""]
        failures = [d for d in report["details"] if d["answerable"]
                    and d["metrics"].get(f"all_evidence@{k}", 0) < 1]
        lines.extend(f"- {d['id']}：{d['question']}" for d in failures)
        if not failures:
            lines.append("未发现证据缺失。")
        lines.append("")
    lines += ["", "## 耗时（毫秒）", "", "| 阶段 | 样本数 | P50 | P95 |",
              "| --- | --- | --- | --- |"]
    for field, values in report["latency_ms"].items():
        p50 = f"{values['p50']:.1f}" if values["p50"] is not None else "未评测"
        p95 = f"{values['p95']:.1f}" if values["p95"] is not None else "未评测"
        lines.append(f"| {field} | {values['count']} | {p50} | {p95} |")
    lines += ["", "检索耗时不包含模型加载和入库，生成耗时不含检索；不代表在线并发性能。", ""]
    if config.get("generation") == "api":
        lines += ["本轮仅调用 API 生成回答；检索耗时和检索指标沿用原本地基线。", ""]
    if config.get("generation","").startswith("controlled-"):
        lines += ["受控流程的@K按必答项/来源及补检轮次串联候选统计，不是旧单query的全局余弦排序，不能当作单变量排序增益。", "",
                  "generation_ms包含规划、事实生成和核验；first_token_ms是核验后输出等待时间。检索计时单独记录。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "run", "score", "generate-api", "run-controlled"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--ks", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--predictions", type=Path, help="score 的结果或 generate-api 复用的本地 predictions.json")
    parser.add_argument("--api-model", default="qwen3.8-flash")
    parser.add_argument("--resume", action="store_true", help="generate-api/run-controlled 从断点续跑")
    parser.add_argument("--chunk-size", type=int, default=260)
    parser.add_argument("--chunk-overlap", type=int, default=60)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--generate-local", action="store_true")
    parser.add_argument("--answer-top-k", type=int, default=4, help="用于生成的片段数，与检索评测 K 分开")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()
    args.ks = sorted(set(args.ks))
    if (min(args.ks) < 1 or not 0 <= args.chunk_overlap < args.chunk_size
            or args.max_new_tokens < 1 or args.answer_top_k < 1):
        parser.error("K、生成长度必须为正，且 0 <= chunk_overlap < chunk_size")
    try:
        if args.resume and args.command not in ("generate-api", "run-controlled"):
            parser.error("--resume 仅用于 generate-api/run-controlled")
        if args.command == "run" and args.output and args.output.exists() and any(args.output.iterdir()):
            raise ValueError("输出目录非空，请换一个目录，避免覆盖已有评测结果")
        data, texts = load_dataset(args.dataset.resolve())
        if args.command == "validate":
            print(json.dumps({"cases": len(data["cases"]),
                              "categories": dict(Counter(c["category"] for c in data["cases"])),
                              "annotation_status": data["annotation_status"]}, ensure_ascii=False, indent=2))
            return
        baseline = None
        if args.command == "run-controlled":
            output = args.output or ROOT/"kb_store"/"evaluation"/datetime.now().strftime("controlled-%Y%m%d-%H%M%S")
            run = run_controlled(data, texts, args, output)
            write_json(output/"predictions.json", run)
        elif args.command == "generate-api":
            if args.predictions is None or args.output is None:
                parser.error("generate-api 需要 --predictions 和独立的 --output")
            if args.output.resolve() == args.predictions.parent.resolve():
                raise ValueError("API 输出目录必须与本地基线目录分开")
            baseline = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
            if args.ks != baseline["config"]["ks"]:
                raise ValueError("API 对照的 K 必须与保存的本地基线一致")
            output = args.output
            run = run_api_replay(data, texts, baseline, args.predictions, output, args.api_model, args.resume)
            write_json(output / "predictions.json", run)
        elif args.command == "run":
            run = run_baseline(data, texts, args)
            output = args.output or ROOT / "kb_store" / "evaluation" / datetime.now().strftime("%Y%m%d-%H%M%S")
            if output.exists() and any(output.iterdir()):
                raise ValueError("输出目录非空，请换一个目录，避免覆盖已有评测结果")
            write_json(output / "predictions.json", run)
        else:
            if args.predictions is None:
                parser.error("score 需要 --predictions")
            run = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
            output = args.output or args.predictions.parent
        report = score_dataset(data, texts, run, args.ks)
        report["run_config"]["ks"] = args.ks
        if run["config"].get("generation") in ("api", "controlled-api"):
            usages = ([p.get("api_response", {}).get("usage") for p in run["predictions"]]
                      if run["config"]["generation"] == "api" else
                      [c.get("usage") for c in (run.get("interrupted_api_calls",[])+[c for p in run["predictions"] for c in p["api_calls"]])])
            count_names = ("reported_cases","total_cases") if run["config"]["generation"] == "api" else ("reported_calls","total_calls")
            report["api_usage"] = {count_names[0]: sum(u is not None for u in usages),
                count_names[1]: len(usages), **{name: sum(u.get(name, 0) for u in usages if u is not None)
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")}}
        write_report(output, data, report)
        if any(p.get("answer") for p in run["predictions"]):
            write_answers(output, data, run, baseline)
        if args.command in ("generate-api", "run-controlled"):
            (output / "predictions.partial.json").unlink()
        print(json.dumps(report["retrieval"], ensure_ascii=False, indent=2))
        print(f"报告：{(output / 'report.md').resolve()}")
    except (ValueError, KeyError, OSError, APIGenerationError, RuntimeError) as exc:
        parser.exit(1, f"评测失败：{exc}\n")


if __name__ == "__main__":
    main()
