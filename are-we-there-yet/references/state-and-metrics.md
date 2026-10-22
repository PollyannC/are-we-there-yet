# 状态、计算与工具

工具：`python3 <skill>/scripts/are_we_there_yet.py --project <实际项目目录> <command>`。Python 3.9+，仅标准库。macOS/Linux 支持互斥保存；无 `flock` 的环境只读使用，不声称跨会话可安全写入。

## 文件与事实来源

```text
<project>/.project-guide/
  project-state.json           唯一权威状态
  dashboard.md                 同源生成的带时间快照
  project-state.previous.json  最近可读取备份
  history/00000001.json        历次权威版本
  reports/report-<uuid>.json   独立报告，尚未合并不算总进度
  reports/rejected-<uuid>.json 被拒写入的候选与原因
```

手工改 dashboard 不改变状态。校验成果、决定或范围变化后，通过工具保存候选再生成展示。没有保存成功时明确“更新尚未保存”；不能说其他会话已同步。`render` 失败但状态成功时，工具会区分提示，重新 render 即可。

## JSON 合约

一个完整可运行例子见 `../assets/example-project/plan.json`。新项目由 AI 按此合约建立新候选，不能照搬示例的完成状态、证据、耗时、并发容量或项目身份。

| 对象 | 字段与约束 |
|---|---|
| 根 | `schema_version:1`；新计划 `revision:0, plan_version:1, history:[]`；更新必须带读取到的修订 |
| project | `id` 稳定字母数字编号；`title/goal/delivery`；`done_when` 非空条件列表；`out_of_scope`；`scope_status:fixed/provisional/unquantified`；`time_zone` 使用已知用户时区，未知用 UTC 并注明 |
| coordinator | 初始化前 `{id:"",generation:0}`；工具维护会话 `id/generation/claimed_at`，不能候选自行修改 |
| execution | `capacity` 真实可用执行者数量，默认 1；`capacity_basis`；`state:unknown/running/stopped/paused/waiting`；`source`；运行时必有 `observed_at`，ISO 时间带偏移 |
| authorization | `allowed/limits` 列表，引用真实授权、投入边界；不保存秘密 |
| tasks[] | 每项都是唯一末级里程碑；`id/part/branch/deliverable/done_when/verify_with/depends_on/owner/state/unknowns/next_action/weight/remaining_minutes/evidence` |
| attention[] | `id/kind/status/question/why/task_ids/if_deferred`；`blocking` 默认为 true，可选未来事项为 false；类型与附加字段见执行参考；解决后必有 `response` |
| handoff | `next_action` 非空；`notes/failures/resources` 列表；资源使用入口引用 |

`part` 是汇总分组，不另外创建有权重的父任务。一个成果只放一个末级项。若计划同时覆盖主线与支线，所有者和依赖在同一记录中；异项目报告待合并，不能自行推断同步。

任务状态：`pending` 未开始/等依赖；`in_progress` 最后工作记录为执行中；`awaiting_verification` 已产出待检查；`verified` 已通过；`blocked` 必须含 `blocked_reason/unblock_when`。状态不代替当前运行信号。每个部分/支线的接回条件写入其最终里程碑的完成条件与依赖。

`remaining_minutes` 是 `null` 或 `{low:20,high:40,basis:"根据已核对的剩余步骤粗估，依据有限"}`。未开始不等于零，verified 可写零；证据失效后先重新估算返工。每项时间必须含检查与必要返工，不混入无法估计的外部等待。

证据：`{path:"verification/lesson-check.txt",method:"检查三课所有必需字段并验证加载",result:"passed",checked_at:"2026-10-22T12:00:00+00:00",note:"满足对应完成条件"}`。保存时工具补上 `sha256`；若已有指纹则核对。证据须为项目内本地文件。外部结果保存脱敏回执并在其中引用版本、对象与检查结果；不要只有一句“我做完了”。成果变化会使对应资格失效，依赖它的资格也失效。

文件指纹只检测变化，不证明检查本身充分。测试记录须绑定相应源码/素材版本；必要时同时把成果文件作为第二条证据，避免“测试日志未变但源码已变”误判。准备重新验证时先记录原资格撤回/待验证，执行检查后更新方法、时间和指纹；不要删除旧指纹来冒充重查。

## 启动、保存与交接

AI 确认目标目录和计划后，将新候选写到本项目的 scratch 位置，初次执行：

```text
python3 <skill>/scripts/are_we_there_yet.py --project <project> init --from <seed.json> --owner <实际会话标识>
```

会话标识优先用宿主实际 chat/session ID。没有宿主 ID 就为该协调会话生成 UUID 并在后续轮次复用，不用固定的 `AI` 冒充唯一会话。同一项目一个协调者；工具不是身份认证系统，其他会话必须遵守报告规则。

开始/恢复先运行 `status --json` 取得当前状态、修订、代次、重算指标。检查实际执行器，核对成果和待合并报告；有合法写入资格才修改副本，通过下列命令保存：

```text
python3 <skill>/scripts/are_we_there_yet.py --project <project> save --from <candidate.json> --owner <id> --generation <读取到的代次> --expected-revision <读取到的修订> --event progress --reason "已完成什么、依据是什么、下一步是什么"
```

`event` 支持 `progress/scope/split/blocked/decision/handoff/revalidate`。更新目标、交付、标准、依赖或权重通常升 `plan_version` 一版，使用 `scope` 并说明实际变化。等价细分可用 `split`，保持项目范围和每部分总权重；不得借拆分扩大承诺或增加进度。计划版本及修订冲突必须重新读取协调，不自动覆盖或循环强写。

工具在同一个操作系统锁内读取最新状态，核对项目 ID、协调者、代次和修订，保存历史/备份后原子替换；视图按已保存状态重建。保存权威状态和展示并非跨文件事务；进程意外退出时，展示的修订可能落后，使用权威状态 render 恢复。

其他会话：`report --from <报告.json> --author <会话id>`。报告写入不改变百分比。协调者核查报告和真实成果后合并，记录报告入口。拒绝保存时保留候选为 `rejected-*`；不要删除锁文件绕过检查。

正常交接：先存 handoff，再 `release --owner <id> --generation <n> --expected-revision <r> --reason "交接说明"`。接手：`claim --owner <新id> --expected-revision <r>`，工具增加代次。

旧协调者未释放时，只有两种真实依据允许接管：宿主确认旧协调会话结束（`--basis host-ended --evidence "真实来源与结果"`），或用户明确转交（`--basis user-transfer --evidence "指令引用"`）。不能把文件过时或用户暂未回复当作接管依据。先确认旧任务不再改同一成果，或隔离工作目录；claim 不停止旧任务。不具备依据就只读并交报告，标记等待协调。旧会话恢复后不能沿用旧代次。

记录损坏：停止总状态写入，不自动初始化覆盖；从 previous/history 检查可读取版本并核对成果。恢复是明确修复操作，不将旧修订直接冒充最新。无法安全修复时保存独立报告和可恢复信息。

## 百分比与工期

已验证完成度 = 当前范围合格末级权重 ÷ 当前范围总权重。权重由 AI 根据交付工作提出并解释；分母不是实测客观工作量。范围暂定时标 provisional，总量无法成立时 unquantified 显示未知。变更范围保留前后计划；撤回资格可以使百分比下降。

`status --json` 动态核对本地证据指纹和依赖，输出总体/部分百分比、失效项、可执行任务、剩余分钟区间、时间泳道和依赖最长链。存在失效证据时不沿用零返工估计；整体时间转为未知，直至重新核验与估算。

有完整剩余区间时，工具按依赖顺序、现有任务顺序和相同可用执行槽位做排程。先在上限情形分配槽位，再用相同槽位和顺序计算下限，保证区间不会因两次不同排程而反转。一个执行者串行；多个执行者须确实可用且可以承担相应任务。共享文件、专属资源和接口约束需加入依赖，无法表达时先按单执行者。显示的最长依赖链没有计入资源争用，不能单独当项目工期；总区间来自资源受限排程。它不是最优排程，任务顺序不同可能得到不同结果。

没有全部剩余依据就整体未知；先给下一次验证检查点。需要人或外部条件时，剩余执行时间与等待分开，交付时刻取决于等待。没有真实历史模型不显示百分比概率，不从完成百分比线性倒推时间，不编造费用。第一版仅提供执行区间，不自动承诺日历完工时刻。

开放的补充/取舍/授权默认阻塞 `task_ids` 中列明的工作；空列表表示影响整个项目，不能用它记录普通可选建议。受阻工作不会出现在可继续列表。未来扩展等明确不阻塞本轮的待选项可设 `blocking:false`，总览显示为可稍后决定，不改变本轮工期或制造必须回答的卡片。
