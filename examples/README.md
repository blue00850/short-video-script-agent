# examples · 输入、实际输出与 Trace

本目录的 9 组用例都由 `scripts/run_examples.py` 调用 CLI 实际生成（`--provider mock`），不是手写伪造的输出。每组包含：

```text
examples/<case>/
├─ input.json      # 实际传给 CLI 的请求
├─ output.json     # CLI 写出的完整结果
└─ trace.jsonl     # 逐步决策记录（每行一个事件）
```

全部结果在 Python 3.8.10 上生成；无网络、无第三方依赖。

## 用例索引

| 目录 | 状态 | 目标验收点 | 关键结果 |
| --- | --- | --- | --- |
| `normal/` | `completed` | 正常生成 | 28.0s/30s，3 镜，P02，review pass |
| `p01_30s/` | `completed` | 参考实例：38→28，P01 | 首稿 38.0，`duration_over`，修正 28.0，P01-C1 |
| `no_material/` | `insufficient_evidence` | 无素材 | 两次 search count=0 → `ask_user` |
| `tool_failure/` | `completed` | 工具失败 | 首次 `tool_timeout`，改写 query 后 22.7s pass |
| `impossible/` | `cannot_satisfy` | 超时长后明确失败 | 6.6s vs 6s，给计算 |
| `rule_violation/` | `completed` | 规则检查 | 首检 3 条错误 → 删除违规 → 28.0 pass |
| `semantic_catch/` | `completed` | 语义层事实审核 | reviewer fail（“不用手动打字”）→ 重写 28.0 pass |
| `step_limit/` | `step_limit_reached` | 预算上限 | 2 步耗尽，partial 28.0，未 review |
| `missing/` | `invalid_input` | 缺关键信息 | 缺 platform，任务不开始，退出码 5 |

`examples/real/` 是真实模型 trace 的预留目录；本次没有 API key，因此没有伪造真实模型输出，只放了复现说明。

## Trace 怎么读

每行一个 JSON 事件。以 `p01_30s` 为例：

```json
{"event":"step","step":2,"action":"draft_script","args":{"title":"...","shots":[...]},
 "reason":"基于已检索到的素材写首稿，并保留素材 ID 与 claim ID。",
 "ok":true,"observation":{"shot_count":3,"total_seconds":38.0}}
```

- `action`：模型这一步选的动作；
- `args`：传给工具的参数（长文本会截断/摘要）；
- `observation`：工具返回的摘要；
- `reason`：模型自述的一句决策依据（不是思维链）；
- `ok`：**工具调用是否成功**，不是检查是否通过。检查结果看 `observation.ok`；
- `review` 事件：独立 reviewer 的 verdict/findings；
- `run_end`：最终状态、预算用量、usage。

因此 `check_rules` 的 step 可能是 `ok=true` 但 `observation.ok=false`（工具正常返回了“不合格”），这是预期行为。

## 复现

```powershell
# 重新生成全部 9 组（会覆盖 output.json 与 trace.jsonl）
python scripts/run_examples.py

# 只跑 p01_30s
python -m src.cli --provider mock --mock-scenario p01_30s `
  --input examples/p01_30s/input.json `
  --out examples/p01_30s/output.json `
  --trace examples/p01_30s/trace.jsonl
```

`examples/eval-summary.md` 有更紧凑的验收矩阵；`docs/03-evaluation.md` 有逐项解释和限制。
