"""AgentLoop — POLL→PROCESS→THINK→ACT 循环引擎，驱动每个 Agent 的运行"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime

# ─── OutstandingTask ──────────────────────────────────────────────

@dataclass
class OutstandingTask:
    task_id: str
    target_agent: str
    instruction: str
    status: str = "PENDING"
    sent_at: datetime = field(default_factory=datetime.now)
    timeout: float = 300
    step_id: str = ""  # PlanStep id，P2 状态机使用


# ─── AgentLoop ────────────────────────────────────────────────────

class AgentLoop(threading.Thread):
    """驱动 Agent 的 POLL→PROCESS→THINK→ACT 核心循环。"""

    def __init__(self, agent, comm_bus, blackboard, poll_interval: float = 0.5):
        super().__init__(daemon=True)
        self.agent = agent
        self.comm_bus = comm_bus
        self.blackboard = blackboard
        self.poll_interval = poll_interval
        self.outstanding_tasks: dict[str, OutstandingTask] = {}
        self.mission_complete = threading.Event()
        self._stop_flag = threading.Event()
        self._result: dict = {}
        self._loop_started = False
        # Let the agent check the stop flag during long-running operations
        self.agent._abort_event = self._stop_flag

    def start(self):
        """幂等启动：如果已启动则跳过"""
        if self._loop_started:
            return
        self._loop_started = True
        super().start()

    # ── 主循环 ────────────────────────────────────────────────

    def run(self):
        while not self._should_stop():
            self._phase_poll()
            self._phase_process()
            self._phase_think()
            self._phase_act()
            # 有待处理任务或收件箱有消息时不睡眠，立即进入下一轮
            has_pending = any(
                t.status == "PENDING"
                for t in self.outstanding_tasks.values()
            ) if self.outstanding_tasks else False
            inbox = self.comm_bus.inboxes.get(self.agent.AGENT_ID)
            has_inbox_msg = not inbox.empty() if inbox else False
            if not has_pending and not has_inbox_msg:
                time.sleep(self.poll_interval)

    # ── Phase 1: POLL ─────────────────────────────────────────

    def _phase_poll(self):
        # Messages are drained and processed by decide() in _phase_think.
        # We only check queue depth here for observability.
        pass

    # ── Phase 2: PROCESS ──────────────────────────────────────

    def _phase_process(self):
        now = datetime.now()
        has_work = False
        for task_id, task in list(self.outstanding_tasks.items()):
            if task.status != "COMPLETED" and (now - task.sent_at).total_seconds() > task.timeout:
                task.status = "TIMEOUT"
                self.blackboard.add_activity(
                    f"任务 {task_id[:8]} (→{task.target_agent}) 超时"
                )
            if task.status == "PENDING":
                has_work = True
        if has_work or self.outstanding_tasks:
            self.agent.update_my_status("busy")

    # ── Phase 3: THINK ────────────────────────────────────────

    def _phase_think(self):
        prev = getattr(self, "_current_decision", {})
        # 上次决策是 wait 且有有效的未完成任务 → 阻塞等新消息到达
        has_pending = any(
            t.status not in ("COMPLETED", "TIMEOUT")
            for t in self.outstanding_tasks.values()
        ) if self.outstanding_tasks else False
        if prev.get("type") == "wait" and has_pending:
            print(f"[AgentLoop] {self.agent.AGENT_ID} 阻塞等待结果... (pending={sum(1 for t in self.outstanding_tasks.values() if t.status not in ('COMPLETED','TIMEOUT'))})")
            self._wait_for_inbox_message(timeout=30.0)
            print(f"[AgentLoop] {self.agent.AGENT_ID} 唤醒，继续决策")

        context = {
            "mission": self.blackboard.read("mission"),
            "outstanding_tasks": self._format_outstanding_tasks(),
            "outstanding_dict": dict(self.outstanding_tasks),  # P3: step_id 匹配
            "blackboard_summary": self.blackboard.get_summary(),
            "team_status": self.comm_bus.get_team_status(),
            "history": [],
        }
        decision = self.agent.decide(context)
        self._current_decision = decision
        # 日志：非 wait 决策打印
        dtype = decision.get("type", "?")
        if dtype != "wait":
            detail = decision.get("content", "") or decision.get("summary", "") or ""
            print(f"[AgentLoop] {self.agent.AGENT_ID} 决策 → {dtype} {detail[:120]}")

    # ── Phase 4: ACT ──────────────────────────────────────────

    def _phase_act(self):
        decision = getattr(self, "_current_decision", None)
        if not decision:
            return

        decisions = decision if isinstance(decision, list) else [decision]

        for d in decisions:
            dtype = d.get("type", "")

            if dtype == "delegate":
                target = d["target"]
                # Map to correct message type based on target agent
                if target.startswith("data_analyst"):
                    msg_type = "analysis_request"
                    ctx_json = None
                elif target.startswith("hawkeye"):
                    msg_type = "delegation"
                    ctx_json = {"output": d["content"]}
                else:
                    msg_type = "delegation"
                    ctx_json = None
                msg = self.agent.send_msg(
                    to=target,
                    msg_type=msg_type,
                    content=d["content"],
                    task_id=d.get("task_id"),
                    context_json=ctx_json,
                )
                self.outstanding_tasks[msg.msg_id] = OutstandingTask(
                    task_id=msg.msg_id,
                    target_agent=d["target"],
                    instruction=d["content"],
                    step_id=d.get("step_id", ""),
                )
                self.blackboard.add_activity(
                    f"{self.agent.AGENT_ID} → {d['target']}: {d['content'][:80]}"
                )

            elif dtype == "execute_local":
                action = d.get("action", "")
                command = d.get("command", "")
                if action == "shell" and hasattr(self.agent, "execute_local"):
                    self.agent.execute_local(command)

            elif dtype == "wait":
                pass

            elif dtype == "complete":
                self._result = d
                self.mission_complete.set()
                self.agent.update_my_status("idle")
                print(f"[AgentLoop] {self.agent.AGENT_ID} 任务完成 → {d.get('summary', '')[:120]}")

    # ── 辅助 ──────────────────────────────────────────────────

    def _format_outstanding_tasks(self) -> str:
        if not self.outstanding_tasks:
            return "(无)"
        lines = []
        for task_id, task in self.outstanding_tasks.items():
            elapsed = (datetime.now() - task.sent_at).total_seconds()
            icon = {"PENDING": "⏳", "COMPLETED": "✅", "TIMEOUT": "⏰"}.get(task.status, "?")
            status_text = {"PENDING": "运行中", "COMPLETED": "已完成", "TIMEOUT": "已超时"}.get(task.status, task.status)
            lines.append(
                f"- [{status_text}] {task_id[:8]}: →{task.target_agent} "
                f"({elapsed:.0f}s) {task.instruction[:100]}"
            )
        return "\n".join(lines)

    def _wait_for_inbox_message(self, timeout: float = 30.0):
        """阻塞等待收件箱有新消息，超时后返回让超时检测有机会运行"""
        import queue
        try:
            inbox = self.comm_bus.inboxes[self.agent.AGENT_ID]
            msg = inbox.get(timeout=timeout)
            # 放回队列，让 decide() 的 drain_inbox() 能正常处理
            inbox.put(msg)
        except queue.Empty:
            pass

    def _should_stop(self) -> bool:
        return self._stop_flag.is_set() or self.mission_complete.is_set()

    # ── 外部控制 ──────────────────────────────────────────────

    def stop(self):
        self._stop_flag.set()

    def get_result(self) -> dict:
        return self._result
