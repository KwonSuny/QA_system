"""检验计分边界，避免重复片段、缺失预测和未复核答案制造虚高成绩。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.evaluation.rag_evaluation import (
    DEFAULT_DATASET, digest, load_dataset, locate_chunks, normalize,
    retrieval_metrics, score_dataset, span_coverage,
    APIGenerationError, ROOT, replay_messages, run_api_replay, write_json,
)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.text = "甲乙丙丁戊己庚辛"
        self.case = {"id": "q1", "source_id": "doc", "category": "fact", "question": "问题",
                     "answerable": True, "reference_answer": "丙丁戊己", "history": [],
                     "evidence": [{"start": 2, "end": 6, "quote": "丙丁戊己"}]}
        self.data = {"schema_version": 1, "name": "test", "annotation_status": "draft",
                     "sources": {}, "cases": [self.case]}
        self.prediction = {"id": "q1", "retrieval_depth": 4,
                           "retrieved": [self.chunk(2, 6)], "answer": None,
                           "answer_context": [self.chunk(2, 6)],
                           "review": {}, "retrieval_ms": 10.0}

    def chunk(self, start, end):
        return {"source_id": "doc", "start": start, "end": end, "text": self.text[start:end]}

    def run_data(self, predictions=None):
        return {"dataset_sha256": digest(json.dumps(self.data, ensure_ascii=False, sort_keys=True)),
                "config": {"ks": [1, 4]}, "predictions": predictions or [self.prediction]}

    def score(self, run=None):
        return score_dataset(self.data, {"doc": self.text}, run or self.run_data(), [1, 4])

    def test_first_relevant_rank(self):
        result = retrieval_metrics(self.case, [self.chunk(0, 2), self.chunk(2, 6)], [1, 4])
        self.assertEqual(result["hit@1"], 0)
        self.assertEqual(result["mrr@4"], 0.5)
        self.assertEqual(result["evidence_recall@4"], 1)

    def test_no_relevant_chunk_is_zero(self):
        result = retrieval_metrics(self.case, [self.chunk(0, 2)], [4])
        self.assertTrue(all(value == 0 for value in result.values()))

    def test_overlaps_do_not_double_count(self):
        self.assertEqual(span_coverage(self.case["evidence"][0],
                                       [self.chunk(2, 4), self.chunk(2, 4)]), 0.5)

    def test_joint_coverage_can_exceed_single_chunk_hit(self):
        result = retrieval_metrics(self.case, [self.chunk(2, 4), self.chunk(4, 6)], [4])
        self.assertEqual(result["hit@4"], 0)
        self.assertEqual(result["evidence_recall@4"], 1)

    def test_multiple_evidence_is_macro_averaged_per_question(self):
        self.case["evidence"].append({"start": 6, "end": 8, "quote": "庚辛"})
        result = retrieval_metrics(self.case, [self.chunk(2, 6)], [4])
        self.assertEqual(result["evidence_recall@4"], 0.5)
        self.assertEqual(result["all_evidence@4"], 0)

    def test_unanswerable_excluded_from_retrieval(self):
        self.case["answerable"] = False
        self.case["evidence"] = []
        self.assertEqual(retrieval_metrics(self.case, [self.chunk(0, 8)], [4]), {})
        self.assertIsNone(self.score()["retrieval"]["metrics"]["hit@4"])

    def test_unreviewed_is_not_zero_or_perfect(self):
        review = self.score()["answer_review"]
        self.assertIsNone(review["answer_accuracy"]["value"])
        self.assertEqual(review["answer_accuracy"]["coverage"], 0)

    def test_manual_review_requires_answer_and_reviewer(self):
        self.prediction["review"] = {"answer_correct": True}
        with self.assertRaisesRegex(ValueError, "没有生成答案"):
            self.score()
        self.prediction["answer"] = "答案"
        with self.assertRaisesRegex(ValueError, "reviewer"):
            self.score()

    def test_review_denominators_and_refusal(self):
        self.prediction["answer"] = "无法回答"
        self.prediction["review"] = {"reviewer": "test", "answer_correct": False, "refused": True}
        review = self.score()["answer_review"]
        self.assertEqual(review["false_refusal_rate"]["value"], 1)
        self.assertEqual(review["supported_answer_rate"]["eligible"], 0)
        self.prediction["review"]["supported_by_context"] = True
        with self.assertRaisesRegex(ValueError, "非拒答"):
            self.score()

    def test_review_uses_actual_generation_context(self):
        self.prediction["answer"] = "答案"
        self.prediction["review"] = {"reviewer": "test", "refused": False, "supported_by_context": True}
        self.prediction["answer_context"] = [self.chunk(0, 2)]
        with self.assertRaisesRegex(ValueError, "answer_context"):
            self.score()

    def test_missing_duplicate_and_unknown_predictions_rejected(self):
        for rows in ([], [self.prediction, self.prediction], [{**self.prediction, "id": "unknown"}]):
            run = self.run_data()
            run["predictions"] = rows
            with self.assertRaisesRegex(ValueError, "恰好"):
                self.score(run)

    def test_wrong_dataset_and_insufficient_depth_rejected(self):
        run = self.run_data()
        run["dataset_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "版本"):
            self.score(run)
        self.prediction["retrieval_depth"] = 1
        with self.assertRaisesRegex(ValueError, "深度"):
            self.score()

    def test_wrong_source_or_fabricated_offsets_rejected(self):
        for changes in ({"source_id": "other"}, {"start": 1}, {"text": "编造"}):
            run = copy.deepcopy(self.run_data())
            run["predictions"][0]["retrieved"][0].update(changes)
            with self.assertRaisesRegex(ValueError, "原文"):
                self.score(run)

    def test_latency_rejects_non_finite_values(self):
        for value in (float("nan"), -1, True):
            self.prediction["retrieval_ms"] = value
            with self.assertRaisesRegex(ValueError, "耗时"):
                self.score()

    def test_chunk_location_handles_overlap_and_whitespace(self):
        chunks = locate_chunks("doc", "甲 乙\n丙丁", ["甲乙丙", "乙丙丁"])
        self.assertEqual([(c["start"], c["end"]) for c in chunks], [(0, 3), (1, 4)])
        with self.assertRaisesRegex(ValueError, "定位"):
            locate_chunks("doc", "甲乙", ["不存在"])

    def test_source_drift_fails_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text(self.text, encoding="utf-8")
            self.data["sources"] = {"doc": {"path": "source.txt", "text_sha256": digest(normalize(self.text))}}
            path = root / "data.json"
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            load_dataset(path)
            (root / "source.txt").write_text("原文变化", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "原文已变化"):
                load_dataset(path)

    def test_seed_evidence_is_valid_and_has_negative_cases(self):
        data, texts = load_dataset(DEFAULT_DATASET)
        self.assertEqual(len(data["cases"]), 30)
        self.assertEqual(len(texts), 2)
        self.assertEqual(sum(not c["answerable"] for c in data["cases"]), 4)
        self.assertEqual(data["annotation_status"], "human_reviewed")

    def test_other_source_same_offsets_cannot_cover_evidence(self):
        other = {**self.chunk(2, 6), "source_id": "other"}
        result = retrieval_metrics(self.case, [other], [4])
        self.assertEqual(result["hit@4"], 0)
        self.assertEqual(result["evidence_recall@4"], 0)

    def test_cross_source_evidence_is_scored_independently(self):
        self.case["retrieval_source_ids"] = ["doc", "other"]
        self.case["evidence"].append({"source_id": "other", "start": 2, "end": 6, "quote": "丙丁戊己"})
        result = retrieval_metrics(self.case, [self.chunk(2, 6)], [4])
        self.assertEqual(result["evidence_recall@4"], 0.5)
        self.assertEqual(result["all_evidence@4"], 0)
        other = {**self.chunk(2, 6), "source_id": "other"}
        result = retrieval_metrics(self.case, [self.chunk(2, 6), other], [4])
        self.assertEqual(result["all_evidence@4"], 1)

    def test_prediction_allows_only_declared_source_pool(self):
        self.case["retrieval_source_ids"] = ["doc", "other"]
        self.prediction["retrieved"] = [{**self.chunk(2, 6), "source_id": "other"}]
        report = score_dataset(self.data, {"doc": self.text, "other": self.text}, self.run_data(), [4])
        self.assertEqual(report["retrieval"]["metrics"]["hit@4"], 0)
        self.case["retrieval_source_ids"] = ["doc"]
        with self.assertRaisesRegex(ValueError, "原文"):
            score_dataset(self.data, {"doc": self.text, "other": self.text}, self.run_data(), [4])

    def test_dataset_rejects_evidence_outside_source_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text(self.text, encoding="utf-8")
            source = {"path": "source.txt", "text_sha256": digest(normalize(self.text))}
            self.data["sources"] = {"doc": source, "other": source}
            self.case["evidence"][0]["source_id"] = "other"
            path = root / "data.json"
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "证据来源"):
                load_dataset(path)
            self.case["retrieval_source_ids"] = ["doc", "other"]
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            load_dataset(path)
            self.case["retrieval_source_ids"] = ["doc", "doc"]
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "检索资料范围"):
                load_dataset(path)

    def test_development_and_test_have_disjoint_fact_groups(self):
        development, dev_texts = load_dataset(DEFAULT_DATASET.parent / "development.json")
        held_out, test_texts = load_dataset(DEFAULT_DATASET.parent / "test.json")
        self.assertEqual(len(development["cases"]), 60)
        self.assertEqual(len(held_out["cases"]), 24)
        self.assertEqual(dev_texts, test_texts)
        self.assertEqual(len(dev_texts), 4)
        dev_groups = {g for c in development["cases"] for g in c["fact_groups"]}
        test_groups = {g for c in held_out["cases"] for g in c["fact_groups"]}
        self.assertFalse(dev_groups & test_groups)
        all_cases = development["cases"] + held_out["cases"]
        self.assertEqual(len({normalize(c["question"]) for c in all_cases}), len(all_cases))
        for case in all_cases:
            self.assertEqual(set(case["retrieval_source_ids"]), set(dev_texts))
            self.assertTrue(case["fact_groups"])

    def test_annotation_review_cannot_silently_claim_human_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text(self.text, encoding="utf-8")
            self.data["sources"] = {"doc": {"path": "source.txt", "text_sha256": digest(normalize(self.text))}}
            path = root / "data.json"
            self.case["annotation_review"] = {"approved": True, "reviewer": None}
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewer"):
                load_dataset(path)
            self.case["annotation_review"]["reviewer"] = "test"
            self.data["annotation_status"] = "human_reviewed"
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不一致"):
                load_dataset(path)
            self.case["annotation_status"] = "human_reviewed"
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            load_dataset(path)
            self.case["annotation_review"]["approved"] = False
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不一致"):
                load_dataset(path)


class APIReplayTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "kb_store").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="api-replay-test-", dir=ROOT / "kb_store")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.texts = {"doc": "甲乙丙丁"}
        self.data = {"schema_version": 1, "name": "api-test", "annotation_status": "draft",
                     "sources": {}, "cases": []}
        self.baseline = {"schema_version": 1, "config": {"ks": [1, 4], "generation": "local",
                         "temperature": 0.0, "max_new_tokens": 512, "answer_top_k": 1,
                         "llm_model": "local", "code_sha256": {"llm_answerer.py":
                         digest((ROOT / "app" / "llm" / "llm_answerer.py").read_text(encoding="utf-8-sig"))}},
                         "predictions": []}
        for i in range(2):
            case_id = f"q{i}"
            self.data["cases"].append({"id": case_id, "source_id": "doc", "category": "multi_turn",
                "question": f"问题{i}", "reference_answer": "NEVER_SEND_REFERENCE", "answerable": True,
                "history": [{"role": "user", "content": f"历史{j}"} for j in range(6)],
                "evidence": [{"start": 0, "end": 2, "quote": "甲乙"}]})
            chunk = {"source_id": "doc", "start": 0, "end": 2, "text": "甲乙", "score": 0.12345}
            self.baseline["predictions"].append({"id": case_id, "retrieval_depth": 4, "retrieved": [chunk],
                "answer_context": [chunk], "answer": "旧答案", "retrieval_ms": 12,
                "generation_ms": 10, "first_token_ms": 1,
                "review": {"reviewer": "human", "answer_correct": True, "refused": False,
                           "supported_by_context": True}})
        self.baseline["dataset_sha256"] = digest(json.dumps(self.data, ensure_ascii=False, sort_keys=True))
        self.source = self.root / "local.json"
        write_json(self.source, self.baseline)
        self.output = self.root / "api"
        self.credentials = patch.multiple("app.evaluation.rag_evaluation", API_KEY="test-key", BASE_URL="https://example.test/v1")
        self.credentials.start()
        self.addCleanup(self.credentials.stop)

    def stream(self, answer="新答案"):
        chunks = [SimpleNamespace(model="returned-model", usage=None, choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=answer), finish_reason="stop")]),
                  SimpleNamespace(model="returned-model", choices=[], usage=SimpleNamespace(
                    model_dump=lambda **kwargs: {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23}))]
        stream = Mock()
        stream.__iter__ = Mock(return_value=iter(chunks))
        return stream

    def run_api(self, client, resume=False):
        return run_api_replay(self.data, self.texts, self.baseline, self.source,
                              self.output, "qwen3.8-flash", resume, client)

    def test_exact_context_history_prompt_and_fresh_reviews(self):
        before = copy.deepcopy(self.baseline)
        client = Mock()
        streams = [self.stream(), self.stream()]
        client.chat.completions.create.side_effect = streams
        expected = replay_messages(self.data, self.baseline)
        run = self.run_api(client)
        self.assertEqual(before, self.baseline)
        for row, old, call in zip(run["predictions"], before["predictions"],
                                  client.chat.completions.create.call_args_list):
            for field in ("retrieved", "answer_context", "retrieval_ms", "retrieval_depth"):
                self.assertEqual(row[field], old[field])
            self.assertEqual(call.kwargs["messages"], expected[row["id"]])
            serialized = json.dumps(call.kwargs["messages"], ensure_ascii=False)
            self.assertNotIn("NEVER_SEND_REFERENCE", serialized)
            self.assertNotIn("历史0", serialized)
            self.assertIn("历史5", serialized)
            self.assertIn('相关度=\\"0.12\\"', serialized)
            self.assertEqual(call.kwargs["max_tokens"], 512)
            self.assertEqual(call.kwargs["temperature"], 0.0)
            self.assertEqual(call.kwargs["extra_body"], {"enable_thinking": False})
            self.assertEqual(row["api_response"]["usage"]["total_tokens"], 23)
            self.assertTrue(all(row["review"][k] is None for k in
                                ("reviewer", "answer_correct", "supported_by_context", "refused")))
        for stream in streams:
            stream.close.assert_called_once()
        self.assertEqual(score_dataset(self.data, self.texts, run, [1, 4])["retrieval"],
                         score_dataset(self.data, self.texts, before, [1, 4])["retrieval"])
        self.assertNotIn("test-key", json.dumps(run))
        self.assertNotIn("https://example.test", json.dumps(run))

    def test_drift_or_missing_actual_context_prevents_calls(self):
        client = Mock()
        for change in ("dataset", "prompt", "context"):
            original = copy.deepcopy(self.baseline)
            if change == "dataset":
                self.baseline["dataset_sha256"] = "changed"
            elif change == "prompt":
                self.baseline["config"]["code_sha256"]["llm_answerer.py"] = "changed"
            else:
                self.baseline["predictions"][0]["answer_context"] = None
            with self.assertRaises(ValueError):
                self.run_api(client)
            self.baseline = original
        client.chat.completions.create.assert_not_called()

    def test_missing_environment_fails_before_api_or_checkpoint(self):
        client = Mock()
        for name in ("API_KEY", "BASE_URL"):
            with patch(f"app.evaluation.rag_evaluation.{name}", None), self.assertRaisesRegex(ValueError, name):
                self.run_api(client)
        client.chat.completions.create.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_checkpoint_resumes_only_unfinished_and_sanitizes_error(self):
        client = Mock()
        failure = RuntimeError("test-key https://example.test/private")
        client.chat.completions.create.side_effect = [self.stream(), failure]
        with self.assertRaises(APIGenerationError) as result:
            self.run_api(client)
        self.assertNotIn("test-key", str(result.exception))
        self.assertNotIn("example.test", str(result.exception))
        partial = json.loads((self.output / "predictions.partial.json").read_text(encoding="utf-8"))
        self.assertEqual(partial["completed_ids"], ["q0"])
        second = Mock()
        second.chat.completions.create.return_value = self.stream("续跑答案")
        run = self.run_api(second, resume=True)
        second.chat.completions.create.assert_called_once()
        self.assertEqual([p["answer"] for p in run["predictions"]], ["新答案", "续跑答案"])

    def test_resume_rejects_context_or_messages_changes(self):
        client = Mock()
        client.chat.completions.create.side_effect = [self.stream(), RuntimeError("interrupted")]
        with self.assertRaises(APIGenerationError):
            self.run_api(client)
        path = self.output / "predictions.partial.json"
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["predictions"][0]["messages"][0]["content"] = "篡改"
        write_json(path, saved)
        client.reset_mock()
        with self.assertRaisesRegex(ValueError, "提示词"):
            self.run_api(client, resume=True)
        client.chat.completions.create.assert_not_called()
        saved["predictions"][0]["messages"] = replay_messages(self.data, self.baseline)["q0"]
        saved["predictions"][1]["messages"][0]["content"] = "篡改未完成题"
        write_json(path, saved)
        with self.assertRaisesRegex(ValueError, "提示词"):
            self.run_api(client, resume=True)
        client.chat.completions.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
