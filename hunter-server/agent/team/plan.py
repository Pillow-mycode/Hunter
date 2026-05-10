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
