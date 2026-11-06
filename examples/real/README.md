# 真实模型运行记录

本目录存放**真实模型**产生的 `output.json` 与 `trace.jsonl`，与 `examples/` 下的 Mock 记录分开，避免把 Mock 说成真实模型效果。

## 当前记录

2026-11-06 15:02（Asia/Shanghai），provider=`deepseek`，CLI 配置 `LLM_MODEL=deepseek-chat`，temperature=0.2。key 只在本地 `.env`，未提交。

| 用例 | 输出 | Trace | 结果 |
| --- | --- | --- | --- |
| `normal`（P02，30s） | `normal.output.json` | `normal.trace.jsonl` | `completed`，6 镜，29.8s，review pass，9 步 / 7 工具 |
| `p01_30s`（P01，30s） | `p01_30s.output.json` | `p01_30s.trace.jsonl` | `completed`，4 镜，27.5s，仅 P01-C1，review pass，9 步 / 7 工具 |

两条命令：

```powershell
python -m src.cli --provider deepseek `
  --input examples/normal/input.json `
  --out examples/real/normal.output.json `
  --trace examples/real/normal.trace.jsonl

python -m src.cli --provider deepseek `
  --input examples/p01_30s/input.json `
  --out examples/real/p01_30s.output.json `
  --trace examples/real/p01_30s.trace.jsonl
```

## 实际发生了什么

两条都不是“一次写对”，而是由工具结果驱动了下一步：

1. `draft_script` 第一次返回 `invalid_script: 第 1 个镜头缺少 claim_ids`；模型下一步补齐 `P02-C1` / `P01-C1`，再提交。
2. `check_rules` 第一次返回 `duration_under`：normal 为 15.7s（下限 24.0s），p01 为 9.4s；模型下一步扩写旁白/镜头，再调用 `check_rules`。
3. 复查通过后，模型仍调用 `review_facts`；reviewer 返回 `pass` 后才 `finish`。

因此两条路径都满足“模型选择动作 → 执行工具 → 观察结果 → 调整下一步或结束”，且调整点不同：一条是补字段，一条是改时长。

## 与 Mock 参考实例的差异

- Mock 的 `examples/p01_30s/` 是题目给的“首稿 38.0s → 压缩到 28.0s”。
- 真实模型没有先写超长，而是首稿 9.4s 偏短，随后**扩写**到 27.5s。
- 两者都完成了“检查 → 调整 → 复查”，但方向不同；真实记录**不能**用来声称“真实模型复现了 38→28”。
- 这次只跑了 2 条，没有覆盖真实模型的无素材、工具失败、规则冲突、无法满足路径；这些路径的现有证据是 Mock。

## 注意

- 真实模型可能不按 schema 输出、可能跳过 `get_material`、可能改写事实；这些都应记录，而不是用 Mock 覆盖。
- reviewer 返回的 `model` 字段是 `deepseek-flash`，CLI 配置与 `run_start` 是 `deepseek-chat`；这里保留服务端原值，不把两者混写。
- 不要提交 `.env`、API key、真实用户数据或未公开产品资料。
- 失败 trace 比“只放成功案例”更有说服力；如果复跑失败，保留失败记录。
