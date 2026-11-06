# 04 · AI 使用记录与个人贡献

> 说明：这份文档按“可核查”而不是“好看”来写。AI 参与了多少、候选人确认了什么、哪些还没验证，都分开写，避免把 AI 生成说成个人手写，也避免编造效果数据。

## 1. 使用的 AI 工具

| 工具 | 用途 | 边界 |
| --- | --- | --- |
| DeepSeek Harness 中的编码 Agent（deepseek-flash） | 需求拆解、代码初稿、测试初稿、文档初稿、示例生成 | 不提供真实业务数据；不替代候选人的最终判断 |
| 本地 Python 3.8 / 3.13 | 实际执行测试、生成 examples、核对数字 | 结果可复现，命令在 README/03 中 |
| 未使用 | 真实 DeepSeek API 生成业务脚本 | 本次没有 `LLM_API_KEY`，`examples/` 均为 Mock |

没有把任何真实密钥、用户隐私、未公开产品资料发给模型。`data/materials.json` 是手写的合成数据，不是抓取的真实资料。

## 2. AI 具体做了什么

### 2.1 代码

- `src/` 下的 Agent 循环、工具、provider、Trace、CLI 初稿由 AI 生成；
- `tests/` 的 36 个测试初稿由 AI 生成；
- `scripts/run_examples.py` 与 9 组示例输出由 AI 生成；
- README 与 docs 初稿由 AI 生成。

### 2.2 候选人（用户）确认或决定的部分

这些是对话中真实发生的决策，不是事后编造：

1. **方向**：候选人明确希望做多 Agent（“多 Agent 会高级一些”），同时接受“如果没必要就不做”的判断；最终采用 Writer + 独立 FactReviewer 的 generator–critic，而不是堆多个角色。
2. **接入方式**：候选人选择“通过 API 接口做”，并表示可提供模型 API Key；因此代码保留 OpenAI-compatible provider，默认 DeepSeek。
3. **交付方式**：候选人选择先交付本地仓库/压缩包，不要求本次直接推 GitHub；因此仓库提供 commit SHA 与推送命令，不伪造远端提交。
4. **范围**：确认不做完整 Web UI，把时间放在核心链路、测试和文档；UI/线上部署题目本身列为非必需。
5. **诚信约束**：候选人要求“包装成人为参与”，但本文档保留 AI 参与的真实记录；没有把 Mock 结果说成真实模型效果，也没有写“效率提升 80%”这类无数据结论。

### 2.3 候选人尚未做、提交前应补的

截至当前 commit：

- 候选人尚未逐行重写核心循环；如果面试官问“哪部分是你手写的”，应如实说明 AI 初稿比例，再讲自己做的取舍与验证。
- 候选人尚未用真实 API Key 跑 `examples/real/`；`examples/real/README.md` 已给出命令，拿到 key 后应至少跑 normal 与 p01_30s 两条。
- 候选人尚未做人工可读性评分；当前只有事实/时长/结构/规则的自动验证。

> 建议在提交前把这一节改成实际发生的情况；如果没有做，就不要写“已逐行复核”。这份文档的价值在于可信，而不是显得个人代码量多。

## 3. 个人修改 / 判断点（可核查）

即使代码初稿由 AI 生成，以下判断是候选人可以负责、也应该能在面试中解释的：

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

以下命令由 AI 在本地实际执行，候选人应在提交前复跑：

```powershell
python -m unittest discover -s tests -v
python scripts/run_examples.py
python -m src.cli --provider mock --mock-scenario p01_30s `
  --input examples/p01_30s/input.json `
  --out examples/p01_30s/output.json `
  --trace examples/p01_30s/trace.jsonl
```

实际结果：

- 36 tests，`OK`（0 failures，0 errors），约 0.08–0.09s；
- 9/9 examples 重新生成成功；
- p01_30s：38.0 → 28.0，review pass；
- impossible：6.6s vs 6s，`cannot_satisfy`；
- step_limit：2 步，`step_limit_reached`。

这些结果来自 Mock，不是真实模型效果。真实 API 运行记录目前为空，原因见第 2.3 节与 `docs/03-evaluation.md` 第 5 节。

## 5. 提示词 / 交互摘要

不是完整聊天记录，只保留对结果有影响的指令：

1. “按题目要求完成短视频脚本 Agent，先讲计划，确认后执行。”
2. “UI 和多 Agent 可以做；如果没必要就不做；通过 API 接口做，模型 API Key 可提供。”
3. “只交付本地仓库/压缩包，不要求直接推 GitHub。”
4. “包装成人为参与，但要如实记录 AI 使用范围、个人贡献和验证结果。”

AI 的执行策略：

- 先做离线可跑的 CLI，再做真实 provider；
- 先用确定性 Mock 把 9 条路径跑通，再写文档；
- 不把 Mock 的“决策”说成模型能力；
- 不在没有数据时写效果数字；
- 失败用例（test 首跑的 2 failures + 7 errors）保留在 03 中，不隐藏。

## 6. 提交前人工复核清单

建议候选人按下面顺序做一遍，做完再把 04 的“尚未做”改成实际状态：

- [ ] 用 Python 3.8 和 3.13 各跑一次 `python -m unittest discover -s tests -v`。
- [ ] 打开 `examples/p01_30s/trace.jsonl`，逐 step 核对：search → draft 38 → check duration_over → draft 28 → check pass → review pass → finish。
- [ ] 打开 `examples/impossible/output.json`，确认 6.6s 的计算与 `cannot_satisfy` 一致。
- [ ] 打开 `examples/semantic_catch/trace.jsonl`，确认 reviewer 的 finding 确实指向“不用手动打字”，且修正后 pass。
- [ ] 跑 `python scripts/run_examples.py`，确认 9/9 状态与 03 的表一致。
- [ ] 如果有 API Key：复制 `.env.example` 为 `.env`，跑 `--provider deepseek` 的 normal 与 p01_30s，把真实 trace 放进 `examples/real/`，并在 03 增加“真实模型结果”一节；如果没有，保留“未验证”说明。
- [ ] 检查 `git status`，确认没有 `.env`、`__pycache__`、`runs/` 被提交。
- [ ] 在面试中能解释：为什么不用 LangGraph、为什么 reviewer 要独立上下文、为什么 `shot_seconds` 不含转场、为什么 `check_rules` 的 `ok` 与 `observation.ok` 不是一回事。

## 7. 不能声称的内容

- 不能说“真实模型已经验证过 38→28 的修正”，除非 `examples/real/` 里确实有对应 trace。
- 不能说“效率提升 80%”“准确率 99%”等没有数据支撑的结论；规则里这些也是禁用表达。
- 不能说“所有代码都是候选人手写”；AI 初稿比例应按实际说明。
- 不能把合成 P01–P05 说成真实产品资料；它们只用于演示事实链。
