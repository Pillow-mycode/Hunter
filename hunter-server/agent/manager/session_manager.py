import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, List
from queue import Queue

from agent.pojo.leader_config import AttackLeaderConfig
from agent.smart_brain.attack_leader import AttackLeader
from agent.system.system_command import write_to_logs

"""
会话管理器
负责多用户并发管理
"""


@dataclass
class Session:
    """会话对象"""
    session_id: str
    leader: AttackLeader
    status: str = "pending"  # pending / running / completed / failed
    result: Optional[dict] = None
    error: Optional[str] = None
    progress_queue: Queue = field(default_factory=Queue)
    pending_confirm: Optional[dict] = None
    pending_input: Optional[str] = None
    confirm_response: Optional[bool] = None
    input_response: Optional[str] = None
    confirm_event: threading.Event = field(default_factory=threading.Event)
    input_event: threading.Event = field(default_factory=threading.Event)


class SessionManager:
    """会话管理器"""

    def __init__(self, max_concurrent: int = 5):
        self.sessions: Dict[str, Session] = {}
        self.lock = threading.Lock()
        self.max_concurrent = max_concurrent

    def create_session(self, user_request: str) -> str:
        """
        创建新会话

        Args:
            user_request: 用户请求

        Returns:
            session_id: 会话ID
        """
        with self.lock:
            active_count = sum(1 for s in self.sessions.values() if s.status == "running")
            if active_count >= self.max_concurrent:
                raise Exception(f"达到最大并发数 ({self.max_concurrent})")

        session_id = str(uuid.uuid4())

        # 创建独立的渗透专家实例
        config = AttackLeaderConfig()
        leader = AttackLeader(config)

        session = Session(
            session_id=session_id,
            leader=leader
        )

        # 设置回调
        leader.on_progress = lambda t, d: self._on_progress(session_id, t, d)
        leader.on_need_confirm = lambda t, m: self._on_need_confirm(session_id, t, m)
        leader.on_need_input = lambda p: self._on_need_input(session_id, p)

        with self.lock:
            self.sessions[session_id] = session

        # 启动执行线程
        thread = threading.Thread(
            target=self._run_session,
            args=(session_id, user_request),
            daemon=True
        )
        thread.start()

        write_to_logs(f"会话管理器: 创建会话 {session_id}")
        return session_id

    def _run_session(self, session_id: str, user_request: str):
        """执行会话"""
        session = self.sessions.get(session_id)
        if not session:
            return

        session.status = "running"
        write_to_logs(f"会话管理器: 开始执行会话 {session_id}")

        try:
            result = session.leader.run(user_request)
            session.status = "completed"
            session.result = result
            write_to_logs(f"会话管理器: 会话完成 {session_id}")
        except Exception as e:
            session.status = "failed"
            session.error = str(e)
            write_to_logs(f"会话管理器: 会话失败 {session_id} - {e}")

        # 发送完成通知
        session.progress_queue.put({
            "type": "session_complete",
            "status": session.status,
            "result": session.result,
            "error": session.error
        })

    def _on_progress(self, session_id: str, event_type: str, data: dict):
        """进度回调"""
        session = self.sessions.get(session_id)
        if session:
            session.progress_queue.put({
                "type": event_type,
                "data": data
            })

    def _on_need_confirm(self, session_id: str, task: dict, message: str) -> bool:
        """确认回调"""
        session = self.sessions.get(session_id)
        if not session:
            return False

        # 设置待确认状态
        session.pending_confirm = {
            "task": task,
            "message": message
        }
        session.confirm_event.clear()

        # 发送确认请求
        session.progress_queue.put({
            "type": "need_confirm",
            "task": task,
            "message": message
        })

        # 等待用户响应
        session.confirm_event.wait()

        # 获取响应
        response = session.confirm_response
        session.pending_confirm = None
        session.confirm_response = None

        return response if response is not None else False

    def _on_need_input(self, session_id: str, prompt: str) -> Optional[str]:
        """输入回调"""
        session = self.sessions.get(session_id)
        if not session:
            return None

        # 设置待输入状态
        session.pending_input = prompt
        session.input_event.clear()

        # 发送输入请求
        session.progress_queue.put({
            "type": "need_input",
            "prompt": prompt
        })

        # 等待用户响应
        session.input_event.wait()

        # 获取响应
        response = session.input_response
        session.pending_input = None
        session.input_response = None

        return response

    def respond_confirm(self, session_id: str, confirmed: bool):
        """响应确认请求"""
        session = self.sessions.get(session_id)
        if session and session.pending_confirm:
            session.confirm_response = confirmed
            session.confirm_event.set()
            write_to_logs(f"会话管理器: 用户确认响应 {session_id} - {confirmed}")

    def respond_input(self, session_id: str, user_input: Optional[str]):
        """响应输入请求"""
        session = self.sessions.get(session_id)
        if session and session.pending_input:
            session.input_response = user_input
            session.input_event.set()
            write_to_logs(f"会话管理器: 用户输入响应 {session_id}")

    def get_session_status(self, session_id: str) -> Optional[dict]:
        """获取会话状态"""
        session = self.sessions.get(session_id)
        if not session:
            return None

        return {
            "session_id": session_id,
            "status": session.status,
            "result": session.result,
            "error": session.error,
            "pending_confirm": session.pending_confirm,
            "pending_input": session.pending_input
        }

    def get_progress(self, session_id: str, timeout: float = 1.0) -> Optional[dict]:
        """获取进度消息"""
        session = self.sessions.get(session_id)
        if not session:
            return None

        try:
            return session.progress_queue.get(timeout=timeout)
        except:
            return None

    def get_all_progress(self, session_id: str) -> List[dict]:
        """获取所有进度消息"""
        session = self.sessions.get(session_id)
        if not session:
            return []

        messages = []
        while not session.progress_queue.empty():
            try:
                messages.append(session.progress_queue.get_nowait())
            except:
                break
        return messages

    def cancel_session(self, session_id: str):
        """取消会话"""
        session = self.sessions.get(session_id)
        if session:
            session.status = "cancelled"
            # 释放等待的事件
            session.confirm_response = False
            session.confirm_event.set()
            session.input_response = None
            session.input_event.set()
            write_to_logs(f"会话管理器: 取消会话 {session_id}")

    def remove_session(self, session_id: str):
        """移除会话"""
        with self.lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                write_to_logs(f"会话管理器: 移除会话 {session_id}")

    def list_sessions(self) -> List[dict]:
        """列出所有会话"""
        with self.lock:
            return [
                {
                    "session_id": sid,
                    "status": s.status
                }
                for sid, s in self.sessions.items()
            ]


# 全局会话管理器实例
session_manager = SessionManager()
