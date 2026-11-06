# 短视频脚本 Agent

面向短视频创作者的可编辑脚本生成 Agent：先检索产品素材，再写分镜脚本，随后用**时长估算**和**品牌/事实规则检查**验证；不通过就根据工具结果改写并复查。交付物包含标题、分镜、旁白、预计总时长、素材来源 ID、风险与任务状态。

本项目是一个 **CLI + 原生 Python** 的 Agent 实现，核心是一个有预算上限的 ReAct 循环，外加一个**独立上下文的事实审核 Agent**（generator–critic）。不依赖任何第三方 Python 包，离线即可复现。

> 数据说明：`data/materials.json` 中的 P01–P05 均为**合成素材**，只用于演示与测试，不代表小影真实产品能力。仓库不包含任何真实密钥或用户隐私数据。

---

## 1. 快速开始（离线，零依赖）

要求：Python 3.8+（本项目在 Python 3.8.10 与 3.13 上验证）。不需要 Node、数据库或网络。

```powershell
# 在仓库根目录执行
python -m src.cli --provider mock --mock-scenario p01_30s `
  --input examples/p01_30s/input.json `
  --out examples/p01_30s/output.json `
  --trace examples/p01_30s/trace.jsonl
```

预期输出摘要：

```text
status: completed
message: 脚本已通过时长、品牌规则和独立事实审核，可以交付。
title: 字幕，让静音观看也不丢信息
duration: 28.0 s / target 30 s
shots: 3
check_ok: True
review: pass
budget: steps 7/12, tool_calls 5/10, reviews 1/2
```

这条路径就是题目参考实例：P01 只声明“支持字幕”，首稿估算 **38.0 秒**，`check_rules` 返回 `duration_over`；模型压缩旁白后重检为 **28.0 秒**，再经过独立事实审核，最后 `finish`。

完整结果在 `examples/p01_30s/output.json`，逐步决策记录在 `examples/p01_30s/trace.jsonl`。

### 直接传参（不写 input 文件）

```powershell
python -m src.cli --provider mock --mock-scenario normal `
  --topic "新手如何快速做一条短视频" --audience "短视频新手" `
  --platform 抖音 --target-seconds 30 --style "口语化、节奏快" `
  --product-id P02
```

### 运行全部示例

```powershell
python scripts/run_examples.py
```

该脚本会用子进程调用 CLI，重新生成 `examples/` 下 9 组 `input.json` / `output.json` / `trace.jsonl`，并断言每组的状态。

### 运行测试

```powershell
python -m unittest discover -s tests -v
```

当前结果：**36 tests, OK**。测试覆盖时长公式、输入校验、规则检查、Agent 九类路径、独立审核、Trace 字段和 CLI 退出码。实际输出见 `examples/test-results.txt`。

---

## 2. 接入真实模型（可选）

默认 `--provider mock` 是为了让评审在没有密钥时也能复现完整流程。Mock 只验证编排与状态机，**不证明真实模型的决策质量**。

接入 DeepSeek（OpenAI-compatible）：

```powershell
Copy-Item .env.example .env
# 编辑 .env，填入 LLM_API_KEY=...
python -m src.cli --provider deepseek `
  --input examples/p01_30s/input.json `
  --out examples/real/p01_30s.json `
  --trace examples/real/p01_30s.trace.jsonl
```

也可以接任意 OpenAI-compatible 服务：

```powershell
python -m src.cli --provider openai `
  --base-url https://your-endpoint/v1 --model your-model `
  --input examples/normal/input.json
```

`--provider auto`：检测到 `LLM_API_KEY` 时用 DeepSeek，否则回退 Mock。

环境变量（`.env` 或系统环境）：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 真实模型时必填 | 不要提交到仓库 |
| `LLM_BASE_URL` | 否 | 默认 `https://api.deepseek.com` |
| `LLM_MODEL` | 否 | 默认 `deepseek-chat` |
| `LLM_TIMEOUT` | 否 | 默认 90 秒 |

`.env.example` 不含任何真实密钥。`.env` 已加入 `.gitignore`。

本仓库已保留两条真实运行（2026-11-06）：`normal` 首稿 15.7s 偏短 → 扩写 29.8s；`p01_30s` 首稿 9.4s → 扩写 27.5s。两条都先因第 1 镜缺 `claim_ids` 被工具拒绝，补齐后再检查。详见 `examples/real/` 与 `docs/03-evaluation.md` 第 2.3 节。真实模型没有复现 Mock 的 38→28，差异已如实记录。

---

## 3. 它如何做决策

每个步骤都是一个“模型选择动作 → 执行工具 → 观察结果 → 调整下一步”的循环：

```text
用户请求
  │
  ├─ validate_request ── 缺 topic/platform/时长 → invalid_input，任务不开始
  │
  └─ WriterAgent（ReAct，最多 12 步 / 10 次工具调用）
        │
        ├─ search_materials → 0 条？改写查询再试一次 → 仍为 0 → ask_user
        ├─ get_material     → 读取 claim 原文，禁止凭记忆写产品事实
        ├─ draft_script     → 输出 title + shots（visual/narration/source_ids/claim_ids）
        ├─ estimate_duration→ 中文 4.2 字/秒、英文 2.5 词/秒、每镜最短 2.0s、转场 0.2s
        ├─ check_rules      → 时长/平台/镜头数/claim/数字/能力词/禁用表达
        ├─ review_facts     → 独立 FactReviewer，只读 claim 目录，error 可否决
        └─ finish           → 终检门禁：check.ok + review pass 才允许 completed
```

关键点：

- **不是固定分支**：下一步由模型根据上一步的 observation 选择。例如 `check_rules` 返回 `duration_over` 后压缩、返回 `duration_under` 后扩写；`draft_script` 返回缺 `claim_ids` 时补齐字段；`search_materials` 返回 `tool_timeout` 后改写查询重试；两次检索都为 0 时，模型选择 `ask_user` 而不是编造。
- **模型不能直接宣布成功**：`finish(completed)` 会被 Agent 重新跑一遍 `check_rules` 并检查 reviewer 结论；不满足就返回 `finish_rejected`，继续循环。
- **明确失败**：6 秒目标 + 最少 3 镜头时，单镜 2.0s + 转场 0.2s，理论下限 6.6s，模型会给出计算并返回 `cannot_satisfy`，而不是硬凑。
- **预算边界**：步数或工具调用耗尽返回 `step_limit_reached`，并附 `partial_script` 与已完成的检查，不伪装成完成。
- **事实可追溯**：每个镜头必须引用 `source_ids` 与 `claim_ids`；字幕、模板、1080P 等能力词若不在所引 claim 中出现，直接判 `ungrounded_capability`；数字若不在 claim 中出现，判 `ungrounded_number`（秒/帧/镜头数等时间结构量豁免）。
- **独立审核**：`FactReviewer` 使用独立上下文，只看需求、脚本和 claim 目录，专门抓机械规则抓不到的语义延伸。例如 P01 只有“支持字幕”，脚本写“不用手动打字”时，reviewer 会报 error，模型删除后重写。

---

## 4. 任务状态与退出码

| 状态 | 含义 | CLI 退出码 |
| --- | --- | --- |
| `completed` | 时长、规则、事实审核全部通过 | 0 |
| `needs_input` | 需要用户补充信息 | 1 |
| `insufficient_evidence` | 素材不足，已请求补充或换主题 | 1 |
| `cannot_satisfy` | 在规则下无法满足（如时长低于理论下限） | 2 |
| `tool_error` | 连续工具失败，无法继续 | 3 |
| `model_error` | 模型调用/JSON 修复失败 | 3 |
| `step_limit_reached` | 达到步数或工具调用上限，任务未完成 | 4 |
| `invalid_input` | 输入缺关键字段或格式错误 | 5 |

`invalid_input` 也会写出 `output.json` 与只含 `validation_error` 的 trace，方便定位。

---

## 5. 目录结构

```text
.
├─ README.md
├─ requirements.txt          # 声明无第三方依赖
├─ .env.example
├─ .gitignore
├─ src/
│  ├─ cli.py                 # CLI 入口、provider 选择、退出码
│  ├─ agent.py               # ReAct 循环、预算、finish 门禁
│  ├─ reviewer.py            # 独立事实审核 Agent
│  ├─ prompts.py             # Writer / Reviewer 系统提示
│  ├─ models.py              # Shot/Script/Decision/Budget/状态
│  ├─ validation.py          # 输入校验、JSON 容错解析
│  ├─ data.py                # 素材索引与 claim 目录
│  ├─ trace.py               # JSONL Trace
│  ├─ env.py                 # .env 读取（不打印密钥）
│  ├─ providers/
│  │  ├─ base.py
│  │  ├─ mock.py             # 确定性 Mock，仅供流程/测试
│  │  └─ openai_compat.py    # OpenAI-compatible API
│  └─ tools/
│     ├─ duration.py         # 时长估算
│     ├─ rules.py            # 品牌/事实/结构检查
│     └─ __init__.py         # ToolBox + 故障注入
├─ data/
│  ├─ materials.json         # 合成素材 P01–P05
│  ├─ brand_rules.json       # 禁用表达、能力词、平台时长
│  └─ config.json            # 预算、时长参数、模型参数
├─ examples/                 # 9 组 Mock 用例 + real/ 2 组真实模型 Trace
├─ tests/                    # 36 个 unittest
├─ scripts/run_examples.py
└─ docs/01–05
```

---

## 6. 评审入口

1. **先看结果**：`examples/p01_30s/output.json`（Mock 38→28）与 `examples/p01_30s/trace.jsonl`；再看 `examples/real/` 的真实模型记录（15.7→29.8、9.4→27.5）。每条 trace 都有动作、参数摘要、观察和一句决策依据。
2. **看覆盖**：`examples/eval-summary.md` 与 `docs/03-evaluation.md` 把 9 组 Mock 用例映射到全部验收点，并单列真实模型 2 条路径。
3. **看取舍**：`docs/02-solution.md` 解释为什么不用 LangGraph/ADK、为什么多一个 reviewer、为什么把时长做成确定性工具。
4. **自己跑**：`python -m unittest discover -s tests -v`；`python scripts/run_examples.py`；或按第 1 节跑单条。
5. **看限制**：`docs/03-evaluation.md` 的“未验证/失败”一节明确区分了 Mock 流程证据与真实模型效果。

---

## 7. 已知限制

- `examples/` 下 9 组 Mock 用例由 `MockProvider` 生成，用于证明**编排、门禁、预算、Trace 和失败状态**；不能据此声称真实模型的决策质量或业务效果。
- `examples/real/` 有 2 条真实 DeepSeek 运行（normal、p01_30s），证明模型会观察工具结果并调整；但只有 2 条、各 1 次，没有覆盖真实模型的无素材/工具失败/无法满足路径，也不能外推为业务效果。
- 真实模型接入需要 `LLM_API_KEY`；没有密钥时 `--provider deepseek` 会明确返回 3，不会静默回退。
- 时长估算是**旁白文本的近似值**，不含画面节奏、停顿、音乐、转场特效；4.2 字/秒是经验参数，真实创作需要人工试听。
- 规则检查是确定性的启发式：能抓住禁用词、无依据数字、能力词延伸和结构问题，但不能覆盖所有语义细微差别；reviewer 是第二道防线，不是绝对保证。
- 当前只做 CLI，没有 Web UI；多 Agent 仅限 Writer + FactReviewer，没有做生产级 Runtime、队列、鉴权或并发。
- 合成素材只覆盖 5 个产品点，不代表真实素材库的召回质量。
