# 02 · 方案与取舍

## 1. 一句话方案

原生 Python 实现的 CLI Agent：Writer 在预算内执行 `search → get → draft → estimate/check → review → finish` 的 ReAct 循环；独立 FactReviewer 只读素材 claim 做第二道事实审核；`finish(completed)` 必须同时通过确定性规则检查和 reviewer，否则打回继续，预算耗尽则返回明确未完成状态。

## 2. 调用流程

```text
CLI / JSON 输入
   │
   ▼
validate_request ── 缺字段/格式错 ──► invalid_input（退出码 5）
   │
   ▼
┌──────────────────────── WriterAgent 循环（≤12 步，≤10 次工具）────────────────────────┐
│                                                                                      │
│  模型输出 JSON {action, args, reason}                                                 │
│    │                                                                                 │
│    ├─ search_materials ── 0 条 ──► 模型改写 query 再试一次 ── 仍 0 ──► ask_user        │
│    ├─ get_material     ── 读取 claim 原文，作为后续写作的唯一事实来源                   │
│    ├─ draft_script     ── 产出 title + shots(source_ids, claim_ids)                    │
│    ├─ estimate_duration── 只算时长，不改脚本                                           │
│    ├─ check_rules      ── 时长/平台/结构/claim/数字/能力词/禁用表达                     │
│    ├─ review_facts     ── FactReviewer 独立审核，severity=error 即 fail                │
│    ├─ ask_user         ── 素材/信息不足，返回问题与选项                                 │
│    └─ finish           ── Agent 重新跑 check + 检查 reviewer，通过才 completed          │
│                                                                                      │
│  每一步把 action/args 摘要/observation/reason 写入 trace.jsonl                          │
└──────────────────────────────────────────────────────────────────────────────────────┘
   │
   ├─ completed / needs_input / insufficient_evidence / cannot_satisfy
   ├─ tool_error / model_error / step_limit_reached / invalid_input
   ▼
output.json（标题、分镜、旁白、总时长、素材来源、风险、任务状态）
```

## 3. 为什么是原生 Python，而不是 LangGraph / ADK / AgentScope

这是本项目最重要的取舍。

| 方案 | 优点 | 本项目不选的原因 |
| --- | --- | --- |
| LangGraph | 图状态机成熟，生态好 | 本题只有 8 个动作、1 个主循环 + 1 个 reviewer；引入图框架后，预算、JSON 修复、finish 门禁、Trace 仍要自己写，反而多一层抽象。评审需要看到“模型如何根据工具结果改动作”，原生循环最直接。 |
| Google ADK | 工具/Agent 抽象完整 | 依赖较重，默认绑定 Gemini 生态；本题模型可替换为 DeepSeek，且需要精确控制“何时拒绝 finish”，框架默认行为会增加解释成本。 |
| AgentScope | 多 Agent 消息传递方便 | 本题的 two-agent 是 generator–critic，不需要复杂消息总线；引入后会掩盖 reviewer 的独立上下文边界。 |
| 原生实现 | 零依赖、可审计、可测试、Trace 完全可控 | 需要自己写循环、预算、状态机；但本题规模小，成本可控。 |

结论：**框架名称不加分，能解释取舍才有价值**。本题的核心不是“把 Agent 搭起来”，而是“让 Agent 在工具结果不利时真的改，且不能假装成功”。原生实现让这条门禁逻辑完全可见、可测。

## 4. 为什么多一个 FactReviewer

只有确定性规则时，能抓住：

- 引用了不存在的 claim；
- claim 不属于 source；
- 数字在 claim 中找不到；
- 出现禁用表达；
- 能力词（字幕/模板/1080P 等）没有 claim 依据；
- 镜头数、平台时长不合格。

但抓不住语义延伸。典型例子：

> 素材只说“支持字幕”，脚本写“不用手动打字”。

“不用手动打字”没有出现任何能力词，也没有数字，机械规则会放过；但它是素材没有承诺的自动化能力。FactReviewer 使用**独立上下文**（只有需求、脚本、claim 目录），专门判断“这句话是否超出 claim 的语义边界”，返回 `verdict` + `findings`；只要有一条 `severity=error`，就强制 fail。

两层职责：

- 规则层：快、确定、可解释，负责硬约束；
- Reviewer：慢、语义、独立，负责软约束；
- Writer：只在两层都通过后才允许 `finish(completed)`。

这也避免了“同一个模型既写又审”的自我确认偏差：reviewer 不复用 writer 的对话历史，也不看 writer 的 reason。

## 5. 动作与工具

| 动作 | 参数 | 作用 | 是否计入 tool_calls |
| --- | --- | --- | --- |
| `search_materials` | `query`, `product_id?` | 关键词检索素材，返回 id/name/claim_ids | 是 |
| `get_material` | `material_id` | 读取素材全部 claim 原文、source、使用约束 | 是 |
| `draft_script` | `title`, `shots[]` | 提交/修改脚本 | 是 |
| `estimate_duration` | `script?` | 只估算，不修改 | 是 |
| `check_rules` | `script?`, `request?` | 跑全部确定性检查 | 是 |
| `review_facts` | 无 | 调用独立 reviewer | 否（计入 reviews） |
| `ask_user` | `question`, `missing`, `options`, `partial_script?` | 信息不足时停下 | 否 |
| `finish` | `status`, `message` | 申请结束 | 否 |

`ToolBox` 还支持故障注入（`--fault search_materials=timeout`），用于复现“工具失败”场景；故障只注入一次，后续调用正常。

## 6. 时长估算

公式（`src/tools/duration.py`）：

```text
speech_seconds = max(
    cjk_chars / 4.2,
    en_words / 2.5
)
shot_seconds = max(2.0, speech_seconds)
total = round(sum(shot_seconds + 0.2 for each shot), 1)
```

- 中文按 4.2 字/秒，英文按 2.5 词/秒；
- 每个镜头至少 2.0 秒（再短的旁白也要给画面停留）；
- 每个镜头加 0.2 秒转场；
- 总时长保留 1 位小数。

用 P01 实测：

- 首稿 157 个汉字 → `157/4.2 + 3×0.2 = 38.0s`；
- 修正稿 115 个汉字 → `115/4.2 + 3×0.2 = 28.0s`；
- 6 秒目标、3 个镜头、每镜 4 个汉字 → 每镜 `max(2.0, 0.95)=2.0`，总 `3×2.2=6.6s`，因此 6 秒不可满足。

为什么把估算做成工具而不是让模型“感觉”时长：

- 可复现、可测试、可解释；
- 模型不能通过“我觉得差不多 30 秒”绕过检查；
- 修改文案后可以立即重算，形成“改 → 查 → 再改”的闭环；
- 评审可以逐镜核对字数与秒数。

局限：这是文本近似，不含停顿、语速变化、音乐、画面节奏；真实制作仍需人工试听。

## 7. 事实可追溯

素材模型：

```json
{
  "id": "P01",
  "name": "小影 · 字幕功能",
  "claims": [
    {"claim_id": "P01-C1", "text": "支持字幕"}
  ],
  "usage_constraints": ["不得延伸为自动识别准确率、自动翻译或效率提升"]
}
```

脚本每个镜头必须带：

```json
{
  "visual": "手机屏幕上的字幕逐句出现",
  "narration": "打开字幕，检查断句和错字……",
  "source_ids": ["P01"],
  "claim_ids": ["P01-C1"]
}
```

检查顺序：

1. `source_ids`/`claim_ids` 非空；
2. claim 存在；
3. claim 的 material 必须在 `source_ids` 中；
4. narration 中出现能力词（字幕/模板/1080P/水印……）时，该词必须出现在所引 claim 文本中；
5. narration/title 中的数字必须在所引 claim 中出现（秒/帧/镜头数等时间结构量豁免）；
6. 禁用短语/正则；
7. 标题也要检查能力和数字；
8. 镜头数 3–8；
9. 平台时长上下限；
10. 目标时长的上下容差（低于目标 80% 判 `duration_under`）。

“数字豁免”是必要的：`30 秒`、`3 个镜头`、`1080P`、`9:16` 这类是创作参数或格式，不是产品效果数据；但 `效率提升 80%`、`准确率 99%` 这类必须能在 claim 中找到，否则报错。

## 8. 状态机与门禁

```text
                    ┌──────────────┐
输入 ──► validate ──►│ invalid_input│
                    └──────────────┘
                           │ 通过
                           ▼
                    ┌──────────────┐
                    │ Writer 循环  │
                    └──────┬───────┘
        ┌──────────────────┼──────────────────┬────────────────┐
        ▼                  ▼                  ▼                ▼
  finish(completed)   ask_user          finish(cannot)   预算耗尽
        │                  │                  │                │
        ▼                  ▼                  ▼                ▼
  重新 check + review  needs_input /     cannot_satisfy   step_limit_reached
  都通过 → completed   insufficient_     （需已有失败 check
  否则 finish_rejected  evidence         且 draft_count≥2）
```

`finish(completed)` 的门禁在 `src/agent.py`：

- 必须有 `last_check` 且 `ok=true`；
- 必须有 `reviewer_passed=true`；
- 否则记录 `finish_rejected`，不结束，继续让模型改。

`finish(cannot_satisfy)` 也不是模型说了算：

- 必须存在失败的 check；
- 必须至少 draft 过 2 次（证明尝试过修正）；
- 否则同样打回。

## 9. 预算与失败语义

默认值（`data/config.json`）：

```json
{
  "max_steps": 12,
  "max_tool_calls": 10,
  "max_json_repairs": 2,
  "max_reviews": 2
}
```

- 每步模型调用计 1 step；
- 本地工具 + `draft_script` 计 tool_calls；
- review 单独计 reviews；
- 模型输出不是合法 JSON 时，最多修复 2 次；仍失败 → `model_error`；
- 连续 3 次工具错误 → `tool_error`；
- 步数或工具调用耗尽 → `step_limit_reached`，带 `partial_script` 与已完成的检查；
- 达到上限绝不返回 `completed`。

这是题目“设置执行步数或工具调用次数上限，达到上限时返回明确未完成状态”的直接实现。

## 10. Provider 设计

`Provider` 接口只有：

```python
generate(system: str, messages: list, state: dict) -> ProviderResult
```

- `OpenAICompatProvider`：`POST {base_url}/chat/completions`，默认 `response_format={"type":"json_object"}`；如果服务端 400 且错误提到 `response_format`，自动去掉 JSON mode 重试一次；401/403 → `auth_error`，429 → `rate_limit`，5xx → `server_error`，网络错误 → `network_error`，空 content → `empty_content`。
- `MockProvider`：按场景和阶段返回预置 JSON，用于确定性测试与离线演示。
- `auto`：有 `LLM_API_KEY` 用 DeepSeek，否则 Mock。

这样真实模型与 Mock 共享同一套 Agent 循环、工具和门禁；切换 provider 不改变业务逻辑。

## 11. Trace 设计

`trace.jsonl` 每行一个事件：

```json
{"ts":"...","elapsed_ms":0,"event":"step","step":3,
 "action":"check_rules","args":{...},"reason":"核对预计时长……",
 "ok":true,"observation":{"ok":false,"errors":[{"code":"duration_over",...}]},
 "usage":{"total_tokens":0}}
```

- `ok` 表示**工具调用是否成功**，不是检查是否通过；检查结果在 `observation.ok`。这样能区分“工具坏了”和“脚本不合格”。
- `reason` 是模型自述的一句决策依据，不是思维链；文档和示例都不要求暴露模型内部推理。
- `review` 事件单独记录 verdict/findings；`run_end` 记录最终状态、预算、usage。
- `summarize` 对长 observation 做摘要，避免 Trace 膨胀，同时保留关键 ids/errors/total。

## 12. 备选方案与放弃原因

1. **让模型直接输出最终脚本，不做工具循环**：无法证明时长和事实，也无法在失败时调整；放弃。
2. **只用规则检查，不加 reviewer**：机械规则抓不住“不用手动打字”这类语义延伸；放弃。
3. **让 reviewer 也调用工具、自己检索**：会增加上下文和预算，且 reviewer 的职责应是“独立判断”，不是“再写一遍”；放弃。
4. **做 Web UI**：题目明确非必需，CLI + Trace 已能完整展示决策链；把时间留给门禁、测试和文档。
5. **用 LangGraph**：见第 3 节；本题规模下框架收益小于解释成本。

## 13. 代码入口

- CLI：`src/cli.py`（`python -m src.cli --help`）
- 主循环：`src/agent.py`
- 独立审核：`src/reviewer.py`
- 提示词：`src/prompts.py`
- 时长：`src/tools/duration.py`
- 规则：`src/tools/rules.py`
- Mock：`src/providers/mock.py`
- 示例生成：`scripts/run_examples.py`
