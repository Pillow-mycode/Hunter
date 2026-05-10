import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PlanStep:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    instruction: str = ""
    target_agent: str = "tool_master"
    depends_on: list[str] = field(default_factory=list)
    status: str = "PENDING"
    result_summary: str = ""
    dispatched_to: Optional[str] = None


@dataclass
class Plan:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    goal: str = ""
    complexity: str = "simple"
    steps: list[PlanStep] = field(default_factory=list)
    current_idx: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def next_step(self) -> Optional[PlanStep]:
        for s in self.steps:
            if s.status == "PENDING":
                return s
        return None

    def has_pending(self) -> bool:
        return any(s.status == "PENDING" for s in self.steps)

    def is_exhausted(self) -> bool:
        return all(s.status in ("DONE", "FAILED") for s in self.steps)

    def get_ready_steps(self) -> list:
        """返回所有依赖已满足且状态为 PENDING 的步骤"""
        done_ids = {s.id for s in self.steps if s.status == "DONE"}
        ready = []
        for s in self.steps:
            if s.status != "PENDING":
                continue
            if all(dep in done_ids for dep in s.depends_on):
                ready.append(s)
        return ready

    def find_step(self, step_id: str):
        """按 id 查找步骤"""
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def validate_dag(self) -> bool:
        """Kahn 拓扑排序 — 检测循环依赖和不存在的依赖"""
        step_ids = {s.id for s in self.steps}
        for s in self.steps:
            for dep in s.depends_on:
                if dep not in step_ids:
                    return False
        in_degree = {s.id: len(s.depends_on) for s in self.steps}
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        sorted_count = 0
        while queue:
            sid = queue.pop(0)
            sorted_count += 1
            for s in self.steps:
                if sid in s.depends_on:
                    in_degree[s.id] -= 1
                    if in_degree[s.id] == 0:
                        queue.append(s.id)
        return sorted_count == len(self.steps)
