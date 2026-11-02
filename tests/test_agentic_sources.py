"""智能来源选择、实际引用与失败边界；不调用外部模型或搜索服务。"""

import json
import unittest
import warnings
from unittest.mock import Mock

from agentic_pipeline import AgenticPipeline


def route(kind, question="什么是向量检索？", query="", specific=False, timely=False):
    return {"action": "answer", "requirements": [{"question": question, "route": kind,
        "public_query": query, "subject_specific": specific, "time_sensitive": timely}]}


def ground(source="S1"):
    plan = {"action": "answer", "resolved_question": "甲机构有多少教师？", "requirements": [
        {"question": "甲机构教师人数", "source_ids": [source]}]}
    draft = {"claims": [{"requirement_id": "R1", "text": "甲机构教师44人。",
        "citations": [{"evidence_id": "E1", "quote": "甲机构教师44人"}]}], "unanswered": []}
    verdict = {"intent_complete": True, "missing_requirements": [],
        "claims": [{"id": "C1", "supported": True, "relevant": True}],
        "requirements": [{"id": "R1", "covered": True}]}
    return plan, draft, verdict


DOC = {"source_id": "kb/D1", "kb_id": "kb", "document_id": "D1", "title": "甲机构", "opening": "甲机构资料"}
HIT = {"text": "甲机构教师44人。", "score": 0.8, "chunk_index": 0, "kb_id": "kb", "document_id": "D1"}
WEB = {"title": "甲机构官网", "url": "https://example.org/about", "text": "甲机构教师44人。",
       "retrieved_at": "2026-10-20T00:00:00+00:00"}
GENERAL_VERDICT = {"correct": True, "complete": True, "stable_general": True,
                   "entity_specific": False, "needs_external_verification": False}
ROUTE_VERDICT = {"intent_preserved": True, "routes_appropriate": True, "public_queries_safe": True}


class AgenticSourceTests(unittest.TestCase):
    def test_explicit_fallback_is_removed_before_model_and_from_polluted_plan(self):
        plan = route('web', question='甲机构教师多少人？', query='甲机构教师人数')
        plan['requirements'].append(route('web', question='如果知识库无法回答，请提供搜索到的关于甲机构教师的网页内容。',
                                          query='甲机构教师人数')['requirements'][0])
        result, complete, _ = self.run_pipeline([plan, *ground()], web=Mock(return_value=[WEB]),
             question='甲机构教师多少人？如果搜索到网页但不能回答，请输出搜索到的内容。')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(len(result['trace']['route_plan']), 1)
        self.assertTrue(result['response_policy']['show_search_on_failure'])
        data = json.loads(complete.call_args_list[0].args[0][1]['content'])
        self.assertEqual(data['original_question'], '甲机构教师多少人？')

    def test_existing_web_evidence_can_be_reused_without_second_search(self):
        missing = {'intent_complete': True, 'missing_requirements': [], 'claims': [],
                   'requirements': [{'id': 'R1', 'covered': False}]}
        plan, draft, verdict = ground('S1')
        draft['claims'][0]['citations'][0]['evidence_id'] = 'E2'
        result, _, _ = self.run_pipeline([route('web', query='甲机构教师人数', timely=True), plan,
            {'claims': []}, missing, {'action': 'use_existing', 'query': '', 'public_query_safe': True}, draft, verdict],
            docs=[DOC], web=Mock(return_value=[WEB]))
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['trace']['search_calls'], 1)
        self.assertEqual(result['trace']['model_calls'], 8)
        self.assertTrue(result['trace']['grounded_runs'][1]['plan_reused'])

    def test_do_not_show_search_results_overrides_fallback_detection(self):
        plan = route('web', query='甲机构教师人数')
        plan['response_policy'] = {'show_search_on_failure': True, 'show_search_results': True}
        missing = {'intent_complete': True, 'missing_requirements': [], 'claims': [],
                   'requirements': [{'id': 'R1', 'covered': False}]}
        result, _, _ = self.run_pipeline([plan, ground()[0], {'claims': []}, missing,
                {'action': 'stop', 'query': '', 'public_query_safe': True}], web=Mock(return_value=[WEB]),
                question='甲机构多少人？如果不能回答，不要输出搜索结果。')
        self.assertFalse(result['show_search_results'])

    def test_verifier_cannot_add_claim_but_writer_can_regenerate_with_evidence(self):
        plan, draft, verdict = ground()
        plan_route = route('web', query='甲机构教师人数')
        result, complete, _ = self.run_pipeline([plan_route, plan, {'claims': []}, verdict,
            {'action': 'stop', 'query': '', 'public_query_safe': True}, draft, verdict], web=Mock(return_value=[WEB]))
        self.assertEqual(result['status'], 'answered')
        self.assertTrue(result['trace']['regenerated_after_validation_failure'])
        self.assertEqual(result['trace']['model_calls'], 8)
        self.assertEqual(len(result['claims']), 1)

    def test_same_named_local_source_cannot_override_web_plan(self):
        plan, draft, verdict = ground('S2')
        plan['requirements'][0]['subject'] = '甲机构'
        web = Mock(return_value=[WEB])
        result, _, _ = self.run_pipeline([route('web', question='甲机构院长是谁？', query='甲机构领导', timely=True),
                                         plan, draft, verdict], docs=[DOC], web=web)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['answer_sources'], ['web'])
        self.assertEqual(result['trace']['grounded_runs'][0]['plan']['requirements'][0]['source_ids'], ['S2'])

    def test_local_first_can_search_twice_within_ten_calls(self):
        plan, draft, verdict = ground('S1')
        missing = {'intent_complete': True, 'missing_requirements': [], 'claims': [],
                   'requirements': [{'id': 'R1', 'covered': False}]}
        draft['claims'][0]['citations'][0]['evidence_id'] = 'E3'
        responses = [route('kb', question='甲机构教师多少人？', query='甲机构教师人数'), ROUTE_VERDICT,
                     plan, {'claims': []}, missing, {'claims': []}, missing,
                     {'action': 'search', 'query': '甲机构教师人数官网', 'public_query_safe': True}, draft, verdict]
        complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in responses])
        kb = Mock(return_value=[{**HIT, 'text': '甲机构教师人数暂未公开。'}])
        web = Mock(side_effect=[[{**WEB, 'text': '甲机构没有公布教师人数。'}],
                                [{**WEB, 'url': 'https://example.org/new-staff'}]])
        result = AgenticPipeline(complete, kb, web).run('甲机构教师多少人？', [], [DOC])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['trace']['search_calls'], 2)
        self.assertEqual(result['trace']['model_calls'], 10)
        self.assertEqual(result['trace']['retrieval_strategy'], 'local_first')
        self.assertTrue(result['trace']['grounded_runs'][1]['plan_reused'])

    def test_fallback_output_policy_keeps_search_results_separate_from_claims(self):
        plan = route('web', question='甲机构教师多少人？', query='甲机构教师人数')
        plan['response_policy'] = {'style': 'concise', 'show_search_on_failure': True}
        missing = {'intent_complete': True, 'missing_requirements': [], 'claims': [],
                   'requirements': [{'id': 'R1', 'covered': False}]}
        result, complete, _ = self.run_pipeline([plan, ground()[0], {'claims': []}, missing,
                 {'action': 'stop', 'query': '', 'public_query_safe': True}], web=Mock(return_value=[WEB]),
                 question='甲机构教师多少人？如果不能回答，请输出搜索到的内容。')
        self.assertEqual(result['status'], 'refused')
        self.assertTrue(result['show_search_results'])
        self.assertFalse(result['search_results'][0]['verified'])
        self.assertEqual(result['citations'], [])
        self.assertEqual(result['answer_sources'], [])
        writer_data = json.loads(complete.call_args_list[3].args[0][1]['content'])
        self.assertEqual(writer_data['response_policy']['style'], 'concise')
        self.assertNotIn('如果', writer_data['original_question'])
        verifier_data = json.loads(complete.call_args_list[4].args[0][1]['content'])
        self.assertNotIn('opening', verifier_data['sources'][0])

    def test_line_chunks_preserve_table_row_and_continuous_original(self):
        from agentic_pipeline import web_chunks
        row = '| 甲 | 院长 | 负责学院行政工作 |\n'
        text = '导航\n' * 390 + row + '正文\n' * 20
        chunks = web_chunks(text)
        self.assertTrue(any(row in chunk for chunk in chunks))
        self.assertTrue(all(chunk in text for chunk in chunks))

    def test_relevant_excerpt_is_not_lost_when_page_text_is_navigation(self):
        web = Mock(return_value=[{**WEB, "text": "网站导航 联系我们 友情链接", "content_kind": "page_text",
                                  "search_excerpt": "甲机构教师44人。"}])
        result, _, _ = self.run_pipeline([route('web', query='甲机构教师人数'), *ground()], web=web)
        self.assertEqual(result['status'], 'answered')
        cited = [e for e in result['evidence'] if e['id'] in result['citations']]
        self.assertEqual(cited[0]['content_kind'], 'search_excerpt')
        self.assertEqual(cited[0]['text'], '甲机构教师44人。')

    def test_followup_uses_new_public_query_and_cites_new_excerpt(self):
        missing = {"intent_complete": True, "missing_requirements": [], "claims": [],
                   "requirements": [{"id": "R1", "covered": False, "source_ids": []}]}
        _, draft, verdict = ground('S2')
        draft['claims'][0]['citations'][0]['evidence_id'] = 'E2'
        responses = [route('web', query='甲机构 教师人数'), ROUTE_VERDICT,
                     ground()[0], {"claims": [], "unanswered": ["R1"]}, missing,
                     {"action": "search", "query": "甲机构 教师人数 官网", "public_query_safe": True},
                     draft, verdict]
        complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in responses])
        unrelated = {**WEB, 'text': '甲机构举办活动，没有教师人数。'}
        target = {**WEB, 'url': 'https://example.org/staff', 'content_kind': 'search_excerpt'}
        web = Mock(side_effect=[[unrelated], [target]])
        result = AgenticPipeline(complete, Mock(), web).run('甲机构教师多少人？', [], [])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['trace']['search_calls'], 2)
        self.assertEqual(result['trace']['model_calls'], 8)
        self.assertEqual(web.call_args_list[1].args[0], '甲机构教师人数官网')
        cited = [e for e in result['evidence'] if e['id'] in result['citations']]
        self.assertEqual(cited[0]['url'], target['url'])
        self.assertEqual(cited[0]['content_kind'], 'search_excerpt')

    def test_followup_cannot_send_unsafe_or_duplicate_query(self):
        for safe, query in [(False, 'private data'), (True, '甲机构 教师人数')]:
            responses = [route('web', query='甲机构 教师人数'), ROUTE_VERDICT,
                         {"action": "search", "query": query, "public_query_safe": safe}]
            complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in responses])
            web = Mock(return_value=[])
            result = AgenticPipeline(complete, Mock(), web).run('甲机构教师多少人？', [], [])
            self.assertEqual(result['trace']['search_calls'], 1)
            web.assert_called_once()

    def test_extra_closing_quote_is_normalized_but_additional_content_is_rejected(self):
        from rag_pipeline import json_object
        self.assertEqual(json_object('{"action":"answer"}"'), {'action': 'answer'})
        for raw in ['{"action":"answer"} extra', '{"action":"answer"}{"override":true}']:
            with self.assertRaises(ValueError):
                json_object(raw)

    def test_local_greedy_config_does_not_inherit_sampling_parameters(self):
        from llm_answerer import LLMAnswerer
        from transformers import GenerationConfig
        answerer = object.__new__(LLMAnswerer)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            original = GenerationConfig(do_sample=False, temperature=0.7, top_p=0.8, top_k=20)
        answerer.model = Mock(generation_config=original)
        config = answerer._generation_config(0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            config.validate()
        self.assertEqual(caught, [])
        self.assertFalse(config.do_sample)
        self.assertEqual(original.temperature, 0.7)
        self.assertEqual(original.top_p, 0.8)

    def run_pipeline(self, responses, docs=None, web=None, kb=None, question="请回答问题"):
        responses = [responses[0], ROUTE_VERDICT, *responses[1:]]
        complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in [*responses, {}, {}]])
        kb = kb or Mock(return_value=[HIT])
        result = AgenticPipeline(complete, kb, web).run(question, [], docs or [])
        return result, complete, kb

    def test_general_answer_has_no_fake_evidence_or_tool_calls(self):
        web = Mock()
        result, complete, kb = self.run_pipeline([route("general"), {"answer": "向量检索通过向量距离查找语义相近的文本。"}, GENERAL_VERDICT], web=web)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer_sources"], ["model"])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["citations"], [])
        self.assertIn("未经过外部资料核验", result["answer"])
        self.assertEqual(complete.call_count, 4)
        web.assert_not_called(); kb.assert_not_called()

    def test_general_verification_is_not_replaced_by_model_confidence(self):
        result, _, _ = self.run_pipeline([route("general"), {"answer": "随便编造的解释"},
                                         {**GENERAL_VERDICT, "correct": False}])
        self.assertEqual(result["status"], "refused")
        self.assertNotIn("随便编造", result["answer"])

    def test_specific_or_current_facts_cannot_escape_to_general_route(self):
        for specific, timely in [(True, False), (False, True)]:
            result, complete, _ = self.run_pipeline([route("general", specific=specific, timely=timely)])
            self.assertEqual(result["status"], "refused")
            self.assertEqual(complete.call_count, 2)
            self.assertNotIn("model", result["answer_sources"])

    def test_kb_answer_uses_k_citations_and_only_actual_support(self):
        result, _, _ = self.run_pipeline([route("kb"), *ground()], docs=[DOC])
        self.assertEqual(result["answer"], "甲机构教师44人。 [K1]")
        self.assertEqual(result["answer_sources"], ["kb"])
        self.assertEqual(result["citations"], ["K1"])
        self.assertEqual(result["claims"][0]["citations"][0]["evidence_id"], "K1")

    def test_web_answer_uses_actual_page_and_w_citations(self):
        web = Mock(return_value=[WEB])
        result, _, kb = self.run_pipeline([route("web", query="甲机构 教师 人数"), *ground()], web=web)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer_sources"], ["web"])
        self.assertIn("[W1]", result["answer"])
        self.assertEqual(result["evidence"][0]["url"], WEB["url"])
        self.assertEqual(result["trace"]["search_calls"], 1)
        kb.assert_not_called()

    def test_web_failure_does_not_fabricate_a_reference(self):
        result, _, _ = self.run_pipeline([route("web", query="甲机构 教师人数")], web=Mock(side_effect=RuntimeError("secret")))
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["evidence"], [])
        self.assertTrue(result["warnings"])
        self.assertNotIn("secret", json.dumps(result))

    def test_insufficient_kb_can_trigger_one_web_fallback(self):
        kb = Mock(return_value=[])
        result, complete, _ = self.run_pipeline([route("kb", query="甲机构 教师人数"), ground()[0], *ground("S2")[1:]],
            docs=[DOC], kb=kb, web=Mock(return_value=[WEB]))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer_sources"], ["web"])
        self.assertEqual(result["trace"]["search_calls"], 1)
        self.assertLessEqual(complete.call_count, 10)

    def test_explicit_kb_only_request_overrides_general_or_web_plan(self):
        web = Mock()
        result, _, _ = self.run_pipeline([route("general")], web=web, question="只根据知识库资料回答")
        self.assertEqual(result["status"], "refused")
        web.assert_not_called()

    def test_do_not_browse_still_allows_stable_general_knowledge(self):
        web = Mock()
        result, _, _ = self.run_pipeline([route("general"), {"answer": "向量检索以向量相似度匹配文本。"}, GENERAL_VERDICT],
            web=web, question="解释向量检索，不要联网")
        self.assertEqual(result["answer_sources"], ["model"])
        web.assert_not_called()

    def test_general_draft_cannot_supply_invented_url_or_citations(self):
        for answer in ["这是答案 [W1]", "参考 https://example.org"]:
            result, complete, _ = self.run_pipeline([route("general"), {"answer": answer}])
            self.assertEqual(result["status"], "refused")
            self.assertEqual(complete.call_count, 3)

    def test_malformed_route_does_not_trigger_tools(self):
        result, _, kb = self.run_pipeline([{"action": "answer", "requirements": [None]}])
        self.assertEqual(result["status"], "failed")
        kb.assert_not_called()

    def test_general_and_grounded_results_keep_distinct_origins(self):
        plan = route("kb")
        plan["requirements"].extend(route("general")["requirements"])
        result, _, _ = self.run_pipeline([plan, *ground(), {"answer": "通用概念解释。"}, GENERAL_VERDICT], docs=[DOC])
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer_sources"], ["kb", "model"])
        self.assertEqual(result["citations"], ["K1"])
        self.assertEqual(result["trace"]["model_calls"], 7)

    def test_route_verifier_blocks_omission_or_private_query_before_search(self):
        web = Mock()
        for verdict in [{**ROUTE_VERDICT, 'intent_preserved': False},
                        {**ROUTE_VERDICT, 'public_queries_safe': False}]:
            complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in [
                route('web', query='不应发送的内容'), verdict,
                route('web', query='不应发送的内容'), verdict]])
            result = AgenticPipeline(complete, Mock(), web).run('原问题', [], [])
            self.assertIn(result['status'], ('failed', 'refused'))
        web.assert_not_called()

    def test_missing_public_query_is_repaired_before_kb_fallback(self):
        web = Mock(return_value=[WEB])
        responses = [route('kb', question='甲机构有多少教师？'), ROUTE_VERDICT,
                     route('kb', question='甲机构有多少教师？', query='甲机构 教师 人数'), ROUTE_VERDICT,
                     ground()[0], *ground('S2')[1:]]
        complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in responses])
        result = AgenticPipeline(complete, Mock(return_value=[]), web).run('甲机构有多少教师？', [], [DOC])
        self.assertEqual(result['status'], 'answered')
        web.assert_called_once_with('甲机构教师人数')
        self.assertLessEqual(result['trace']['model_calls'], 10)

    def test_rejected_answer_as_question_can_be_replanned(self):
        web = Mock(return_value=[WEB])
        bad = route('kb', question='甲机构教师44人。')
        responses = [bad, {**ROUTE_VERDICT, 'intent_preserved': False},
                     route('web', question='甲机构有多少教师？', query='甲机构 教师 人数'),
                     ROUTE_VERDICT, *ground()]
        complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in responses])
        result = AgenticPipeline(complete, Mock(), web).run('甲机构有多少教师？', [], [])
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(len(result['trace']['route_errors']), 1)
        first_data = json.loads(complete.call_args_list[0].args[0][1]['content'])
        self.assertRegex(first_data['current_date'], r'^\d{4}-\d{2}-\d{2}$')

    def test_private_empty_query_is_not_automatically_sent(self):
        web = Mock()
        responses = [route('kb', question='内部账户余额？'), ROUTE_VERDICT,
                     route('kb', question='内部账户余额？'), ROUTE_VERDICT]
        complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in responses])
        result = AgenticPipeline(complete, Mock(), web).run('内部账户余额？', [], [])
        web.assert_not_called()
        self.assertIn('未生成', ''.join(result['warnings']))
