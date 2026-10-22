---
name: are-we-there-yet
description: Use when a user delegates a multi-step AI coding project and needs project navigation, a persistent dashboard, mainline/branch coordination, evidence-backed progress, or help judging when human decisions are needed. Especially relevant to nontechnical vibe coding, scattered execution, repeated stops, and cross-session recovery. Small one-step edits and ordinary Q&A do not need this workflow.
metadata:
  short-description: 到哪了：有终点、有依据、能接续的 AI 协作
---

# 到哪了 · Are We There Yet?

帮助使用者随时回答：交付什么、到哪里了、凭什么这样判断、接下来做什么、我需要做什么。用户掌握目标与实质取舍；AI 负责授权范围内的工程判断和持续推进。

调用名：`$are-we-there-yet`。为接续旧项目，本版继续使用 `.project-guide/` 保存状态；改名不迁移或重建已有记录。

## 开始与恢复

1. 先复用当前需求、授权和成果，确定实际项目目录。已有 `.project-guide/project-state.json` 时先恢复，不能重新初始化。用户已有任务系统时先把本次交付整理到此记录，避免同时维护两份可编辑真相；不自动连接外部服务。
2. 新项目整理目标、有限交付终点、完成标准、各部分和依赖、主支线接回条件、授权与投入边界。已明确的内容直接采用；只问真正缺少且影响执行的业务信息。技术选型由 AI 查证并判断，不要求用户审批整张计划。
3. 有文件和 Python 能力时，读取 [状态与工具](references/state-and-metrics.md)，通过附带工具保存。它执行确定的校验和计算，不能代替实际验证或授权判断。先保留全局交付框架，近期细化为互不重复的可验证末级里程碑；未知部分明示。
4. 先读 [执行与介入](references/execution-and-decisions.md)。开始时展示精简状态卡和固定总览入口，随后开始实际工作。展示格式见 [卡片与总览](references/presentation.md)。使用用户的语言；工程命令由 AI 执行，不交给非技术用户操作。

## 每轮执行契约

- 从依赖已满足、能推进交付的工作开始；优先调查阻塞后续工作的关键未知。完成一个单元后验证、记录证据、更新状态并继续。还有可执行的已授权工作时，不问“要不要继续”。
- 建立支线时写清有限交付物、接回主线条件及对范围和工期的影响。记录“可以并行”与“实际运行”的区别；没有真实执行者就串行排程。启用本 skill 不授权额外 agents、外发、付费或发布。
- 初稿、代码已生成、工具正在运行均不算已验证完成。百分比只来自工具汇总的合格末级权重；说明它是当前计划的估计模型。没有可靠总量就显示暂不可量化，没有时间依据就显示暂无法可靠估计。
- 开始/恢复、里程碑通过、阻塞、需人介入、实质范围或工期变化、本轮结束时保存。普通调用不刷屏，重要变化展示卡片。固定 dashboard 永远是带时间与修订号的快照；工具不会自动检测执行器。AI 须检查实际运行能力并记录来源，不能把旧运行信号当作当前证明。
- 普通工程选择记为仅需知晓并继续。真正缺信息、需目标取舍、超出已有授权时，按参考资料创建可回答的事项；仅等待受影响工作，独立工作继续。沉默不算同意，已有授权不重复询问。
- 本轮结束前保存下一步、已验证成果、失败尝试、关键决定和资源入口，按所有权规则交接。只有交付完成、用户暂停、真实阻塞、宿主限制或既定投入边界触发时才停止；结束时不承诺离线继续执行。

## 最小工具入口

用实际 skill 路径替换 `<skill>`，用实际项目路径替换 `<project>`：

```text
python3 <skill>/scripts/are_we_there_yet.py --project <project> --help
python3 <skill>/scripts/are_we_there_yet.py --project <project> status --json
python3 <skill>/scripts/are_we_there_yet.py --project <project> card
```

权威记录只能经工具写入。非协调会话提交报告；不要直接编辑总状态来绕过所有权、代次或修订检查。没有可靠文件能力时，在聊天保留可复制的状态与交接记录，明确“未持久保存”；无互斥能力的环境限制为只读总览/独立报告，不伪装同步成功。

完整虚构例子在 `assets/example-project/`。它仅用于试用显示和计算，不能当成用户真实成果。
