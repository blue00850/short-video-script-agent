# 验证摘要（examples）

> 生成方式：`python scripts/run_examples.py`，provider=`mock`。这些是**流程证据**，不是真实模型效果；原因与边界见 `docs/03-evaluation.md`。

## 1. 总表

| # | 用例 | 状态 | 关键数字 | 决策链（动作序列） |
| --- | --- | --- | --- | --- |
| 1 | `normal` | `completed` | 28.0s / 30s；3 镜；P02 | search → draft → check pass → review pass → finish |
| 2 | `p01_30s` | `completed` | 38.0 → 28.0；P01-C1 | search → draft 38 → check `duration_over` → draft 28 → check pass → review pass → finish |
| 3 | `no_material` | `insufficient_evidence` | 2 次 search 均 0 | search 0 → rewrite query → search 0 → ask_user |
| 4 | `tool_failure` | `completed` | 22.7s / 25s；P03 | search `tool_timeout` → rewrite query → search 1 → draft → check pass → review pass → finish |
| 5 | `impossible` | `cannot_satisfy` | 6.6s vs 6s；3 镜 | search → draft 6.6 → check over → draft 6.6 → check over → finish(cannot) |
| 6 | `rule_violation` | `completed` | 27.0 → 28.0 | search → draft 27（含 80%）→ check 3 errors → draft 28 → check pass → review pass → finish |
| 7 | `semantic_catch` | `completed` | 26.1 → 28.0 | search → draft 26.1（含“不用手动打字”）→ check pass → review fail → draft 28 → check pass → review pass → finish |
| 8 | `step_limit` | `step_limit_reached` | 2 步；partial 28.0 | search → draft → budget exhausted |
| 9 | `missing` | `invalid_input` | 缺 `platform` | validation_error，任务不开始 |

退出码：completed=0，insufficient_evidence=1，cannot_satisfy=2，step_limit_reached=4，invalid_input=5。

## 2. 必验点映射

| 题目必验 | 用例 | 可核对字段/事件 |
| --- | --- | --- |
| 正常生成 | normal | `output.title/shots/estimated_total_seconds/materials_used` |
| 缺关键信息 | missing | `output.errors[].field == "platform"`；trace 只有 `validation_error` |
| 无素材 | no_material | trace step1/2 `observation.count == 0`；`output.question` |
| 工具失败 | tool_failure | step1 `observation.error.code == "tool_timeout"`；step2 `args.query` 变化 |
| 超时长后的修正 | p01_30s | step3 `duration_over`；step4 total 28.0；step5 errors=[] |
| 超时长后的明确失败 | impossible | `output.best_attempt.estimated_total_seconds == 6.6`；`blocking_errors` |
| 规则检查 | rule_violation | 首检 3 条错误；修正后 `check.ok=true` |
| 事实追溯 | p01_30s / normal | `materials_used[].claim_id` + 每镜 `claim_ids` |
| 动态决策 | p01_30s / tool_failure / no_material / semantic_catch | 相邻 step 的 action/reason 变化 |
| 步数上限 | step_limit | `budget.steps_used == max_steps == 2`；状态为 `step_limit_reached` |

## 3. 关键 Trace 摘录

### 3.1 p01_30s：38 → 28

```text
step 1 search_materials  args={"query":"小影 字幕","product_id":"P01"}  obs={"count":1}
step 2 draft_script      obs={"shot_count":3,"total_seconds":38.0}
step 3 check_rules       obs={"ok":false,"errors":[{"code":"duration_over","message":"预计 38.0 秒，超过目标 30 秒"}]}
step 4 draft_script      reason="预计时长超过目标，压缩旁白并重检。"  obs={"total_seconds":28.0}
step 5 check_rules       obs={"ok":true,"errors":[]}
step 6 review_facts      obs={"verdict":"pass","findings":[]}
step 7 finish            obs={"status":"completed"}
```

对应文件：`examples/p01_30s/trace.jsonl`、`examples/p01_30s/output.json`。

最终 `materials_used` 只有 P01-C1（“支持字幕”），`risks` 明确写“P01 仅包含一条事实，未延伸识别准确率、自动翻译等能力”。

### 3.2 tool_failure：超时后改写查询

```text
step 1 search_materials  obs={"ok":false,"error":{"code":"tool_timeout","message":"素材检索服务超时（注入故障）"}}
step 2 search_materials  reason="检索工具超时，换一个更具体的查询重试一次。"  args={"query":"小影 模板 竖屏","product_id":"P03"}  obs={"count":1}
step 3 draft_script      obs={"total_seconds":22.7}
step 4 check_rules       obs={"ok":true,"errors":[]}
step 5 review_facts      obs={"verdict":"pass"}
step 6 finish            obs={"status":"completed"}
```

对应文件：`examples/tool_failure/trace.jsonl`。

### 3.3 no_material：两次 0 结果后追问

```text
step 1 search_materials  obs={"count":0,"hint":"没有匹配素材；可以改写查询或去掉 product_id 重试一次，仍无结果则 ask_user。"}
step 2 search_materials  args={"query":"小影 AI 数字人 素材","product_id":"P99"}  obs={"count":0}
step 3 ask_user          obs={"question":"素材库中没有找到“AI 数字人直播”相关事实，是否补充产品素材，或更换主题？"}
run_end                  status="insufficient_evidence"
```

对应文件：`examples/no_material/trace.jsonl`。

### 3.4 semantic_catch：机械规则放过，reviewer 抓住

```text
step 2 draft_script   obs={"total_seconds":26.1}   # 含“不用手动打字”
step 3 check_rules    obs={"ok":true,"errors":[]}  # 机械规则确实放过
review                verdict="fail"
  finding: shot=2, message="素材只写了“支持字幕”，没有“不用手动打字”这类自动化能力，属于能力延伸。"
step 5 draft_script   obs={"total_seconds":28.0}   # 删除该句
step 6 check_rules    obs={"ok":true}
review                verdict="pass"
step 8 finish         obs={"status":"completed"}
```

对应文件：`examples/semantic_catch/trace.jsonl`。

### 3.5 impossible：6.6s 的硬下限

```text
step 2 draft_script  obs={"total_seconds":6.6}
step 3 check_rules   obs={"ok":false,"errors":[{"code":"duration_over","message":"预计 6.6 秒，超过目标 6 秒"}]}
step 4 draft_script  obs={"total_seconds":6.6}  # 每镜压到 4 字，仍受 2.0s 下限约束
step 5 check_rules   obs={"ok":false,"errors":[{"code":"duration_over"}]}
step 6 finish        obs={"status":"cannot_satisfy","message":"3 个镜头 × 每镜最短 2.0 秒 + 3 × 0.2 秒转场 = 6.6 秒，已经超过 6 秒目标；再压缩旁白也无法低于单镜最短时长。"}
```

对应文件：`examples/impossible/trace.jsonl`、`output.json`。

## 4. 测试摘要

```text
python -m unittest discover -s tests -v
Ran 36 tests in 0.081s
OK
```

完整输出：`examples/test-results.txt`。

## 5. 一句话结论

在 Mock 编排下，9 条路径全部达到预期状态；最关键的 p01_30s 完成了“38.0 → 检查失败 → 28.0 → 复查通过 → 独立审核通过”的闭环。真实模型效果尚未验证，不能把本摘要当作真实模型能力或业务效果数据。
