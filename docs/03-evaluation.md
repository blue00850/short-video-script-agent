# 03 · 效果验证与限制

## 1. 验证口径

本项目把“效果”拆成三层，避免把流程跑通说成模型效果好：

| 层 | 验证什么 | 证据 |
| --- | --- | --- |
| 编排层 | 动作选择、工具结果观察、下一步调整、预算耗尽 | 9 组 `examples/*/trace.jsonl` + Agent 测试 |
| 规则层 | 时长、镜头数、claim、数字、禁用表达 | `tests/test_core.py` 的 Rule/Duration 测试 |
| 语义层 | 只声明“支持字幕”时是否写了“不用手动打字” | `examples/semantic_catch/` + Reviewer 测试 |

**重要边界**：仓库里的 9 组 examples 都由 `MockProvider` 生成。它们证明的是“给定这些工具结果，Agent 的循环、门禁、状态和 Trace 正确”，**不证明真实 DeepSeek/其他模型也会做出同样决策**。真实模型接入代码已完成，但本次没有可用的 `LLM_API_KEY`，因此 `examples/real/` 没有伪造的运行记录。

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

## 3. 测试结果

命令：

```powershell
python -m unittest discover -s tests -v
```

实际结果（2026-11-06）：

```text
Ran 36 tests in 0.081s

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

这些失败都已修复，并保留在测试/文档中，作为“验证不是走过场”的证据。

## 5. 未验证 / 限制

- **真实模型未运行**：没有 `LLM_API_KEY`，`examples/` 全部是 Mock。真实模型是否会按同样的 JSON schema、是否会在 38s 后主动压缩、是否会编造事实，尚未用数据证明。`examples/real/README.md` 给出复现命令；拿到 key 后应至少跑 normal 与 p01_30s 两条，并人工核对 trace。
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
```

所有结果均可在无网络、无第三方包的 Python 3.8+ 环境复现。
