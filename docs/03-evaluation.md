# 03 · 效果验证与限制

## 1. 验证口径

本项目把“效果”拆成三层，避免把流程跑通说成模型效果好：

| 层 | 验证什么 | 证据 |
| --- | --- | --- |
| 编排层 | 动作选择、工具结果观察、下一步调整、预算耗尽 | 9 组 `examples/*/trace.jsonl` + Agent 测试 |
| 规则层 | 时长、镜头数、claim、数字、禁用表达 | `tests/test_core.py` 的 Rule/Duration 测试 |
| 语义层 | 只声明“支持字幕”时是否写了“不用手动打字” | `examples/semantic_catch/` + Reviewer 测试 |

**重要边界**：`examples/` 下的 9 组流程用例由 `MockProvider` 生成，证明的是“给定这些工具结果，Agent 的循环、门禁、状态和 Trace 正确”。另有 2 组真实 DeepSeek 运行记录在 `examples/real/`（`normal`、`p01_30s`），证明在该 JSON schema 与工具集下，真实模型会观察工具结果并调整动作；但 2 条路径不能代表所有主题、所有模型或业务效果。两类证据在目录和文档中始终分开。

## 2. 九组用例：预期 vs 实际

| 用例 | 预期 | 实际 | 证据 |
| --- | --- | --- | --- |
| `normal` | 正常生成，时长/规则/review 全过 | `completed`，28.0s/30s，3 镜，P02，review pass | `examples/normal/output.json`、`trace.jsonl` |
| `p01_30s` | P01 只有“支持字幕”；首稿 38s，压缩到 28s，引用 P01 | 首稿 38.0 → `duration_over` → 修正 28.0 → pass；`materials_used` 仅 P01-C1 | `examples/p01_30s/` |
| `missing` | 缺 platform，不开始任务 | `invalid_input`，字段级错误，trace 只有 `validation_error` | `examples/missing/` |
| `no_material` | P99 查不到，改写查询；仍无则追问，不编造 | 两次 search count=0 → `ask_user` → `insufficient_evidence` | `examples/no_material/` |
| `tool_failure` | 首次 search 超时，观察后改写 query 重试 | step1 `tool_timeout`；step2 query 改为“小影 模板 竖屏”，count=1；最终 22.7s pass | `examples/tool_failure/` |
| `impossible` | 6s 目标 + 最少 3 镜 → 理论下限 6.6s，明确失败 | 两次 draft 都是 6.6s；`cannot_satisfy`，给出 6.6s 计算 | `examples/impossible/` |
| `rule_violation` | 用户要求“效率提升80%”被规则拦截并删除 | 首检 3 条错误（标题 80%、禁用表达、镜头 1 的 80%）→ 修正 28.0 → pass | `examples/rule_violation/` |
| `semantic_catch` | 机械检查放过“不用手动打字”，reviewer 抓住 | 首稿 26.1s 机械 pass → review fail（shot 2）→ 重写 28.0 → review pass | `examples/semantic_catch/` |
| `step_limit` | 2 步上限内未完成，明确返回未完成 | `step_limit_reached`，2 步，partial 28.0s，未 review | `examples/step_limit/` |

### 2.1 参考实例的逐项对应（p01_30s）

题目要求：P01 仅包含“支持字幕”，用户要 30 秒；首稿 38 秒时应压缩并重新估算；修正 28 秒时输出应包含分镜、P01 引用及总时长。

实际 trace（`examples/p01_30s/trace.jsonl`）：

| 步骤 | 动作 | 工具参数/结果摘要 | 下一步与依据 |
| --- | --- | --- | --- |
| 1 | `search_materials` | query=`小影 字幕`, product_id=`P01`；count=1 | 拿到 P01-C1，进入写作 |
| 2 | `draft_script` | 3 镜，157 个汉字；`total_seconds=38.0` | 先检查再决定是否交付 |
| 3 | `check_rules` | `ok=false`，`duration_over`：“预计 38.0 秒，超过目标 30 秒” | 超时，压缩旁白后重检 |
| 4 | `draft_script` | 3 镜，115 个汉字；`total_seconds=28.0` | 重新检查 |
| 5 | `check_rules` | `ok=true`，errors=[] | 机械检查过了，交给独立审核 |
| 6 | `review_facts` | verdict=`pass`，findings=[] | 可以 finish |
| 7 | `finish` | `completed` | 输出 28.0s、3 镜、P01 引用 |

最终输出（节选，`examples/p01_30s/output.json`）：

```json
{
  "title": "字幕，让静音观看也不丢信息",
  "estimated_total_seconds": 28.0,
  "target_seconds": 30,
  "platform": "抖音",
  "materials_used": [
    {
      "material_id": "P01",
      "claim_id": "P01-C1",
      "text": "支持字幕",
      "source": "synthetic://materials/P01#C1"
    }
  ],
  "duration_check": {"ok": true, "total_seconds": 28.0, "accepted_low_seconds": 24.0}
}
```

逐镜时长：44 字 = 10.5s，33 字 = 7.9s，38 字 = 9.0s；加 3×0.2s 转场 = 28.0s。`shot_seconds` 是单镜 speech，不含转场；总时长才加转场，测试里专门固定了这个语义。

### 2.2 失败场景的“明确未完成”

`impossible` 的最终输出不是一句“做不到”，而是：

```json
{
  "status": "cannot_satisfy",
  "message": "3 个镜头 × 每镜最短 2.0 秒 + 3 × 0.2 秒转场 = 6.6 秒，已经超过 6 秒目标；再压缩旁白也无法低于单镜最短时长。",
  "output": {
    "best_attempt": {"estimated_total_seconds": 6.6, "shots": ["..."]},
    "blocking_errors": [{"code": "duration_over", "message": "预计 6.6 秒，超过目标 6 秒"}]
  }
}
```

`step_limit` 的最终输出包含 `partial_script`、`estimated_total_seconds=28.0`、`checks=null`，状态 `step_limit_reached`，不会把半成品标成 `completed`。

## 2.3 真实模型运行结果（DeepSeek，2026-11-06）

两条命令使用 `.env` 中的 `LLM_API_KEY`，provider=`deepseek`，配置模型 `deepseek-chat`，temperature=0.2。完整输出与逐 step trace：

- `examples/real/normal.output.json`、`examples/real/normal.trace.jsonl`
- `examples/real/p01_30s.output.json`、`examples/real/p01_30s.trace.jsonl`

| 用例 | 真实模型实际动作链 | 最终结果 |
| --- | --- | --- |
| `normal`（P02/30s） | search 1 命中 → get P02 → draft 15.7s（第 1 镜缺 `claim_ids`，工具返回 `invalid_script`）→ 补齐后 draft 成功 → check 报 `duration_under`（15.7 < 24.0）→ 扩写 → check pass（29.8s）→ review pass → finish | `completed`，6 镜，29.8s，P02-C1–C5，9 步 / 7 次工具 / 1 次 review |
| `p01_30s`（P01/30s） | search 1 命中 → get P01（仅“支持字幕”）→ draft 9.4s（同样第 1 镜缺 `claim_ids`，被工具拒绝）→ 补齐 → check 报 `duration_under`（9.4 < 24.0）→ 扩写到 4 镜 → check pass（27.5s）→ review pass → finish | `completed`，4 镜，27.5s，仅 P01-C1，9 步 / 7 次工具 / 1 次 review |

这两条真实 trace 的价值不在“数字碰巧接近 30 秒”，而在于相邻步骤的因果关系：

1. **工具拒绝 → 模型改参数**：`draft_script` 返回 `第 1 个镜头缺少 claim_ids`，下一步不是重试同一份草稿，而是给第 1 镜补 `P02-C1` / `P01-C1`；`reason` 写明“补齐每镜 claim_ids”。
2. **检查失败 → 模型改内容**：`check_rules` 返回 `duration_under` 和具体差额，下一步 `draft_script` 扩写旁白，再调用 `check_rules`；不是固定重试。
3. **机械检查通过 ≠ 结束**：两条都继续调用 `review_facts`，reviewer 独立返回 `pass` 后才 `finish`。
4. **事实约束生效**：P01 真实稿只引用 `P01-C1`，最终 `materials_used` 只有这一条；没有出现“自动识别”“不用手动打字”等未提供能力。

**与 Mock 参考实例的差异（必须如实说明）**：Mock 的 `p01_30s` 是题目给的“首稿 38.0 → 压缩到 28.0”；真实模型没有先写超长，而是首稿 9.4 秒偏短，随后**扩写**到 27.5 秒。两者都完成了“检查 → 调整 → 复查”的闭环，但方向不同。真实记录不支持“真实模型复现了 38→28”这种说法；38→28 的证据是 `examples/p01_30s/` 的 Mock 运行。

另外，reviewer 返回的 `model` 字段是 `deepseek-flash`（服务端标识），而 CLI 配置与 `run_start` 记录的是 `deepseek-chat`；本文保留原始字段，不把两者混写。

## 3. 测试结果

命令：

```powershell
python -m unittest discover -s tests -v
```

实际结果（2026-11-06）：

```text
Ran 36 tests in 0.106s

OK
```

覆盖：

| 测试组 | 数量 | 关键断言 |
| --- | --- | --- |
| Duration | 4 | P01 首稿 38.0、修正 28.0、P02 28.0、单镜下限 2.0 且总 6.6 |
| Validation | 5 | 缺 platform、平台别名、目标时长范围、未知动作、围栏 JSON |
| Rule | 8 | claim 不存在/归属错误、能力词、标题、数字、禁用表达、时长上下限 |
| Agent | 10 | 9 条路径 + finish 门禁 + JSON 修复 + 连续工具错误 + 工具调用上限 |
| Reviewer | 2 | 语义延伸 fail、grounded pass |
| Trace | 1 | step 事件包含 action/args/reason/observation |
| CLI | 4 | 正常写文件、缺字段退出 5、step limit 退出 4、未知 fault 拒绝 |

完整输出：`examples/test-results.txt`。

## 4. 开发中实际失败过什么

诚实记录，不掩饰：

1. **Windows 临时目录**：7 个 Agent 测试在 `TemporaryDirectory` 退出后才读 trace，Windows 已删目录，报 `FileNotFoundError: F:\temp\tmp...\trace.jsonl`。修法：把读取放进 `with` 块内。
2. **时长断言写错**：最初把 `shot_seconds` 当成“含转场”，期望 `[10.0, 8.8, 8.4]`，实际是单镜 speech `[13.8, 12.1, 11.4]`；单镜下限测试实际 `[2.0, 2.0, 2.0]` 而非 `[2.2, ...]`。修的是测试期望，不是产品逻辑；总时长仍 38.0/6.6。
3. **禁用表达重复**：首版规则同时命中 phrase 和 regex，同一条“效率提升80%”报 3 次；已按归一化文本去重，现在 rule_violation 首检是 3 条不同错误。
4. **Test 断言被 risks 干扰**：`rule_violation` 的 `risks` 会有意写“用户要求的效率提升80%无依据”，导致全文搜关键词会误判；改为只检查 `output.shots`。
5. **首次真实模型启动失败**：`python -m src.cli --provider deepseek ...` 报 `初始化失败：'NoneType' object has no attribute 'get'`。原因是 `src/env.py` 的 `load_env()` 只把值写入 `os.environ`、返回 `None`，而 CLI 写成了 `load_env().get("LLM_API_KEY")`。修法是让 `load_env()` 返回解析后的 `dict`，同时保留“不覆盖已有环境变量、不打印值”的行为；修复后两条真实运行成功。这个 bug 在 Mock 测试里不会暴露，因为 Mock 分支不读 `.env`。

这些失败都已修复，并保留在测试/文档中，作为“验证不是走过场”的证据。

## 5. 未验证 / 限制

- **真实模型只跑了 2 条**：`normal` 与 `p01_30s` 各 1 次，均为 `completed`；没有重复采样，也没有覆盖 `no_material`、`tool_failure`、`impossible`、`rule_violation` 等真实路径。真实模型在“无素材时是否追问”“工具连续失败是否停”“规则冲突是否删除”上的行为，仍只有 Mock 证据。`examples/real/README.md` 给出复现命令。
- **真实模型没有复现 38→28**：它先写短（9.4s）再扩写到 27.5s，属于“时长不足修正”；“超时长压缩”的证据是 `examples/p01_30s/` 的 Mock。这个差异是真实运行结果，不应改写。
- **reviewer 的 model 字段**：reviewer 返回 `deepseek-flash`，而 CLI 配置是 `deepseek-chat`；记录保留原值，说明服务端路由/标识与配置名不完全一致，未进一步追查。
- **Mock 的“决策”是预置的**：它按场景返回不同动作，能验证循环和门禁，但不能当作模型能力证据。文档和 README 都明确标注。
- **时长是文本近似**：4.2 字/秒是经验值；没有真实配音、停顿、音乐、画面节奏数据。`duration_check` 只能作为创作前的估算。
- **规则是启发式**：能力词表、数字豁免、禁用正则都可能漏判/误判；reviewer 是补充，不是绝对保证。
- **样本小**：9 条用例、5 个合成素材，不能代表真实素材库的召回率和长尾主题。
- **没有人工可读性评分**：脚本“好不好看”没有量化，当前只验证事实、时长、结构和规则。
- **没有 UI/部署**：题目非必需，本次明确不做。

## 6. 复现方式

```powershell
# 全部测试
python -m unittest discover -s tests -v

# 重新生成 9 组示例（会覆盖 examples/*/output.json 与 trace.jsonl）
python scripts/run_examples.py

# 单条 P01 参考实例
python -m src.cli --provider mock --mock-scenario p01_30s `
  --input examples/p01_30s/input.json `
  --out examples/p01_30s/output.json `
  --trace examples/p01_30s/trace.jsonl

# 真实模型（需要 .env 中的 LLM_API_KEY；会消耗 API 配额）
python -m src.cli --provider deepseek `
  --input examples/normal/input.json `
  --out examples/real/normal.output.json `
  --trace examples/real/normal.trace.jsonl

python -m src.cli --provider deepseek `
  --input examples/p01_30s/input.json `
  --out examples/real/p01_30s.output.json `
  --trace examples/real/p01_30s.trace.jsonl
```

Mock 结果可在无网络、无第三方包的 Python 3.8+ 环境复现；真实模型结果需要有效 API key，数字会随模型版本和采样变化。
