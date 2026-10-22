"""CLI contract tests: earned progress, honest estimates and fenced state writes.

Run from any directory: python3 -m unittest discover -s <skill>/tests -v
Each test uses an isolated real project; no network or product files are touched.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "are_we_there_yet.py"


def task(key, weight, deps=None, minutes=None):
    return {"id": key, "part": key, "branch": "主线", "deliverable": key + "交付",
            "done_when": ["成果可使用"], "verify_with": "检查本地成果", "depends_on": deps or [],
            "owner": "AI", "state": "pending", "unknowns": [], "next_action": "实现并检查",
            "weight": weight, "remaining_minutes": minutes, "evidence": []}


def plan():
    return {"schema_version": 1,
            "project": {"id": "trial", "title": "练习站", "goal": "完成一次练习",
                        "delivery": "三课可用", "done_when": ["完整流程通过验证"],
                        "out_of_scope": ["扩大课程"], "scope_status": "fixed", "time_zone": "Asia/Hong_Kong"},
            "plan_version": 1, "revision": 0, "coordinator": {"id": "", "generation": 0},
            "execution": {"capacity": 1, "capacity_basis": "当前一个执行者", "state": "unknown", "source": "未核验"},
            "authorization": {"allowed": ["本地实现和验证"], "limits": ["未授权发布"]},
            "tasks": [task("A", 20, minutes={"low": 10, "high": 20, "basis": "按当前内容粗估"}),
                      task("B", 30, ["A"], {"low": 60, "high": 90, "basis": "流程粗估"}),
                      task("C", 30, ["A"], {"low": 30, "high": 45, "basis": "素材粗估"}),
                      task("D", 20, ["B", "C"], {"low": 20, "high": 30, "basis": "接入粗估"})],
            "attention": [], "handoff": {"next_action": "开始 A", "notes": [], "failures": [], "resources": []},
            "history": []}


class GuideCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="are-we-there-yet-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seed = self.root / "seed.json"
        self.seed.write_text(json.dumps(plan(), ensure_ascii=False))

    def call(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.root), *args],
                                text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def initialize(self):
        self.call("init", "--from", str(self.seed), "--owner", "session-a")
        return self.read()

    def read(self):
        return json.loads((self.root / ".project-guide/project-state.json").read_text())

    def save(self, state, event="progress", reason="实际完成检查", success=True):
        candidate = self.root / "candidate.json"
        candidate.write_text(json.dumps(state, ensure_ascii=False))
        return self.call("save", "--from", str(candidate), "--owner", state["coordinator"]["id"],
                         "--generation", str(state["coordinator"]["generation"]),
                         "--expected-revision", str(state["revision"]), "--event", event,
                         "--reason", reason, success=success)

    def verified(self, state, key):
        leaf = next(t for t in state["tasks"] if t["id"] == key)
        artifact = self.root / (key + ".txt")
        artifact.write_text(key + "检查通过")
        leaf["state"] = "verified"
        leaf["remaining_minutes"] = {"low": 0, "high": 0, "basis": "已通过"}
        leaf["evidence"] = [{"path": artifact.name, "method": "核对完整内容", "result": "passed",
                            "checked_at": "2026-10-22T12:00:00+00:00", "note": "成果满足完成条件"}]

    def metrics(self):
        return json.loads(self.call("status", "--json").stdout)["metrics"]

    def test_new_project_does_not_earn_progress_for_started_work(self):
        state = self.initialize()
        state["tasks"][0]["state"] = "in_progress"
        self.save(state)
        self.assertEqual(self.metrics()["percent"], 0)
        self.assertTrue((self.root / ".project-guide/dashboard.md").exists())

    def test_verified_weight_is_counted_once_and_evidence_change_invalidates_it(self):
        state = self.initialize()
        self.verified(state, "A")
        self.save(state)
        self.assertEqual(self.metrics()["percent"], 20)
        (self.root / "A.txt").write_text("后来内容发生变化")
        self.assertEqual(self.metrics()["percent"], 0)
        self.assertIn("A", self.metrics()["stale_task_ids"])

    def test_verified_task_requires_actual_evidence(self):
        state = self.initialize()
        state["tasks"][0]["state"] = "verified"
        result = self.save(state, success=False)
        self.assertIn("evidence", result.stderr)
        self.assertEqual(self.read()["revision"], 1)

    def test_verified_task_cannot_skip_dependencies(self):
        state = self.initialize()
        self.verified(state, "B")
        self.save(state, success=False)
        self.assertEqual(self.metrics()["percent"], 0)

    def test_cycle_duplicate_ids_and_nonfinite_weights_are_rejected(self):
        for mutation in ("cycle", "duplicate", "nan"):
            with self.subTest(mutation=mutation):
                state = plan()
                if mutation == "cycle": state["tasks"][0]["depends_on"] = ["D"]
                elif mutation == "duplicate": state["tasks"][1]["id"] = "A"
                else: state["tasks"][0]["weight"] = float("nan")
                self.seed.write_text(json.dumps(state))
                self.call("validate", "--from", str(self.seed), success=False)

    def test_scope_change_requires_new_plan_and_keeps_old_snapshot(self):
        state = self.initialize()
        state["tasks"].append(task("E", 10))
        self.save(state, success=False)
        state["plan_version"] = 2
        self.save(state, event="scope", reason="用户要求增加复习页")
        self.assertEqual(self.read()["plan_version"], 2)
        before = json.loads((self.root / ".project-guide/history/00000001.json").read_text())
        self.assertEqual(len(before["tasks"]), 4)

    def test_equivalent_leaf_split_keeps_the_same_denominator(self):
        state = self.initialize()
        original = state["tasks"].pop(1)
        b1, b2 = copy.deepcopy(original), copy.deepcopy(original)
        b1.update(id="B1", weight=10)
        b2.update(id="B2", weight=20)
        state["tasks"].extend([b1, b2])
        state["tasks"][2]["depends_on"] = ["B1", "B2", "C"]
        self.save(state, event="split", reason="将同一交付拆成两个检查点")
        self.assertEqual(self.metrics()["total_weight"], 100)

    def test_parallel_estimate_respects_capacity(self):
        state = self.initialize()
        self.verified(state, "A")
        self.save(state)
        self.assertEqual(self.metrics()["remaining_minutes"], [110, 165])
        state = self.read()
        state["execution"].update(capacity=2, capacity_basis="确有两名已授权执行者、无共享资源冲突")
        self.save(state)
        self.assertEqual(self.metrics()["remaining_minutes"], [80, 120])

    def test_missing_estimate_and_open_wait_do_not_fabricate_delivery_time(self):
        state = self.initialize()
        state["tasks"][0]["remaining_minutes"] = None
        state["attention"] = [{"id": "Q1", "kind": "input", "status": "open", "question": "请提供来源入口",
                                "why": "当前资料缺少来源", "task_ids": ["A"], "if_deferred": "A 等待；检查其他资料"}]
        self.save(state)
        metrics = self.metrics()
        self.assertIsNone(metrics["remaining_minutes"])
        self.assertEqual(metrics["delivery_time"], "depends_on_wait")

    def test_stale_revision_does_not_overwrite_state_and_preserves_candidate_report(self):
        state = self.initialize()
        old = copy.deepcopy(state)
        state["handoff"]["next_action"] = "先核对主线接口"
        self.save(state)
        old["handoff"]["next_action"] = "不应覆盖"
        self.save(old, success=False)
        self.assertEqual(self.read()["handoff"]["next_action"], "先核对主线接口")
        self.assertTrue(list((self.root / ".project-guide/reports").glob("rejected-*.json")))

    def test_takeover_requires_basis_and_fences_old_owner(self):
        old = self.initialize()
        self.call("claim", "--owner", "session-b", "--expected-revision", "1", success=False)
        self.call("claim", "--owner", "session-b", "--expected-revision", "1", "--basis", "host-ended",
                  "--evidence", "宿主已报告旧会话结束，成果写入进程已停止")
        self.assertEqual(self.read()["coordinator"]["generation"], 2)
        self.save(old, success=False)
        self.assertEqual(self.read()["coordinator"]["id"], "session-b")

    def test_release_and_claim_support_normal_handoff(self):
        state = self.initialize()
        self.call("release", "--owner", "session-a", "--generation", "1", "--expected-revision", "1",
                  "--reason", "本轮已结束，交由下个会话")
        state = self.read()
        self.call("claim", "--owner", "session-b", "--expected-revision", str(state["revision"]))
        self.assertEqual(self.read()["coordinator"]["generation"], 2)

    def test_saved_running_signal_is_always_a_snapshot(self):
        state = self.initialize()
        state["execution"].update(state="running", source="宿主进程检查", observed_at="2026-10-22T12:00:00+00:00")
        self.save(state)
        text = self.call("card").stdout
        self.assertIn("快照", text)
        self.assertIn("待核实", text)
        self.assertIn("2026-10-22", text)

    def test_unquantified_scope_keeps_the_percent_unknown(self):
        state = self.initialize()
        state["project"]["scope_status"] = "unquantified"
        state["plan_version"] = 2
        self.save(state, event="scope", reason="先探索未明的接入范围")
        self.assertIsNone(self.metrics()["percent"])

    def test_decision_requires_implications_and_a_recommendation(self):
        state = self.initialize()
        state["attention"] = [{"id": "Q1", "kind": "decision", "status": "open", "question": "扩大课程吗",
                                "why": "会改变范围", "task_ids": ["C"], "if_deferred": "保持现有三课"}]
        self.save(state, success=False)

    def test_concurrent_saves_have_one_winner(self):
        state = self.initialize()
        candidate = self.root / "race.json"
        candidate.write_text(json.dumps(state))
        command = [sys.executable, str(SCRIPT), "--project", str(self.root), "save", "--from", str(candidate),
                   "--owner", "session-a", "--generation", "1", "--expected-revision", "1",
                   "--event", "progress", "--reason", "并发检查"]
        processes = [subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        results = [p.communicate() for p in processes]
        self.assertEqual(sorted(p.returncode for p in processes), [0, 2], str(results))
        self.assertEqual(self.read()["revision"], 2)

    def test_corrupt_state_is_not_silently_overwritten(self):
        self.initialize()
        (self.root / ".project-guide/project-state.json").write_text("{broken")
        self.call("status", success=False)
        self.assertTrue((self.root / ".project-guide/project-state.previous.json").exists())

    def test_report_does_not_change_authoritative_state(self):
        self.initialize()
        report = self.root / "report.json"
        report.write_text(json.dumps({"task_id": "A", "finding": "有新证据"}))
        self.call("report", "--from", str(report), "--author", "worker-b")
        self.assertEqual(self.read()["revision"], 1)
        self.assertEqual(len(list((self.root / ".project-guide/reports").glob("report-*.json"))), 1)

    def test_changed_evidence_does_not_prevent_handoff_or_invent_rework_duration(self):
        state = self.initialize()
        self.verified(state, "A")
        self.save(state)
        (self.root / "A.txt").write_text("接手前成果已改变")
        self.assertIsNone(self.metrics()["remaining_minutes"])
        self.call("claim", "--owner", "session-b", "--expected-revision", "2", "--basis", "host-ended",
                  "--evidence", "原协调会话已结束，先接手核对变化")
        self.assertEqual(self.read()["coordinator"]["id"], "session-b")
        self.assertEqual(self.metrics()["percent"], 0)

    def test_rounding_cannot_show_100_before_all_delivery_conditions_pass(self):
        state = self.initialize()
        state["tasks"][0]["weight"] = 99997
        for leaf in state["tasks"][1:]:
            leaf["weight"] = 1
        state["plan_version"] = 2
        self.verified(state, "A")
        self.save(state, event="scope", reason="测试极不均匀的实际交付权重")
        self.assertLess(self.metrics()["percent"], 100)
        self.assertFalse(self.metrics()["all_verified"])

    def test_releasing_coordination_does_not_assert_workers_have_stopped(self):
        state = self.initialize()
        state["execution"].update(state="running", source="实际后台执行器", observed_at="2026-10-22T12:00:00+00:00")
        self.save(state)
        self.call("release", "--owner", "session-a", "--generation", "1", "--expected-revision", "2",
                  "--reason", "仅释放状态协调职责")
        self.assertNotEqual(self.read()["execution"]["state"], "stopped")

    def test_part_summary_includes_remaining_work_without_external_wait(self):
        state = self.initialize()
        self.verified(state, "A")
        state["tasks"][1]["part"] = "练习流程"
        state["tasks"][3]["part"] = "练习流程"
        state["plan_version"] = 2
        self.save(state, event="scope", reason="汇总流程交付为同一部分")
        self.assertEqual(self.metrics()["parts"]["练习流程"].get("remaining_minutes"), [80, 120])

    def test_human_blocked_work_is_not_offered_as_ready(self):
        state = self.initialize()
        state["attention"] = [{"id": "Q1", "kind": "input", "status": "open", "question": "请提供来源",
                                "why": "素材必须来自约定来源", "task_ids": ["A"], "if_deferred": "A 等待"}]
        self.save(state)
        self.assertNotIn("A", self.metrics()["ready_task_ids"])

    def test_optional_decision_does_not_delay_current_delivery(self):
        state = self.initialize()
        state["attention"] = [{"id": "Q1", "kind": "decision", "status": "open", "blocking": False,
                                "question": "以后扩课吗", "why": "后续覆盖选择", "task_ids": ["C"],
                                "if_deferred": "继续原三课", "recommendation": "本轮先交三课", "criterion": "按试用优先级",
                                "options": [{"label": name, "benefit": "更早试用" if index == 0 else "更多覆盖",
                                             "cost": "覆盖少" if index == 0 else "投入增加", "risk": "代表性有限",
                                             "reversibility": "后续可调整"} for index, name in enumerate(["三课", "扩课"])]}]
        self.save(state)
        self.assertEqual(self.metrics()["delivery_time"], "range_only")
        self.assertEqual(self.metrics()["open_attention_ids"], [])

    def test_stale_task_row_does_not_keep_the_old_zero_remaining_time(self):
        state = self.initialize()
        self.verified(state, "A")
        self.save(state)
        (self.root / "A.txt").write_text("成果已被替换，返工未知")
        self.call("render")
        rows = (self.root / ".project-guide/dashboard.md").read_text().splitlines()
        row = next(line for line in rows if line.startswith("| A ·"))
        self.assertIn("暂无法可靠估计", row)

    def test_estimate_bounds_use_one_resource_plan_and_cannot_reverse(self):
        state = plan()
        state["execution"].update(capacity=2, capacity_basis="两个可交换执行者")
        inputs = [("A", 19, 19, []), ("B", 16, 18, []), ("C", 2, 8, []), ("D", 24, 30, []),
                  ("E", 7, 14, ["B", "D"]), ("F", 2, 7, []), ("G", 9, 15, ["A"]), ("H", 29, 29, ["F", "G"])]
        state["tasks"] = [task(key, 1, deps, {"low": lo, "high": hi, "basis": "独立审阅复现输入"})
                          for key, lo, hi, deps in inputs]
        self.seed.write_text(json.dumps(state))
        self.initialize()
        interval = self.metrics()["remaining_minutes"]
        self.assertLessEqual(interval[0], interval[1])
        # Upper plan: slot1 A,D,E; slot2 B,C,F,G,H. Reusing those
        # sequences at the low durations finishes at max(50,58)=58.
        self.assertEqual(interval, [58, 77])

    def test_completed_card_does_not_imply_delivery_conditions_are_still_unmet(self):
        state = self.initialize()
        for key in ("A", "B", "C", "D"):
            self.verified(state, key)
        state["execution"].update(state="stopped", source="全部交付已核验", observed_at="2026-10-22T12:00:00+00:00")
        state["handoff"]["next_action"] = "已交付，无剩余必要工作"
        self.save(state)
        self.assertTrue(self.metrics()["all_verified"])
        self.assertIn("无未完成事项", self.call("card").stdout)

    def test_fyi_does_not_create_a_deferred_human_decision(self):
        state = self.initialize()
        state["attention"] = [{"id":"I1", "kind":"info", "status":"open", "blocking":False,
                                "question":"已按现有授权完成技术选择", "why":"仅供知晓，无需作选择",
                                "task_ids":["A"], "if_deferred":"AI继续当前工作"}]
        self.save(state)
        view = (self.root / ".project-guide/dashboard.md").read_text()
        self.assertNotIn("可稍后决定", view)
        self.assertEqual(self.metrics()["open_attention_ids"], [])


if __name__ == "__main__":
    unittest.main()
