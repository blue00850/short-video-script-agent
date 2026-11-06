# 真实模型运行记录（预留）

本目录用于存放**真实模型**产生的 `output.json` 与 `trace.jsonl`，与 `examples/` 下的 Mock 记录分开，避免把 Mock 说成真实模型效果。

## 当前状态

**空。** 本次开发没有可用的 `LLM_API_KEY`，因此没有生成真实模型 trace；没有用 Mock 冒充。

## 如何生成

1. 复制环境模板并填入 key（不要把 `.env` 提交）：

```powershell
Copy-Item .env.example .env
# 编辑 .env：LLM_API_KEY=sk-...
```

2. 跑两条最小路径（normal 与 p01_30s）：

```powershell
python -m src.cli --provider deepseek `
  --input examples/normal/input.json `
  --out examples/real/normal.json `
  --trace examples/real/normal.trace.jsonl

python -m src.cli --provider deepseek `
  --input examples/p01_30s/input.json `
  --out examples/real/p01_30s.json `
  --trace examples/real/p01_30s.trace.jsonl
```

3. 检查真实 trace 是否出现：

- 模型是否先 `search_materials`，而不是直接写；
- 38.0s 后是否 `check_rules` 并看到 `duration_over`；
- 下一步是否 `draft_script`，且重新 `check_rules`；
- 是否调用 `review_facts`；
- JSON 是否合法，是否触发 `json_repair`；
- 最终是 `completed`、`cannot_satisfy` 还是 `step_limit_reached`。

4. 把结果补进 `docs/03-evaluation.md` 的“真实模型结果”一节；如果模型表现与 Mock 不同，如实记录差异，不要改写成 Mock 的结果。

## 注意

- 真实模型可能不按 schema 输出、可能跳过 `get_material`、可能在 38s 后不压缩；这些都应该记录，而不是用 Mock 覆盖。
- 不要提交 `.env`、API key、真实用户数据或未公开产品资料。
- 如果模型失败，保留失败 trace；失败记录比“只放成功案例”更有说服力。
