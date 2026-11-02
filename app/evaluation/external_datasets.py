"""将官方中文问答快照转换为独立、待人工审核的开发诊断集。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import tarfile
import urllib.request
from pathlib import Path

from app.rag.rag_pipeline import normalize

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "external" / "raw"
SEED = 20261014


def download_snapshots(manifest: dict):
    """只下载带 URL 的原始数据，按固定哈希验收，不下载基线模型。"""
    RAW.mkdir(parents=True, exist_ok=True)
    for name, item in manifest.items():
        if "url" not in item:
            continue
        target = RAW / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]:
            continue
        request = urllib.request.Request(item["url"], headers={"User-Agent": "qasystem-dataset-import"})
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read(200 * 1024 * 1024 + 1)
        if len(raw) > 200 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"下载大小或哈希不匹配：{name}")
        target.write_bytes(raw)
    with tarfile.open(RAW / "dureader_checklist.dataset.tar.gz") as archive:
        for name in ["dureader_dev.json", "DuReader-License.docx"]:
            item = manifest[name]
            with archive.extractfile(item["archive_member"]) as member:
                raw = member.read()
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError(f"归档成员哈希不匹配：{name}")
            (RAW / name).write_bytes(raw)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_verified(name: str, manifest: dict) -> bytes:
    raw = (RAW / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest[name]["sha256"]:
        raise ValueError(f"官方快照校验失败：{name}")
    return raw


class DatasetBuilder:
    def __init__(self, name: str):
        self.path = ROOT / "evaluation" / "external" / f"{name}_development.json"
        self.texts = {}
        self.data = {"schema_version": 1, "name": name + " 中文扩充开发诊断",
                     "split": "development", "annotation_status": "imported_pending_review",
                     "version": "external-v1", "seed": SEED,
                     "evaluation_track": "scoped_passage_retrieval",
                     "annotation_notes": "原始公开标注经转换；尚未经 sunyeu 人工审核，不代表官方基准成绩。各题只在授权候选篇章内检索，无答案标签仅在该范围有效。",
                     "sources": {}, "cases": []}

    def source(self, text: str, dataset: str) -> str:
        source_id = dataset + "_" + sha(text)[:16]
        if source_id not in self.texts:
            self.texts[source_id] = text
            path = ROOT / "data" / "external" / "prepared" / "documents" / f"{source_id}.txt"
            self.data["sources"][source_id] = {
                "path": Path(os.path.relpath(path, self.path.parent)).as_posix(),
                "title": f"{dataset} 原始篇章 {sha(text)[:8]}",
                "text_sha256": sha(normalize(text))}
        return source_id

    def add(self, case_id, question, answer, category, candidates, evidence, origin):
        scope = list(dict.fromkeys(self.source(t, origin["dataset"]) for t in candidates))
        spans = []
        for item in evidence:
            text, quote = item[:2]
            source_id = self.source(text, origin["dataset"])
            start = item[2] if len(item) == 3 else normalize(text).find(normalize(quote))
            if start < 0 or normalize(text)[start:start+len(normalize(quote))] != normalize(quote):
                raise ValueError(f"无法定位证据：{case_id}")
            span = {"source_id": source_id, "start": start,
                    "end": start + len(normalize(quote)), "quote": quote}
            if span not in spans:
                spans.append(span)
        self.data["cases"].append({
            "id": case_id, "source_id": spans[0]["source_id"] if spans else scope[0],
            "category": category, "question": question, "history": [],
            "answerable": bool(evidence), "reference_answer": answer,
            "evidence": spans, "retrieval_source_ids": scope,
            "fact_groups": [f"{origin['dataset']}:{origin.get('original_file', origin.get('original_split', ''))}:{origin['original_id']}"],
            "external_origin": origin, "annotation_status": "imported_pending_review",
            "annotation_review": {"reviewer": None, "approved": None, "notes": ""}})

    def save(self, provenance):
        self.data["provenance"] = provenance
        for source_id, text in self.texts.items():
            path = self.path.parent / self.data["sources"][source_id]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        write_json(self.path, self.data)
        lines = [f"# {self.data['name']}", "", self.data["annotation_notes"], "",
                 "在同名 JSON 的 annotation_review 填写 reviewer、approved 和 notes。",
                 "确认通过后，再将逐题及整体 annotation_status 改为 human_reviewed。",
                 "同一 RGB 原题的不同变体必须留在同一划分，不能分到训练与测试两侧。", ""]
        for case in self.data["cases"]:
            lines += [f"## {case['id']} · {case['category']}", "", case["question"], "",
                      f"可回答：{case['answerable']}；参考答案：{case['reference_answer']}", "",
                      f"原始标注：{json.dumps(case['external_origin'], ensure_ascii=False)}", "",
                      "证据："]
            lines += [f"- {e['source_id']} [{e['start']},{e['end']})：{e['quote']}" for e in case["evidence"]] or ["- 无答案证据；需核对下列全部候选资料是否确实不足。"]
            for sid in case["retrieval_source_ids"]:
                lines += ["", f"### 候选资料 {sid}", "", self.texts[sid], ""]
        self.path.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")


def answer_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [text for item in value for text in answer_strings(item)]


def rgb_support(row) -> list[tuple[str, str]]:
    positives = row["positive"]
    nested = bool(positives and isinstance(positives[0], list))
    pool = [text for group in positives for text in group] if nested else positives
    support = []
    for answer in row["answer"]:
        answers = answer_strings(answer)
        candidates = []
        for text in pool:
            for sentence in re.findall(r"[^。！？\n]+[。！？]?", text):
                if "..." in sentence or "…" in sentence:
                    continue
                if any(normalize(a) in normalize(sentence) for a in answers):
                    candidates.append((text, sentence.strip()))
        if not candidates:
            raise ValueError("参考答案不能按原文匹配定位，需要人工标注")
        support.append(min(candidates, key=lambda x: (len(x[1]), len(x[0]))))
    if nested and not all(any(text in group for text, _ in support) for group in positives):
        raise ValueError("无法证明全部原始信息组均参与答案，需要人工标注")
    return list(dict.fromkeys(support))


def prepare_rgb(manifest):
    builder = DatasetBuilder("rgb")
    rng = random.Random(SEED)
    exclusions = []
    refined = [json.loads(line) for line in read_verified("zh_refine.json", manifest).decode("utf-8").splitlines()]
    integrated = [json.loads(line) for line in read_verified("zh_int.json", manifest).decode("utf-8").splitlines()]
    rng.shuffle(refined)
    rng.shuffle(integrated)
    count = 0
    for row in refined:
        try:
            support = rgb_support(row)
            answers = answer_strings(row["answer"])
            negatives = [text for text in row["negative"]
                         if not any(normalize(a) in normalize(text) for a in answers)]
            if len(negatives) < 3:
                raise ValueError("不足3条未出现参考答案的原始干扰资料")
        except ValueError as exc:
            exclusions.append({"file": "zh_refine.json", "id": row["id"], "reason": str(exc)})
            continue
        rng.shuffle(negatives)
        positive_texts = list(dict.fromkeys(t for t, _ in support))
        for variant in ["clean", "noise", "no_evidence"]:
            docs = (positive_texts if variant == "clean" else
                    positive_texts + negatives[:3] if variant == "noise" else negatives[:3])
            rng.shuffle(docs := list(docs))
            origin = {"dataset": "rgb", "original_file": "zh_refine.json", "original_id": row["id"],
                      "variant": variant, "original_answer": row["answer"],
                      "evidence_annotation": "答案词面匹配提取的候选支持句，待人工检查主语与完整性",
                      "answerability_annotation": "派生：仅提供原始 negative 篇章" if variant == "no_evidence" else "原始 positive 篇章"}
            builder.add(f"rgb-{row['id']}-{variant}", row["query"],
                        "资料不足，应拒答。" if variant == "no_evidence" else "；".join(answers),
                        "unanswerable" if variant == "no_evidence" else "noise" if variant == "noise" else "fact",
                        docs, [] if variant == "no_evidence" else support, origin)
        count += 1
        if count == 10:
            break
    integrated_count = 0
    for row in integrated:
        try:
            support = rgb_support(row)
        except ValueError as exc:
            exclusions.append({"file": "zh_int.json", "id": row["id"], "reason": str(exc)})
            continue
        docs = list(dict.fromkeys(t for t, _ in support)) + row["negative"][:2]
        rng.shuffle(docs)
        builder.add(f"rgb-int-{row['id']}", row["query"], "；".join(answer_strings(row["answer"])),
                    "multi_evidence", docs, support,
                    {"dataset": "rgb", "original_file": "zh_int.json", "original_id": row["id"],
                     "variant": "integration", "original_answer": row["answer"],
                     "evidence_annotation": "各子答案对应支持句，待人工检查"})
        integrated_count += 1
        if integrated_count == 10:
            break
    if count != 10 or integrated_count != 10:
        raise ValueError("RGB 可转换样本不足，不能静默缩减样本数")
    builder.save({"repository": "https://github.com/chen700564/RGB",
                  "revision": manifest["chen700564/RGB"]["revision"],
                  "raw_sha256": {n: manifest[n]["sha256"] for n in ["zh_refine.json", "zh_int.json"]},
                  "license": "CC BY-NC-SA 4.0，非商业用途", "selection_exclusions": exclusions})
    return builder


def prepare_checklist(manifest):
    builder = DatasetBuilder("dureader_checklist")
    data = json.loads(read_verified("dureader_dev.json", manifest))
    strata = {}
    for group in data["data"]:
        for paragraph in group["paragraphs"]:
            for question in paragraph["qas"]:
                kind = question.get("type", "in-domain")
                category = ("vocab" if kind.startswith("vocab") else
                            "reasoning" if kind.startswith("reasoning") else kind)
                strata.setdefault((category, question["is_impossible"]), []).append((paragraph, question))
    rng = random.Random(SEED)
    for category in ["vocab", "phrase", "semantic-role", "reasoning"]:
        for impossible in [False, True]:
            pool = strata[(category, impossible)]
            rng.shuffle(pool)
            count = (4 if category == "reasoning" else 6 if category == "vocab" else 5) if impossible else 5
            if len(pool) < count:
                raise ValueError("DuReader 分层样本不足")
            for paragraph, question in pool[:count]:
                text = paragraph["context"]
                evidence = []
                answers = question["answers"]
                if not impossible:
                    # 原始答案跨度可能是替代答案，选一个有效跨度，保留全部答案作审核。
                    valid = [a for a in answers if a["text"] and a["answer_start"] >= 0
                             and text[a["answer_start"]:a["answer_start"]+len(a["text"])] == a["text"]]
                    if not valid:
                        raise ValueError(f"DuReader 原始答案偏移失配：{question['id']}")
                    evidence = [(text, valid[0]["text"], len(normalize(text[:valid[0]["answer_start"]])))]
                builder.add("checklist-" + question["id"], question["question"],
                            "资料不足，应拒答。" if impossible else "；".join(a["text"] for a in answers),
                            "unanswerable" if impossible else category,
                            [text], evidence,
                            {"dataset": "dureader_checklist", "original_split": "dev", "original_id": question["id"],
                             "original_type": question["type"], "original_title": paragraph.get("title", ""),
                             "original_answers": answers, "is_impossible": impossible})
                source_id = builder.source(text, "dureader_checklist")
                if paragraph.get("title"):
                    builder.data["sources"][source_id]["title"] = " ".join(paragraph["title"].split())[:300]
    builder.save({"repository": "https://github.com/baidu/DuReader/tree/master/DuReader-Checklist",
                  "revision": manifest["baidu/DuReader"]["revision"],
                  "archive_sha256": manifest["dureader_checklist.dataset.tar.gz"]["sha256"],
                  "raw_sha256": manifest["dureader_dev.json"]["sha256"],
                  "license": "原始参赛者协议，仅限非商业科研或学术用途；见 data/external/DuReader-License.txt"})
    return builder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="按固定 manifest 下载和校验官方数据快照")
    parser.add_argument("--download-only", action="store_true", help="只恢复原始快照，不修改派生集及人工审核")
    parser.add_argument("--force", action="store_true", help="明确允许覆盖已有派生集和审核视图")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data" / "external" / "manifest.json").read_text(encoding="utf-8"))
    if args.download or args.download_only:
        download_snapshots(manifest)
    if args.download_only:
        return
    if not args.force and any((ROOT / "evaluation" / "external" / f"{name}_development.json").exists()
                              for name in ["rgb", "dureader_checklist"]):
        parser.error("派生集已存在，避免覆盖人工审核；确需重建时使用 --force")
    for builder in [prepare_rgb(manifest), prepare_checklist(manifest)]:
        print(f"{builder.path.name}: {len(builder.data['cases'])} cases, {len(builder.texts)} sources")


if __name__ == "__main__":
    main()
