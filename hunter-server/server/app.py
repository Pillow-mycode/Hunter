"""
Hunter Server - FastAPI 服务端
部署在 Kali Linux 上，执行渗透测试任务

Version 3.0 - 持久化存储架构
- 使用 SQLite 持久化存储会话和消息
- 所有消息按顺序存储，确保历史完整性
- 服务端重启后数据不丢失
- 客户端只负责渲染，不存储数据
"""
import os
import sys
import json
import asyncio
import uuid
from datetime import datetime
from typing import Dict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 切换工作目录到项目根目录（确保相对路径正确）
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(override=True)

from agent.pojo.leader_config import AttackLeaderConfig
from agent.smart_brain.attack_leader import AttackLeader
from agent.manager.database_manager import get_database, DatabaseManager


# ============== 数据模型 ==============

class SessionRequest(BaseModel):
    """会话请求"""
    name: Optional[str] = None  # 会话名称（可选）


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    status: str
    message: str


class MessageRequest(BaseModel):
    """消息请求（通过 WebSocket 发送）"""
    message: str  # 用户的渗透测试需求


# ============== 会话管理器 ==============

class SessionManager:
    """
    会话管理器 - 使用 SQLite 持久化存储

    职责：
    1. 管理会话生命周期
    2. 存储所有消息（按顺序）
    3. 管理 WebSocket 连接
    4. 管理 AttackLeader 实例
    """

    def __init__(self):
        self.db: DatabaseManager = get_database()
        self.websockets: Dict[str, WebSocket] = {}  # session_id -> websocket（运行时）
        self.input_queues: Dict[str, asyncio.Queue] = {}  # session_id -> input queue（运行时）
        self.leader_instances: Dict[str, AttackLeader] = {}  # session_id -> AttackLeader 实例（运行时）
        self.task_cancelled: Dict[str, bool] = {}  # session_id -> is current task cancelled（运行时）

    def create_session(self, name: Optional[str] = None) -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())[:8]
        session_name = name or f"会话 {session_id}"

        # 持久化到数据库
        self.db.create_session(session_id, session_name)

        # 初始化运行时状态
        self.input_queues[session_id] = asyncio.Queue()
        self.task_cancelled[session_id] = False

        print(f"[会话创建] ID: {session_id}, 名称: {session_name}")
        return session_id

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话信息"""
        session = self.db.get_session(session_id)
        if session:
            # 确保运行时状态存在
            if session_id not in self.input_queues:
                self.input_queues[session_id] = asyncio.Queue()
            if session_id not in self.task_cancelled:
                self.task_cancelled[session_id] = False
        return session

    def list_sessions(self) -> list:
        """列出所有会话"""
        return self.db.list_sessions()

    def update_session_status(self, session_id: str, status: str):
        """更新会话状态"""
        self.db.update_session_status(session_id, status)

    def delete_session(self, session_id: str):
        """删除会话"""
        # 清理运行时状态
        self.websockets.pop(session_id, None)
        self.input_queues.pop(session_id, None)
        self.leader_instances.pop(session_id, None)
        self.task_cancelled.pop(session_id, None)

        # 从数据库删除
        self.db.delete_session(session_id)
        print(f"[会话删除] ID: {session_id}")

    def cancel_current_task(self, session_id: str) -> bool:
        """取消当前任务"""
        session = self.db.get_session(session_id)
        if session and session["status"] == "running":
            self.task_cancelled[session_id] = True
            self.db.update_session_status(session_id, "idle")
            # 记录取消消息
            self.db.add_message(session_id, "system", "任务已被用户取消")
            return True
        return False

    def get_or_create_leader(self, session_id: str) -> AttackLeader:
        """获取或创建 AttackLeader 实例"""
        if session_id not in self.leader_instances:
            config = AttackLeaderConfig()
            leader = AttackLeader(config)

            # 从数据库恢复对话历史到 Leader
            history = self.db.get_conversation_history(session_id)
            if history:
                leader.context["conversation_history"] = history
                print(f"[Leader] 恢复会话 {session_id} 的对话历史: {len(history)} 条")

            self.leader_instances[session_id] = leader

        return self.leader_instances[session_id]

    # ==================== 消息存储 ====================

    def add_message(self, session_id: str, msg_type: str, content: str, metadata: dict = None):
        """
        添加消息到会话（持久化）

        Args:
            session_id: 会话ID
            msg_type: 消息类型 (user, progress, command, assistant, confirm, input, file, error, system)
            content: 消息内容
            metadata: 额外元数据
        """
        self.db.add_message(session_id, msg_type, content, metadata)

    def get_messages(self, session_id: str) -> list:
        """获取会话的所有消息（按顺序）"""
        return self.db.get_messages(session_id)

    def get_conversation_history(self, session_id: str) -> list:
        """获取对话历史（用于 LLM）"""
        return self.db.get_conversation_history(session_id)

    # ==================== WebSocket 通信 ====================

    async def send_message(self, session_id: str, msg_type: str, data: dict):
        """向客户端发送消息"""
        ws = self.websockets.get(session_id)
        if ws:
            try:
                await ws.send_json({
                    "type": msg_type,
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                    "data": data
                })
                print(f"[WebSocket] 发送消息: {msg_type} -> {session_id}")
            except Exception as e:
                print(f"[WebSocket] 发送消息失败: {e}")

    async def send_and_store(self, session_id: str, ws_type: str, db_type: str,
                             content: str, data: dict = None, metadata: dict = None):
        """
        发送消息到客户端并存储到数据库

        Args:
            session_id: 会话ID
            ws_type: WebSocket 消息类型
            db_type: 数据库消息类型
            content: 消息内容
            data: WebSocket 消息数据（可选，默认使用 content）
            metadata: 数据库元数据（可选）
        """
        # 存储到数据库
        self.db.add_message(session_id, db_type, content, metadata)

        # 发送到客户端
        ws_data = data if data is not None else {"message": content}
        await self.send_message(session_id, ws_type, ws_data)

    async def wait_for_input(self, session_id: str, prompt: str, timeout: float = 300) -> Optional[str]:
        """等待用户输入"""
        # 存储输入请求
        self.db.add_message(session_id, "input_request", prompt)

        # 更新状态
        self.db.update_session_status(session_id, "need_input")

        # 发送到客户端
        await self.send_message(session_id, "need_input", {"prompt": prompt})

        try:
            queue = self.input_queues.get(session_id)
            if queue:
                result = await asyncio.wait_for(queue.get(), timeout=timeout)

                # 存储用户输入
                self.db.add_message(session_id, "input_response", result)
                self.db.update_session_status(session_id, "running")

                return result
        except asyncio.TimeoutError:
            self.db.add_message(session_id, "system", "输入超时")
            return None
        return None

    async def wait_for_confirm(self, session_id: str, task: dict, message: str, timeout: float = 300) -> bool:
        """等待用户确认"""
        # 存储确认请求
        self.db.add_message(session_id, "confirm_request", message, {"task": task})

        # 更新状态
        self.db.update_session_status(session_id, "need_confirm")

        # 发送到客户端
        await self.send_message(session_id, "need_confirm", {
            "message": message,
            "task": task
        })

        try:
            queue = self.input_queues.get(session_id)
            if queue:
                result = await asyncio.wait_for(queue.get(), timeout=timeout)
                confirmed = result.lower() in ["y", "yes", "是", "true", "1"]

                # 存储用户确认结果
                self.db.add_message(session_id, "confirm_response",
                                   "确认执行" if confirmed else "取消执行")
                self.db.update_session_status(session_id, "running" if confirmed else "idle")

                return confirmed
        except asyncio.TimeoutError:
            self.db.add_message(session_id, "system", "确认超时，已取消")
            return False
        return False


# ============== 全局实例 ==============

session_manager = SessionManager()


# ============== FastAPI 应用 ==============

BANNER = r"""
██╗  ██╗██╗   ██╗███╗   ██╗████████╗███████╗██████╗
██║  ██║██║   ██║████╗  ██║╚══██╔══╝██╔════╝██╔══██╗
███████║██║   ██║██╔██╗ ██║   ██║   █████╗  ██████╔╝
██╔══██║██║   ██║██║╚██╗██║   ██║   ██╔══╝  ██╔══██╗
██║  ██║╚██████╔╝██║ ╚████║   ██║   ███████╗██║  ██║
╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
        LLM-Driven Automated Penetration Testing
                    Version 3.0.0
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    db = get_database()
    stats = db.get_stats()

    print(BANNER)
    print("=" * 55)
    print("  Server starting on http://0.0.0.0:8000")
    print("  WebSocket endpoint: ws://0.0.0.0:8000/ws/{session_id}")
    print("-" * 55)
    print(f"  Database: {stats['db_path']}")
    print(f"  Sessions: {stats['session_count']}, Messages: {stats['message_count']}")
    print("=" * 55)
    yield
    print("\nHunter Server 关闭...")
    db.close()


app = FastAPI(
    title="Hunter Server",
    description="LLM 驱动的自动化渗透测试服务 - 持久化存储版",
    version="3.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== HTTP 接口 ==============

@app.get("/")
async def root():
    """服务状态"""
    db = get_database()
    stats = db.get_stats()
    return {
        "service": "Hunter Server",
        "status": "running",
        "version": "3.0.0",
        "mode": "persistent",
        "stats": stats
    }


@app.post("/session", response_model=SessionResponse)
async def create_session(request: SessionRequest = None):
    """创建新会话"""
    name = request.name if request else None
    session_id = session_manager.create_session(name)

    return SessionResponse(
        session_id=session_id,
        status="created",
        message=f"会话已创建，请通过 WebSocket 连接 /ws/{session_id}"
    )


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取会话状态"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@app.get("/session/{session_id}/messages")
async def get_session_messages(session_id: str):
    """
    获取会话的所有消息（按顺序）

    返回完整的消息历史，客户端根据此数据渲染界面
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = session_manager.get_messages(session_id)
    return {
        "session_id": session_id,
        "session_name": session.get("name", ""),
        "session_status": session.get("status", "idle"),
        "messages": messages
    }


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    session_manager.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


@app.get("/sessions")
async def list_sessions():
    """列出所有会话"""
    return session_manager.list_sessions()


@app.post("/session/{session_id}/cancel")
async def cancel_session_task(session_id: str):
    """取消会话中当前正在执行的任务"""
    if session_manager.cancel_current_task(session_id):
        return {"status": "cancelled", "session_id": session_id}
    raise HTTPException(status_code=400, detail="无法取消任务")


# ============== WebSocket 接口 ==============

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 连接处理 - 会话模式"""
    session = session_manager.get_session(session_id)
    if not session:
        await websocket.accept()
        await websocket.close(code=4004, reason="会话不存在")
        return

    await websocket.accept()
    session_manager.websockets[session_id] = websocket

    try:
        # 发送连接成功消息
        await session_manager.send_message(session_id, "connected", {
            "message": "已连接到会话",
            "session_id": session_id,
            "session_name": session["name"]
        })

        # 监听客户端消息
        while True:
            try:
                data = await websocket.receive_json()
            except RuntimeError as e:
                print(f"[WebSocket] 连接已断开: {session_id} - {e}")
                break

            msg_type = data.get("type")

            if msg_type == "message":
                # 用户发送新消息
                user_message = data.get("data", {}).get("message", "")
                if user_message:
                    # 重置取消标志
                    session_manager.task_cancelled[session_id] = False

                    # 存储用户消息到数据库
                    session_manager.add_message(session_id, "user", user_message)

                    # 启动任务执行
                    asyncio.create_task(run_session_task(session_id, user_message))

            elif msg_type == "input":
                # 用户输入（响应 need_input）
                user_input = data.get("data", {}).get("input", "")
                queue = session_manager.input_queues.get(session_id)
                if queue:
                    await queue.put(user_input)

            elif msg_type == "cancel":
                # 取消当前任务
                session_manager.cancel_current_task(session_id)
                await session_manager.send_message(session_id, "cancelled", {
                    "message": "任务已取消"
                })

    except WebSocketDisconnect:
        print(f"客户端断开连接: {session_id}")
    except Exception as e:
        print(f"[WebSocket] 异常: {session_id} - {e}")
    finally:
        session_manager.websockets.pop(session_id, None)


async def run_session_task(session_id: str, command: str):
    """执行会话中的任务"""
    session = session_manager.get_session(session_id)
    if not session:
        return

    session_manager.update_session_status(session_id, "running")
    await session_manager.send_message(session_id, "status", {"status": "running"})
    await session_manager.send_message(session_id, "task_started", {
        "message": "开始执行任务",
        "command": command
    })

    main_loop = asyncio.get_running_loop()

    try:
        print(f"[执行任务] 会话 {session_id}, 命令: {command}")

        leader = session_manager.get_or_create_leader(session_id)

        def is_cancelled():
            return session_manager.task_cancelled.get(session_id, False)

        # 回调函数 - 存储并发送进度消息
        def on_progress(message: str):
            if is_cancelled():
                raise InterruptedError("任务已取消")

            # 判断消息类型并存储
            if message.startswith('[武器大师] 正在运行:'):
                cmd = message[len('[武器大师] 正在运行:'):].strip()
                # 存储命令消息
                future = asyncio.run_coroutine_threadsafe(
                    store_and_send_progress(session_id, "command", cmd, message),
                    main_loop
                )
                future.result(timeout=5)
            elif message.startswith('[回复]'):
                reply = message[4:].strip()
                # 存储中间回复
                future = asyncio.run_coroutine_threadsafe(
                    store_and_send_progress(session_id, "reply", reply, message),
                    main_loop
                )
                future.result(timeout=5)
            elif message.startswith('[文件]'):
                file_info = message[4:].strip()
                # 存储文件通知
                future = asyncio.run_coroutine_threadsafe(
                    store_and_send_progress(session_id, "file", file_info, message),
                    main_loop
                )
                future.result(timeout=5)
            else:
                # 普通进度消息
                future = asyncio.run_coroutine_threadsafe(
                    store_and_send_progress(session_id, "progress", message, message),
                    main_loop
                )
                future.result(timeout=5)

        def on_need_input(prompt: str) -> Optional[str]:
            if is_cancelled():
                return None
            future = asyncio.run_coroutine_threadsafe(
                session_manager.wait_for_input(session_id, prompt),
                main_loop
            )
            return future.result(timeout=300)

        def on_need_confirm(task_info: dict, message: str) -> bool:
            if is_cancelled():
                return False
            future = asyncio.run_coroutine_threadsafe(
                session_manager.wait_for_confirm(session_id, task_info, message),
                main_loop
            )
            return future.result(timeout=300)

        leader.on_progress = on_progress
        leader.on_need_input = on_need_input
        leader.on_need_confirm = on_need_confirm

        # 在线程池中执行
        result = await main_loop.run_in_executor(
            None,
            leader.run,
            command
        )

        if is_cancelled():
            return

        # 存储最终结果
        if result and result.get("report"):
            report = result["report"]
            # 构建完整的回复内容
            reply_content = build_reply_content(report)
            # 存储到数据库
            session_manager.add_message(session_id, "assistant", reply_content, {"report": report})

        session_manager.update_session_status(session_id, "idle")

        await session_manager.send_message(session_id, "task_completed", {
            "status": "completed",
            "result": result
        })

        print(f"[任务完成] 会话 {session_id} 任务完成")

    except InterruptedError:
        print(f"[任务取消] 会话 {session_id} 任务已被用户取消")
        session_manager.update_session_status(session_id, "idle")
    except Exception as e:
        session_manager.update_session_status(session_id, "idle")
        # 存储错误消息
        session_manager.add_message(session_id, "error", str(e))
        await session_manager.send_message(session_id, "error", {
            "message": str(e)
        })
        print(f"[任务错误] 会话 {session_id}: {e}")


async def store_and_send_progress(session_id: str, msg_type: str, content: str, raw_message: str):
    """存储并发送进度消息"""
    # 存储到数据库
    session_manager.add_message(session_id, msg_type, content)
    # 发送到客户端
    await session_manager.send_message(session_id, "progress", {"message": raw_message})


def build_reply_content(report: dict) -> str:
    """构建回复内容"""
    parts = []

    if report.get("summary"):
        parts.append(report["summary"])

    if report.get("conclusion"):
        parts.append(f"\n结论: {report['conclusion']}")

    if report.get("recommendations"):
        recs = report["recommendations"]
        if recs:
            parts.append("\n建议:")
            for i, rec in enumerate(recs, 1):
                parts.append(f"  {i}. {rec}")

    return "\n".join(parts) if parts else "任务已完成"


# ============== 启动入口 ==============

if __name__ == "__main__":
    import uvicorn
    print(f"工作目录: {os.getcwd()}")
    print(f"项目根目录: {PROJECT_ROOT}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
