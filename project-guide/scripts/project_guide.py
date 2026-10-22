#!/usr/bin/env python3
"""Project Guide 0.1 — local state, evidence-backed metrics and snapshot views.

Python 3.9+, standard library. Mutations require POSIX flock (macOS/Linux).
This helper records assertions; the agent remains responsible for meaningful
verification, authorization, runtime observation and correct project selection.
"""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import fcntl
except ImportError:
    fcntl = None

VERSION = "0.1.0"
STATES = {"pending", "in_progress", "awaiting_verification", "verified", "blocked"}
LABELS = {"pending": "未开始", "in_progress": "最后记录：执行中", "awaiting_verification": "待验证",
          "verified": "已验证", "blocked": "遇阻"}
KINDS = {"info": "仅需知晓", "input": "需要补充", "decision": "需要取舍", "authorization": "需要授权"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class GuideError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise GuideError(message)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise GuideError("无法读取 JSON %s：%s；不会自动覆盖，请核查 previous/history。" % (path, exc))


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pg-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def location(root):
    root = Path(root).resolve()
    require(root.is_dir(), "项目目录必须已经存在。")
    guide = root / ".project-guide"
    require(not guide.is_symlink(), ".project-guide 不能是符号链接；请明确项目位置。")
    return root, guide


@contextmanager
def locked(guide):
    require(fcntl is not None, "此环境无安全互斥机制：只读 status/card/validate 可用；请由支持 flock 的单一宿主保存。")
    guide.mkdir(parents=True, exist_ok=True)
    with (guide / ".lock").open("a") as lock:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, "状态被另一个写入者锁定；未保存，请稍后重新读取。")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def text_field(value, key):
    require(isinstance(value.get(key), str) and bool(value[key].strip()), "字段 %s 必须是非空文字。" % key)


def list_field(value, key, nonempty=False):
    require(isinstance(value.get(key), list), "字段 %s 必须为列表。" % key)
    if nonempty:
        require(bool(value[key]), "字段 %s 不能为空。" % key)


def number(value, minimum=0):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= minimum


def topological(tasks):
    by_id = {t["id"]: t for t in tasks}
    seen, stack, ordered = set(), set(), []

    def visit(key):
        require(key not in stack, "依赖形成循环：%s。" % key)
        if key in seen:
            return
        stack.add(key)
        for dependency in by_id[key]["depends_on"]:
            require(dependency in by_id, "未知依赖 %s。" % dependency)
            visit(dependency)
        stack.remove(key)
        seen.add(key)
        ordered.append(key)

    for key in by_id:
        visit(key)
    return ordered


def evidence_file(root, reference):
    require(isinstance(reference, str) and reference.strip(), "evidence.path 必须指向本地验证记录或成果。")
    path = (root / reference).resolve()
    require(path.is_relative_to(root), "evidence.path 必须在当前项目内；外部证据请保存本地核验回执。")
    relative = path.relative_to(root).as_posix()
    require(not relative.startswith(".project-guide/history/") and
            relative not in {".project-guide/project-state.json", ".project-guide/project-state.previous.json",
                             ".project-guide/dashboard.md"}, "总状态或展示本身不能作为交付完成证据。")
    require(path.is_file(), "evidence 文件不存在：%s。" % reference)
    return path


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(state):
    require(isinstance(state, dict) and state.get("schema_version") == 1, "仅支持 schema_version 1。")
    project = state.get("project", {})
    for field in ("id", "title", "goal", "delivery", "time_zone"):
        text_field(project, field)
    require(bool(ID.fullmatch(project["id"])), "project.id 使用稳定的英文字母、数字或短横线编号。")
    for field in ("done_when", "out_of_scope"):
        list_field(project, field, nonempty=field == "done_when")
    require(project.get("scope_status") in {"fixed", "provisional", "unquantified"}, "scope_status 不正确。")
    require(type(state.get("plan_version")) is int and state["plan_version"] >= 1, "plan_version 必须为正整数。")
    require(type(state.get("revision")) is int and state["revision"] >= 0, "revision 必须为非负整数。")
    require(isinstance(state.get("coordinator"), dict), "缺少 coordinator。")
    execution = state.get("execution", {})
    require(type(execution.get("capacity")) is int and 1 <= execution["capacity"] <= 32, "capacity 必须为 1—32 个真实可用执行者。")
    text_field(execution, "capacity_basis")
    require(execution.get("state") in {"unknown", "running", "stopped", "paused", "waiting"}, "execution.state 不正确。")
    text_field(execution, "source")
    if execution["state"] == "running":
        text_field(execution, "observed_at")
    require(isinstance(state.get("authorization"), dict), "缺少授权边界。")
    for field in ("allowed", "limits"):
        list_field(state["authorization"], field)
    list_field(state, "tasks", True)
    keys = []
    for task in state["tasks"]:
        require(isinstance(task, dict), "task 必须为对象。")
        for field in ("id", "part", "branch", "deliverable", "verify_with", "owner", "next_action"):
            text_field(task, field)
        require(bool(ID.fullmatch(task["id"])), "task.id 只使用字母、数字、短横线或下划线。")
        keys.append(task["id"])
        for field in ("done_when", "depends_on", "unknowns", "evidence"):
            list_field(task, field, nonempty=field == "done_when")
        require(all(isinstance(d, str) for d in task["depends_on"]), "依赖必须是任务编号。")
        require(len(set(task["depends_on"])) == len(task["depends_on"]), "依赖不能重复。")
        require(task.get("state") in STATES, "未知任务状态。")
        require(number(task.get("weight")) and task["weight"] > 0, "weight 必须是有限正数。")
        estimate = task.get("remaining_minutes")
        if estimate is not None:
            require(isinstance(estimate, dict) and number(estimate.get("low")) and number(estimate.get("high")), "工期必须是有限非负分钟区间或 null。")
            require(estimate["low"] <= estimate["high"], "工期下限不能大于上限。")
            text_field(estimate, "basis")
        if task["state"] == "blocked":
            text_field(task, "blocked_reason")
            text_field(task, "unblock_when")
        if task["state"] == "verified":
            require(bool(task["evidence"]), "verified 必须提供 evidence；开始、初稿和耗时不计完成。")
        for evidence in task["evidence"]:
            require(isinstance(evidence, dict), "evidence 必须为对象。")
            for field in ("path", "method", "checked_at", "note"):
                text_field(evidence, field)
            require(evidence.get("result") == "passed", "完成证据 result 必须为 passed。")
    require(len(set(keys)) == len(keys), "任务编号重复。")
    topological(state["tasks"])
    list_field(state, "attention")
    attention_ids = []
    for item in state["attention"]:
        require(isinstance(item, dict), "attention 必须为对象。")
        for field in ("id", "question", "why", "if_deferred"):
            text_field(item, field)
        attention_ids.append(item["id"])
        require(item.get("kind") in KINDS, "未知关注类别。")
        require(item.get("status") in {"open", "resolved"}, "关注状态必须为 open 或 resolved。")
        require(type(item.get("blocking", True)) is bool, "blocking 必须是布尔值。")
        list_field(item, "task_ids")
        require(all(key in keys for key in item["task_ids"]), "关注事项引用未知任务。")
        if item["kind"] == "decision":
            list_field(item, "options", True)
            require(len(item["options"]) >= 2, "有实际取舍时至少说明两个可行选择。")
            for option in item["options"]:
                for field in ("label", "benefit", "cost", "risk", "reversibility"):
                    text_field(option, field)
            text_field(item, "recommendation")
            text_field(item, "criterion")
        if item["kind"] == "authorization":
            for field in ("action", "target", "consequences", "recovery", "prepared"):
                text_field(item, field)
        if item["status"] == "resolved":
            text_field(item, "response")
    require(len(set(attention_ids)) == len(attention_ids), "关注事项编号重复。")
    require(isinstance(state.get("handoff"), dict), "缺少交接记录。")
    text_field(state["handoff"], "next_action")
    for field in ("notes", "failures", "resources"):
        list_field(state["handoff"], field)
    list_field(state, "history")
    return state


def fingerprint_evidence(state, root, previous=None):
    previous_tasks = {t["id"]: t for t in previous["tasks"]} if previous else {}
    for task in state["tasks"]:
        for evidence in task["evidence"]:
            if evidence in previous_tasks.get(task["id"], {}).get("evidence", []) and evidence.get("sha256"):
                # Preserve an old assertion without re-certifying it. Read-time
                # metrics withdraw stale credit, so recovery can still proceed.
                continue
            path = evidence_file(root, evidence["path"])
            actual = file_hash(path)
            if evidence.get("sha256"):
                require(evidence["sha256"] == actual, "evidence 已变化：%s；先撤回完成资格或重新验证并更新证据。" % evidence["path"])
            else:
                evidence["sha256"] = actual


def qualified_tasks(state, root):
    by_id = {t["id"]: t for t in state["tasks"]}
    qualified, stale = set(), []
    for key in topological(state["tasks"]):
        task = by_id[key]
        if task["state"] != "verified":
            continue
        valid = bool(task["evidence"])
        for evidence in task["evidence"]:
            try:
                valid = valid and bool(evidence.get("sha256")) and file_hash(evidence_file(root, evidence["path"])) == evidence["sha256"]
            except (GuideError, OSError):
                valid = False
        if valid and all(dep in qualified for dep in task["depends_on"]):
            qualified.add(key)
        else:
            stale.append(key)
    return qualified, stale


def schedule(tasks, qualified, capacity, bound, assignment=None):
    """Deterministic list schedule with identical workers and explicit dependencies.

    This is an illustrative resource-feasible forecast, not an optimal scheduler
    or statistical confidence interval. Shared resources need dependency edges.
    """
    order = topological(tasks)
    by_id = {t["id"]: t for t in tasks}
    workers, finishes, rows = [0.0] * capacity, {}, []
    for key in order:
        task = by_id[key]
        if key in qualified:
            finishes[key] = 0.0
            continue
        dep_end = max([finishes[d] for d in task["depends_on"]] or [0])
        index = assignment[key] - 1 if assignment is not None else min(range(capacity), key=lambda i: max(workers[i], dep_end))
        start = max(workers[index], dep_end)
        end = start + task["remaining_minutes"][bound]
        workers[index], finishes[key] = end, end
        rows.append({"id": key, "worker": index + 1, "start": start, "end": end})
    return max(finishes.values(), default=0), rows


def forecast(tasks, qualified, capacity):
    high, rows = schedule(tasks, qualified, capacity, "high")
    # Keep the exact same worker assignment and sequence at both bounds.
    # Independent greedy schedules can reverse an otherwise valid interval.
    assignment = {row["id"]: row["worker"] for row in rows}
    low, _ = schedule(tasks, qualified, capacity, "low", assignment)
    return [low, high], rows


def metrics(state, root):
    qualified, stale = qualified_tasks(state, root)
    tasks = state["tasks"]
    total = sum(t["weight"] for t in tasks)
    earned = sum(t["weight"] for t in tasks if t["id"] in qualified)
    percent = None if state["project"]["scope_status"] == "unquantified" else earned_percent(earned, total, len(qualified) == len(tasks))
    pending = [t for t in tasks if t["id"] not in qualified]
    estimates_known = not stale and all(t.get("remaining_minutes") is not None for t in pending)
    remaining, rows = None, []
    if estimates_known:
        remaining, rows = forecast(tasks, qualified, state["execution"]["capacity"])
    blockers = [a for a in state["attention"] if a["status"] == "open" and a["kind"] != "info" and a.get("blocking", True)]
    waits = bool(blockers) or any(t["state"] == "blocked" for t in pending)
    parts = {}
    for task in tasks:
        part = parts.setdefault(task["part"], {"earned": 0, "total": 0})
        part["total"] += task["weight"]
        if task["id"] in qualified:
            part["earned"] += task["weight"]
    for name, part in parts.items():
        leaves = [t for t in tasks if t["part"] == name]
        complete = all(t["id"] in qualified for t in leaves)
        part["percent"] = earned_percent(part["earned"], part["total"], complete)
        part["remaining_minutes"] = None
        if not any(t["id"] in stale for t in leaves) and all(t["id"] in qualified or t["remaining_minutes"] is not None for t in leaves):
            subset = copy.deepcopy(leaves)
            ids = {t["id"] for t in subset}
            for leaf in subset:
                leaf["depends_on"] = [d for d in leaf["depends_on"] if d in ids]
            part["remaining_minutes"], _ = forecast(subset, qualified, state["execution"]["capacity"])
    blocked_by_human = {key for a in blockers for key in a["task_ids"]}
    project_wait = any(not a["task_ids"] for a in blockers)
    ready = [t["id"] for t in pending if not project_wait and t["id"] not in blocked_by_human and t["state"] != "blocked" and all(d in qualified for d in t["depends_on"])]
    critical = []
    if estimates_known and pending:
        lengths, chains = {}, {}
        for key in topological(tasks):
            task = next(t for t in tasks if t["id"] == key)
            predecessor = max(task["depends_on"], key=lambda d: lengths[d], default=None)
            lengths[key] = (lengths[predecessor] if predecessor else 0) + (0 if key in qualified else task["remaining_minutes"]["high"])
            chains[key] = (chains[predecessor] if predecessor else []) + ([] if key in qualified else [key])
        critical = chains[max(lengths, key=lengths.get)]
    return {"percent": percent, "earned_weight": earned, "total_weight": total,
            "qualified_task_ids": sorted(qualified), "stale_task_ids": stale, "parts": parts,
            "remaining_minutes": remaining, "schedule_high": rows, "dependency_chain": critical,
            "ready_task_ids": ready, "delivery_time": "depends_on_wait" if waits else ("range_only" if remaining is not None else "unknown"),
            "open_attention_ids": [a["id"] for a in blockers], "all_verified": len(qualified) == len(tasks)}


def md(value):
    return str(value).replace("\n", " ").replace("|", "\\|").replace("`", "'")


def earned_percent(earned, total, complete):
    return 100.0 if complete else min(99.9, round(earned / total * 100, 1))


def local_time(value, state):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(state["project"]["time_zone"])).isoformat(timespec="seconds")
    except (ValueError, AttributeError, ZoneInfoNotFoundError):
        return value


def percent_text(value):
    return "暂不可量化" if value is None else "%g%%" % value


def duration(value):
    return "暂无法可靠估计" if value is None else "%g—%g 分钟" % tuple(value)


def run_text(state):
    execution = state["execution"]
    when = local_time(execution.get("observed_at", "未取得核验时间"), state)
    if execution["state"] == "running":
        return "截至 %s 最后确认执行中；当前运行状态待核实（来源：%s）" % (when, execution["source"])
    label = {"unknown": "待核实", "stopped": "已结束", "paused": "已暂停", "waiting": "等待条件"}[execution["state"]]
    return "截至 %s 记录为%s；快照不代表当前运行（来源：%s）" % (when, label, execution["source"])


def card(state, result):
    human = [a for a in state["attention"] if a["status"] == "open" and a["kind"] != "info" and a.get("blocking", True)]
    need = "；".join(a["id"] + " " + a["question"] for a in human) or "暂无，无需操作"
    unknowns = [u for t in state["tasks"] for u in t["unknowns"]]
    wait = "；交付日期取决于等待条件" if result["delivery_time"] == "depends_on_wait" else ""
    return "\n".join([
        "项目：%s · 计划 v%s · 修订 %s · 快照 %s" % (state["project"]["title"], state["plan_version"], state["revision"], local_time(state.get("updated_at", "未保存"), state)),
        "本次交付：" + state["project"]["delivery"],
        "当前范围已验证完成度：" + percent_text(result["percent"]),
        "关键未知：" + ("；".join(unknowns[:2]) or ("无未完成事项" if result["all_verified"] else "当前未记录；仍需满足完整完成条件")),
        "运行核验：" + run_text(state),
        "下一步：" + state["handoff"]["next_action"],
        "剩余执行时间：" + duration(result["remaining_minutes"]) + "（粗估，非统计预测）" + wait,
        "需要你：" + need,
        "完整计划与证据：.project-guide/dashboard.md",
    ]) + "\n"


def dashboard(state, result):
    lines = ["# " + md(state["project"]["title"]) + " · 项目总览", "",
             "> 固定文件是带时间的快照。打开文件不会检查执行器；刷新时须由 AI 核验。", "",
             "计划 v%s · 修订 %s · 保存时间 %s · 时区 %s（时间带 UTC 偏移）" % (state["plan_version"], state["revision"], local_time(state.get("updated_at", "未保存"), state), md(state["project"]["time_zone"])), "",
             "**目标：** " + md(state["project"]["goal"]), "", "**本次交付：** " + md(state["project"]["delivery"]), "",
             "| 当前范围已验证完成度 | 剩余执行时间 | 预计交付时间 |", "|---|---|---|",
             "| %s | %s，粗估 | %s |" % (percent_text(result["percent"]), duration(result["remaining_minutes"]),
               "取决于待解决条件，等待时间未计入" if result["delivery_time"] == "depends_on_wait" else "只提供执行区间，不承诺具体时刻"), "",
             "范围：%s。完成度只计通过检查且证据仍有效的末级里程碑。权重是计划估计，不是客观工作量测量。" % {"fixed":"本轮范围已约定","provisional":"范围暂定","unquantified":"总量尚不可可靠量化"}[state["project"]["scope_status"]], "",
             "## 需要你关注", ""]
    opened = [a for a in state["attention"] if a["status"] == "open"]
    if not any(a["kind"] != "info" and a.get("blocking", True) for a in opened):
        lines += ["暂无需要你回答或操作的事项。AI 继续推进已授权工作。", ""]
    for item in sorted(opened, key=lambda a: a["kind"] == "info"):
        lines += ["### %s · %s" % (md(item["id"]), KINDS[item["kind"]]), "", "**" + md(item["question"]) + "**", "",
                  "为什么现在需要：" + md(item["why"]), "", "影响任务：" + ("、".join(item["task_ids"]) or "项目整体"), ""]
        if item["kind"] == "decision" and not item.get("blocking", True):
            lines += ["可稍后决定；不阻塞本轮交付，无需现在回答。", ""]
        if item["kind"] == "decision":
            lines += ["| 选择 | 收益 | 代价 | 风险 | 恢复能力 |", "|---|---|---|---|---|"]
            for option in item["options"]:
                lines.append("| " + " | ".join(md(option[k]) for k in ("label", "benefit", "cost", "risk", "reversibility")) + " |")
            lines += ["", "AI 推荐：" + md(item["recommendation"]), "", "判断依据：" + md(item["criterion"]), ""]
        elif item["kind"] == "authorization":
            for field, label in (("action", "具体动作"), ("target", "对象"), ("consequences", "后果"), ("recovery", "恢复能力"), ("prepared", "已完成准备")):
                lines += [label + "：" + md(item[field]), ""]
        lines += ["暂不回答：" + md(item["if_deferred"]), ""]
    lines += ["## 全局交付与依赖", "", "| 部分 | 已验证权重 / 总权重 | 部分完成度 | 本部分剩余执行（不含外部依赖等待） |", "|---|---:|---:|---|"]
    for name, part in result["parts"].items():
        lines.append("| %s | %g / %g | %s | %s |" % (md(name), part["earned"], part["total"], percent_text(part["percent"]), duration(part["remaining_minutes"])))
    lines += ["", "| 编号 · 交付物 | 主支线 / 负责人 | 状态 | 依赖 | 剩余执行时间 | 下一步 / 解除条件 |", "|---|---|---|---|---|---|"]
    for task in state["tasks"]:
        label = "证据失效，需重新核验" if task["id"] in result["stale_task_ids"] else LABELS[task["state"]]
        remaining = [0, 0] if task["id"] in result["qualified_task_ids"] else ([task["remaining_minutes"]["low"], task["remaining_minutes"]["high"]] if task["remaining_minutes"] and task["id"] not in result["stale_task_ids"] else None)
        lines.append("| %s · %s | %s / %s | %s | %s | %s | %s |" % (task["id"], md(task["deliverable"]), md(task["branch"]), md(task["owner"]), label, ", ".join(task["depends_on"]) or "无", duration(remaining), md(task.get("unblock_when") if task["state"] == "blocked" else task["next_action"])))
    for task in state["tasks"]:
        if task["state"] == "blocked":
            lines += ["", "**%s 遇阻原因：** %s；解除条件：%s" % (task["id"], md(task["blocked_reason"]), md(task["unblock_when"]))]
    if any(t["depends_on"] for t in state["tasks"]):
        lines += ["", "```mermaid", "flowchart LR"]
        for index, task in enumerate(state["tasks"]):
            lines.append('  %s["%s"]' % (task["id"], task["id"]))
            for dep in task["depends_on"]:
                lines.append("  %s --> %s" % (dep, task["id"]))
        lines += ["```", "", "图不能显示时，上表的依赖编号仍完整保留。图中可并行不代表已启动多个执行者。"]
    lines += ["", "依赖最长链（未计资源争用）：" + (" → ".join(result["dependency_chain"]) or "暂无可靠时间依据"), "",
              "实际排程容量：%s。依据：%s。" % (state["execution"]["capacity"], md(state["execution"]["capacity_basis"])), "",
              "排程按依赖与现有任务顺序做资源受限粗估，假设执行者可互换；共享资源冲突需记录成依赖或按一个执行者估算。不是最优排程或概率保证。", ""]
    if result["schedule_high"]:
        lines += ["### 预计时间泳道", "", "从本次快照起的剩余分钟，上限情形；不含等待。", "",
                  "| 任务 | 执行槽位 | 开始分钟 | 结束分钟 |", "|---|---:|---:|---:|"]
        for row in result["schedule_high"]:
            lines.append("| %s | %s | %g | %g |" % (row["id"], row["worker"], row["start"], row["end"]))
        lines += [""]
    lines += ["## 当前执行与下一步", "", run_text(state), "", "可开始或继续：" + ("、".join(result["ready_task_ids"]) or "暂无，请查看等待或完成条件"), "",
              "**下一步：** " + md(state["handoff"]["next_action"]), "", "## 完成标准与证据", ""]
    for condition in state["project"]["done_when"]:
        lines.append("- " + md(condition))
    lines += ["", "以下是已记录的验证证据；指纹检查只证明文件未变化，AI 仍须判断检查是否充分。", ""]
    for task in state["tasks"]:
        if task["unknowns"]:
            lines += ["**%s 关键未知：** %s" % (task["id"], "；".join(md(u) for u in task["unknowns"])), ""]
        for evidence in task["evidence"]:
            lines += ["- %s · `%s` · %s · %s · %s" % (task["id"], md(evidence["path"]), md(evidence["method"]), md(evidence["checked_at"]), "有效" if task["id"] in result["qualified_task_ids"] else "未取得当前完成资格")]
    lines += ["", "## 范围与授权", "", "本轮暂不包含：" + ("；".join(md(x) for x in state["project"]["out_of_scope"]) or "未另列"), "",
              "已授权：" + ("；".join(md(x) for x in state["authorization"]["allowed"]) or "按当前对话授权"), "",
              "投入与授权边界：" + ("；".join(md(x) for x in state["authorization"]["limits"]) or "按当前对话和宿主要求"), "",
              "## 最近变化与交接", ""]
    for event in state["history"][-8:]:
        lines.append("- %s · r%s · %s · %s · 完成度 %s" % (event["at"], event["revision"], md(event["event"]), md(event["reason"]), percent_text(event.get("percent"))))
    for field, label in (("notes", "交接说明"), ("failures", "已尝试失败方法"), ("resources", "恢复所需资源")):
        lines += ["", "**" + label + "：**"]
        lines += ["- " + md(x) for x in state["handoff"][field]] or ["- 暂无记录"]
    lines += ["", "权威记录：`project-state.json`。最近备份：`project-state.previous.json`；历史：`history/`；待合并报告：`reports/`。", "",
              "恢复时先核对项目身份、协调者代次、真实成果和执行器。普通打开文件不产生后台执行。", ""]
    return "\n".join(lines)


def scope_signature(state):
    project = state["project"]
    fields = ("goal", "delivery", "done_when", "out_of_scope", "scope_status")
    task_fields = ("id", "part", "branch", "deliverable", "done_when", "verify_with", "weight", "depends_on")
    return json_text({"project": {k: project[k] for k in fields},
                      "tasks": sorted([{k: task[k] for k in task_fields} for task in state["tasks"]], key=lambda t: t["id"])})


def validate_transition(previous, candidate, event):
    require(candidate["project"]["id"] == previous["project"]["id"], "项目身份不匹配。")
    delta = candidate["plan_version"] - previous["plan_version"]
    require(delta in {0, 1}, "计划版本只能保持或加一。")
    changed = scope_signature(candidate) != scope_signature(previous)
    if delta:
        require(event == "scope", "新计划版本使用 event=scope 并说明范围变更原因。")
    if changed and delta == 0:
        if event == "split":
            def groups(state):
                weights = defaultdict(float)
                for task in state["tasks"]:
                    weights[task["part"]] += task["weight"]
                return dict(weights)
            require(candidate["project"] == previous["project"] and groups(candidate) == groups(previous), "拆分须保持交付范围与每部分总权重；实际范围变化应升计划版本。")
        else:
            raise GuideError("交付、完成标准、依赖或权重发生变化；需新计划版本和 event=scope，等价拆分可用 event=split。")


def reject_report(guide, candidate, cause):
    report = guide / "reports" / ("rejected-" + uuid.uuid4().hex + ".json")
    atomic_write(report, json_text({"at": stamp(), "cause": str(cause), "candidate": candidate}))
    return report


def commit(root, guide, state, previous, event, reason):
    validate(state)
    fingerprint_evidence(state, root, previous)
    previous_tasks = {t["id"]: t for t in previous["tasks"]} if previous else {}
    qualified, _ = qualified_tasks(state, root)
    for task in state["tasks"]:
        old = previous_tasks.get(task["id"], {})
        if task["state"] == "verified" and (old.get("state") != "verified" or old.get("evidence") != task["evidence"]):
            require(all(dep in qualified for dep in task["depends_on"]), "verified 任务 %s 仍有未验证或证据失效的依赖。" % task["id"])
    state["revision"] = (previous["revision"] if previous else 0) + 1
    state["updated_at"] = stamp()
    for task in state["tasks"]:
        old = next((t for t in previous["tasks"] if t["id"] == task["id"]), None) if previous else None
        if old != task:
            task["updated_at"] = state["updated_at"]
    result = metrics(state, root)
    state["history"] = copy.deepcopy(previous["history"]) if previous else []
    state["history"].append({"at": state["updated_at"], "revision": state["revision"], "plan_version": state["plan_version"],
                             "event": event, "reason": reason, "percent": result["percent"],
                             "previous_percent": metrics(previous, root)["percent"] if previous else None})
    payload = json_text(state)
    view = dashboard(state, result)
    # Backups are durable before the authoritative atomic replace. Views may be
    # stale if the process dies next; their explicit revision/time exposes this.
    if previous:
        atomic_write(guide / "history" / ("%08d.json" % previous["revision"]), json_text(previous))
    atomic_write(guide / "project-state.previous.json", json_text(previous or state))
    atomic_write(guide / "project-state.json", payload)
    try:
        atomic_write(guide / "dashboard.md", view)
    except OSError as exc:
        print("权威状态已保存，但 dashboard 未刷新：%s；运行 render 可恢复。" % exc, file=sys.stderr)
    return state


def credentials(state, args):
    require(state["revision"] == args.expected_revision, "修订冲突：当前 r%s；请重新读取再协调。" % state["revision"])
    require(state["coordinator"].get("id") == args.owner and state["coordinator"].get("generation") == args.generation,
            "协调者所有权或代次不匹配；禁止覆盖，请提交 report。")


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--version", action="version", version=VERSION)
    cli.add_argument("--project", required=True, help="目标项目的已有目录")
    commands = cli.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="由已整理的计划建立本地记录；不会覆盖已有项目")
    initialize.add_argument("--from", dest="source", required=True)
    initialize.add_argument("--owner", required=True, help="实际协调会话的稳定标识")
    save = commands.add_parser("save", help="在锁内校验身份、代次和修订，保存候选记录")
    save.add_argument("--from", dest="source", required=True)
    for command in (save,):
        command.add_argument("--owner", required=True)
        command.add_argument("--generation", type=int, required=True)
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument("--event", choices=["progress", "scope", "split", "blocked", "decision", "handoff", "revalidate"], required=True)
        command.add_argument("--reason", required=True)
    status = commands.add_parser("status", help="只读状态并重新计算证据指纹；不会核验执行器")
    status.add_argument("--json", action="store_true")
    commands.add_parser("card", help="输出简洁状态快照")
    commands.add_parser("render", help="从当前权威状态重建固定总览，不更新运行信号")
    validate_command = commands.add_parser("validate", help="检查候选结构和本地证据，不保存")
    validate_command.add_argument("--from", dest="source", required=True)
    claim = commands.add_parser("claim", help="正常接手或有依据地接管；不会终止旧执行任务")
    claim.add_argument("--owner", required=True)
    claim.add_argument("--expected-revision", type=int, required=True)
    claim.add_argument("--basis", choices=["host-ended", "user-transfer"])
    claim.add_argument("--evidence", help="宿主结束证据或用户转交指令引用；不能凭猜测填写")
    release = commands.add_parser("release", help="保存交接，释放协调者所有权")
    for name, options in (("--owner", {}), ("--generation", {"type": int}), ("--expected-revision", {"type": int}), ("--reason", {})):
        release.add_argument(name, required=True, **options)
    report = commands.add_parser("report", help="写独立报告，不改权威状态或取得所有权")
    report.add_argument("--from", dest="source", required=True)
    report.add_argument("--author", required=True)
    return cli


def main():
    args = parser().parse_args()
    root, guide = location(args.project)
    state_path = guide / "project-state.json"
    if args.command == "validate":
        state = validate(read_json(args.source))
        fingerprint_evidence(state, root)
        print("结构与本地证据检查通过；不代表业务验证已充分。")
        return
    if args.command == "report":
        require(state_path.exists(), "请先由协调者建立项目记录。")
        payload = {"at": stamp(), "author": args.author, "report": read_json(args.source)}
        path = guide / "reports" / ("report-" + uuid.uuid4().hex + ".json")
        atomic_write(path, json_text(payload))
        print(str(path))
        return
    if args.command in {"status", "card"}:
        state = validate(read_json(state_path))
        result = metrics(state, root)
        print(json_text({"state": state, "metrics": result}) if args.command == "status" and args.json else card(state, result), end="")
        return
    with locked(guide):
        if args.command == "init":
            require(not state_path.exists(), "项目记录已存在；请恢复现有状态，不能再次 init。")
            state = validate(read_json(args.source))
            require(state["revision"] == 0, "初始计划 revision 必须为 0。")
            state["coordinator"] = {"id": args.owner, "generation": 1, "claimed_at": stamp()}
            commit(root, guide, state, None, "init", "由现有需求建立交付约定")
        else:
            current = validate(read_json(state_path))
            if args.command == "render":
                atomic_write(guide / "dashboard.md", dashboard(current, metrics(current, root)))
                print(str(guide / "dashboard.md"))
                return
            candidate = read_json(args.source) if args.command == "save" else copy.deepcopy(current)
            try:
                if args.command == "save":
                    credentials(current, args)
                    validate(candidate)
                    require(candidate["revision"] == current["revision"] and candidate["coordinator"] == current["coordinator"], "候选修订或协调者与读取版本不一致。")
                    validate_transition(current, candidate, args.event)
                    commit(root, guide, candidate, current, args.event, args.reason)
                elif args.command == "release":
                    credentials(current, args)
                    candidate["coordinator"]["id"] = ""
                    candidate["handoff"]["notes"].append(args.reason)
                    commit(root, guide, candidate, current, "handoff", args.reason)
                elif args.command == "claim":
                    require(current["revision"] == args.expected_revision, "修订冲突；请重新读取。")
                    require(current["coordinator"].get("id") != args.owner, "此会话已持有所有权；读取当前代次，不要再次接管。")
                    if current["coordinator"].get("id"):
                        require(bool(args.basis) and bool(args.evidence and args.evidence.strip()), "旧协调者未释放；必须有 host-ended 或 user-transfer 的真实依据。")
                    candidate["coordinator"] = {"id": args.owner, "generation": current["coordinator"]["generation"] + 1,
                                                 "claimed_at": stamp(), "basis": args.basis or "released", "evidence": args.evidence or "原协调者正常释放"}
                    candidate["execution"].update(state="unknown", source="接管不证明旧任务已停止；恢复时核验", observed_at=stamp())
                    commit(root, guide, candidate, current, "handoff", args.evidence or "接手已释放项目")
            except GuideError as exc:
                report = reject_report(guide, candidate, exc)
                raise GuideError(str(exc) + " 候选已保留：" + str(report))
    print("已保存 %s；dashboard.md 已生成。" % state_path)


if __name__ == "__main__":
    try:
        main()
    except (GuideError, OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print("Project Guide：%s" % error, file=sys.stderr)
        sys.exit(2)
