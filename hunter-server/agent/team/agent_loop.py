"""AgentLoop — POLL→PROCESS→THINK→ACT 循环引擎，驱动每个 Agent 的运行"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime

from agent.team.protocol import (
    InterAgentMessage,
    MSG_TASK_RESULT,
    MSG_ANALYSIS_RESULT,
    MSG_ACK,
)

# ─── OutstandingTask ──────────────────────────────────────────────

@dataclass
class OutstandingTask:
    task_id: str
    target_agent: str
    instruction: str
    status: str = "PENDING"
    sent_at: datetime = field(default_factory=datetime.now)
    timeout: float = 300


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
        self._pending_inbox: list[InterAgentMessage] = []

    # ── 主循环 ────────────────────────────────────────────────

    def run(self):
        while not self._should_stop():
            self._phase_poll()
            self._phase_process()
            self._phase_think()
            self._phase_act()
            time.sleep(self.poll_interval)

    # ── Phase 1: POLL ─────────────────────────────────────────

    def _phase_poll(self):
        msgs = self.agent.drain_inbox()
        for msg in msgs:
            if msg.msg_type in (MSG_TASK_RESULT, MSG_ANALYSIS_RESULT, MSG_ACK):
                self._match_reply(msg)
            else:
                self._pending_inbox.append(msg)

    def _match_reply(self, msg: InterAgentMessage):
        reply_to = msg.reply_to
        if reply_to and reply_to in self.outstanding_tasks:
            self.outstanding_tasks[reply_to].status = "COMPLETED"

    # ── Phase 2: PROCESS ──────────────────────────────────────

    def _phase_process(self):
        now = datetime.now()
        for task_id, task in list(self.outstanding_tasks.items()):
            if task.status != "COMPLETED" and (now - task.sent_at).total_seconds() > task.timeout:
                task.status = "TIMEOUT"
                self.blackboard.add_activity(
                    f"任务 {task_id[:8]} (→{task.target_agent}) 超时"
                )
        self.agent.update_my_status("busy")

    # ── Phase 3: THINK ────────────────────────────────────────

    def _phase_think(self):
        context = {
            "mission": self.blackboard.read("mission"),
            "outstanding_tasks": self._format_outstanding_tasks(),
            "new_inbox": self._summarize_inbox(),
            "blackboard_summary": self.blackboard.get_summary(),
            "team_status": self.comm_bus.get_team_status(),
            "history": [],
        }
        decision = self.agent.decide(context)
        self._current_decision = decision

    # ── Phase 4: ACT ──────────────────────────────────────────

    def _phase_act(self):
        decision = getattr(self, "_current_decision", None)
        if not decision:
            return

        dtype = decision.get("type", "")

        if dtype == "delegate":
            msg = self.agent.send_msg(
                to=decision["target"],
                msg_type="delegation",
                content=decision["content"],
                task_id=decision.get("task_id"),
            )
            self.outstanding_tasks[msg.msg_id] = OutstandingTask(
                task_id=msg.msg_id,
                target_agent=decision["target"],
                instruction=decision["content"],
            )
            self.blackboard.add_activity(
                f"{self.agent.AGENT_ID} → {decision['target']}: {decision['content'][:80]}"
            )

        elif dtype == "execute_local":
            action = decision.get("action", "")
            command = decision.get("command", "")
            if action == "shell" and hasattr(self.agent, "execute_local"):
                self.agent.execute_local(command)

        elif dtype == "wait":
            pass

        elif dtype == "complete":
            self._result = decision
            self.mission_complete.set()
            self.agent.update_my_status("idle")

        self._pending_inbox.clear()

    # ── 辅助 ──────────────────────────────────────────────────

    def _format_outstanding_tasks(self) -> str:
        if not self.outstanding_tasks:
            return "(无)"
        lines = []
        for task_id, task in self.outstanding_tasks.items():
            elapsed = (datetime.now() - task.sent_at).total_seconds()
            icon = {"PENDING": "⏳", "COMPLETED": "✅", "TIMEOUT": "⏰"}.get(task.status, "?")
            lines.append(
                f"{icon} {task_id[:8]}: →{task.target_agent} "
                f"({elapsed:.0f}s) {task.instruction[:60]}"
            )
        return "\n".join(lines)

    def _summarize_inbox(self) -> str:
        if not self._pending_inbox:
            return "(无)"
        lines = []
        for msg in self._pending_inbox[-5:]:
            lines.append(f"来自 {msg.from_agent}: {msg.content[:120]}")
        return "\n".join(lines)

    def _should_stop(self) -> bool:
        return self._stop_flag.is_set() or self.mission_complete.is_set()

    # ── 外部控制 ──────────────────────────────────────────────

    def stop(self):
        self._stop_flag.set()

    def get_result(self) -> dict:
        return self._result
