"""受限的 Tavily 搜索：仅发送检索词，不发送知识库正文；保存可引用的网页快照。"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from api_answerer import mask_key
from db import SearchSetting

import os, sys, json

def normalize_web_query(query):
    # 中文实体之间的模型分词空格会显著改变搜索排序，保留英文词与数字之间的间隔。
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", query.strip())

def safe_web_url(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".localhost")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host and not any(char.isspace() for char in url)
    except ValueError:
        return False


class SearchStore:
    def __init__(self, db, cipher):
        self.db, self.cipher = db, cipher

    def key(self, user_id):
        with self.db.session() as session:
            row = session.get(SearchSetting, user_id)
            return self.cipher.decrypt(row.api_key_enc) if row else ""

    def view(self, user_id):
        key = self.key(user_id)
        return {"provider": "tavily", "configured": bool(key), "api_key_masked": mask_key(key)}

    def save(self, user_id, api_key):
        if not api_key.strip():
            raise ValueError("搜索密钥不能为空")
        with self.db.session() as session:
            row = session.get(SearchSetting, user_id)
            if row is None:
                session.add(SearchSetting(user_id=user_id, api_key_enc=self.cipher.encrypt(api_key.strip())))
            else:
                row.api_key_enc = self.cipher.encrypt(api_key.strip())

    def delete(self, user_id):
        with self.db.session() as session:
            row = session.get(SearchSetting, user_id)
            if row:
                session.delete(row)


class TavilySearch:
    def __init__(self, api_key):
        self.api_key = api_key

    def search(self, query):
        if not self.api_key or not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError("搜索服务未配置或检索词不合法")
        query = normalize_web_query(query)
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                response = client.post("https://api.tavily.com/search",
                    headers={"Authorization": "Bearer " + self.api_key},
                    json={"query": query, "max_results": 5, "search_depth": "advanced",
                          "include_raw_content": True, "include_answer": False})
                response.raise_for_status()
                data = response.json()
            documents, urls = [], set()
            for row in data.get("results", [])[:5]:
                if not isinstance(row, dict):
                    continue
                url, text = row.get("url"), row.get("raw_content")
                content_kind = "page_text"
                if not isinstance(text, str) or not text.strip():
                    text, content_kind = row.get("content"), "search_excerpt"
                # 摘录可以支持其明示的事实，但必须与提取正文区分，不能冒充完整阅读。
                if not safe_web_url(url) or url in urls or not isinstance(text, str) or not text.strip():
                    continue
                urls.add(url)
                text = text.strip()[:16000]
                documents.append({"source_type": "web", "url": url,
                    "title": str(row.get("title") or url)[:300], "text": text,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "content_kind": content_kind,
                    "search_excerpt": str(row.get("content") or "")[:6000],
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "published_at": str(row.get("published_date") or "")[:100]})
            return documents
        except Exception:
            raise ValueError("网页搜索失败，暂不能核验网络事实；请检查搜索配置或稍后重试") from None

