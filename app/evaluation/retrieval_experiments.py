"""本地检索对照：复用冻结的改写，比较池化、查询指令、BM25和RRF，不生成答案。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.evaluation.rag_evaluation import digest, load_dataset, locate_chunks, retrieval_metrics, write_json
from app.rag.rag_pipeline import lexical_tokens

ROOT = Path(__file__).resolve().parents[2]
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def binary_metrics(ranking: list[str], relevant: set[str], ks: list[int]) -> dict:
    if not relevant or len(ranking) != len(set(ranking)):
        raise ValueError("指标要求非空正例及不重复的候选")
    result = {}
    for k in ks:
        hits = [i for i, doc in enumerate(ranking[:k], 1) if doc in relevant]
        dcg = sum(1 / math.log2(i + 1) for i in hits)
        ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
        result.update({f"recall@{k}": len(hits) / len(relevant),
                       f"mrr@{k}": 1 / hits[0] if hits else 0.0,
                       f"ndcg@{k}": dcg / ideal})
    return result


def select_subset(corpus_ids, query_ids, qrels, query_count, corpus_size, seed):
    """先固定查询，保留全部已标注正例，再按固定哈希选择干扰项。"""
    corpus_ids, query_ids = set(corpus_ids), set(query_ids)
    if not 1 <= query_count <= len(query_ids) or not 1 <= corpus_size <= len(corpus_ids):
        raise ValueError("查询数或候选规模超出数据范围")
    order = lambda key: (digest(f"{seed}:{key}"), key)
    selected_queries = sorted(query_ids, key=order)[:query_count]
    positives = set()
    for qid in selected_queries:
        if not qrels.get(qid) or not qrels[qid] <= corpus_ids:
            raise ValueError("正例缺失或引用了不存在的语料")
        positives.update(qrels[qid])
    if len(positives) > corpus_size:
        raise ValueError("候选规模小于全部正例数量，不能丢弃正例；请增大corpus-size")
    negatives = sorted(corpus_ids - positives, key=order)[:corpus_size - len(positives)]
    return selected_queries, sorted(positives | set(negatives)), len(positives)


class BM25Index:
    def __init__(self, texts):
        self.postings = defaultdict(list)
        lengths = []
        for index, text in enumerate(texts):
            bag = Counter(lexical_tokens(text))
            lengths.append(sum(bag.values()))
            for token, count in bag.items():
                self.postings[token].append((index, count))
        self.lengths = np.asarray(lengths, dtype=np.float64)
        self.average = float(self.lengths.mean()) or 1.0

    def scores(self, question):
        result = np.zeros(len(self.lengths), dtype=np.float64)
        for token in sorted(set(lexical_tokens(question))):
            entries = self.postings.get(token, [])
            if not entries:
                continue
            idf = math.log(1 + (len(result) - len(entries) + 0.5) / (len(entries) + 0.5))
            for index, count in entries:
                result[index] += idf * count * 2.5 / (
                    count + 1.5 * (0.25 + 0.75 * self.lengths[index] / self.average))
        return result


def rank_scores(scores, allowed, depth, positive_only=False):
    candidates = np.asarray(sorted(allowed), dtype=np.int64)
    if positive_only:
        candidates = candidates[scores[candidates] > 0]
    return candidates[np.argsort(-scores[candidates], kind="stable")][:depth].tolist()


def rrf(dense, lexical, depth):
    scores = defaultdict(float)
    for ranking in (dense, lexical):
        for rank, index in enumerate(ranking, 1):
            scores[index] += 1 / (60 + rank)
    return sorted(scores, key=lambda index: (-scores[index], index))[:depth]


class EmbeddingProbe:
    def __init__(self, device, batch_size):
        import torch
        from app.knowledge.local_model import resolve_embedding_model_path
        from app.knowledge.local_rag_engine import LocalEmbeddingModel

        self.torch, self.batch_size = torch, batch_size
        model_path = Path(resolve_embedding_model_path())
        if not model_path.is_dir():
            raise ValueError("需要已有的本地BGE权重；本实验禁止下载模型")
        self.encoder = LocalEmbeddingModel(str(model_path), device=device)
        self.model_metadata = {"name": model_path.name, "device": self.encoder.device,
            "files_sha256": {p.name: file_digest(p) for p in sorted(model_path.iterdir())
                             if p.is_file() and p.suffix in {".json", ".safetensors", ".bin", ".txt"}}}
        self.timings = []

    def encode(self, texts, label):
        from app.knowledge.local_rag_engine import _mean_pool
        torch = self.torch
        result = {"mean": [], "cls": []}
        started = time.perf_counter()
        with torch.inference_mode():
            for start in range(0, len(texts), self.batch_size):
                inputs = self.encoder.tokenizer(texts[start:start + self.batch_size], padding=True,
                    truncation=True, max_length=512, return_tensors="pt")
                inputs = {k: v.to(self.encoder.device) for k, v in inputs.items()}
                hidden = self.encoder.model(**inputs).last_hidden_state
                for name, pooled in (("mean", _mean_pool(hidden, inputs["attention_mask"])),
                                     ("cls", hidden[:, 0])):
                    result[name].append(torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().float().numpy())
                if start % (self.batch_size * 32) == 0:
                    print(f"{label}: {min(start+self.batch_size,len(texts))}/{len(texts)}", flush=True)
        self.timings.append({"label": label, "texts": len(texts),
                             "elapsed_ms": (time.perf_counter() - started) * 1000,
                             "note": "mean和CLS共享同一次前向计算，不能视作任一单方案的独立耗时"})
        return {name: np.concatenate(parts) for name, parts in result.items()}


def school_track(dataset_path, frozen_run):
    from app.knowledge.kb_service import KnowledgeBaseManager

    data, texts = load_dataset(dataset_path)
    saved = json.loads(frozen_run.read_text(encoding="utf-8-sig"))
    if saved.get("dataset_sha256") != digest(json.dumps(data, ensure_ascii=False, sort_keys=True)):
        raise ValueError("冻结改写与开发集版本不一致")
    rows = saved["predictions"]
    if len(rows) != len(data["cases"]) or {p["id"] for p in rows} != {c["id"] for c in data["cases"]}:
        raise ValueError("冻结改写缺题、重题或混入其他题目")
    predictions = {p["id"]: p for p in rows}
    splitter = SimpleNamespace(chunk_size=saved["config"]["chunk_size"], chunk_overlap=saved["config"]["chunk_overlap"])
    corpus = []
    for sid, text in texts.items():
        # 只调用真实切分方法，不创建业务数据库或修改用户索引。
        chunks = KnowledgeBaseManager._split_text(splitter, text)
        corpus.extend({**c, "id": f"{sid}:{c['chunk_index']}"} for c in locate_chunks(sid, text, chunks))
    titles = {source["title"]: sid for sid, source in data["sources"].items()}
    if len(titles) != len(data["sources"]):
        raise ValueError("来源标题不唯一，无法还原冻结规划的来源映射")
    jobs = {name: [] for name in ("current", "history", "rewrite", "rewrite_scoped")}
    for case in data["cases"]:
        trace = predictions[case["id"]]["pipeline_trace"]
        original = json.loads(next(s for s in trace["steps"] if s["stage"] == "plan")["messages"][1]["content"])
        if original["question"] != case["question"] or original["history"] != case.get("history", [])[-5:]:
            raise ValueError("冻结规划输入与当前题目或历史不一致")
        scope = set(case.get("retrieval_source_ids", texts))
        plan = trace.get("plan", {})
        aliases = {s["id"]: titles[s["title"]] for s in trace["source_catalog"]}
        planned_scope = {aliases[sid] for r in plan.get("requirements", []) for sid in r["source_ids"]}
        history = "\n".join(f"{h['role']}: {h['content']}" for h in case.get("history", [])[-5:])
        rewrite = plan.get("resolved_question", case["question"])
        for name, query, allowed in (("current", case["question"], scope),
                ("history", (history + "\n" + case["question"]).strip(), scope),
                ("rewrite", rewrite, scope), ("rewrite_scoped", rewrite, scope & planned_scope)):
            jobs[name].append({"id": case["id"], "query": query, "category": case["category"],
                              "allowed": [i for i, c in enumerate(corpus) if c["source_id"] in allowed]})
    metadata = {"kind": "school", "dataset_sha256": saved["dataset_sha256"],
                "frozen_run_sha256": file_digest(frozen_run), "corpus_count": len(corpus),
                "queries": len(data["cases"]), "chunk_size": splitter.chunk_size, "chunk_overlap": splitter.chunk_overlap,
                "note": "复用规划阶段实际改写与初始来源绑定；不读取标准改写作检索输入。单query全局精确排序，不等于在线多要求补检流程。"}
    cases = {c["id"]: c for c in data["cases"]}
    def metrics(qid, ranking, ks):
        return retrieval_metrics(cases[qid], [corpus[i] for i in ranking], ks)
    return corpus, jobs, metrics, metadata


def t2_track(root, query_count, corpus_size, seed):
    import pyarrow.parquet as pq

    paths = {name: root / name / "dev-00000-of-00001.parquet" for name in ("corpus", "queries", "data")}
    corpus_rows = pq.read_table(paths["corpus"]).to_pylist()
    query_rows = pq.read_table(paths["queries"]).to_pylist()
    corpus_map = {r["_id"]: r for r in corpus_rows}
    query_map = {r["_id"]: r["text"] for r in query_rows}
    if len(corpus_map) != len(corpus_rows) or len(query_map) != len(query_rows):
        raise ValueError("T2包含重复ID")
    qrels = defaultdict(set)
    for row in pq.read_table(paths["data"]).to_pylist():
        if row["score"] != 1:
            raise ValueError("本实验只接受当前二元正相关标注版本")
        if row["query-id"] not in query_map or row["corpus-id"] not in corpus_map:
            raise ValueError("T2标注引用不存在")
        qrels[row["query-id"]].add(row["corpus-id"])
    qids, cids, positive_count = select_subset(corpus_map, query_map, qrels, query_count, corpus_size, seed)
    corpus = [{"id": cid, "text": "\n".join(v for v in (corpus_map[cid]["title"], corpus_map[cid]["text"]) if v)} for cid in cids]
    jobs = {"current": [{"id": qid, "query": query_map[qid], "category": "retrieval",
                          "allowed": list(range(len(corpus)))} for qid in qids]}
    metadata = {"kind": "t2_subset", "seed": seed, "corpus_count": len(corpus), "queries": len(qids),
                "total_corpus_count": len(corpus_rows), "total_query_count": len(query_rows),
                "positive_corpus_count": positive_count, "selected_query_ids": qids, "selected_corpus_ids": cids,
                "files_sha256": {name: file_digest(path) for name, path in paths.items()},
                "preprocessing": "非空title与原始text以换行连接；保留HTML；不切片；嵌入最多512 token；BM25读取全文",
                "note": "固定查询、全部已标注正例及固定干扰项的子集诊断；不能与完整MTEB或官方T2Ranking成绩比较。"}
    def metrics(qid, ranking, ks):
        return binary_metrics([corpus[i]["id"] for i in ranking], qrels[qid], ks)
    return corpus, jobs, metrics, metadata


def run_track(track, probe, output, ks, candidate_depth):
    corpus, jobs, metric, metadata = track
    documents = probe.encode([c["text"] for c in corpus], metadata["kind"] + " 文档")
    unique = list(dict.fromkeys(j["query"] for group in jobs.values() for j in group))
    query_index = {q: i for i, q in enumerate(unique)}
    plain = probe.encode(unique, metadata["kind"] + " 查询")
    instructed = probe.encode([QUERY_INSTRUCTION + q for q in unique], metadata["kind"] + " 查询指令")
    np.savez(output / "document_vectors.npz", **documents)
    query_vectors = {**plain, **{name + "_instruction": value for name, value in instructed.items()}}
    scores = {name: vectors @ documents[name.split('_')[0]].T for name, vectors in query_vectors.items()}
    started = time.perf_counter()
    lexical = BM25Index([c["text"] for c in corpus])
    lexical_scores = {q: lexical.scores(q) for q in unique}
    lexical_ms = (time.perf_counter() - started) * 1000
    variants = {}
    for mode, queries in jobs.items():
        for method in ["bm25"] + list(query_vectors) + [name + "_rrf" for name in query_vectors]:
            rows = []
            for q in queries:
                started = time.perf_counter()
                lex = rank_scores(lexical_scores[q["query"]], q["allowed"], candidate_depth, positive_only=True)
                if method == "bm25":
                    ranking = lex[:max(ks)]
                else:
                    dense_method = method.removesuffix("_rrf")
                    dense = rank_scores(scores[dense_method][query_index[q["query"]]], q["allowed"], candidate_depth)
                    ranking = rrf(dense, lex, max(ks)) if method.endswith("_rrf") else dense[:max(ks)]
                rows.append({"id": q["id"], "category": q["category"], "query": q["query"],
                             "ranking": [corpus[i]["id"] for i in ranking], "metrics": metric(q["id"], ranking, ks),
                             "ranking_ms": (time.perf_counter() - started) * 1000})
            def aggregate(items):
                keys = {k for r in items for k in r["metrics"]}
                return {k: float(np.mean([r["metrics"][k] for r in items if k in r["metrics"]])) for k in sorted(keys)}
            variants[f"{mode}/{method}"] = {"metrics": aggregate(rows), "evaluated": sum(bool(r["metrics"]) for r in rows),
                "by_category": {cat: aggregate([r for r in rows if r["category"] == cat]) for cat in sorted({r["category"] for r in rows})},
                "details": rows}
        print(f"{metadata['kind']} {mode}：9种检索方案已完成", flush=True)
    result = {"metadata": metadata, "ks": ks, "candidate_depth": candidate_depth,
              "search": "L2归一化向量精确点积；RRF两路各取candidate_depth，常数60；并列按固定语料顺序",
              "lexical_index_and_queries_ms": lexical_ms,
              "embedding_vectors_bytes": sum(v.nbytes for v in documents.values()), "variants": variants}
    write_json(output / "results.json", result)
    return result


def write_summary(output, reports, manifest):
    lines = ["# 检索对照实验", "", "全程本地，无生成API调用。生产索引、编码与问答流程未切换。", "",
             "mean/cls分别表示平均池化/首token池化；instruction只加到查询；rrf为双路排名融合。", "",
             "每行使用相同固定候选池与全局Top-K；冻结改写避免重复模型调用。未使用留出集调参。", ""]
    for name, report in reports.items():
        keys = ["hit@4", "evidence_recall@4", "all_evidence@4", "mrr@4"] if name == "school" else ["recall@4", "recall@8", "mrr@8", "ndcg@8"]
        lines += [f"## {name}", "", report["metadata"]["note"], "",
                  "| 方案 | " + " | ".join(keys) + " |", "| --- | " + " | ".join(["---:"] * len(keys)) + " |"]
        for variant, result in report["variants"].items():
            lines.append("| " + variant + " | " + " | ".join(f"{result['metrics'].get(k,0):.4f}" for k in keys) + " |")
        lines.append("")
    lines += ["## 计时与限制", "", "两种池化共享一次前向计算，编码耗时不能当作单方案延迟。ranking_ms仅为缓存分数后的选排和计分，不是端到端检索延迟。", "",
              "BM25按全文计分，BGE最多读512 token；T2保留原始HTML。这些是固定实验条件，不据子集成绩自动替换生产模型。", "",
              "学校指标由原文证据覆盖计算；T2使用二元相关性Recall/MRR/nDCG，两个数据集的指标不能互换。", "",
              "语料向量、固定查询/候选ID、源数据/模型/代码摘要和逐题排名均保存在本目录。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(output / "manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=("school", "t2", "all"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation/development.json")
    parser.add_argument("--frozen-run", type=Path, default=ROOT / "kb_store/evaluation/controlled-dev-qwen38-v2-20261012/predictions.json")
    parser.add_argument("--t2-root", type=Path, default=ROOT / "T2Retrieval")
    parser.add_argument("--query-count", type=int, default=200)
    parser.add_argument("--corpus-size", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--candidate-depth", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    ks = [1, 2, 4, 8, 10]
    if args.batch_size < 1 or args.candidate_depth < max(ks):
        parser.error("batch-size必须为正，candidate-depth必须至少为10")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("输出目录非空，请使用新目录")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ANONYMIZED_TELEMETRY="False")
    # 先核验数据和冻结输入，再加载权重；实验不连接任何生成服务。
    tracks = {}
    if args.track in ("school", "all"):
        tracks["school"] = school_track(args.dataset.resolve(), args.frozen_run.resolve())
    if args.track in ("t2", "all"):
        tracks["t2"] = t2_track(args.t2_root, args.query_count, args.corpus_size, args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    probe = EmbeddingProbe(args.device, args.batch_size)
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "model": probe.model_metadata, "query_instruction": QUERY_INSTRUCTION, "max_length": 512,
        "batch_size": args.batch_size, "seed": args.seed, "api_calls": 0,
        "code_sha256": {name: file_digest(ROOT / name) for name in
                        ("retrieval_experiments.py", "local_rag_engine.py", "kb_service.py", "rag_pipeline.py", "rag_evaluation.py")},
        "versions": {name: importlib.metadata.version(name) for name in ("numpy", "torch", "transformers", "pyarrow")}}
    reports = {}
    for name, track in tracks.items():
        folder = args.output / name
        folder.mkdir()
        write_json(folder / "selection.json", track[3])
        reports[name] = run_track(track, probe, folder, ks, args.candidate_depth)
        manifest["encoding_timings"] = probe.timings
        if probe.encoder.device == "cuda":
            manifest["cuda_peak_allocated_bytes"] = probe.torch.cuda.max_memory_allocated()
        write_summary(args.output, reports, manifest)
    print(f"报告：{args.output / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
