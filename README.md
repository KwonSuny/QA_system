# QASystem：基于证据的多用户知识库问答系统

基于 FastAPI 的中文 RAG 应用，支持多用户知识库、多轮对话、TXT / Markdown / DOCX / PDF 导入，以及本地或云端生成、独立的本地或在线嵌入。回答保留来源归属和可展开引用，并通过结构、原文与语义检查减少张冠李戴、无依据回答和漏答。

适用于 RAG 学习、课程项目进阶和受控环境中的原型验证，不是面向公网的生产部署方案。

## 功能与技术

| 能力 | 实现 |
| --- | --- |
| 多用户与隔离 | FastAPI、SQLAlchemy、SQLite；账号、知识库、会话及 API 配置按用户隔离 |
| 知识库 | ChromaDB 向量索引；保留文档、标题、章节与来源边界，支持多个知识库管理和融合 |
| 混合检索 | 本地 BGE 或 OpenAI 兼容在线嵌入，向量检索与中文 BM25 通过 RRF 融合 |
| 多轮问答 | 结合对话历史消解指代、改写追问、拆分需求；历史只用于理解问题，不充当事实证据 |
| 答案生成 | 事实引用连续原文；分析结论关联已核验前提；支持部分回答、拒答和最多一轮补检 |
| 来源选择 | 严格知识库模式；智能补充模式可结合知识库、稳定通识和 Tavily 网页搜索 |
| 文件读取 | python-docx、pypdf 提取文本；保留表格/章节或 PDF 页码线索 |
| 前端与流式交互 | 原生 HTML / CSS / JavaScript；SSE 返回阶段状态与经核验的回答 |
| 凭据保护 | PBKDF2-SHA256 密码哈希、Fernet 加密保存 API Key |
| 评测 | 检索指标、人工答案评分、API 重放与核心回归测试 |

默认受控流程通常调用模型 3 次，补检后最多 5 次；智能补充模式另有独立预算。受控流程会等待核验后再返回答案，首字延迟高于单次生成。核验与生成使用同一模型，不能视为独立事实裁判。

## 快速开始

### 1. 环境与依赖

推荐 Python 3.12。先创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Linux / macOS 激活命令为 `source .venv/bin/activate`。

PyTorch 体积较大，请按 CPU / CUDA 硬件从 [PyTorch 安装页面](https://pytorch.org/get-started/locally/)选择安装命令。然后安装项目依赖：

```bash
python -m pip install -r requirements.txt
```

若使用测试依赖，可执行 `python -m pip install -r requirements-dev.txt`。依赖文件不包含模型权重。

### 2. 配置管理员并启动

应用不会自动读取 `.env`。首次启动前，在当前终端设置管理员账号与强密码：

```powershell
# Windows PowerShell
$env:APP_ADMIN_USER = "admin"
$env:APP_ADMIN_PASSWORD = "替换为强密码"
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

```bash
# Linux / macOS
export APP_ADMIN_USER=admin
export APP_ADMIN_PASSWORD='替换为强密码'
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

访问 <http://127.0.0.1:8000>。首次启动会创建本地数据库并把 `data/aidata.txt` 导入为管理员的默认知识库。`data/` 包含软件工程学院、计算机学院、人工智能学院与中山大学的公开资料快照；`evaluation/seed.json` 与其配套资料则是虚构的开发诊断集。

管理员环境变量仅在创建首个管理员时生效；若已有管理员，需要通过应用内管理功能修改密码。首次启动默认管理员账号为 `admin / admin123`，仅适用于本地试用，应立即更改。

### 3. 准备模型

默认嵌入模型为 `BAAI/bge-small-zh-v1.5`，默认生成模型为 `Qwen/Qwen2.5-1.5B-Instruct`。模型查找顺序为环境变量、项目 `models/` / `model/` 目录，最后回退到 Hugging Face 模型 ID。缺少本地权重时可能联网下载。

```powershell
$env:LOCAL_EMBEDDING_MODEL = "D:\models\bge-small-zh-v1.5"
$env:LOCAL_LLM_MODEL = "D:\models\Qwen2.5-1.5B-Instruct"
```

也可登录后配置 OpenAI 兼容的生成 API。生成与嵌入配置相互独立；在线嵌入会将文档正文及查询发送到所配置服务，界面会要求确认。在线生成会发送问题、必要对话历史与本轮检索证据。

## 来源与引用

- “严格知识库”仅按选定知识库回答，证据不足时拒答。
- “智能补充”可以选择知识库、稳定通识或受控网页搜索。明确要求“只根据知识库”会覆盖智能路由；“不要联网”会阻止搜索。
- 知识库引用使用 `[K1]`，网页引用使用 `[W1]`；通识回答标明未经过外部资料核验。
- 网页搜索需在“检索与联网”配置 Tavily Key 并启用联网。只发送必要的公开检索词，不发送知识库正文；网页内容不会自动导入知识库。
- 网页检索结果与实际答案引用分开展示；未被核验的搜索摘录不会伪装成事实引用。
- 在线嵌入配置按知识库隔离。更换嵌入模型需要显式重建索引；新索引成功后才切换，失败时保留原索引。

每个知识库可以单独选择本地或在线嵌入模型。在线服务须兼容 OpenAI `/embeddings` 接口。当前不支持供应商专用 `input_type` 或多模态嵌入协议。

## 文档导入

支持 `.txt`、`.md`、`.text`、`.docx` 和文本型 `.pdf`。DOCX 提取正文段落和表格，不做图片 OCR；PDF 提取文字层并记录物理页码，扫描 PDF 需先自行 OCR。复杂多栏、公式和表格可能影响抽取顺序，导入后请检查内容。上传原始二进制文件不会保留，解析后文本存入本地运行目录。

将多份资料合并导入时，可用以下标题标识来源：

```markdown
# 来源文档：甲研究所
甲研究所资料……

# 来源文档：乙研究所
乙研究所资料……
```

## 评测与回归

发布包带有 12 道虚构机构诊断题及两份虚构资料，覆盖来源归属、跨资料比较、追问、分析和拒答。标注状态为助手草稿，适合演示和修改评测流程，不是已审核基准，也不代表模型准确率。`data/` 另包含四份公开学校/学院资料，供默认知识库及手动导入使用；它们未被混入虚构评测集。

```bash
# 校验发布包附带的虚构评测资料，不调用模型 API
python -B rag_evaluation.py validate

# 93 项核心回归测试；模型/API 使用测试替身
python -B -m unittest discover -s tests -v
```

检索基线可用 `rag_evaluation.py run --help` 查看参数；调用在线模型的受控评测会产生 API 费用。答案评分分别记录正确性、上下文支持度和拒答状态；检索命中不能替代答案质量评测。

## 项目结构

```text
.
├── server.py                 # FastAPI 接口、认证、SSE
├── agentic_pipeline.py       # 智能来源规划与网页/通识补充
├── rag_pipeline.py           # 需求规划、来源约束、生成、核验与补检
├── kb_service.py             # 知识库管理、切分、向量与混合检索
├── embedding_service.py      # 在线嵌入配置与协议校验
├── web_search.py             # Tavily 搜索与网页证据快照
├── document_reader.py        # TXT / Markdown / DOCX / PDF 解析
├── db.py / auth.py / crypto.py
├── static/                   # 原生 Web 前端
├── data/                    # 四份公开学校/学院资料快照
├── evaluation/               # 虚构诊断题与资料
├── tests/                    # 核心回归测试
├── requirements*.txt         # 运行和测试依赖
└── kb_store/                 # 首次运行创建的数据库、向量和本地资料
```

## 安全与适用边界

默认仅监听 `127.0.0.1`，适合本地或可信网络原型。公开部署前还需完善 HTTPS、注册和调用限流、服务端 API 地址访问控制及登录凭证保护。浏览器登录 token 保存在 `localStorage`。不要将 API Key、`kb_store/`、模型权重、真实用户资料或私有知识库提交到 Git。

本项目代码尚未附带开源许可证；公开展示不等于授予复用授权。依赖库和模型各自遵循其许可证，使用前请分别确认。
