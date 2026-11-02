"""检验公开数据转换时的范围、原始偏移和审核状态。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.evaluation.external_datasets as external
from app.evaluation.rag_evaluation import load_dataset


class ExternalDatasetTests(unittest.TestCase):
    def test_imported_datasets_load_without_overwriting_human_reviews(self):
        for name, answerable_count in [("rgb", 30), ("dureader_checklist", 20)]:
            path = external.ROOT / "evaluation" / "external" / f"{name}_development.json"
            data, texts = load_dataset(path)
            self.assertEqual(len(data["cases"]), 40)
            self.assertEqual(sum(c["answerable"] for c in data["cases"]), answerable_count)
            self.assertEqual(data["annotation_status"], "imported_pending_review")
            for case in data["cases"]:
                self.assertIn(case["annotation_review"]["approved"], (None, True, False))
                self.assertEqual(case["history"], [])
                self.assertTrue(set(case["retrieval_source_ids"]) <= texts.keys())

    def test_new_imports_start_pending_without_claiming_human_review(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(external, "ROOT", Path(directory)):
            builder = external.DatasetBuilder("fixture")
            builder.add("q", "甲有多少人？", "12人", "fact", ["甲有12人。"],
                        [("甲有12人。", "12人")], {"dataset": "fixture", "original_id": "q"})
            builder.save({"test_fixture": True})
            data, _ = load_dataset(builder.path)
            self.assertEqual(data["annotation_status"], "imported_pending_review")
            self.assertIsNone(data["cases"][0]["annotation_review"]["approved"])

    def test_rgb_negative_scope_excludes_positive_evidence(self):
        path = external.ROOT / "evaluation" / "external" / "rgb_development.json"
        data, _ = load_dataset(path)
        grouped = {}
        for case in data["cases"]:
            origin = case["external_origin"]
            if origin["original_file"] == "zh_refine.json":
                grouped.setdefault(origin["original_id"], {})[origin["variant"]] = case
        self.assertEqual(len(grouped), 10)
        for variants in grouped.values():
            clean, noise, missing = (variants[v] for v in ["clean", "noise", "no_evidence"])
            self.assertEqual(clean["fact_groups"], missing["fact_groups"])
            self.assertEqual(clean["evidence"], noise["evidence"])
            self.assertFalse(set(clean["retrieval_source_ids"]) & set(missing["retrieval_source_ids"]))
            self.assertFalse(missing["answerable"])
            self.assertEqual(missing["evidence"], [])

    def test_multivalue_answer_not_assumed_to_match_group_count(self):
        row = {"answer": ["喜剧", "甲", "乙"], "positive": [["类型为喜剧。"], ["导演为甲和乙。"]]}
        support = external.rgb_support(row)
        self.assertEqual(len(support), 2)
        with self.assertRaises(ValueError):
            external.rgb_support({"answer": ["甲"], "positive": [["甲导演。"], ["电影票房亿元。"]]})

    def test_original_repeated_answer_offset_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(external, "ROOT", Path(directory)):
            builder = external.DatasetBuilder("fixture")
            builder.add("q", "后一段是多少？", "12", "fact", ["甲12；乙12"],
                        [("甲12；乙12", "12", 5)], {"dataset": "fixture", "original_id": "q"})
            self.assertEqual(builder.data["cases"][0]["evidence"][0]["start"], 5)

    def test_modified_raw_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(external, "RAW", Path(directory)):
            (Path(directory) / "sample.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "校验失败"):
                external.read_verified("sample.json", {"sample.json": {"sha256": "0" * 64}})

    def test_official_answer_offsets_survive_whitespace_normalization(self):
        path = external.ROOT / "evaluation" / "external" / "dureader_checklist_development.json"
        data, texts = load_dataset(path)
        for case in data["cases"]:
            if not case["answerable"]:
                continue
            official = case["external_origin"]["original_answers"][0]
            text = texts[case["source_id"]]
            start = official["answer_start"]
            self.assertEqual(text[start:start+len(official["text"])], official["text"])
            self.assertEqual(case["evidence"][0]["start"], len(external.normalize(text[:start])))


if __name__ == "__main__":
    unittest.main()
