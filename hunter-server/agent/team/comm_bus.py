"""CommunicationBus — Agent 间线程安全的消息路由中心"""

import copy
import queue
import threading
import logging
from typing import Optional

from agent.team.protocol import InterAgentMessage
from agent.manager.database_manager import get_database

logger = logging.getLogger(__name__)

class CommunicationBus:
    """线程安全的消息路由中心，支持异步投递和同步等待双模式。"""

    def __init__(self, session_id: str = ""):
        self._session_id = session_id
        self.inboxes: dict[str, queue.Queue] = {}
        self._pending_replies: dict[str, tuple[threading.Event, list]] = {}
        self._lock = threading.Lock()
        self._db = get_database()
        self.on_send = None  # Optional[Callable[[InterAgentMessage], None]]

    # ── Agent 注册 ────────────────────────────────────────────

    def register_agent(self, agent_id: str) -> None:
        """注册新 agent，创建收件箱（幂等）"""
        if agent_id not in self.inboxes:
            self.inboxes[agent_id] = queue.Queue()

    def unregister_agent(self, agent_id: str) -> None:
        """注销 agent，清理收件箱"""
        self.inboxes.pop(agent_id, None)

    # ── 异步发送 ──────────────────────────────────────────────

    def send(self, msg: InterAgentMessage) -> None:
        if msg.to_agent not in self.inboxes:
            raise ValueError(f"Unknown agent: {msg.to_agent}")
        self.inboxes[msg.to_agent].put(msg)
        self._persist(msg)
        if self.on_send:
            self.on_send(msg)

    def drain_inbox(self, agent_id: str) -> list[InterAgentMessage]:
        if agent_id not in self.inboxes:
            return []
        msgs = []
        q = self.inboxes[agent_id]
        while True:
            try:
                msgs.append(q.get_nowait())
            except queue.Empty:
                break
        return msgs

    # ── 同步发送 + 等待回复 ──────────────────────────────────

    def send_and_wait(self, msg: InterAgentMessage, timeout: float = 300) -> InterAgentMessage:
        # Don't mutate caller's message — create a copy with expect_reply set
        msg = copy.deepcopy(msg)
        msg.expect_reply = True
        event = threading.Event()
        result_holder: list[InterAgentMessage] = []

        with self._lock:
            self._pending_replies[msg.msg_id] = (event, result_holder)

        self.send(msg)

        if not event.wait(timeout):
            with self._lock:
                self._pending_replies.pop(msg.msg_id, None)
            raise TimeoutError(
                f"send_and_wait timed out after {timeout}s (msg_id={msg.msg_id})"
            )

        return result_holder[0]

    def reply(self, to_msg_id: str, reply_msg: InterAgentMessage) -> None:
        with self._lock:
            entry = self._pending_replies.pop(to_msg_id, None)

        if entry is not None:
            event, result_holder = entry
            result_holder.append(reply_msg)
            event.set()
        else:
            self.send(reply_msg)

    # ── 广播 ──────────────────────────────────────────────────

    def broadcast(self, msg: InterAgentMessage) -> None:
        self._persist(msg)
        for agent_id in list(self.inboxes.keys()):
            if agent_id == msg.from_agent:
                continue
            self.inboxes[agent_id].put(copy.deepcopy(msg))

    # ── 状态查询 ──────────────────────────────────────────────

    def get_team_status(self) -> dict:
        return {aid: self.inboxes[aid].qsize() for aid in self.inboxes}

    def list_agents(self) -> list[str]:
        return list(self.inboxes.keys())

    # ── 内部 ──────────────────────────────────────────────────

    def _persist(self, msg: InterAgentMessage) -> None:
        try:
            self._db.save_agent_message({
                "session_id": self._session_id,
                "msg_id": msg.msg_id,
                "sender": msg.from_agent,
                "receiver": msg.to_agent,
                "msg_type": msg.msg_type,
                "content": msg.content,
                "context_json": msg.context_json,
                "expect_reply": msg.expect_reply,
                "reply_to": msg.reply_to,
            })
        except Exception:
            logger.debug("Failed to persist agent message", exc_info=True)
