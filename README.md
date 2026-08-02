# 笔记本智能导购 Agent：确定性搜索核心

这是开发任务 01 的实现：包含经过类型校验的数据模型、10 款明确标记为 `mock` 的种子 SKU、JSONL 加载与质量检查、场景化确定性排序、硬约束过滤、品牌多样性重排和 nearest 冲突候选。当前版本不包含 LLM、RAG、向量库、图片解析或界面。

## 环境与安装

需要 Python 3.10 或更高版本。Windows PowerShell 示例：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## 运行

```powershell
.venv\Scripts\python scripts/check_data_quality.py
.venv\Scripts\python scripts/demo_search.py
.venv\Scripts\python -m pytest
```

重新从 Pydantic 模型导出 JSON Schema：

```powershell
.venv\Scripts\python scripts/generate_schemas.py
```

## 目录

- `src/shopping_agent/models/`：Pydantic 领域模型与枚举
- `src/shopping_agent/data/`：JSONL 加载和跨记录校验
- `src/shopping_agent/scoring/`：五类场景模板与可复现评分
- `src/shopping_agent/search/`：硬过滤、排序、多样性和 nearest 逻辑
- `data/`：模拟商品、文档和生成的 JSON Schema
- `scripts/`：质量检查、Schema 导出和演示
- `tests/`：确定性核心单元测试

## 数据声明

`data/products.jsonl` 和 `data/documents.jsonl` 全部为教学用模拟数据，均标记 `data_kind=mock`、`verification_status=待核验`，来源使用 `mock://`。它们不能被解释为真实市场价格或已核验商品参数。文档加载后仅 `fact` 与 `evidence` 可进入后续事实证据流程，`derived` 不可用于事实校验。
