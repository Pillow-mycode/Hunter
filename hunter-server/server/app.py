"""
Hunter Server - FastAPI 服务端
部署在 Kali Linux 上，执行渗透测试任务

Version 2.0 - 会话模式架构
- 一个会话可以包含多条消息
- WebSocket 连接绑定到会话，而不是任务
- 任务完成后不关闭 WebSocket，等待下一条消息
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
load_dotenv()

from agent.pojo.leader_config import AttackLeaderConfig
from agent.smart_brain.attack_leader import AttackLeader


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


# ============== 会话管理 ==============

class SessionManager:
    """会话管理器 - 管理会话和消息"""

    def __init__(self):
        self.sessions: Dict[str, dict] = {}  # session_id -> session info
        self.websockets: Dict[str, WebSocket] = {}  # session_id -> websocket
        self.input_queues: Dict[str, asyncio.Queue] = {}  # session_id -> input queue
        self.leader_instances: Dict[str, AttackLeader] = {}  # session_id -> AttackLeader 实例
        self.current_tasks: Dict[str, asyncio.Task] = {}  # session_id -> current running task
        self.task_cancelled: Dict[str, bool] = {}  # session_id -> is current task cancelled

    def create_session(self, name: Optional[str] = None) -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())[:8]
        self.sessions[session_id] = {
            "session_id": session_id,
            "name": name or f"会话 {session_id}",
            "status": "idle",  # idle, running, closed
            "created_at": datetime.now().isoformat(),
            "messages": [],  # 会话中的所有消息
            "message_count": 0
        }
        self.input_queues[session_id] = asyncio.Queue()
        self.task_cancelled[session_id] = False
        return session_id

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话信息"""
        return self.sessions.get(session_id)

    def list_sessions(self) -> list:
        """列出所有会话"""
        return list(self.sessions.values())

    def update_session(self, session_id: str, **kwargs):
        """更新会话状态"""
        if session_id in self.sessions:
            self.sessions[session_id].update(kwargs)

    def add_message_to_session(self, session_id: str, role: str, content: str):
        """添加消息到会话"""
        if session_id in self.sessions:
            self.sessions[session_id]["messages"].append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat()
            })
            self.sessions[session_id]["message_count"] += 1

    def cancel_current_task(self, session_id: str) -> bool:
        """取消当前任务"""
        if session_id in self.sessions:
            if self.sessions[session_id]["status"] == "running":
                self.task_cancelled[session_id] = True
                self.sessions[session_id]["status"] = "idle"
                return True
        return False

    def get_or_create_leader(self, session_id: str) -> AttackLeader:
        """获取或创建 AttackLeader 实例"""
        if session_id in self.leader_instances:
            return self.leader_instances[session_id]

        # 创建新实例
        config = AttackLeaderConfig()
        self.leader_instances[session_id] = AttackLeader(config)
        return self.leader_instances[session_id]

    def get_session_messages(self, session_id: str) -> list:
        """获取会话的对话历史"""
        leader = self.leader_instances.get(session_id)
        if leader:
            return leader.context.get("conversation_history", [])
        return []

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

    async def wait_for_input(self, session_id: str, prompt: str, timeout: float = 300) -> Optional[str]:
        """等待用户输入"""
        await self.send_message(session_id, "need_input", {"prompt": prompt})
        try:
            queue = self.input_queues.get(session_id)
            if queue:
                result = await asyncio.wait_for(queue.get(), timeout=timeout)
                return result
        except asyncio.TimeoutError:
            return None
        return None

    async def wait_for_confirm(self, session_id: str, task: dict, message: str, timeout: float = 300) -> bool:
        """等待用户确认"""
        await self.send_message(session_id, "need_confirm", {
            "message": message,
            "task": task
        })
        try:
            queue = self.input_queues.get(session_id)
            if queue:
                result = await asyncio.wait_for(queue.get(), timeout=timeout)
                return result.lower() in ["y", "yes", "是", "true", "1"]
        except asyncio.TimeoutError:
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
                    Version 2.0.0
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    print(BANNER)
    print("=" * 55)
    print("  Server starting on http://0.0.0.0:8000")
    print("  WebSocket endpoint: ws://0.0.0.0:8000/ws/{session_id}")
    print("=" * 55)
    yield
    print("\nHunter Server 关闭...")


app = FastAPI(
    title="Hunter Server",
    description="LLM 驱动的自动化渗透测试服务 - 会话模式",
    version="2.0.0",
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
    return {
        "service": "Hunter Server",
        "status": "running",
        "version": "2.0.0",
        "mode": "session"
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
    """获取会话的对话历史"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = session_manager.get_session_messages(session_id)
    return {
        "session_id": session_id,
        "messages": messages
    }


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
        # 必须先 accept 才能 close
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

        # 监听客户端消息（不自动执行任务，等待用户发送消息）
        while True:
            try:
                data = await websocket.receive_json()
            except RuntimeError as e:
                # WebSocket 已断开
                print(f"[WebSocket] 连接已断开: {session_id} - {e}")
                break

            msg_type = data.get("type")

            if msg_type == "message":
                # 用户发送新消息，执行任务
                user_message = data.get("data", {}).get("message", "")
                if user_message:
                    # 重置取消标志
                    session_manager.task_cancelled[session_id] = False
                    # 保存用户消息
                    session_manager.add_message_to_session(session_id, "user", user_message)
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
                # 注意：不关闭 WebSocket，继续等待下一条消息

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

    session_manager.update_session(session_id, status="running")
    await session_manager.send_message(session_id, "status", {"status": "running"})
    await session_manager.send_message(session_id, "task_started", {
        "message": "开始执行任务",
        "command": command
    })

    # 获取当前事件循环（在主线程中）
    main_loop = asyncio.get_running_loop()

    try:
        print(f"[执行任务] 会话 {session_id}, 命令: {command}")

        # 获取或创建该会话的 AttackLeader 实例
        leader = session_manager.get_or_create_leader(session_id)

        # 设置取消检查函数
        def is_cancelled():
            return session_manager.task_cancelled.get(session_id, False)

        # 设置回调函数（这些会在线程池中被调用）
        def on_progress(message: str):
            # 检查是否被取消
            if is_cancelled():
                raise InterruptedError("任务已取消")
            # 从线程池中安全地调度到主事件循环
            asyncio.run_coroutine_threadsafe(
                session_manager.send_message(session_id, "progress", {"message": message}),
                main_loop
            )

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

        # 在线程池中执行（因为 AttackLeader.run 是同步的）
        result = await main_loop.run_in_executor(
            None,
            leader.run,
            command
        )

        # 检查是否被取消
        if is_cancelled():
            return

        # 保存助手回复到会话
        if result and result.get("report"):
            report = result["report"]
            reply_content = report.get("summary", "任务已完成")
            session_manager.add_message_to_session(session_id, "assistant", reply_content)

        # 更新会话状态为空闲（不是完成，因为会话可以继续）
        session_manager.update_session(session_id, status="idle")

        await session_manager.send_message(session_id, "task_completed", {
            "status": "completed",
            "result": result
        })

        # 关键改动：任务完成后不关闭 WebSocket，继续等待下一条消息
        print(f"[任务完成] 会话 {session_id} 任务完成，等待下一条消息")

    except InterruptedError:
        # 任务被取消
        print(f"[任务取消] 会话 {session_id} 任务已被用户取消")
        session_manager.update_session(session_id, status="idle")
    except Exception as e:
        session_manager.update_session(session_id, status="idle")
        await session_manager.send_message(session_id, "error", {
            "message": str(e)
        })
        print(f"[任务错误] 会话 {session_id}: {e}")
        # 关键改动：任务失败后也不关闭 WebSocket


# ============== 启动入口 ==============

if __name__ == "__main__":
    import uvicorn
    print(f"工作目录: {os.getcwd()}")
    print(f"项目根目录: {PROJECT_ROOT}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
