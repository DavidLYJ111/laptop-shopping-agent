# 约束推理与 Agent 分支设计 v0.3

**项目名称**：基于多模态 RAG 与约束推理的电商智能导购 Agent
**设计原则**：结构化硬约束 + 场景化软偏好 + 违约成本冲突处理 + 精简工具调用
**适用范围**：第一版笔记本电脑品类
**更新日期**：2026-08-01

---

## 一、核心设计思想（v0.3 修订要点）

### 1.1 修订动机

v0.3 针对以下问题进行了修正：

1. **约束边界不清晰**：v0.2 中 "轻便" 直接映射为 weight_max=1.5，过度推断用户意图
2. **排序指标过于简化**：cpu_cores、gpu_vram_gb、battery_wh 不能准确代表性能/续航
3. **工具粒度混乱**：v0.2 的 12 个工具中存在大量内部工作流节点，不应全部作为 LLM 可调用的外部工具
4. **冲突处理不具体**：v0.2 的 "最接近候选" 没有明确的计算逻辑
5. **偏好权重不可复现**：LLM 直接输出 0.0–1.0 小数，难以复现实验结果

### 1.2 v0.3 关键改进

| 改进项 | v0.2 | v0.3 |
|--------|------|------|
| 约束来源 | 无区分 | 明确区分 `explicit`（用户明确说）和 `inferred`（系统推断） |
| 模糊表达处理 | 直接转硬约束 | 模糊表达优先进软偏好，影响大时追问 |
| 追问轮次 | 单一限制 | 澄清轮（clarification_turn）和冲突解决轮（conflict_resolution_turn）分离 |
| 冲突候选排序 | 普通软偏好排序 | 专用**违约成本**计算，独立于正常排序 |
| 工具数量 | 12 个（含工作流节点） | **5 个外部工具** + 6 个内部工作流节点 |
| 偏好权重 | LLM 输出小数 | 三级制：low / medium / high，程序固定映射 |
| 排序维度 | cpu_cores / gpu_vram_gb / battery_wh | 预计算 **cpu_performance_score / gpu_performance_score / portability_score / battery_capacity_score** |
| 排序策略 | 固定权重 | **场景化基础权重** + 用户偏好调整 |

---

## 二、硬约束与软偏好字段定义

### 2.1 硬约束字段（Hard Constraints）

硬约束必须同时满足两个条件：
- **条件 A**：用户使用了明确数字或强限制表达（"必须、至少、不超过、只要、只要…就…、只考虑、限定在"）
- **条件 B**：该约束可以从结构化字段中直接验证

| 字段名 | 类型 | 验证字段 | 强限制表达示例 |
|--------|------|----------|---------------|
| `budget_max` | int/None | `price` | "预算8000以内/不超过8000" |
| `budget_min` | int/None | `price` | "预算8000以上/至少8000" |
| `gpu_required` | bool/None | `gpu_type` | "必须独显/只要带显卡的" |
| `gpu_vram_min` | int/None | `gpu_vram_gb` | "显存至少8G" |
| `ram_min` | int/None | `ram_gb` | "内存至少32G/不低于16G" |
| `storage_min` | int/None | `storage_capacity` | "硬盘至少1T" |
| `weight_max` | float/None | `weight_kg` | "重量不超过1.5kg" |
| `screen_size_range` | [float, float]/None | `screen_size` | "14到16寸之间" |
| `resolution_min` | string/None | `resolution` | "分辨率至少2.5K"（可选） |
| `refresh_rate_min` | int/None | `refresh_rate` | "刷新率不低于144Hz"（可选） |
| `cpu_brand` | string/None | `cpu_brand` | "只要Intel的/必须是AMD" |
| `category` | string/None | `product_category` | "只要游戏本/限定轻薄本" |
| `required_ports` | list[string]/None | `ports` | "必须有雷电4接口" |

### 2.2 软偏好字段（Soft Preferences）

软偏好包括两类：
- **用户明确表达但模糊的偏好**（"轻便、高刷、续航好、性能强"）
- **用户未明确表达但可从场景推断的偏好**

| 偏好名 | 类型 | 取值 | 说明 |
|--------|------|------|------|
| `performance` | enum | low / medium / high | 性能重视程度 |
| `portability` | enum | low / medium / high | 便携重视程度 |
| `battery_life` | enum | low / medium / high | 续航重视程度 |
| `value_for_money` | enum | low / medium / high | 性价比重视程度 |
| `brand` | list[string] | 品牌名称 | 品牌偏好（非强制） |
| `scenarios` | list[string] | 场景描述 | 使用场景偏好 |

### 2.3 约束元数据结构

每个硬约束和软偏好都附加元数据：

```json
{
  "field": "budget_max",
  "value": 8000,
  "source_type": "explicit",
  "confidence": 0.95,
  "source_text": "预算8000以内"
}
```

| 元数据字段 | 说明 | 示例 |
|-----------|------|------|
| `field` | 约束字段名 | `budget_max` |
| `value` | 提取值 | `8000` |
| `source_type` | 来源类型：`explicit`（用户明确说）或 `inferred`（系统推断） | `explicit` |
| `confidence` | 提取置信度：0.0–1.0 | `0.95` |
| `source_text` | 原始文本片段 | "预算8000以内" |

### 2.4 约束分类决策规则

**规则 1：强限制表达检测**

以下关键词触发硬约束标记（`source_type = explicit`）：
- 预算："预算X元/以内/以下/不超过/最多/上限/之内"
- 下限："至少/最低/不低于/以上/起"
- 独显："必须独显/只要独显/必须带显卡/非核显不可"
- 内存："至少XGB/不低于X/XG起步"
- 重量："不超过Xkg/轻于X/Xkg以下"
- 屏幕："X到Y寸/只要X寸"
- 品牌："只要/只考虑/限定/必须是 XX品牌"
- 品类："只要游戏本/限定轻薄本"
- 接口："必须有/需要/要求 XX接口"

**规则 2：模糊表达处理**

以下表达**不进入硬约束**，而是进入软偏好：
- "轻便" → `portability: high`（软偏好，不设置 weight_max）
- "高刷" → 如果无明确数字，不设置 refresh_rate_min，仅影响排序权重
- "续航好" → `battery_life: high`（软偏好，不设置 battery_min）
- "性能强" → `performance: high`（软偏好）
- "便宜点" → `value_for_money: high`（不设置 budget_max）
- "最好是XX品牌" → `brand: ["XX"]`（软偏好，不设置硬约束）

**规则 3：追问触发**

当模糊表达影响推荐质量较大时，系统追问：
- "轻便" + 未提及重量 → 追问："您对重量有具体要求吗？（如不超过1.5kg）"
- "高刷" + 未提及数字 → 追问："您对刷新率有要求吗？（如144Hz以上）"
- "续航好" + 未提及场景 → 追问："您通常需要外出使用多久？"

**规则 4：默认假设标注**

如果追问后信息仍不完整，系统继续执行，但输出中必须说明：

```
"基于您提供的信息，我将按以下默认假设为您推荐：
• 预算范围：不限（您未指定）
• 重量要求：无特别限制
• 使用场景：综合办公与轻度娱乐

如果您有更具体的需求，可以随时告诉我。"
```

### 2.5 CPU 品牌 / 品类 / 品牌偏好的特殊处理

| 用户表达 | 处理方式 | 类型 |
|----------|----------|------|
| "必须是联想" / "只考虑华硕" | `brand: ["联想"]` 硬约束 | hard |
| " preferably 联想" / "最好联想" | `brand: ["联想"]` 软偏好 | soft |
| "只要游戏本" / "限定轻薄本" | `category: "游戏本"` 硬约束 | hard |
| "适合办公" / "平时编程用" | `scenarios: ["办公", "编程"]` + 推断 category | soft（推断） |
| "必须是Intel CPU" | `cpu_brand: "Intel"` 硬约束 | hard |
| "Intel 更好吧？" | `cpu_brand: "Intel"` 软偏好 | soft |

---

## 三、追问机制：澄清轮与冲突解决轮

### 3.1 两轮的定义与区别

| 维度 | 澄清轮（Clarification Turn） | 冲突解决轮（Conflict Resolution Turn） |
|------|---------------------------|--------------------------------------|
| **触发条件** | 需求信息不足，无法有效过滤 | 硬约束过滤后候选集为空 |
| **目的** | 补齐缺失的关键信息 | 引导用户放宽约束以恢复候选 |
| **次数限制** | 最多 **1 轮**，每轮最多 **2 个问题** | **不占用**澄清轮次数 |
| **用户回复后的动作** | 更新状态 → 重新评估 → 继续主流程 | 更新约束 → 重新过滤 → 展示结果 |
| **系统行为** | 主动询问 | 分析冲突 → 提供选项 → 展示最接近候选 |
| **输出内容** | 追问文本 | 冲突说明 + 放宽选项 + 最接近候选 |

### 3.2 澄清轮流程

```
用户输入
  → 提取约束和偏好
  → 检查 missing_critical_info（缺失的关键信息）
    ├─ 如果追问次数 < 1 且 缺失信息存在:
    │   → 触发澄清轮
    │   → 生成追问文本（最多2个问题）
    │   → 等待用户回复
    │   → 用户回复后更新状态
    │   → 如果仍然缺失但已达次数上限:
    │     → 标记 default_assumptions，继续执行
    │     → 输出中说明默认假设
    └─ 否则:
      → 继续主流程
```

### 3.3 冲突解决轮流程

```
硬约束过滤后候选集为空
  → 触发冲突解决轮
  → 分析冲突：
    • 列出每个硬约束及其严格程度
    • 计算各约束的"放宽潜力"
  → 生成冲突说明文本
  → 提供放宽选项（2-3个）
  → 计算并展示 1-2 款最接近候选（基于违约成本）
  → 等待用户选择
  → 用户选择后更新约束 → 重新过滤
```

### 3.4 追问模板示例

**澄清轮示例**：

```
用户："想买台笔记本"
Agent："好的！为了给您精准推荐，想先确认两点：
1. 您的预算大概在什么范围？（如5000-8000元）
2. 主要用来做什么？（如办公、编程、游戏、设计）"
```

```
用户："推荐个游戏本"
Agent："游戏本的选择范围很大，想再确认一下：
1. 您的预算上限是多少？
2. 主要玩什么类型的游戏？（如3A大作、网游、轻度游戏）"
```

**冲突解决轮示例**：

```
用户："想要1kg以下的游戏本，带RTX 4060，预算6000"

Agent：
"我检查了知识库中的48款笔记本，没有找到同时满足这三项条件的商品。

【冲突分析】
• 带 RTX 4060 的笔记本最轻为 2.1kg，无法满足 1kg 以下
• 带 RTX 4060 的笔记本最低价为 6499 元，超出您的预算

【建议调整方案】
1. 放宽重量到 2.2kg 以内、预算到 6500 元
2. 放弃独显要求，选择 1kg 以下的高性能核显轻薄本
3. 仅放宽重量到 2.2kg，保持预算6000

【最接近候选参考】
• 联想 拯救者R7000（2.15kg / ¥6499）
  - 满足：独显 RTX 4060
  - 违反：重量（超0.15kg）、预算（超499元）

您希望调整哪项条件？"
```

### 3.5 默认假设说明

如果澄清轮后信息仍不完整：

```
Agent 输出追加：
"⚠️ 说明：由于您未提供以下信息，我采用了默认假设进行推荐：
• 预算范围：不限（默认）
• 重量要求：无特别限制（默认）
• 内存需求：16GB 以上（默认）

如果您有更具体的需求，请随时告诉我，我可以为您重新筛选。"
```

---

## 四、冲突处理：违约成本与最接近候选

### 4.1 违约成本计算

当硬约束过滤结果为空时，计算每款商品的**违约成本**（Violation Cost）：

```
violation_cost(sku) = Σ(violation_score(constraint_i))

其中：
violation_score(constraint) = 
  0                               如果商品满足该约束
  importance(constraint) × violation_magnitude  如果不满足

importance(constraint):
  • gpu_required: 1.0（最高，因为二元约束）
  • budget_max: 0.9
  • budget_min: 0.3（下限通常较灵活）
  • ram_min: 0.7
  • weight_max: 0.6
  • screen_size_range: 0.5
  • storage_min: 0.4
  • gpu_vram_min: 0.8
  • category: 0.8
  • cpu_brand: 0.6
  • required_ports: 0.7

violation_magnitude:
  • 数值类约束：|实际值 - 约束边界| / 约束边界（超出比例）
  • 二元约束：1.0（只要违反就是完全违反）
  • 范围约束：|实际值 - 最近边界| / 范围跨度
```

### 4.2 违约成本示例

假设用户约束：
- budget_max = 6000
- weight_max = 1.0
- gpu_required = true

候选商品：

| 商品 | price | weight_kg | gpu_type | 违约项 | 违约成本 |
|------|-------|-----------|----------|--------|----------|
| SKU-A | 5499 | 0.95 | 核显 | gpu_required | 1.0 × 1.0 = **1.0** |
| SKU-B | 6499 | 1.05 | 独显 | budget_max(超499/6000=0.083), weight_max(超0.05/1.0=0.05) | 0.9×0.083 + 0.6×0.05 = **0.105** |
| SKU-C | 6999 | 0.98 | 独显 | budget_max(超999/6000=0.167) | 0.9×0.167 = **0.15** |

违约成本排序：SKU-B(0.105) < SKU-C(0.15) < SKU-A(1.0)

**最接近候选**：SKU-B、SKU-C

### 4.3 最接近候选展示规则

1. **最多展示 2 款**
2. **必须明确标注**：
   - ✅ 满足了哪些约束
   - ❌ 违反了哪些约束
   - 📊 违反幅度（具体数值）
3. **不得混入"完全符合"推荐列表**
4. **单独分区展示**：在"最接近候选"区域展示，与正常推荐物理隔离

### 4.4 冲突解决后的流程

用户选择放宽某约束后：
1. 更新 `UserNeedState` 中对应约束值
2. 标记该约束的 `source_type` 为 `user_adjusted`
3. 重新执行过滤 → 排序 → 推荐
4. 输出中说明："根据您放宽的条件，已为您重新筛选"

---

## 五、工具与工作流节点分离

### 5.1 设计原则

- **工作流节点**：系统内部的决策和编排逻辑，不对外暴露为 LLM 可调用的工具
- **外部工具**：需要实际执行查询、计算、校验等操作的单元，有明确的输入输出，可被 LLM 调用或程序直接调用

### 5.2 内部工作流节点（6 个）

| 节点 | 功能 | 说明 |
|------|------|------|
| `intent_recognition` | 识别用户意图类型 | 规则 + LLM 分类 |
| `constraint_extraction` | 从用户输入提取硬约束和软偏好 | LLM + 规则校验 |
| `followup_decision` | 判断是否触发澄清轮 | 基于缺失信息检查 |
| `state_update` | 更新用户需求状态 | 合并新约束到历史状态 |
| `recommendation_generation` | 生成推荐理由和对比分析 | LLM + 证据模板 |
| `conflict_routing` | 判断过滤结果是否触发冲突解决 | 候选集数量检查 |

### 5.3 外部可调用工具（5 个）

#### 工具 1：parse_product_image

**功能**：解析用户上传的商品详情页截图或参数表截图，提取品牌、型号、价格和主要参数，匹配知识库 SKU

**输入**：
```json
{
  "image_path": "user_upload/screenshot.png",
  "image_type": "param_page" // 或 "product_image"
}
```

**输出**：
```json
{
  "matched_skus": [
    {
      "sku_id": "lnv_y7p_2024_i7_4060_32",
      "match_confidence": 0.92,
      "extracted_params": {
        "brand": "联想",
        "model": "拯救者Y7000P",
        "price": 7999,
        "cpu": "i7-14650HX",
        "gpu": "RTX 4060"
      }
    }
  ],
  "extracted_text": "联想拯救者Y7000P 2024..."
}
```

**使用场景**：用户上传截图后调用

---

#### 工具 2：search_products

**功能**：执行完整的商品搜索流程，包括结构化过滤、混合检索和候选排序

**输入**：
```json
{
  "hard_constraints": {
    "budget_max": 8000,
    "gpu_required": true,
    "ram_min": 16,
    "weight_max": 2.0
  },
  "soft_preferences": {
    "performance": "high",
    "portability": "medium",
    "scenarios": ["编程开发", "轻度游戏"]
  },
  "search_mode": "normal", // "normal" 或 "nearest"
  "top_k": 5
}
```

**输出**（normal 模式）：
```json
{
  "results": [
    {
      "sku_id": "lnv_y7p_2024_i7_4060_32",
      "rank": 1,
      "total_score": 0.87,
      "dimension_scores": {
        "cpu": 0.85,
        "gpu": 0.90,
        "portability": 0.60,
        "battery": 0.70,
        "value": 0.75,
        "scenario_match": 0.92
      },
      "constraint_check": {
        "budget_max": "pass",
        "gpu_required": "pass",
        "ram_min": "pass",
        "weight_max": "pass"
      }
    }
  ],
  "filtered_count": 12,
  "total_pool": 48,
  "search_mode": "normal"
}
```

**输出**（nearest 模式，过滤为空时）：
```json
{
  "results": [],
  "nearest_candidates": [
    {
      "sku_id": "...",
      "violation_cost": 0.15,
      "violations": [
        {
          "field": "budget_max",
          "constraint_value": 6000,
          "actual_value": 6499,
          "magnitude": 0.083
        }
      ],
      "satisfied_constraints": ["gpu_required", "weight_max", "ram_min"]
    }
  ],
  "search_mode": "nearest"
}
```

**使用场景**：约束提取后调用，根据过滤结果自动切换模式

---

#### 工具 3：retrieve_evidence

**功能**：为指定 SKU 检索相关的事实证据和文本证据

**输入**：
```json
{
  "sku_ids": ["lnv_y7p_2024_i7_4060_32", "asus_tianxuan5_2024"],
  "query_context": "编程开发 游戏 性能",
  "evidence_types": ["fact", "evidence"] // 不包含 derived
}
```

**输出**：
```json
{
  "evidence": [
    {
      "sku_id": "lnv_y7p_2024_i7_4060_32",
      "documents": [
        {
          "type": "fact",
          "source": "联想官网",
          "content": "CPU: i7-14650HX, 16核24线程"
        },
        {
          "type": "evidence",
          "source": "什么值得买评测",
          "content": "编程场景下编译速度快，多线程性能优秀"
        }
      ]
    }
  ]
}
```

**使用场景**：生成推荐理由前调用，为 Top-K 候选获取证据

---

#### 工具 4：compare_products

**功能**：对多个 SKU 进行参数对齐和差异分析

**输入**：
```json
{
  "sku_ids": ["lnv_y7p_2024_i7_4060_32", "asus_tianxuan5_2024"],
  "compare_dimensions": ["price", "cpu", "gpu", "ram", "weight", "screen"]
}
```

**输出**：
```json
{
  "comparison_matrix": {
    "price": {
      "lnv_y7p_2024_i7_4060_32": 7999,
      "asus_tianxuan5_2024": 7799,
      "winner": "asus_tianxuan5_2024",
      "diff": "联想贵200元"
    },
    "cpu": {
      "lnv_y7p_2024_i7_4060_32": "i7-14650HX",
      "asus_tianxuan5_2024": "i7-13620H",
      "winner": "lnv_y7p_2024_i7_4060_32",
      "diff": "联想CPU更强"
    }
  },
  "summary": "华硕便宜200元且更轻，联想CPU更强"
}
```

**使用场景**：意图为 compare 时调用，或推荐理由中需要对比时

---

#### 工具 5：verify_response

**功能**：校验最终生成的推荐回答的质量和准确性

**输入**：
```json
{
  "response_text": "为您推荐联想拯救者Y7000P，搭载i7-14650HX和RTX 4060，售价7999元...",
  "recommended_skus": ["lnv_y7p_2024_i7_4060_32"],
  "user_constraints": {
    "budget_max": 8000,
    "gpu_required": true
  },
  "evidence_used": [
    {
      "sku_id": "lnv_y7p_2024_i7_4060_32",
      "evidence_id": "doc_001",
      "content": "CPU: i7-14650HX"
    }
  ]
}
```

**输出**：
```json
{
  "verification_passed": true,
  "checks": {
    "constraint_compliance": {
      "passed": true,
      "details": "所有推荐商品均满足用户硬约束"
    },
    "parameter_accuracy": {
      "passed": true,
      "details": "推荐理由中的参数与知识库一致",
      "verified_params": [
        {"param": "cpu_model", "kb_value": "i7-14650HX", "response_value": "i7-14650HX", "match": true}
      ]
    },
    "evidence_support": {
      "passed": true,
      "details": "所有推荐理由均有对应证据支持",
      "evidence_coverage": 0.95
    }
  },
  "confidence": 0.92
}
```

**内部子模块**：

##### 5.3.5.1 check_constraint_compliance

- 检查所有推荐 SKU 是否满足用户硬约束
- 输出：每个约束的通过/失败状态

##### 5.3.5.2 check_parameter_accuracy

- 从推荐理由文本中提取参数声明（如"搭载 i7-14650HX"）
- 与 `products.jsonl` 中的对应字段比对
- 输出：参数名、知识库值、文本值、是否匹配

##### 5.3.5.3 check_evidence_support

- 检查推荐理由中的每个论点是否有对应的证据文档
- 证据覆盖率 = 有证据支持的论点数 / 总论点数
- 输出：覆盖率、缺失支持的论点列表

---

### 5.4 工具调用编排流程

```
用户输入
  → [工作流: intent_recognition]
    ├─ 意图 = purchase
    │   → [工作流: constraint_extraction]
    │   → [工作流: followup_decision]
    │     ├─ 信息不足 → 生成追问 → 等待
    │     └─ 信息充足 → 继续
    │   → [工作流: state_update]
    │   → 调用 search_products (normal)
    │     ├─ 候选为空 → [工作流: conflict_routing]
    │     │   → 调用 search_products (nearest)
    │     │   → 展示冲突分析和最接近候选
    │     │   → 等待用户决策 → 更新状态 → 重新搜索
    │     └─ 有候选 → 继续
    │   → 调用 retrieve_evidence (Top-K)
    │   → [工作流: recommendation_generation]
    │   → 调用 verify_response
    │   → 流式输出结果
    │
    ├─ 意图 = compare
    │   → 提取 SKU 列表
    │   → 调用 compare_products
    │   → 调用 retrieve_evidence
    │   → 生成对比分析
    │   → 流式输出
    │
    ├─ 意图 = inquiry
    │   → 匹配 SKU
    │   → 调用 retrieve_evidence
    │   → 生成回答
    │   → 流式输出
    │
    └─ 意图 = multimodal
      → 调用 parse_product_image
      → 根据匹配结果路由到 purchase/compare/inquiry
```

---

## 六、可复现的偏好权重机制

### 6.1 三级偏好强度

| 用户表达 | 偏好强度 | 程序映射值 |
|----------|----------|------------|
| "非常重视/必须/首要考虑" | `high` | 0.85 |
| "比较看重/希望/ preferably" | `medium` | 0.60 |
| "无所谓/一般/不太在意" | `low` | 0.35 |
| 未提及 | 默认值 | 0.50 |

### 6.2 LLM 提取要求

LLM 在提取软偏好时，只输出 `low` / `medium` / `high`，不输出小数。

提取 Prompt 示例：
```
请从用户查询中提取软偏好，每个偏好只能是 "low" / "medium" / "high" 之一：

用户："想买台笔记本，主要编程用，希望轻便点，续航无所谓"

输出：
{
  "performance": "medium",
  "portability": "high",
  "battery_life": "low"
}
```

### 6.3 实验复现保障

- 三级制的映射值（0.35 / 0.50 / 0.60 / 0.85）在代码中**硬编码**
- 同一查询在不同运行中产生的排序结果**完全一致**
- 消融实验时，可以固定某些偏好为 `medium`，观察其他偏好的影响

---

## 七、修正后的场景化排序方法

### 7.1 商品预计算分数

在数据采集阶段或系统初始化阶段，为每款商品预计算以下分数：

| 分数名称 | 计算方法 | 说明 |
|----------|----------|------|
| `cpu_performance_score` | 基于 CPU 代际 + 核心数 + 基础频率的归一化分数 | 不是简单用 cpu_cores |
| `gpu_performance_score` | 基于 GPU 型号代际 + 显存 + TGP 的归一化分数 | 不是简单用 gpu_vram_gb |
| `portability_score` | 基于 weight_kg 的反向归一化（越轻分越高） | 直接反映便携性 |
| `battery_capacity_score` | 基于 battery_wh 的归一化 | **仅为容量代理指标，不对真实续航作保证** |

**CPU 性能评分规则（示例）**：
```
cpu_score = base_score(cpu_generation) + cores_score(cpu_cores) + freq_score(base_frequency)

其中：
- base_score: Intel 13代=60, 14代=70; AMD 7000系=65, 8000系=75; Apple M3=80
- cores_score: 每核+2分（最多+32分）
- freq_score: 每0.1GHz +1分（最多+20分）
- 最终归一化到 0–1
```

**GPU 性能评分规则（示例）**：
```
gpu_score = base_score(gpu_tier) + vram_score(vram_gb) + tgp_score(tgp_w)

其中：
- base_score: RTX 4050=50, 4060=70, 4070=85, 4080=95
- vram_score: 每GB +5分
- tgp_score: 每10W +2分
- 最终归一化到 0–1
```

**免责声明**：
- `battery_capacity_score` 标注为"电池容量评分"，不是"续航评分"
- 输出时说明："电池容量评分基于电池瓦时数，实际续航受使用场景影响"

### 7.2 场景化基础权重

不同场景使用不同的**基础权重模板**：

| 场景 | cpu | gpu | ram | battery | weight | price | 说明 |
|------|-----|-----|-----|---------|--------|-------|------|
| **办公学习** | 0.20 | 0.05 | 0.25 | 0.30 | 0.15 | 0.05 | 重视续航和便携 |
| **编程开发** | 0.25 | 0.10 | 0.30 | 0.15 | 0.10 | 0.10 | 重视CPU和内存 |
| **游戏娱乐** | 0.20 | 0.35 | 0.15 | 0.10 | 0.05 | 0.15 | 重视GPU |
| **视频剪辑/设计** | 0.25 | 0.30 | 0.25 | 0.10 | 0.05 | 0.05 | 重视GPU和内存 |

**场景推断规则**：
- 用户明确说"编程/写代码/开发" → 编程开发场景
- 用户明确说"游戏/打3A/玩网游" → 游戏娱乐场景
- 用户明确说"剪辑/设计/渲染" → 视频剪辑/设计场景
- 用户说"办公/学习/写论文" → 办公学习场景
- 用户说"综合/都做点/不确定" → 使用默认权重（各维度均衡）

### 7.3 用户偏好调整

在场景基础权重上，叠加用户显式偏好：

```
final_weight(dimension) = base_weight(dimension) × (1 + preference_boost(dimension))

其中 preference_boost:
  • preference = "high": +0.3
  • preference = "medium": +0.0
  • preference = "low": -0.2
  • 未提及: +0.0

最后归一化，确保所有维度权重之和为 1.0
```

### 7.4 最终排序公式

```
total_score(sku) = Σ(
  dimension_weight × sku_dimension_score
)

其中 dimension ∈ {cpu, gpu, ram, battery, weight, price, scenario_match, brand_match}

各维度 sku 分数：
• cpu: cpu_performance_score
• gpu: gpu_performance_score
• ram: ram_gb 归一化
• battery: battery_capacity_score
• weight: portability_score
• price: 性价比分数 (性能综合分 / price，归一化)
• scenario_match: 商品 scenario_desc 与用户 scenarios 的语义相似度
• brand_match: 0/1（是否在用户 brand 列表中）
```

### 7.5 排序结果解释性

推荐理由中必须说明排序依据：

```
"基于您的需求（编程开发、重视便携），系统按以下权重评估：
• CPU性能：25%（编程场景基础权重）
• 内存：30%（编程场景基础权重）
• 便携：+15%（您强调轻便）
• GPU：-5%（您未强调游戏）

Top 1 拯救者Y7000P 在这些维度表现均衡..."
```

---

## 八、完整业务流程示例（v0.3 版）

### 示例 1：正常购买咨询（含场景推断）

```
用户："想买台笔记本写代码，预算7000左右，希望轻便一点"

Agent 处理：
1. 意图识别 → purchase
2. 约束提取：
   • budget_max = 7000 (explicit, 0.95, "预算7000左右")
   • scenarios = ["编程开发"] (inferred, 0.80, "写代码")
   • portability = "high" (explicit, 0.90, "希望轻便一点")
3. 检查 missing_critical_info：
   • 预算 ✓ | 场景 ✓ | 重量模糊但已作为偏好
   • 无需追问（信息充足）
4. 硬约束过滤：budget_max ≤ 7000
   • 过滤后候选：18款
5. 场景推断 → "编程开发"场景
   • 基础权重：cpu=0.25, gpu=0.10, ram=0.30, battery=0.15, weight=0.10, price=0.10
6. 用户偏好调整：portability=high → weight 权重 +0.3
   • 最终权重：cpu=0.22, gpu=0.09, ram=0.26, battery=0.13, weight=0.19, price=0.11
7. 排序 → Top 5
8. 检索证据 → 生成推荐理由
9. 校验 → 通过
10. 输出：

"为您推荐以下笔记本（基于编程场景 + 便携偏好）：

Top 1: 联想 ThinkBook 14+ 2024 (¥6499)
• CPU: Ultra 5 125H | GPU: 核显 | 内存: 32GB | 重量: 1.5kg
• 推荐理由：32GB大内存适合多开IDE和虚拟机，1.5kg便于携带
• 证据：官方规格表（32GB内存）、评测（编程场景编译速度优秀）

Top 2: 华硕 灵耀14 2024 (¥6999)
..."
```

### 示例 2：触发澄清轮

```
用户："推荐个笔记本"

Agent：
"好的！为了给您精准推荐，想先确认两点：
1. 您的预算大概在什么范围？
2. 主要用来做什么？"

用户："预算8000以内，打游戏"

Agent：[信息充足，继续主流程]
```

### 示例 3：触发冲突解决轮 + 最接近候选

```
用户："想要1kg以下的游戏本，RTX 4060，预算6000"

Agent 处理：
1. 约束提取：
   • weight_max = 1.0 (explicit, 0.95)
   • gpu_required = true (explicit, 0.98)
   • budget_max = 6000 (explicit, 0.95)
2. 硬约束过滤 → 结果为空（0款）
3. 触发冲突解决轮
4. 违约成本计算：
   • 联想 R7000: 违反 budget(超499/6000=8.3%) + weight(超1.15/1.0=115%) → 成本=0.9×0.083+0.6×1.15=0.075+0.69=0.765
   • 机械革命 极光Pro: 违反 budget(超300/6000=5%) + weight(超1.05/1.0=105%) → 成本=0.9×0.05+0.6×1.05=0.045+0.63=0.675
   • 排序：极光Pro(0.675) < R7000(0.765)
5. 输出：

"没有找到同时满足这三项条件的笔记本。

【冲突分析】
• 带 RTX 4060 的笔记本最轻约 2.05kg，无法满足 1kg 以下
• 带 RTX 4060 的笔记本最低价约 6299 元，超出预算

【建议方案】
1. 放宽重量到 2.2kg、预算到 6500 元
2. 放弃独显，选择 1kg 核显轻薄本
3. 仅放宽重量到 2.2kg

【最接近候选】
• 机械革命 极光Pro 2024（2.05kg / ¥6299）
  ✅ 满足：独显 RTX 4060
  ❌ 违反：重量（超1.05kg）、预算（超299元）

您希望怎么调整？"

用户："那就放宽重量吧"

Agent：[更新 weight_max=2.2, source_type=user_adjusted]
→ 重新过滤 → 有候选 → 正常推荐
```

---

## 九、关键设计决策确认

| 决策项 | v0.3 方案 | 说明 |
|--------|-----------|------|
| 硬约束字段 | **13 个** | 新增 storage_min, gpu_vram_min, required_ports，可选 resolution_min/refresh_rate_min |
| 约束来源 | **explicit / inferred 区分** | 明确标注每个约束的提取来源和置信度 |
| 模糊表达 | **软偏好优先** | "轻便"→portability=high，不直接映射 weight_max |
| 追问机制 | **澄清轮 1 次 + 冲突解决轮独立** | 冲突解决不占用追问次数 |
| 冲突处理 | **违约成本 + 最接近候选** | 违约成本独立于排序，候选单独分区展示 |
| 工具数量 | **5 个外部工具** | parse_product_image, search_products, retrieve_evidence, compare_products, verify_response |
| 工作流节点 | **6 个内部节点** | 意图识别、约束提取、追问判断、状态更新、推荐生成、冲突路由 |
| 偏好权重 | **三级制 low/medium/high** | 程序固定映射，保证实验复现 |
| 排序维度 | **预计算分数 + 场景化权重** | cpu_performance_score, gpu_performance_score, portability_score, battery_capacity_score |
| 场景模板 | **4 个场景** | 办公学习、编程开发、游戏娱乐、视频剪辑/设计 |
| 参数校验 | **verify_response 内部三检查** | 约束满足率、参数准确性、证据支持率 |

---

## 附录：v0.3 后续修订要点（已确认，纳入最终设计）

以下修订由项目负责人于 2026-08-01 确认，直接并入当前设计：

### A. 违约成本与约束优先级（v0.3.1）

**约束元数据增强**：每个硬约束增加 `priority` 和 `relaxable` 字段：

| 用户表达 | priority | relaxable | 说明 |
|----------|----------|-----------|------|
| "最重要、绝对不能、不能妥协" | `critical` | `false` | 违反则该商品直接排除 |
| 普通明确硬约束 | `normal` | `true` | 可参与违约成本计算 |
| "可以适当放宽、差一点也行" | `relaxable` | `true` | 违约成本权重降低 |

**违约成本分层排序规则**（替代简单求和）：

```
排序优先级（从高到低）：
1. 违反约束数量（越少越好）
2. 是否违反 critical 或 relaxable=false 的约束（无违反优先）
3. 加权违反幅度（violation_cost 求和，critical 约束权重 ×2）
4. 正常推荐分数（处理并列）
```

**数值安全**：
- 违反幅度上限设为 200%（即超出约束边界 2 倍时封顶）
- 单点约束（如 screen_size = 14.0）不使用除法，改用绝对差值

### B. 场景模板扩展（v0.3.2）

最终 5 个场景：

| 场景 | CPU | GPU | RAM | Battery | Weight | Price | 说明 |
|------|-----|-----|-----|---------|--------|-------|------|
| 办公学习 | 0.20 | 0.05 | 0.25 | 0.30 | 0.15 | 0.05 | 重视续航和便携 |
| 编程开发/数据分析 | 0.25 | 0.10 | 0.30 | 0.15 | 0.10 | 0.10 | 重视CPU和内存 |
| **AI/深度学习** | 0.15 | **0.35** | **0.30** | 0.05 | 0.05 | 0.10 | **重视GPU性能和显存** |
| 游戏娱乐 | 0.20 | 0.35 | 0.15 | 0.10 | 0.05 | 0.15 | 重视GPU |
| 视频剪辑/设计 | 0.20 | 0.30 | 0.25 | 0.10 | 0.05 | 0.10 | 重视GPU和内存 |

AI/深度学习场景额外关注：
- `gpu_performance_score`（权重 0.35）
- `gpu_vram_gb`（影响大模型训练能力）
- `ram_gb`（权重 0.30，数据集加载需要大内存）
- 散热/性能释放（如有可靠证据）

### C. 结果多样性控制（v0.3.3）

`verify_response` 保留三项核心检查，**不增加多样性检查**。

`search_products` 正常模式后增加轻量 `diversity_rerank`：
- Top-5 中同一品牌最多 2 款
- 用户明确限定品牌时不应用该限制
- 符合条件商品不足时允许突破
- 同品牌明显更优时允许保留，但输出中说明

多样性作为推荐策略，后续可单独评估品牌覆盖率。

### D. 全路径校验与失败处理（v0.3.4）

| 路径 | 校验内容 | 额外要求 |
|------|----------|----------|
| purchase | 约束满足 + 参数准确 + 证据支持 | 完整三项 |
| compare | 参数准确 + 证据支持 | 不检查约束满足（无主动约束） |
| inquiry | 参数准确 + 证据支持 | 不检查约束满足 |
| multimodal | 参数准确 + 证据支持 + 图片解析置信度 + SKU 匹配置信度 | 保留解析可信度 |

**校验失败处理**：
- 第一次失败 → 定向修正（如参数错误则重写该句） → 重新校验
- 第二次失败 → 输出保守答案，标记"部分内容无法确认"
- 禁止无限循环

---

**本方案及所有修订确认后，进入第三个关键决策：评估体系与测试集构造。**
