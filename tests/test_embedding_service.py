"""在线向量协议、用户隔离与失败时保留索引；所有外部请求均为模拟。"""

import json
import os
import httpx
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ["ANONYMIZED_TELEMETRY"] = "False"

from app.llm.api_answerer import validate_embedding_endpoint
from app.core.crypto import SecretCipher
from app.core.db import Database, EmbeddingProfile, KnowledgeIndex, User
from app.knowledge.embedding_service import EmbeddingStore, RemoteEmbeddingModel, embedding_fingerprint
from app.knowledge.web_search import SearchStore, TavilySearch, safe_web_url, normalize_web_query


CONFIG = {"provider": "api", "base_url": "https://api.openai.com/v1", "model": "test-embedding",
          "api_key": "dummy-private-test-key", "dimensions": 3, "batch_size": 2}


class RemoteProtocolTests(unittest.TestCase):
    def test_real_sdk_builds_expected_embedding_request_without_network(self):
        def send(client, request, **kwargs):
            body = json.loads(request.content)
            self.assertEqual(request.url.path, '/v1/embeddings')
            self.assertEqual(body['input'], ['甲', '乙'])
            self.assertEqual(body['dimensions'], 3)
            self.assertEqual(body['encoding_format'], 'float')
            return httpx.Response(200, request=request, json={'object': 'list', 'model': CONFIG['model'],
                'data': [{'object': 'embedding', 'index': 1, 'embedding': [0.0, 1.0, 0.0]},
                         {'object': 'embedding', 'index': 0, 'embedding': [1.0, 0.0, 0.0]}],
                'usage': {'prompt_tokens': 2, 'total_tokens': 2}})
        with patch('app.knowledge.embedding_service.validate_embedding_endpoint', return_value=CONFIG['base_url']), \
             patch.object(httpx.Client, 'send', autospec=True, side_effect=send):
            result = RemoteEmbeddingModel(CONFIG).encode(['甲', '乙'])
        self.assertEqual(result, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    def client(self):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        return client

    def test_response_indices_are_reordered_and_batches_are_bounded(self):
        client = self.client()
        client.embeddings.create.side_effect = [SimpleNamespace(data=[
            SimpleNamespace(index=1, embedding=[0, 1, 0]), SimpleNamespace(index=0, embedding=[1, 0, 0])]),
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0, 0, 1])])]
        with patch('app.knowledge.embedding_service.validate_embedding_endpoint', return_value=CONFIG['base_url']), \
             patch('app.knowledge.embedding_service.OpenAI', return_value=client):
            rows = RemoteEmbeddingModel(CONFIG).encode(['甲', '乙', '丙'])
        self.assertEqual(rows, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.assertEqual(client.embeddings.create.call_count, 2)

    def test_malformed_vectors_never_reach_chroma_and_errors_hide_credentials(self):
        for vector in [[float('nan'), 0, 1], [1, 2], [0, 0, 0], [True, 1, 0]]:
            client = self.client()
            client.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=vector)])
            with patch('app.knowledge.embedding_service.validate_embedding_endpoint', return_value=CONFIG['base_url']), \
                 patch('app.knowledge.embedding_service.OpenAI', return_value=client), self.assertRaises(ValueError) as error:
                RemoteEmbeddingModel(CONFIG).encode('甲')
            self.assertNotIn(CONFIG['api_key'], str(error.exception))
        client = self.client(); client.embeddings.create.side_effect = RuntimeError(CONFIG['api_key'])
        with patch('app.knowledge.embedding_service.validate_embedding_endpoint', return_value=CONFIG['base_url']), \
             patch('app.knowledge.embedding_service.OpenAI', return_value=client), self.assertRaises(ValueError) as error:
            RemoteEmbeddingModel(CONFIG).encode('甲')
        self.assertNotIn(CONFIG['api_key'], str(error.exception))

    def test_endpoint_policy_blocks_private_hosts_credentials_and_redirect_targets(self):
        for url in ['http://api.openai.com/v1', 'https://127.0.0.1/v1', 'https://evil.test/v1',
                    'https://user:password@api.openai.com/v1', 'https://api.openai.com.evil.test/v1']:
            with self.subTest(url=url), self.assertRaises(ValueError): validate_embedding_endpoint(url)
        with patch('app.llm.api_answerer.socket.getaddrinfo', return_value=[(0, 0, 0, '', ('127.0.0.1', 443))]), self.assertRaises(ValueError):
            validate_embedding_endpoint(CONFIG['base_url'], resolve=True)
        self.assertEqual(validate_embedding_endpoint(CONFIG['base_url']), CONFIG['base_url'])

    def test_fingerprint_ignores_key_rotation_but_not_vector_space(self):
        self.assertEqual(embedding_fingerprint(CONFIG), embedding_fingerprint({**CONFIG, 'api_key': 'new-key'}))
        for key, value in [('dimensions', 2), ('model', 'other'), ('base_url', 'https://dashscope.aliyuncs.com/v1')]:
            self.assertNotEqual(embedding_fingerprint(CONFIG), embedding_fingerprint({**CONFIG, key: value}))

    def test_tavily_distinguishes_body_and_excerpt_and_never_provider_answer(self):
        response = Mock(); response.json.return_value = {'answer': '禁止直接使用的摘要答案', 'results': [
            {'url': 'https://example.org', 'title': '官网', 'raw_content': '实际可读取的正文'},
            {'url': 'https://example.net', 'content': '只有搜索摘要'},
            {'url': 'http://127.0.0.1/private', 'raw_content': '内网'}]}
        client = self.client(); client.post.return_value = response
        with patch('app.knowledge.web_search.httpx.Client', return_value=client):
            docs = TavilySearch('dummy-search-key').search('公开问题')
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]['text'], '实际可读取的正文')
        self.assertEqual(docs[0]['content_kind'], 'page_text')
        self.assertEqual(docs[1]['text'], '只有搜索摘要')
        self.assertEqual(docs[1]['content_kind'], 'search_excerpt')
        sent = client.post.call_args.kwargs['json']
        self.assertEqual(sent['query'], '公开问题')
        self.assertFalse(sent['include_answer'])
        self.assertEqual(sent['search_depth'], 'advanced')
        self.assertEqual(sent['max_results'], 5)
        self.assertNotIn('history', sent)
        for url in ['javascript:alert(1)', 'http://localhost/a', 'http://10.0.0.1/a', 'https://u:p@example.org']:
            self.assertFalse(safe_web_url(url))

    def test_query_normalization_preserves_latin_words_and_years(self):
        self.assertEqual(normalize_web_query(' 甲大学 人工智能学院 院长 '), '甲大学人工智能学院院长')
        self.assertEqual(normalize_web_query('Open AI 2025 教师人数'), 'Open AI 2025 教师人数')


class IndexBindingTests(unittest.TestCase):
    def setUp(self):
        from app.knowledge.kb_service import KnowledgeBaseManager
        root = Path(__file__).resolve().parents[1] / 'kb_store'; root.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='embedding-index-test-', dir=root)
        self.root = Path(self.tmp.name)
        self.db = Database(self.root/'test.db')
        self.store = EmbeddingStore(self.db, SecretCipher(self.root/'secret.key'))
        self.search_store = SearchStore(self.db, self.store.cipher)
        with self.db.session() as s:
            a = User(username='a', salt='unused', password_hash='unused'); b = User(username='b', salt='unused', password_hash='unused')
            s.add_all([a, b]); s.flush(); self.uid, self.other = a.id, b.id
        self.manager = KnowledgeBaseManager(self.db, self.root/'store', embedding_store=self.store)
        self.local = Mock(); self.local.encode.side_effect = lambda values: [[1.0, 0.5] for _ in ([values] if isinstance(values, str) else values)]
        self.manager._embedding_model = self.local
        self.profile = self.store.create(self.uid, '在线测试', CONFIG['base_url'], CONFIG['api_key'], CONFIG['model'], dimensions=3)

    def tearDown(self):
        close = getattr(self.manager.db_client, 'close', None)
        if close: close()
        else: self.manager.db_client._system.stop()
        self.db.engine.dispose(); self.tmp.cleanup()

    def remote_vectors(self, values):
        return [[0.1, 0.2, 1.0] for _ in ([values] if isinstance(values, str) else values)]

    def test_users_cannot_read_config_keys_or_use_others_embedding(self):
        self.assertEqual(self.store.list(self.other), [])
        self.assertNotIn('api_key', self.store.list(self.uid)[0])
        with self.db.session() as s:
            self.assertNotIn(CONFIG['api_key'], s.get(EmbeddingProfile, self.profile['id']).api_key_enc)
        with self.assertRaises(ValueError): self.store.get(self.other, self.profile['id'])
        with patch('app.knowledge.kb_service.RemoteEmbeddingModel.encode') as encode, self.assertRaises(ValueError):
            self.manager.create(self.other, '越权', text='正文', embedding_profile_id=self.profile['id'])
        encode.assert_not_called()
        self.search_store.save(self.uid, 'dummy-search-key')
        self.assertFalse(self.search_store.view(self.other)['configured'])
        self.assertNotIn('api_key', self.search_store.view(self.uid))

    def test_reindex_switches_space_only_after_success_and_keeps_old_index(self):
        kb = self.manager.create(self.uid, '甲机构', text='甲机构教师44人。')
        old = self.manager._index(kb['id'])
        with patch('app.knowledge.kb_service.RemoteEmbeddingModel.encode', side_effect=self.remote_vectors):
            new = self.manager.reindex(self.uid, kb['id'], self.profile['id'])
            self.assertEqual(new['embedding_provider'], 'api')
            self.assertEqual(len(self.manager.query(self.uid, kb['id'], '教师')), 1)
            self.store.rotate_key(self.uid, self.profile['id'], 'rotated-dummy-key')
            self.assertEqual(len(self.manager.query(self.uid, kb['id'], '教师')), 1)
        self.assertEqual(self.manager.db_client.get_collection(old.collection_name).count(), 1)
        active = self.manager._index(kb['id'])
        with patch('app.knowledge.kb_service.RemoteEmbeddingModel.encode', side_effect=ValueError('模拟超时')), self.assertRaises(ValueError):
            self.manager.reindex(self.uid, kb['id'], self.profile['id'])
        self.assertEqual(self.manager._index(kb['id']).id, active.id)
        with self.assertRaises(ValueError): self.store.delete(self.uid, self.profile['id'])
        with patch('app.knowledge.kb_service.RemoteEmbeddingModel.encode') as encode:
            self.assertEqual(self.manager.query(self.other, kb['id'], '教师'), [])
        encode.assert_not_called()

    def test_online_creation_does_not_load_local_model_and_reopen_keeps_binding(self):
        with patch('app.knowledge.kb_service.RemoteEmbeddingModel.encode', side_effect=self.remote_vectors):
            kb = self.manager.create(self.uid, '在线库', text='甲机构教师44人。', embedding_profile_id=self.profile['id'])
        self.local.encode.assert_not_called()
        with self.db.session() as session:
            self.assertEqual(session.query(KnowledgeIndex).filter_by(kb_id=kb['id'], active=1).count(), 1)
        self.assertEqual(self.manager.get(self.uid, kb['id'])['embedding_profile_id'], self.profile['id'])

    def test_http_reindex_confirmation_and_smart_history_metadata(self):
        if os.getenv("QASYSTEM_SKIP_HTTP_CLIENT_TESTS") == "1":
            self.skipTest("当前 Windows 沙箱无法创建 asyncio socketpair；HTTP 客户端集成测试保留供常规环境运行")
        import app.api.server as server
        from fastapi.testclient import TestClient
        from app.services.conversation_service import ConversationService
        from test_agentic_sources import route, GENERAL_VERDICT, ROUTE_VERDICT
        kb = self.manager.create(self.uid, '甲机构', text='甲机构教师44人。')
        backend = Mock(); backend.call_log = []
        backend.complete_messages.side_effect = [json.dumps(r, ensure_ascii=False) for r in
            [route('general'), ROUTE_VERDICT, {'answer': '向量检索以向量距离匹配语义。'}, GENERAL_VERDICT]]
        conversations = ConversationService(self.db)
        providers = Mock(); providers.get.return_value = SimpleNamespace(model='mock-chat')
        previous = dict(server.app.dependency_overrides)
        server.app.dependency_overrides[server.get_current_user] = lambda: {'id': self.uid}
        try:
            with patch.object(server, 'get_manager', return_value=self.manager), \
                 patch.object(server, 'get_embedding_store', return_value=self.store), \
                 patch.object(server, 'get_search_store', return_value=self.search_store), \
                 patch.object(server, 'get_conversations', return_value=conversations), \
                 patch.object(server, 'get_api_store', return_value=providers), \
                 patch.object(server, 'APIAnswerer', return_value=backend), \
                 patch.object(server, 'STORE_DIR', self.root/'traces'):
                client = TestClient(server.app)
                response = client.post('/api/kbs/'+kb['id']+'/reindex', json={'embedding_profile_id': self.profile['id']})
                self.assertEqual(response.status_code, 400)
                with patch('app.knowledge.kb_service.RemoteEmbeddingModel.encode', side_effect=self.remote_vectors):
                    response = client.post('/api/kbs/'+kb['id']+'/reindex',
                        json={'embedding_profile_id': self.profile['id'], 'confirm_external': True})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['kb']['embedding_provider'], 'api')
                response = client.post('/api/chat', json={'source_mode': 'smart', 'question': '解释向量检索',
                    'provider': 'api', 'provider_id': 'mock'})
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                meta = [e for e in events if e['type'] == 'meta'][-1]
                self.assertEqual(meta['chunks'], [])
                self.assertEqual(meta['metadata']['answer_sources'], ['model'])
                saved = client.get('/api/conversations/'+meta['conversation_id']).json()['conversation']['messages'][-1]
                self.assertEqual(saved['chunks'], [])
                self.assertEqual(saved['metadata']['answer_sources'], ['model'])
                self.assertEqual(client.post('/api/chat', json={'question': '严格问题'}).status_code, 400)
                server.app.dependency_overrides[server.get_current_user] = lambda: {'id': self.other}
                self.assertEqual(client.get('/api/embeddings/providers').json()['providers'], [])
                with patch('app.knowledge.kb_service.RemoteEmbeddingModel.encode') as encode:
                    response = client.post('/api/kbs/'+kb['id']+'/reindex',
                        json={'embedding_profile_id': self.profile['id'], 'confirm_external': True})
                self.assertEqual(response.status_code, 404)
                encode.assert_not_called()
        finally:
            server.app.dependency_overrides.clear(); server.app.dependency_overrides.update(previous)
