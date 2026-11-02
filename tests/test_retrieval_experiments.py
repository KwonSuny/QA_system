"""检索实验的标签、固定候选池、排序与前端引用渲染回归。"""

import json
import math
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

import numpy as np

from app.rag.rag_pipeline import hybrid_order
from app.evaluation.retrieval_experiments import BM25Index, binary_metrics, rank_scores, rrf, select_subset


class RetrievalExperimentTests(unittest.TestCase):
    def test_binary_metrics_count_all_positives_in_denominator(self):
        result = binary_metrics(['negative', 'a', 'b'], {'a', 'b', 'unretrieved'}, [1, 2, 4])
        self.assertEqual(result['recall@1'], 0)
        self.assertEqual(result['recall@2'], 1 / 3)
        self.assertEqual(result['recall@4'], 2 / 3)
        self.assertEqual(result['mrr@4'], 0.5)
        self.assertAlmostEqual(result['ndcg@4'], (1/math.log2(3)+0.5)/(1+1/math.log2(3)+0.5))

    def test_duplicates_or_empty_qrels_cannot_inflate_score(self):
        with self.assertRaises(ValueError):
            binary_metrics(['a', 'a'], {'a'}, [2])
        with self.assertRaises(ValueError):
            binary_metrics(['a'], set(), [1])

    def test_subset_preserves_all_positives_and_is_order_independent(self):
        corpus = [str(i) for i in range(15)]
        queries = ['q1', 'q2', 'q3']
        labels = {'q1': {'1', '2'}, 'q2': {'3', '4'}, 'q3': {'5', '6'}}
        first = select_subset(corpus, queries, labels, 2, 8, 42)
        second = select_subset(reversed(corpus), reversed(queries), labels, 2, 8, 42)
        self.assertEqual(first, second)
        qids, cids, positives = first
        self.assertEqual(len(cids), 8)
        self.assertEqual(positives, 4)
        self.assertTrue(set().union(*(labels[q] for q in qids)) <= set(cids))
        with self.assertRaises(ValueError):
            select_subset(corpus, queries, labels, 3, 2, 42)

    def test_bm25_matches_production_lexical_scoring(self):
        rows = [{'id': 'a', 'text': '甲学院开展可信大模型研究'},
                {'id': 'b', 'text': '乙学院可信大模型研究包含隐私安全'},
                {'id': 'c', 'text': '学校位于广州'}]
        scores = BM25Index([r['text'] for r in rows]).scores('可信大模型隐私')
        production = {r['id']: r['lexical_score'] for r in hybrid_order(rows, '可信大模型隐私', ['a','b','c'])}
        for i, row in enumerate(rows):
            self.assertAlmostEqual(scores[i], production[row['id']])

    def test_candidate_filter_precedes_rank_and_ties_are_stable(self):
        scores = np.asarray([1.0, 3.0, 1.0, -1.0])
        self.assertEqual(rank_scores(scores, [3, 2, 0], 2), [0, 2])
        self.assertEqual(rank_scores(scores, [3], 2, positive_only=True), [])
        self.assertEqual(rank_scores(scores, [], 2), [])

    def test_rrf_deduplicates_and_rewards_agreement(self):
        self.assertEqual(rrf([0, 1, 2], [2, 1, 3], 4), [2, 1, 0, 3])


class MarkdownRenderingTests(unittest.TestCase):
    def test_link_quotes_cannot_create_html_attributes(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('需要Node执行现有前端渲染函数')
        source = (Path(__file__).resolve().parents[1] / 'app/static/app.js').read_text(encoding='utf-8')
        functions = source[source.index('function escapeHtml('):source.index('function clampInt(')]
        inputs = ['[链接](https://example.test/" title="injected)',
                  '[普通](https://example.test/?a=1&b=2)', '<img src=x>', '[不安全](javascript:alert(1))']
        script = functions + '\nprocess.stdout.write(JSON.stringify(' + json.dumps(inputs) + '.map(markdown)));'
        result = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', check=True)
        outputs = json.loads(result.stdout)
        class Tags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))
        for rendered in outputs[:2]:
            parser = Tags(); parser.feed(rendered)
            anchors = [attrs for tag, attrs in parser.tags if tag == 'a']
            self.assertEqual(len(anchors), 1)
            self.assertEqual(set(anchors[0]), {'href', 'target', 'rel'})
        for rendered in outputs[2:]:
            parser = Tags(); parser.feed(rendered)
            self.assertFalse(any(tag in {'img', 'a'} for tag, _ in parser.tags))


if __name__ == '__main__':
    unittest.main()
