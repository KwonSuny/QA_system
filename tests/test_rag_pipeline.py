"""检验来源边界、引用校验、拒答和有界补检；不调用真实模型服务。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["ANONYMIZED_TELEMETRY"] = "False"

from rag_pipeline import EvidencePipeline, document_fingerprint, heading_contexts, hybrid_order, json_object, merge_documents, source_documents


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.documents = [{"source_id": "kb/D1", "kb_id": "kb", "document_id": "D1",
                           "title": "甲学院", "opening": "甲学院人数资料"}]
        self.hit = {"text": "甲学院教职工44人，专任教师26人。", "score": 0.7, "chunk_index": 0,
                    "document_id": "D1", "kb_id": "kb"}
        self.plan = {"action": "answer", "resolved_question": "甲学院有多少教职工？",
                     "requirements": [{"question": "甲学院教职工总人数", "source_ids": ["S1"]}]}
        self.draft = {"claims": [{"requirement_id": "R1", "text": "甲学院教职工44人。",
                                 "citations": [{"evidence_id": "E1", "quote": "甲学院教职工44人"}]}], "unanswered": []}
        self.verdict = {"intent_complete": True, "missing_requirements": [],
                        "claims": [{"id": "C1", "supported": True, "relevant": True, "reason": "人数有据"}],
                        "requirements": [{"id": "R1", "covered": True, "reason": "完整"}]}

    def run_pipeline(self, responses, search=None):
        complete = Mock(side_effect=[json.dumps(r, ensure_ascii=False) for r in responses])
        search = search or Mock(return_value=[self.hit])
        result = EvidencePipeline(complete, search).run("它有多少人？", [{"role":"user","content":"问甲学院"}], self.documents)
        return result, complete, search

    def test_verified_claims_are_the_only_rendered_answer(self):
        self.draft["answer"] = "自由散文中的错误数字999人，不应输出"
        result,complete,search = self.run_pipeline([self.plan,self.draft,self.verdict])
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"], "甲学院教职工44人。 [E1]")
        self.assertNotIn("999", result["answer"])
        self.assertEqual(result["trace"]["model_calls"], 3)
        self.assertEqual(search.call_args.args[1], "甲学院教职工总人数")
        self.assertNotIn("history", json.loads(complete.call_args_list[1].args[0][1]["content"]))

    def test_unknown_source_does_not_trigger_search(self):
        self.plan["requirements"][0]["source_ids"] = ["other-user-kb"]
        result,complete,search = self.run_pipeline([self.plan])
        self.assertEqual(result["status"], "failed")
        search.assert_not_called()
        self.assertEqual(complete.call_count, 1)

    def test_fabricated_quote_is_not_published(self):
        self.draft["claims"][0]["citations"][0]["quote"] = "甲学院教职工999人"
        empty = {**self.verdict, "claims": [], "requirements": [{"id":"R1","covered":False}]}
        result,complete,_ = self.run_pipeline([self.plan,self.draft,empty,self.draft,empty])
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["claims"], [])
        self.assertLessEqual(complete.call_count, 5)

    def test_existing_quote_with_false_claim_requires_semantic_verification(self):
        self.draft["claims"][0]["text"] = "甲学院专任教师44人。"
        self.verdict["claims"][0].update(supported=False,reason="44是教职工，不是专任教师")
        self.verdict["requirements"][0]["covered"] = False
        result,complete,_ = self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result["status"], "refused")
        self.assertNotIn("专任教师44", result["answer"])
        self.assertEqual(complete.call_count, 5)

    def test_cross_source_binding_cannot_be_used_as_proof(self):
        self.documents.append({"source_id":"kb2/D1","kb_id":"kb2","document_id":"D1",
                               "title":"乙学院","opening":"乙学院科研资料"})
        self.plan["requirements"].append({"question":"乙学院科研平台数量","source_ids":["S2"]})
        other = {**self.hit,"text":"乙学院科研平台8个。","kb_id":"kb2"}
        self.draft["claims"][0]["citations"] = [{"evidence_id":"E2","quote":"乙学院科研平台8个"}]
        search=Mock(side_effect=[ [self.hit],[other],[self.hit],[other] ])
        empty = {**self.verdict, "claims": [], "requirements": [{"id":"R1","covered":False},{"id":"R2","covered":False}]}
        result,_,_ = self.run_pipeline([self.plan,self.draft,empty,self.draft,empty],search)
        self.assertEqual(result["status"],"refused")

    def test_true_but_irrelevant_background_does_not_answer_question(self):
        self.verdict["claims"][0].update(relevant=False,reason="问学费，人数不能作答")
        self.verdict["requirements"][0]["covered"] = False
        result,_,_ = self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result["status"],"refused")

    def test_incomplete_answer_is_partial_and_retry_is_bounded(self):
        self.plan["requirements"].append({"question":"甲学院专任教师人数","source_ids":["S1"]})
        self.verdict["requirements"].append({"id":"R2","covered":False,"reason":"漏专任人数","retry_query":"甲学院专任教师有多少名？"})
        result,complete,search = self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result["status"],"partial")
        self.assertIn("缺少足够依据", result["answer"])
        self.assertIn("甲学院教职工44", result["answer"])
        self.assertEqual(complete.call_count,5)
        self.assertEqual(search.call_args.args[1],"甲学院专任教师有多少名？")

    def test_retry_can_complete_missing_requirement(self):
        self.plan["requirements"].append({"question":"甲学院专任教师人数","source_ids":["S1"]})
        first=json.loads(json.dumps(self.verdict));first["requirements"].append({"id":"R2","covered":False,"reason":"漏项"})
        second=json.loads(json.dumps(self.draft));second["claims"].append({"requirement_id":"R2","text":"专任教师26人。",
            "citations":[{"evidence_id":"E1","quote":"专任教师26人"}]})
        final=json.loads(json.dumps(self.verdict));final["claims"].append({"id":"C2","supported":True,"relevant":True,"reason":"26有据"});final["requirements"].append({"id":"R2","covered":True,"reason":"完整"})
        result,complete,_=self.run_pipeline([self.plan,self.draft,first,second,final])
        self.assertEqual(result["status"],"answered")
        self.assertIn("26人",result["answer"])
        self.assertEqual(complete.call_count,5)

    def test_string_boolean_or_missing_verdict_is_rejected(self):
        self.verdict["claims"][0]["supported"]="true"
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result["status"],"failed")

    def test_non_object_nested_values_fail_closed(self):
        self.draft["claims"]=["malformed"]
        empty = {**self.verdict, "claims": [], "requirements": [{"id":"R1","covered":False}]}
        result,_,_=self.run_pipeline([self.plan,self.draft,empty,self.draft,empty])
        self.assertEqual(result["status"],"refused")

    def test_no_hits_refuses_without_generation(self):
        result,complete,_=self.run_pipeline([self.plan],Mock(return_value=[]))
        self.assertEqual(result["status"],"refused")
        self.assertEqual(complete.call_count,1)

    def test_original_intent_must_be_verified_even_if_plan_is_covered(self):
        self.verdict['intent_complete'] = False
        result,complete,_ = self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result['status'],'partial')
        self.assertIn('全部要求尚未',result['answer'])
        payload = json.loads(complete.call_args_list[2].args[0][1]['content'])
        self.assertEqual(payload['original_question'],'它有多少人？')
        self.assertEqual(payload['history_intent_only'][0]['content'],'问甲学院')

    def test_unambiguous_subject_corrects_initial_document_binding(self):
        self.documents.append({'source_id':'kb2/D1','kb_id':'kb2','document_id':'D1','title':'乙学院','opening':'乙学院'})
        self.plan['requirements'][0].update(subject='甲学院',source_ids=['S2'])
        result,_,search = self.run_pipeline([self.plan,self.draft,self.verdict])
        self.assertEqual(result['status'],'answered')
        self.assertEqual(search.call_args.args[0]['id'],'S1')
        self.assertTrue(result['trace']['binding_corrections'])

    def test_verifier_adds_omitted_requirement_for_one_retry(self):
        first=json.loads(json.dumps(self.verdict));first['intent_complete']=False
        first['missing_requirements']=[{'subject':'甲学院','question':'甲学院专任教师人数','source_ids':['S1']}]
        second=json.loads(json.dumps(self.draft));second['claims'].append({'requirement_id':'R2','text':'专任教师26人。',
            'citations':[{'evidence_id':'E1','quote':'专任教师26人'}]})
        final=json.loads(json.dumps(self.verdict));final['claims'].append({'id':'C2','supported':True,'relevant':True})
        final['requirements'].append({'id':'R2','covered':True})
        result,complete,_=self.run_pipeline([self.plan,self.draft,first,second,final])
        self.assertEqual(result['status'],'answered')
        self.assertEqual(complete.call_count,5)
        self.assertIn('26人',result['answer'])

    def test_invalid_claim_does_not_discard_other_verified_facts(self):
        self.draft['claims'].append({'requirement_id':'R1','text':'错误999人',
            'citations':[{'evidence_id':'E1','quote':'999人'}]})
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict])
        self.assertEqual(result['status'],'answered')
        self.assertNotIn('999',result['answer'])

    def test_verifier_source_repair_retrieves_correct_document(self):
        self.documents.append({'source_id':'kb2/D1','kb_id':'kb2','document_id':'D1','title':'乙学院','opening':'乙学院'})
        self.plan['requirements'][0]['source_ids']=['S2']
        first={**self.verdict,'claims':[],'requirements':[{'id':'R1','covered':False,'source_ids':['S1']} ]}
        second=json.loads(json.dumps(self.draft));second['claims'][0]['citations'][0]['evidence_id']='E2'
        search=Mock(side_effect=[[{**self.hit,'text':'乙学院资料','kb_id':'kb2'}],[self.hit]])
        result,complete,_=self.run_pipeline([self.plan,{'claims':[]},first,second,self.verdict],search)
        self.assertEqual(result['status'],'answered')
        self.assertEqual(complete.call_count,5)
        self.assertEqual(search.call_args.args[0]['id'],'S1')

    def test_json_requires_complete_object(self):
        self.assertEqual(json_object('```json\n{"a":1}\n```'),{"a":1})
        for value in ('[]','{"a":1} trailing','{"a":'):
            with self.assertRaises(ValueError):json_object(value)


class ReasoningPipelineTests(unittest.TestCase):
    def setUp(self):
        self.documents = [
            {'source_id':'a/D1','kb_id':'a','document_id':'D1','title':'澄川研究所','opening':'领域论文榜资料'},
            {'source_id':'b/D1','kb_id':'b','document_id':'D1','title':'云汀研究所','opening':'行业专利榜资料'}]
        self.hits = {
            'S1': {'text':'澄川研究所机器视觉论文榜位列第9，仅统计机器视觉论文。','score':0.8,'chunk_index':0,'kb_id':'a','document_id':'D1'},
            'S2': {'text':'云汀研究所绿色材料行业专利榜位列第6，仅统计授权专利。','score':0.8,'chunk_index':0,'kb_id':'b','document_id':'D1'}}
        self.plan = {'action':'answer','resolved_question':'比较两机构局部指标是否说明整体优劣','requirements':[
            {'id':'R1','kind':'fact','subject':'澄川研究所','question':'澄川的论文榜及统计口径','source_ids':['S1']},
            {'id':'R2','kind':'fact','subject':'云汀研究所','question':'云汀的专利榜及统计口径','source_ids':['S2']},
            {'id':'R3','kind':'analysis','subject':'整体优劣','question':'这些局部指标能说明两机构整体优劣吗？','source_ids':['S1'],'depends_on':['R1','R2']}]}
        self.draft = {'claims':[
            {'id':'F1','kind':'fact','requirement_id':'R1','text':self.hits['S1']['text'],
             'citations':[{'evidence_id':'E1','quote':self.hits['S1']['text']}]},
            {'id':'F2','kind':'fact','requirement_id':'R2','text':self.hits['S2']['text'],
             'citations':[{'evidence_id':'E2','quote':self.hits['S2']['text']}]},
            {'id':'A1','kind':'inference','requirement_id':'R3','text':'不能由不同局部指标判定两机构整体优劣。',
             'premise_ids':['F1','F2'],'rationale':'两个榜单的领域及统计指标不同，不是整体评价。'}]}
        self.verdict = {'intent_complete':True,'missing_requirements':[],'revised_requirements':None,
            'claims':[{'id':cid,'supported':True,'relevant':True} for cid in ['F1','F2','A1']],
            'requirements':[{'id':rid,'covered':True} for rid in ['R1','R2','R3']]}

    def run_pipeline(self, responses):
        complete=Mock(side_effect=[json.dumps(r,ensure_ascii=False) for r in responses])
        search=Mock(side_effect=lambda source,q,k:[self.hits[source['id']]])
        result=EvidencePipeline(complete,search).run('比较两机构整体优劣',[],self.documents)
        return result,complete,search

    def test_cross_document_inference_inherits_premise_citations(self):
        result,complete,search=self.run_pipeline([self.plan,self.draft,self.verdict])
        self.assertEqual(result['status'],'answered')
        self.assertEqual(search.call_count,2)
        self.assertEqual(complete.call_count,3)
        inference=result['claims'][-1]
        self.assertEqual(inference['premise_ids'],['F1','F2'])
        self.assertEqual([c['evidence_id'] for c in inference['citations']],['E1','E2'])
        self.assertIn('据此分析：',result['answer'])
        self.assertEqual(result['trace']['plan']['requirements'][2]['source_ids'],['S1','S2'])

    def test_false_premise_blocks_inference_even_when_verifier_approves_it(self):
        self.verdict['claims'][1]['supported']=False
        self.verdict['requirements'][1]['covered']=False
        result,complete,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result['status'],'partial')
        self.assertEqual([c['id'] for c in result['claims']],['F1'])
        self.assertNotIn('据此分析',result['answer'])
        self.assertEqual(complete.call_count,5)

    def test_incomplete_premise_requirement_cannot_support_full_comparison(self):
        self.verdict['requirements'][1]['covered']=False
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result['status'],'partial')
        self.assertTrue(all(c['kind']=='fact' for c in result['claims']))

    def test_unsupported_inference_is_removed_without_removing_valid_facts(self):
        self.verdict['claims'][2]['supported']=False
        self.verdict['requirements'][2]['covered']=False
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual([c['id'] for c in result['claims']],['F1','F2'])
        self.assertEqual(result['status'],'partial')

    def test_missing_or_self_referencing_premise_is_rejected(self):
        self.draft['claims'][2]['premise_ids']=['F1','A1']
        self.verdict['claims']=self.verdict['claims'][:2]
        self.verdict['requirements'][2]['covered']=False
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['trace']['discarded_claims'][0]['code'],'premise_unknown')

    def test_analysis_dependency_cycle_does_not_trigger_search(self):
        self.plan['requirements'][2]['depends_on']=['R3']
        result,complete,search=self.run_pipeline([self.plan])
        self.assertEqual(result['status'],'failed')
        search.assert_not_called()
        self.assertEqual(complete.call_count,1)

    def test_duplicate_fact_ids_cannot_be_chosen_as_inference_premises(self):
        self.draft['claims'][1]['id']='F1'
        self.verdict['claims']=[]
        for v in self.verdict['requirements']:v['covered']=False
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result['status'],'refused')
        self.assertEqual(result['claims'],[])
        self.assertIn('claim_id',[c['code'] for c in result['trace']['discarded_claims']])

    def test_malformed_evidence_id_does_not_discard_other_valid_facts(self):
        self.draft['claims'][0]['citations'][0]['evidence_id']=[]
        self.verdict['claims']=[self.verdict['claims'][1]]
        for v in self.verdict['requirements']:
            if v['id']!='R2':v['covered']=False
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual([c['id'] for c in result['claims']],['F2'])
        self.assertIn('citation_format',[c['code'] for c in result['trace']['discarded_claims']])

    def test_inference_cannot_omit_a_declared_premise(self):
        self.draft['claims'][2]['premise_ids']=['F1']
        self.verdict['claims']=self.verdict['claims'][:2]
        self.verdict['requirements'][2]['covered']=False
        result,_,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result['trace']['discarded_claims'][0]['code'],'premise_scope')
        self.assertNotIn('据此分析',result['answer'])

    def test_ellipsis_quote_remains_invalid_and_feedback_is_specific(self):
        self.draft['claims'][0]['citations'][0]['quote']='澄川研究所……第9'
        self.verdict['claims']=[self.verdict['claims'][1]]
        for v in self.verdict['requirements']:
            if v['id']!='R2':v['covered']=False
        result,complete,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual([c['id'] for c in result['claims']],['F2'])
        retry=json.loads(complete.call_args_list[3].args[0][1]['content'])
        self.assertIn('quote_not_contiguous',[c['code'] for c in retry['previous_discarded_claims']])

    def test_whole_plan_replacement_merges_over_split_requirements(self):
        fixture=PipelineTests();fixture.setUp()
        fixture.plan['requirements']=[{'id':'R1','question':'基础项目单项数量','source_ids':['S1']},
            {'id':'R2','question':'应用项目单项数量','source_ids':['S1']},
            {'id':'R3','question':'协作项目数量','source_ids':['S1']}]
        fixture.hit['text']='基础与应用项目合计12项，协作项目7项。'
        draft={'claims':[{'id':'F1','requirement_id':'R1','text':'基础与应用项目合计12项。',
            'citations':[{'evidence_id':'E1','quote':'基础与应用项目合计12项'}]},
            {'id':'F2','requirement_id':'R3','text':'协作项目7项。','citations':[{'evidence_id':'E1','quote':'协作项目7项'}]}]}
        first={'intent_complete':False,'missing_requirements':[],
            'claims':[{'id':'F1','supported':True,'relevant':False},{'id':'F2','supported':True,'relevant':True}],
            'requirements':[{'id':'R1','covered':False,'retry_query':'基础项目单独数量'},
                            {'id':'R2','covered':False},{'id':'R3','covered':True}],
            'revision_reason':'原问要求两组统计，误将第一组合计拆成单项',
            'revised_requirements':[{'id':'R1','question':'基础与应用项目合计数量','source_ids':['S1']},
                                   {'id':'R3','question':'协作项目数量','source_ids':['S1']}]}
        final={'intent_complete':True,'missing_requirements':[],
            'claims':[{'id':'F1','supported':True,'relevant':True},{'id':'F2','supported':True,'relevant':True}],
            'requirements':[{'id':'R1','covered':True},{'id':'R3','covered':True}]}
        result,complete,search=fixture.run_pipeline([fixture.plan,draft,first,draft,final])
        self.assertEqual(result['status'],'answered')
        self.assertEqual(complete.call_count,5)
        self.assertNotIn('暂不能确定',result['answer'])
        self.assertEqual(search.call_args.args[1],'基础与应用项目合计数量')
        self.assertEqual(len(result['trace']['plan']['requirements']),3)
        self.assertEqual(len(result['trace']['final_requirements']),2)

    def test_invalid_replacement_cannot_expand_authorized_sources(self):
        self.verdict.update(revision_reason='纠正来源',revised_requirements=[
            {'id':'R1','question':'未知来源数量','source_ids':['unauthorized']}])
        result,_,search=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,self.verdict])
        self.assertEqual(result['status'],'failed')
        self.assertTrue(all(c.args[0]['id'] in {'S1','S2'} for c in search.call_args_list))

    def test_last_round_plan_change_cannot_skip_reverification(self):
        self.verdict['requirements'][2]['covered']=False
        self.verdict['claims'][2]['supported']=False
        last=json.loads(json.dumps(self.verdict))
        last.update(revision_reason='删除分析要求',revised_requirements=self.plan['requirements'][:2])
        result,complete,_=self.run_pipeline([self.plan,self.draft,self.verdict,self.draft,last])
        self.assertEqual(result['status'],'partial')
        self.assertEqual(complete.call_count,5)
        self.assertFalse(result['trace']['intent_complete'])


class SourceAndRetrievalTests(unittest.TestCase):
    def test_fingerprint_and_heading_ranges_survive_whitespace(self):
        text='一、师资\n甲学院教师44人。\n二、平台\n乙教授：建立实验室。'
        self.assertEqual(document_fingerprint(text),document_fingerprint(text.replace('\n','\r\n')))
        sections=heading_contexts(text,[text])[0]
        self.assertTrue(any('师资' in s['heading'] for s in sections))
        self.assertTrue(any('平台' in s['heading'] for s in sections))
        self.assertTrue(any('乙教授' in s['heading'] for s in sections))
        self.assertTrue(all(sections[i]['start'] < sections[i+1]['start'] for i in range(len(sections)-1)))
    def test_merge_preserves_titles_boundaries_and_nested_sources(self):
        merged=merge_documents([{"title":"甲学院","text":"教职工44人。"},{"title":"乙学院","text":"科研平台8个。"}])
        docs=source_documents(merged,"混合库")
        self.assertEqual([d["title"] for d in docs],["甲学院","乙学院"])
        self.assertEqual([d["document_id"] for d in docs],["D1","D2"])
        self.assertNotIn("乙学院",docs[0]["text"])
        again=source_documents(merge_documents(docs),"第二次融合")
        self.assertEqual([d["title"] for d in again],["甲学院","乙学院"])

    def test_invalid_marker_cannot_silently_replace_title(self):
        with self.assertRaises(ValueError):source_documents('[RAG_SOURCE:e30=]\n文本','库')

    def test_bm25_adds_lexical_hit_when_vector_candidate_misses(self):
        rows=[{"id":"a","text":"任意背景资料"},{"id":"b","text":"TrustedGPT可靠性安全性公平性"}]
        result=hybrid_order(rows,'TrustedGPT', ['a'])
        self.assertIn('b',[r['id'] for r in result])
        self.assertGreater(next(r['lexical_score'] for r in result if r['id']=='b'),0)

    def test_real_manager_filters_document_and_rejects_other_user(self):
        from db import Database,User
        from kb_service import KnowledgeBaseManager
        root=Path(__file__).resolve().parents[1]/'kb_store'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='scope-test-',dir=root) as directory:
            db=Database(Path(directory)/'test.db')
            manager=KnowledgeBaseManager(db,Path(directory)/'store')
            fake=Mock();fake.encode.side_effect=lambda values: [[0.2,0.3,1.0] for _ in ([values] if isinstance(values,str) else values)]
            manager._embedding_model=fake
            try:
                with db.session() as session:
                    user=User(username='scope',salt='unused',password_hash='unused');session.add(user);session.flush();uid=user.id
                text=merge_documents([{'title':'甲学院','text':'甲学院研究生55人。'},{'title':'乙学院','text':'乙学院科研平台8个。'}])
                kb=manager.create(uid,'联合资料',text=text)
                catalog=manager.document_catalog(uid,kb['id'])
                self.assertEqual(len(catalog),2)
                found=manager.query_evidence(uid,kb['id'],'D2','乙学院科研平台',4)
                self.assertTrue(found)
                self.assertTrue(all(r['document_id']=='D2' and '55' not in r['text'] for r in found))
                self.assertTrue(all(r['document_sha256']==catalog[1]['document_sha256'] for r in found))
                count=fake.encode.call_count
                self.assertEqual(manager.query_evidence(uid+100,kb['id'],'D2','科研平台',4),[])
                self.assertEqual(fake.encode.call_count,count)
                manager._kb_file(kb['id']).write_text(text+'\n原文变更。',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'版本不一致'):
                    manager.query_evidence(uid,kb['id'],'D2','科研平台',4)
            finally:
                close=getattr(manager.db_client,'close',None)
                if close:close()
                else:manager.db_client._system.stop()
                db.engine.dispose()


class ServerPipelineTests(unittest.TestCase):
    def test_api_route_buffers_draft_and_persists_cited_sources_and_trace(self):
        import server
        fixture=PipelineTests();fixture.setUp()
        backend=Mock();backend.complete_messages.side_effect=[json.dumps(v,ensure_ascii=False) for v in
            [fixture.plan,fixture.draft,fixture.verdict]];backend.call_log=[]
        manager=Mock();manager.get.return_value={'id':'kb'};manager.document_catalog.return_value=fixture.documents
        manager.query_evidence.return_value=[fixture.hit]
        conversations=Mock();conversations.create.return_value={'id':'conversation'}
        providers=Mock();providers.get.return_value=SimpleNamespace(model='qwen3.8-flash')
        root=Path(__file__).resolve().parents[1]/'kb_store'
        with tempfile.TemporaryDirectory(prefix='server-pipeline-test-',dir=root) as directory:
            with patch.object(server,'get_manager',return_value=manager),patch.object(server,'get_conversations',return_value=conversations),\
                 patch.object(server,'get_api_store',return_value=providers),patch.object(server,'APIAnswerer',return_value=backend),\
                 patch.object(server,'STORE_DIR',Path(directory)),\
                 patch.object(server,'StreamingResponse',side_effect=lambda iterator,**kw:iterator):
                req=server.ChatRequest(kb_id='kb',question='甲学院多少教职工？',provider='api',provider_id='p')
                events=[json.loads(item.removeprefix('data: ').strip()) for item in server.chat(req,{'id':1})]
                tokens=[e['content'] for e in events if e['type']=='token']
                self.assertEqual(tokens,['甲学院教职工44人。 [E1]'])
                metadata=[e for e in events if e['type']=='meta'][-1]
                self.assertEqual(metadata['chunks'][0]['source_title'],'甲学院')
                self.assertEqual(metadata['chunks'][0]['evidence_id'],'E1')
                self.assertEqual(metadata['model_calls'],3)
                manager.query.assert_not_called()
                backend.close.assert_called_once()
                saved=conversations.add_message.call_args
                self.assertEqual(saved.args[2],'assistant')
                self.assertEqual(saved.args[4][0]['evidence_id'],'E1')
                files=list((Path(directory)/'rag_traces/1').glob('*.json'))
                self.assertEqual(len(files),1)
                trace=json.loads(files[0].read_text(encoding='utf-8'))
                self.assertEqual(trace['status'],'answered')
                self.assertEqual(trace['trace']['model_calls'],3)

    def test_stale_index_reports_rebuild_and_does_not_publish_answer(self):
        import server
        fixture=PipelineTests();fixture.setUp()
        backend=Mock();backend.complete_messages.return_value=json.dumps(fixture.plan,ensure_ascii=False)
        manager=Mock();manager.get.return_value={'id':'kb'};manager.document_catalog.return_value=fixture.documents
        manager.query_evidence.side_effect=ValueError('原文与索引版本不一致，请重新保存知识库以重建索引')
        conversations=Mock();conversations.create.return_value={'id':'conversation'}
        providers=Mock();providers.get.return_value=SimpleNamespace(model='qwen3.8-flash')
        with patch.object(server,'get_manager',return_value=manager),patch.object(server,'get_conversations',return_value=conversations),\
             patch.object(server,'get_api_store',return_value=providers),patch.object(server,'APIAnswerer',return_value=backend),\
             patch.object(server,'StreamingResponse',side_effect=lambda iterator,**kw:iterator):
            events=[json.loads(item.removeprefix('data: ').strip()) for item in server.chat(
                server.ChatRequest(kb_id='kb',question='多少人？',provider='api',provider_id='p'),{'id':1})]
        self.assertFalse(any(e['type']=='token' for e in events))
        self.assertIn('重建索引',next(e['message'] for e in events if e['type']=='error'))
        self.assertEqual(conversations.add_message.call_count,1)
        backend.close.assert_called_once()


class CompletionAndResumeTests(unittest.TestCase):
    def test_completion_records_tokens_and_hides_provider_errors(self):
        from api_answerer import APIAnswerer,APIProvider
        client=Mock()
        usage=SimpleNamespace(model_dump=lambda **kw:{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13})
        client.chat.completions.create.return_value=SimpleNamespace(model='qwen3.8-flash',usage=usage,
            choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{}'))])
        with patch('api_answerer.OpenAI',return_value=client) as factory:
            api=APIAnswerer(APIProvider('id','name','https://example.test/v1','test-key','qwen3.8-flash'),max_retries=0)
            self.assertEqual(api.complete_messages([],1536),'{}')
            self.assertEqual(factory.call_args.kwargs['max_retries'],0)
            self.assertEqual(api.call_log[0]['usage']['total_tokens'],13)
            self.assertEqual(client.chat.completions.create.call_args.kwargs['extra_body'],{'enable_thinking':False})
            client.chat.completions.create.side_effect=RuntimeError('test-key private-endpoint')
            with self.assertRaises(RuntimeError) as error:api.complete_messages([],1536)
            self.assertNotIn('test-key',str(error.exception))
            self.assertNotIn('private-endpoint',str(error.exception))
            self.assertEqual(api.call_log[-1]['status'],'failed')
            api.close()

    def test_controlled_checkpoint_resumes_without_repeating_completed_case(self):
        from rag_evaluation import ROOT,digest,run_controlled,score_dataset
        fixture=PipelineTests();fixture.setUp()
        text=fixture.hit['text'];quote='甲学院教职工44人'
        data={'schema_version':1,'name':'resume-test','annotation_status':'draft','sources':{'doc':{'title':'甲学院'}},
            'cases':[{'id':f'q{i}','source_id':'doc','category':'fact','question':'甲学院多少教职工？','history':[],
                      'reference_answer':'44人','answerable':True,'evidence':[{'start':0,'end':len(quote),'quote':quote}]} for i in range(2)]}
        args=SimpleNamespace(resume=False,generate_local=False,api_model='qwen3.8-flash',ks=[1,4],device='cpu',
                             answer_top_k=4,max_new_tokens=1536,chunk_size=260,chunk_overlap=60)
        responses=[json.dumps(v,ensure_ascii=False) for v in [fixture.plan,fixture.draft,fixture.verdict]]
        first=Mock();first.call_log=[];first.complete_messages.side_effect=responses+[RuntimeError('interrupt')]
        second=Mock();second.call_log=[];second.complete_messages.side_effect=responses
        embed=Mock();embed.encode.side_effect=lambda v:[[0.2,0.3,1.0] for _ in ([v] if isinstance(v,str) else v)]
        with tempfile.TemporaryDirectory(prefix='controlled-resume-test-',dir=ROOT/'kb_store') as directory:
            output=Path(directory)/'run'
            with patch.multiple('rag_evaluation',API_KEY='test-key',BASE_URL='https://example.test/v1'),\
                 patch('kb_service.KnowledgeBaseManager._embedder',return_value=embed),\
                 patch('api_answerer.APIAnswerer',side_effect=[first,second]):
                with self.assertRaises(RuntimeError):run_controlled(data,{'doc':text},args,output)
                saved=json.loads((output/'predictions.partial.json').read_text(encoding='utf-8'))
                self.assertEqual(len(saved['predictions']),1)
                args.resume=True
                result=run_controlled(data,{'doc':text},args,output)
                self.assertEqual(len(result['predictions']),2)
                self.assertEqual(second.complete_messages.call_count,3)
                score_dataset(data,{'doc':text},result,[1,4])


if __name__ == '__main__':
    unittest.main()
