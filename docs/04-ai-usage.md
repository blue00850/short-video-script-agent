# 04 · AI 使用记录与个人贡献

> 说明：这份文档按“可核查”而不是“好看”来写。AI 参与了多少、候选人确认了什么、验证结果是什么，都分开写，避免把 AI 生成说成个人手写，也避免编造效果数据。

## 1. 使用的 AI 工具

| 工具 | 用途 | 边界 |
| --- | --- | --- |
| DeepSeek Harness 中的编码 Agent（deepseek-flash） | 需求拆解、代码初稿、测试初稿、文档初稿、示例生成 | 不提供真实业务数据；不替代候选人的最终判断 |
| 本地 Python 3.8 / 3.13 | 实际执行测试、生成 examples、核对数字 | 结果可复现，命令在 README/03 中 |
| DeepSeek API（OpenAI-compatible） | 2 条真实模型运行：`normal`、`p01_30s` | key 由候选人提供，只放在本机 `.env`；未提交。真实结果只代表这 2 次运行 |

没有把任何真实密钥、用户隐私、未公开产品资料发给模型。`data/materials.json` 是编写的合成数据，不是抓取的真实资料。

## 2. AI 具体做了什么

### 2.1 代码

- `src/` 下的 Agent 循环、工具、provider、Trace、CLI 初稿由 AI 生成；
- `tests/` 的 36 个测试初稿由 AI 生成；
- `scripts/run_examples.py` 与 9 组示例输出由 AI 生成；
- README 与 docs 初稿由 AI 生成。

### 2.2 候选人确认或决定的部分

这些是对话中真实发生的决策：

1. **方向**：候选人最终采用 Writer + 独立 FactReviewer 的 generator–critic，而不是堆多个角色。
2. **接入方式**：候选人选择“通过 API 接口做”，并表示可提供模型 API Key；因此代码保留 OpenAI-compatible provider，默认 DeepSeek。
3. **交付方式**：候选人在本地完成项目，并推送到 GitHub 提交。
4. **范围**：确认不做完整 Web UI，把时间放在核心链路、测试和文档。
5. **诚信与边界**：候选人要求按题目规范如实记录 AI 使用范围、个人贡献和验证结果；不以 Mock 冒充真实模型，不写没有数据支撑的效果结论。

### 2.3 候选人的职责与复核

候选人负责需求定义、架构取舍、验收标准与最终提交；AI 负责代码、测试、示例与文档初稿。提交前已在 Python 3.8 环境复跑 36 个测试与 9 组示例，关键 Trace 见 `examples/` 与 `examples/real/`。

- 核心循环的代码初稿由 AI 完成；候选人负责需求、架构取舍与验收。面试中应按实际说明 AI 初稿比例，不声称逐行手写。
- 真实 API 两条已由 AI 执行：`examples/real/normal.*`、`examples/real/p01_30s.*`。候选人应能解释“缺 claim_ids → 补齐”“duration_under → 扩写”的因果关系。

## 3. 个人负责的工程判断

候选人负责的工程判断包括：

| 判断点 | 选择 | 理由 |
| --- | --- | --- |
| 框架 | 原生 Python，不用 LangGraph/ADK | 本题规模小；预算、门禁、Trace 必须完全可控；框架会隐藏决策边界 |
| 形态 | CLI，不做 Web UI | 题目三选一；UI 非必需；时间优先给循环、测试、文档 |
| 多 Agent | Writer + FactReviewer | 机械规则抓不住“支持字幕 → 不用手动打字”的语义延伸；独立上下文避免自我确认 |
| 时长 | 确定性公式 + 工具 | 模型“感觉”不可复现；工具才能形成“改→查→再改”的闭环 |
| 失败 | `cannot_satisfy` 必须给计算 | 6s 目标 + 3 镜下限 6.6s，硬凑会骗用户 |
| 预算 | 12 步 / 10 次工具 / 2 次 review | 足够完成正常修正，又能在异常时明确停下 |
| 数据 | 合成素材，明确标注 | 不冒充真实产品；避免编造事实 |
| 真实性 | Mock 与真实模型分开写 | Mock 只验证流程，不证明模型决策质量 |

## 4. 验证记录

以下命令已在本地实际执行，候选人可随时复跑：

```powershell
python -m unittest discover -s tests -v
python scripts/run_examples.py
python -m src.cli --provider mock --mock-scenario p01_30s `
  --input examples/p01_30s/input.json `
  --out examples/p01_30s/output.json `
  --trace examples/p01_30s/trace.jsonl
```

实际结果：

- 36 tests，`OK`（0 failures，0 errors），约 0.10s；
- 9/9 Mock examples 重新生成成功；
- p01_30s：38.0 → 28.0，review pass；
- impossible：6.6s vs 6s，`cannot_satisfy`；
- step_limit：2 步，`step_limit_reached`。

真实 API（2026-11-06 15:02，DeepSeek-compatible）：

- `normal`：15.7s 偏短 → 扩写 → 29.8s，6 镜，review pass，`completed`，21.9s；
- `p01_30s`：9.4s 偏短 → 扩写 → 27.5s，4 镜，仅 P01-C1，review pass，`completed`，19.5s；
- 两条都先因第 1 镜缺 `claim_ids` 被 `draft_script` 拒绝，补齐后才继续；
- 真实 trace 在 `examples/real/`，详细对照见 `docs/03-evaluation.md` 第 2.3 节。

Mock 结果只证明编排；真实 API 结果只代表上述 2 次运行，不能外推为业务效果。

## 5. 提示词 / 交互摘要

不是完整聊天记录，只保留对结果有影响的指令：

1. “按题目要求完成短视频脚本 Agent，先讲计划，确认后执行。”
2. “UI 和多 Agent 可以做；如果没必要就不做；通过 API 接口做，模型 API Key 可提供。”
3. “本地完成，提交时推送到 GitHub。”
4. “按题目规范如实记录 AI 使用范围、个人贡献和验证结果。”

AI 的执行策略：

- 先做离线可跑的 CLI，再做真实 provider；
- 先用确定性 Mock 把 9 条路径跑通，再写文档；
- 不把 Mock 的“决策”说成模型能力；
- 不在没有数据时写效果数字；
- 失败用例（test 首跑的 2 failures + 7 errors）保留在 03 中，不隐藏。

## 6. 边界

- `examples/` 下 9 组是 Mock，用于证明编排、门禁、预算、Trace 和失败状态；`examples/real/` 的 2 条是真实 DeepSeek 运行，样本小，不外推为业务效果。
- 不写“效率提升 80%”“准确率 99%”等没有数据支撑的结论；规则中这些也是禁用表达。
- `data/materials.json` 的 P01–P05 是合成素材，仅用于演示事实链，不冒充真实产品资料。

