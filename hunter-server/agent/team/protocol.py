"""Agent间通信消息协议 — InterAgentMessage 数据结构 + 消息类型常量"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

# ─── Agent identity ────────────────────────────────────────────────

AgentId = Literal["leader", "tool_master", "data_analyst", "hawkeye"]

# ─── 消息类型常量 ──────────────────────────────────────────────────

MSG_DELEGATION = "delegation"
MSG_TASK_RESULT = "task_result"
MSG_QUERY = "query"
MSG_INPUT_ALERT = "input_alert"
MSG_TIMEOUT_ALERT = "timeout_alert"
MSG_PROCESS_STALLED = "process_stalled"
MSG_FINDING_ALERT = "finding_alert"
MSG_ANALYSIS_REQUEST = "analysis_request"
MSG_ANALYSIS_RESULT = "analysis_result"
MSG_HELP_REQUEST = "help_request"
MSG_ACK = "ack"

VALID_MSG_TYPES: frozenset[str] = frozenset({
    MSG_DELEGATION,
    MSG_TASK_RESULT,
    MSG_QUERY,
    MSG_INPUT_ALERT,
    MSG_TIMEOUT_ALERT,
    MSG_PROCESS_STALLED,
    MSG_FINDING_ALERT,
    MSG_ANALYSIS_REQUEST,
    MSG_ANALYSIS_RESULT,
    MSG_HELP_REQUEST,
    MSG_ACK,
})


# ─── InterAgentMessage ─────────────────────────────────────────────

@dataclass
class InterAgentMessage:
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    from_agent: AgentId = "leader"
    to_agent: AgentId = "leader"
    msg_type: str = ""
    content: str = ""
    task_id: Optional[str] = None
    context_json: Optional[dict] = None
    expect_reply: bool = False
    reply_to: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        if self.msg_type and self.msg_type not in VALID_MSG_TYPES:
            raise ValueError(
                f"Invalid msg_type '{self.msg_type}'. Must be one of: "
                f"{', '.join(sorted(VALID_MSG_TYPES))}"
            )

    def to_dict(self) -> dict:
        d = {
            "msg_id": self.msg_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "msg_type": self.msg_type,
            "content": self.content,
            "expect_reply": self.expect_reply,
            "timestamp": self.timestamp,
        }
        if self.task_id is not None:
            d["task_id"] = self.task_id
        if self.context_json is not None:
            d["context_json"] = self.context_json
        if self.reply_to is not None:
            d["reply_to"] = self.reply_to
        return d

    @classmethod
    def from_dict(cls, data: dict) -> InterAgentMessage:
        return cls(
            msg_id=data.get("msg_id", ""),
            from_agent=data.get("from_agent", ""),
            to_agent=data.get("to_agent", ""),
            msg_type=data.get("msg_type", ""),
            content=data.get("content", ""),
            task_id=data.get("task_id"),
            context_json=data.get("context_json"),
            expect_reply=data.get("expect_reply", False),
            reply_to=data.get("reply_to"),
            timestamp=data.get("timestamp", ""),
        )
