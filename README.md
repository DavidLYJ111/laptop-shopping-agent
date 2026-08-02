# 笔记本智能导购 Agent

这是课程项目的 Day 3 可部署版本：用户用自然语言和表单描述购机需求，服务端通过 OpenAI Responses API 的 Structured Outputs 提取约束，复用确定性搜索核心筛选与排序 10 款 mock 笔记本，再从本地 `fact/evidence` 文档中检索证据并生成可校验的推荐说明。

> 当前商品和文档均为教学用 mock 数据，不代表实时市场价格或已核验商品信息。

## 核心链路

1. 第一次模型调用只负责意图、硬约束和软偏好的结构化提取。
2. 表单值以确定性规则覆盖自然语言提取结果。
3. `search_products` 执行硬过滤、场景评分、品牌多样性重排及 nearest 冲突分析。
4. 本地检索只允许 `fact` 和 `evidence` 文档进入上下文，排除 `derived`。
5. 第二次模型调用只为固定候选生成解释，不得改变 SKU 或排名。
6. 服务端校验 SKU、排名、证据 ID、normal/nearest 语义与 mock 数据声明后才返回前端。

模型失败、超时、输出不符合 Schema 或确定性校验失败时，每个模型阶段最多纠正重试一次；仍失败则返回安全错误，不回显密钥、系统提示词或原始异常。

## 目录

- `src/shopping_agent/agent/`：结构化 Schema、提示词加载、OpenAI 适配与工作流编排
- `src/shopping_agent/api/`：FastAPI 入口、健康检查和推荐接口
- `src/shopping_agent/search/`、`scoring/`：Day 1 的确定性搜索与排序
- `src/shopping_agent/retrieval/`：本地可信证据检索
- `data/`：10 款 mock SKU、30 条文档及 JSON Schema
- `web/index.html`：调用真实后端接口的单文件前端
- `scripts/`：数据质检、搜索演示、Schema 生成和真实模型冒烟脚本
- `tests/`：确定性核心、数据和 Day 3 API/Agent 测试

## 本地安装

需要 Python 3.10 或更高版本。PowerShell：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，填入自己的服务端密钥：

```dotenv
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-5-mini
APP_ENV=development
```

`.env` 已被 Git 忽略。不要把真实密钥写入 HTML、提交到仓库或粘贴到日志中。

## 启动与使用

```powershell
.venv\Scripts\python -m uvicorn shopping_agent.api.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`。也可以检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

`ai_enabled=false` 表示未配置密钥；此时页面可打开，但 `/api/recommend` 会返回明确的 503 配置提示，不会伪造推荐。

## 测试和演示

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python scripts/check_data_quality.py
.venv\Scripts\python scripts/demo_search.py
```

真实 OpenAI 冒烟测试与 mock 单元测试分开运行，并会产生 API 用量：

```powershell
.venv\Scripts\python scripts/smoke_openai.py
```

脚本未检测到 `OPENAI_API_KEY` 时会直接退出并提示配置，不会把 mock 结果标记为真实调用。

## API

`POST /api/recommend` 请求示例：

```json
{
  "message": "预算 7000 元，主要编程和数据分析，希望轻一点，内存至少 32GB",
  "session_id": "demo-001",
  "form_constraints": {
    "budget_max": 7000,
    "ram_min": 32,
    "scenario": "编程开发/数据分析",
    "weight_max": 1.8
  }
}
```

响应会包含结构化需求、`normal` 或 `nearest` 模式、固定候选排序、约束满足/违反项、证据 ID、证据内容和 mock 数据声明。

## Render 部署

仓库根目录已提供 `render.yaml`：

1. 在 GitHub 网页新建一个空仓库，不要勾选自动创建 README、License 或 `.gitignore`。
2. 将本地提交推送到 GitHub（不要提交 `.env`）：

```powershell
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

如果已经存在名为 `origin` 的远程地址，先用 `git remote -v` 核对，不要重复添加或覆盖不明地址。

3. 在 Render 选择 **New > Blueprint**，连接该仓库。
4. 在服务环境变量中设置 `OPENAI_API_KEY`；`OPENAI_MODEL` 默认是 `gpt-5-mini`。
5. 部署后访问 `/api/health`，确认 `status=ok`、`ai_enabled=true`。
6. 在网页完成至少一次 normal 查询和一次冲突约束 nearest 查询。

若不使用 Blueprint，构建命令为 `pip install -e .`，启动命令为：

```text
uvicorn shopping_agent.api.main:app --host 0.0.0.0 --port $PORT
```

## 当前边界

- 没有真实电商抓取、向量数据库、图片解析或实时价格。
- 图片入口只说明 P1 能力尚未开放，不会伪装成已识图。
- 模型仅提取与表述；商品候选、过滤、排序和 nearest 计算均来自确定性代码。
- 未配置真实 API 密钥时，无法完成真实模型端到端冒烟和公开可用部署。
