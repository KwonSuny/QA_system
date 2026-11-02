# QASystem：基于证据的多用户知识库问答系统

FastAPI 中文 RAG 应用，支持多用户知识库、多轮对话、TXT / Markdown / DOCX / PDF 导入、本地或云端生成，以及每库独立的本地/在线嵌入配置。系统保留文档归属与引用证据，结合检索、规划、生成和核验，支持拒答、部分回答、分析结论及按需联网。


## 项目结构

```text
.
├── app/
│   ├── api/           # FastAPI 路由、认证依赖与 SSE
│   ├── core/          # SQLite 模型、认证与密钥加密
│   ├── knowledge/     # 文档解析、知识库、向量化与网页搜索
│   ├── llm/           # 本地及 OpenAI 兼容生成后端
│   ├── rag/           # 严格证据流程与智能来源路由
│   ├── services/      # 会话与消息持久化
│   ├── evaluation/    # 评测、公开数据转换及检索实验工具
│   └── static/        # HTML / CSS / JavaScript
├── data/              # 学院/学校资料及公开基准所需派生文本
├── evaluation/        # 已审核题集、留出集与虚构开发诊断集
├── tests/             # 项目全部 8 个 unittest 模块
├── docs/              # 架构图与 RAG 流程图
├── requirements*.txt
├── .gitignore
└── README.md
```

Python 模块按职责归类，目录和文件名均使用小写 `snake_case`。应用数据、静态资源和评测数据放在项目根的独立目录；运行路径由代码位置解析，不依赖当前启动目录。

## 技术与主要流程

- **后端与存储**：FastAPI、SQLAlchemy、SQLite、ChromaDB、SSE。
- **检索与生成**：本地 BGE、OpenAI 兼容在线嵌入、中文 BM25 + RRF、Transformers 本地生成、OpenAI SDK 云端生成。
- **文件与安全**：python-docx、pypdf、PBKDF2-SHA256、Fernet；用户、知识库、会话和 API 配置隔离。
- **回答流程**：历史消解指代与需求规划 → 按授权来源检索 → 带证据生成 → 结构、引用及语义核验 → 最多一轮补检。
- **来源模式**：严格知识库模式；智能补充模式可结合本地库、稳定通识和 Tavily 网页证据。明确要求“只根据知识库”或“不要联网”会限制来源。
- **引用显示**：知识库 `[K1]` 与网页 `[W1]` 分开展示；未经核验的搜索结果不会作为答案引用。



## 安装与运行

推荐 Python 3.12。请在项目根目录创建独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Linux / macOS 使用 `source .venv/bin/activate` 激活。PyTorch 体积较大，请先从 [PyTorch 安装页面](https://pytorch.org/get-started/locally/)选择适配 CPU 或 CUDA 的构建，再安装项目依赖：

```bash
python -m pip install -r requirements.txt
```

首次启动前配置管理员账号和强密码。应用不会自动读取 `.env`：

```powershell
# Windows PowerShell
$env:APP_ADMIN_USER = "admin"
$env:APP_ADMIN_PASSWORD = "替换为强密码"
python -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
```

```bash
# Linux / macOS
export APP_ADMIN_USER=admin
export APP_ADMIN_PASSWORD='替换为强密码'
python -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
```

访问 <http://127.0.0.1:8000>。首次启动会创建 `kb_store/` 并将 `data/aidata.txt` 导入管理员的默认知识库。管理员变量仅在创建首个管理员时生效；未配置时默认账号为 `admin / admin123`，仅限本地试用，首次使用后应立即改密。默认嵌入和生成模型分别是 `BAAI/bge-small-zh-v1.5` 与 `Qwen/Qwen2.5-1.5B-Instruct`；可用 `LOCAL_EMBEDDING_MODEL`、`LOCAL_LLM_MODEL` 指向本地权重，缺少权重时可能从 Hugging Face 下载。

如只用在线嵌入且不希望启动时载入默认本地知识库，可在启动前设置 `APP_SEED_DEFAULT_KB=0`。生成 API、Tavily 搜索及在线嵌入配置在应用内分别管理；使用在线嵌入需显式确认文本外发。

## 功能使用

### 账号与知识库

首次启动后使用管理员账号登录。若启动前设置了 `APP_ADMIN_USER` 和 `APP_ADMIN_PASSWORD`，使用对应值；未设置时初始账号为 `admin / admin123`。普通用户可在登录页注册，注册后拥有独立的知识库、模型配置和对话记录。

左侧“知识库”区域点击 **＋** 创建知识库，填写名称和简介，再粘贴正文或选择 TXT、Markdown、DOCX、PDF 文件。创建后选择知识库即可开始提问。点击知识库卡片上的编辑按钮可更新名称、简介或正文；删除会同时移除该库的索引和资料，且无法撤销。

需要联合查询多个库时，点击知识库区域的融合按钮，至少选择两个知识库并为新库命名。融合会创建一个新的知识库，原库默认保留；新库会保留来源标记，便于答案引用溯源。

### 配置回答模型、嵌入和联网

- **回答模型**：点击右上角“我的 API”→“添加配置”，填写服务名称、OpenAI 兼容 Base URL、模型名和 API Key。保存后在顶部“模型”下拉框选择该配置；选择“本地模型”则使用本机已准备好的生成模型。API 配置属于当前账号。
- **嵌入模型**：点击“检索与联网”添加在线嵌入配置，填写 Base URL、模型名和 Key，可按服务要求指定向量维度及批量大小。创建或融合知识库时可选择该配置，并确认允许发送文本。已有库更换嵌入配置时，先保存正文，再点击“按所选配置重建索引”；只有新索引成功后才会切换。
- **网页搜索**：在“检索与联网”填写 Tavily API Key 并保存。每次问答还需选择“智能补充”并勾选“允许联网”才会搜索。搜索服务会收到必要的问题和公开检索词，不会收到知识库正文；网页结果只用于当前回答，不会自动写入知识库。

在线生成会将问题、必要的对话历史和本轮检索证据发送给所选模型；在线嵌入会将知识库正文及查询发送给所选嵌入服务。请只配置你允许使用的服务，并留意服务费用。

### 提问、来源模式与引用

1. 选择左侧知识库，在顶部“来源”选择“严格知识库”，输入问题并按 Enter 发送（Shift+Enter 换行）。顶部“片段”设置检索数量 Top-K，默认 4；“温度”控制生成随机度。
2. 严格模式仅根据所选知识库作答；证据不足时可能拒答。追问可直接结合当前对话历史理解指代，但历史内容本身不会作为新事实证据。
3. “智能补充”可结合已选知识库、稳定通识和网页搜索；也可不选择知识库，直接询问通用问题。要联网时还需单独勾选“允许联网”。“只根据知识库”会限制为知识库来源，“不要联网”会阻止网页搜索。
4. 回答下方可展开引用查看实际采用的资料片段：`[K1]` 等表示知识库来源，`[W1]` 等表示网页来源。未作为依据的搜索结果会与已引用来源分开展示；通识回答会标记为“未经外部资料核验”。请结合原文核对重要结论。

左侧“历史对话”会保存已提交的问答。点击 **＋** 或“清空对话”会切换到新的空白对话视图，原对话仍保留在历史列表中；选择历史项可继续查看或追问，也可重命名或删除。删除历史对话不可撤销。

管理员可通过“用户管理”查看用户和资源概况、创建用户、重置密码或删除用户。删除用户会一并删除其知识库、对话和配置，请谨慎操作。

## 资料与评测

`data/` 包含四份公开学校/学院资料和 RGB / DuReader-Checklist 派生文本。`evaluation/` 包含已审核开发题与留出题、12 道虚构推理诊断题，以及外部数据集派生评测题。题集保持独立，留出集不可用于调参。第三方数据许可与来源说明见 `data/external/dureader_license.txt` 及 `evaluation/external/` 内的说明文件；请勿超出原许可范围使用。

校验默认已审核数据或虚构诊断集，不调用模型：

```bash
python -B -m app.evaluation.rag_evaluation validate
python -B -m app.evaluation.rag_evaluation validate --dataset evaluation/reasoning_development.json
```

安装测试依赖并运行完整回归：

```bash
python -m pip install -r requirements-dev.txt
python -B -m unittest discover -s tests -v
```

当前 8 个模块共 135 个测试，模型与 API 使用测试替身；覆盖来源规划、引用核验、文档解析、嵌入配置、数据集转换、评测流程和检索实验。若运行环境禁止创建 Windows asyncio socketpair，可设置 `QASYSTEM_SKIP_HTTP_CLIENT_TESTS=1` 跳过两项 HTTP 客户端集成测试；其他测试不受影响。测试通过不等于真实模型回答质量或泛化能力已验证。T2Retrieval 的 Parquet 文件未随包分发；运行对应实验需自行准备数据并安装 `pyarrow`。

受控 API 评测可能产生费用，参数可用以下命令查看：

```bash
python -m app.evaluation.rag_evaluation --help
python -m app.evaluation.retrieval_experiments --help
```

## 文档读取与来源格式

支持 `.txt`、`.md`、`.text`、`.docx` 与文本型 `.pdf`。DOCX 提取段落和表格但不识别图片；PDF 提取文字层并保留页码，扫描件需先 OCR。复杂多栏、公式或表格可能导致顺序不准，入库前请检查。上传二进制文件不长期留存，解析文本保存至本机运行目录。

合并多来源材料时用标题标识来源：

```markdown
# 来源文档：甲
甲资料……

# 来源文档：乙
乙资料……
```

默认监听 `127.0.0.1`。公开部署前需完善 HTTPS、限流、注册防护、服务端 API 地址访问控制及登录凭证保护。浏览器登录 token 使用 `localStorage`。

