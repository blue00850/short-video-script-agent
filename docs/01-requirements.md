# 01 · 需求与验收口径

## 1. 用户与场景

**主要用户**：需要持续产出短视频的创作者/小团队运营（本次聚焦“新手也能看懂、能直接改”的口播类短视频）。

**典型任务**：给一个主题、受众、平台、目标时长和风格，要求生成一条**有事实依据**的短视频脚本；脚本要能直接编辑，且不能为了效果编造产品能力或数据。

**用户真正关心的三件事**：

1. 脚本能拍：有标题、分镜、旁白，镜头数量合理。
2. 时长能对上：估算总时长落在目标附近，超了要真的改，而不是口头说“已压缩”。
3. 事实能追溯：每一句产品能力都能回到素材 ID / claim ID；没有素材时宁可停下来问，也不编。

## 2. 输入

请求是一个 JSON 对象（CLI 也支持同名参数）：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `topic` | 是 | 视频主题 |
| `platform` | 是 | 抖音/快手/视频号/小红书/B站等，决定时长上下限 |
| `audience` | 否 | 目标受众，默认“短视频新手” |
| `target_seconds` | 否 | 目标时长，1–600 的整数；默认 30 |
| `style` | 否 | 风格，默认“口语化、节奏快” |
| `product_id` | 否 | 限定素材 ID（如 P01），用于“只讲这个产品”的场景 |
| `must_include` | 否 | 必须出现的短语数组 |
| `max_steps` | 否 | 覆盖默认最大决策步数（1–30） |

示例：`examples/p01_30s/input.json`

```json
{
  "topic": "给新手讲清楚小影的字幕功能",
  "audience": "短视频新手",
  "platform": "抖音",
  "target_seconds": 30,
  "style": "口语化、节奏快",
  "product_id": "P01"
}
```

## 3. 输出

`completed` 时输出：

| 字段 | 说明 |
| --- | --- |
| `title` | 标题 |
| `shots[]` | 分镜：`index`、`visual`（画面）、`narration`（旁白/字幕文案）、`source_ids`、`claim_ids` |
| `estimated_total_seconds` | 预估总时长 |
| `materials_used[]` | 实际引用的素材与 claim 原文、source |
| `duration_check` | 时长检查明细（每镜字数、speech、总时长、容差） |
| `brand_check` | 规则检查结果 |
| `risks[]` | 风险与限制（如合成数据、素材只覆盖一条事实） |
| `task_status` | `completed` |

非 `completed` 时也必须给出明确状态与原因，例如：

- `insufficient_evidence`：`question`、`missing`、`options`；
- `cannot_satisfy`：`best_attempt`、`blocking_errors`、计算说明；
- `step_limit_reached`：`partial_script`、`estimated_total_seconds`、`checks`；
- `invalid_input`：逐条字段错误。

## 4. 范围

**做**：

- CLI 单条脚本生成；
- 素材检索、素材详情、时长估算、规则检查、事实审核、追问、结束等动作；
- 有上限的 ReAct 循环与明确失败状态；
- 两个 Agent：Writer（执行循环）+ FactReviewer（独立事实审核）；
- 确定性 Mock，用于离线演示与测试；
- OpenAI-compatible 真实模型接入；
- JSONL Trace、9 组示例、36 个测试、评估文档。

**不做**（本次明确排除）：

- Web UI、账号体系、线上部署；
- 视频生成/剪辑、真实素材库接入；
- 多轮人工协作编辑、版本管理；
- 生产级任务队列、鉴权、并发、监控；
- 用真实用户数据做效果评估。

## 5. 成功标准

| 编号 | 标准 | 验证方式 |
| --- | --- | --- |
| S1 | 正常请求能生成完整可编辑脚本 | `examples/normal/` |
| S2 | 缺关键信息时不开始任务，返回字段级错误 | `examples/missing/` + CLI 测试 |
| S3 | 没有素材时不编造，改写查询后仍无结果则追问 | `examples/no_material/` |
| S4 | 工具失败时能观察错误并调整动作 | `examples/tool_failure/` |
| S5 | 首稿 38s 超 30s 时能压缩到 28s 并重检通过 | `examples/p01_30s/` |
| S6 | 规则不允许的内容会被拦截并改写 | `examples/rule_violation/` |
| S7 | 语义层能力延伸能被独立 reviewer 抓住并修正 | `examples/semantic_catch/` |
| S8 | 物理上无法满足时明确失败并给出计算 | `examples/impossible/` |
| S9 | 达到步数/工具上限时返回未完成，不伪装成功 | `examples/step_limit/` + 测试 |
| S10 | 每个产品事实都能回到素材 claim | `materials_used`、`claim_ids`、reviewer |
| S11 | 测试可执行、可重复 | `python -m unittest discover -s tests -v` |

## 6. 关键约束

- 不提交真实密钥；`.env` 忽略，`.env.example` 为空。
- 所有素材标注 `synthetic`，文档不得把合成数据说成真实产品资料。
- 没有效果数据时，不写“效率提升 80%”等结论；规则里也把这类表达列为禁用。
- Mock 结果只证明流程，不证明真实模型效果；真实模型运行需单独记录。
- 执行有硬上限：默认 12 步、10 次工具调用、2 次 review、2 次 JSON 修复；耗尽必须返回明确未完成状态。

## 7. 验收点与文件的对应

| 题目验收点 | 对应用例/测试 | 证据 |
| --- | --- | --- |
| 正常生成 | normal | `examples/normal/output.json`、`trace.jsonl` |
| 缺关键信息 | missing | `examples/missing/output.json`、`trace.jsonl` |
| 无素材 | no_material | `examples/no_material/trace.jsonl` |
| 工具失败 | tool_failure | `examples/tool_failure/trace.jsonl` |
| 超时长后的修正 | p01_30s | 首稿 38.0 → 修正 28.0，见 trace step 2–5 |
| 超时长后明确失败 | impossible | 6.6s vs 6s，见 output 的 `best_attempt`/`blocking_errors` |
| 规则检查 | rule_violation | 首检 5 条错误 → 修正后 0 条 |
| 动态决策 | p01_30s / tool_failure / semantic_catch / no_material | 每步 reason + 下一步动作不同 |
| 预算上限 | step_limit + Agent 测试 | 2 步耗尽，`step_limit_reached` |
| 事实可追溯 | 全部 completed 用例 | `materials_used` + `claim_ids` |
