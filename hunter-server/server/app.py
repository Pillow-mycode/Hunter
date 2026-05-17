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
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 切换工作目录到项目根目录（确保相对路径正确）
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(override=True)

from agent.pojo.leader_config import AttackLeaderConfig
from agent.pojo.attack_config import AttackToolMasterConfig
from agent.pojo.hawkeye_config import HawkeyeConfig
from agent.pojo.analyst_config import DataAnalystConfig
from agent.smart_brain.attack_leader import AttackLeader
from agent.smart_brain.attack_tool_master import AttackToolMaster
from agent.smart_brain.hawkeye import Hawkeye
from agent.smart_brain.data_analyst import DataAnalyst
from agent.manager.database_manager import get_database, DatabaseManager
from agent.team.comm_bus import CommunicationBus
from agent.team.blackboard import Blackboard
from agent.team.agent_loop import AgentLoop
from agent.team.agent_pool import AgentPool
from agent.team.protocol import InterAgentMessage
from llm.factory import ProviderFactory
from server.config_api import router as config_router


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
        # AgentLoop 协同基础设施（per session）
        self.comm_buses: Dict[str, CommunicationBus] = {}
        self.blackboards: Dict[str, Blackboard] = {}
        self.agent_loops: Dict[str, Dict[str, AgentLoop]] = {}

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
        # 停止所有 AgentLoop 线程
        loops = self.agent_loops.pop(session_id, {})
        for loop in loops.values():
            loop.stop()

        # 清理运行时状态
        self.websockets.pop(session_id, None)
        self.input_queues.pop(session_id, None)
        self.leader_instances.pop(session_id, None)
        self.task_cancelled.pop(session_id, None)
        self.comm_buses.pop(session_id, None)
        self.blackboards.pop(session_id, None)

        # 从数据库删除
        self.db.delete_session(session_id)
        print(f"[会话删除] ID: {session_id}")

    def cancel_current_task(self, session_id: str) -> bool:
        """取消当前任务"""
        session = self.db.get_session(session_id)
        if session and session["status"] == "running":
            self.task_cancelled[session_id] = True
            self.db.update_session_status(session_id, "idle")
            # 通过 CommBus 广播中止消息给所有 Agent
            comm_bus = self.comm_buses.get(session_id)
            if comm_bus:
                cancel_msg = InterAgentMessage(
                    from_agent="leader",
                    to_agent="leader",
                    msg_type="cancel",
                    content="[系统] 任务已被用户取消，请立即停止所有操作。",
                )
                comm_bus.broadcast(cancel_msg)
            # 停止所有 AgentLoop
            loops = self.agent_loops.get(session_id, {})
            for loop in loops.values():
                loop.stop()
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

    def setup_team(self, session_id: str, main_loop, on_need_input, on_need_confirm,
                   max_steps: int = 50, confirm_interval: int = 10):
        """创建 Agent 团队：CommBus + Blackboard + AgentPool + AgentLoops。

        返回 (leader, loops_dict)。会话复用时创建新的 AgentLoop 线程。
        """
        def on_agent_progress(message: str):
            print(message)
            asyncio.run_coroutine_threadsafe(
                store_and_send_progress(session_id, "progress", message, message),
                main_loop
            )

        if session_id in self.comm_buses:
            # 会话复用路径
            leader = self.leader_instances.get(session_id)
            comm_bus = self.comm_buses[session_id]
            blackboard = self.blackboards[session_id]
            pool = self.agent_pools.get(session_id) if hasattr(self, "agent_pools") else None
            if not leader or not comm_bus or not blackboard:
                raise RuntimeError(f"会话 {session_id} 团队资源不完整")

            old_loops = self.agent_loops.pop(session_id, {})
            for old_loop in old_loops.values():
                old_loop.stop()

            agents = {}
            for aid, old_loop in old_loops.items():
                agents[aid] = old_loop.agent

            leader.on_progress = on_agent_progress
            leader.on_need_input = on_need_input
            leader.on_need_confirm = on_need_confirm
            leader._max_steps = max_steps
            leader._confirm_interval = confirm_interval
            for aid, agent in agents.items():
                if hasattr(agent, 'on_progress'):
                    agent.on_progress = on_agent_progress
                if hasattr(agent, 'on_need_input'):
                    agent.on_need_input = on_need_input
            if pool and hasattr(pool, 'set_new_instance_callback'):
                def _setup_new_instance(iid, agent):
                    if hasattr(agent, 'on_progress'):
                        agent.on_progress = on_agent_progress
                    if hasattr(agent, 'on_need_input'):
                        agent.on_need_input = on_need_input
                pool.set_new_instance_callback(_setup_new_instance)

            def make_stream_callback(agent_name: str):
                def on_stream_chunk(chunk: str):
                    asyncio.run_coroutine_threadsafe(
                        session_manager.send_message(session_id, "stream", {
                            "agent": agent_name,
                            "chunk": chunk,
                        }),
                        main_loop
                    )
                return on_stream_chunk
            leader.stream_callback = make_stream_callback("leader")

            loops = {}
            for aid, agent in agents.items():
                loops[aid] = AgentLoop(agent, comm_bus, blackboard)

            # 设置 loop_factory，确保后续 acquire 创建新实例时自动创建 AgentLoop
            if pool:
                for iid, loop in loops.items():
                    if iid != "leader":
                        pool.register_loop(iid, loop)

                def make_loop(agent, iid):
                    loop = AgentLoop(agent, comm_bus, blackboard)
                    loops[iid] = loop
                    return loop

                pool.set_loop_factory(make_loop)

            self.agent_loops[session_id] = loops
            print(f"[Team] 会话 {session_id} 复用团队，已创建新 AgentLoop 线程")
            return leader, loops

        # 1. 创建 CommBus + Blackboard
        comm_bus = CommunicationBus(session_id=session_id)
        blackboard = Blackboard()

        # 2. 注册 Leader
        comm_bus.register_agent("leader")

        # 3. AgentPool + 工厂注册（在 Leader 之前创建）
        pool = AgentPool(comm_bus, blackboard)
        pool.register_factory("tool_master",
            lambda iid: AttackToolMaster(AttackToolMasterConfig(),
                                         comm_bus=comm_bus, blackboard=blackboard, agent_id=iid, agent_pool=pool))
        pool.register_factory("data_analyst",
            lambda iid: DataAnalyst(DataAnalystConfig(),
                                    comm_bus=comm_bus, blackboard=blackboard, agent_id=iid, agent_pool=pool))
        pool.register_factory("hawkeye",
            lambda iid: Hawkeye(HawkeyeConfig(),
                                comm_bus=comm_bus, blackboard=blackboard, agent_id=iid, agent_pool=pool))

        # 4. Leader 实例
        leader_config = AttackLeaderConfig()
        leader = AttackLeader(leader_config, comm_bus=comm_bus, blackboard=blackboard, agent_pool=pool)
        leader._max_steps = max_steps
        leader._confirm_interval = confirm_interval
        history = self.db.get_conversation_history(session_id)
        if history:
            leader.context["conversation_history"] = history

        # 5. loop_factory：acquire 创建新实例时自动创建并启动 AgentLoop
        loops = {}  # 提前声明，供 loop_factory 闭包引用

        def make_loop(agent, iid):
            loop = AgentLoop(agent, comm_bus, blackboard)
            loops[iid] = loop
            return loop

        pool.set_loop_factory(make_loop)

        # 6. 预创建各类型一个实例（acquire 会自动通过 loop_factory 创建 AgentLoop）
        for atype in ("tool_master", "data_analyst", "hawkeye"):
            iid, agent = pool.acquire(atype)
            if iid:
                pool.release(iid)

        # 7. 进度回调
        def on_agent_message(msg: InterAgentMessage):
            ctx_info = f" task={msg.task_id}" if msg.task_id else ""
            print(f"[CommBus] {msg.from_agent} → {msg.to_agent} | {msg.msg_type}{ctx_info} | {msg.content[:150]}")
            asyncio.run_coroutine_threadsafe(
                store_and_send_progress(
                    session_id, "progress",
                    f"[{msg.from_agent}→{msg.to_agent}] {msg.msg_type}: {msg.content[:200]}",
                    f"[{msg.from_agent}→{msg.to_agent}] {msg.content[:200]}"
                ),
                main_loop
            )
        comm_bus.on_send = on_agent_message

        # 8. Leader 回调 + Agent 进度回调
        leader.on_progress = on_agent_progress
        leader.on_need_input = on_need_input
        leader.on_need_confirm = on_need_confirm
        for iid, agent in pool.list_instances().items():
            if hasattr(agent, 'on_progress'):
                agent.on_progress = on_agent_progress
            if hasattr(agent, 'on_need_input'):
                agent.on_need_input = on_need_input
        def _setup_new_instance(iid, agent):
            if hasattr(agent, 'on_progress'):
                agent.on_progress = on_agent_progress
            if hasattr(agent, 'on_need_input'):
                agent.on_need_input = on_need_input
        pool.set_new_instance_callback(_setup_new_instance)

        def make_stream_callback(agent_name: str):
            def on_stream_chunk(chunk: str):
                asyncio.run_coroutine_threadsafe(
                    session_manager.send_message(session_id, "stream", {
                        "agent": agent_name,
                        "chunk": chunk,
                    }),
                    main_loop
                )
            return on_stream_chunk
        leader.stream_callback = make_stream_callback("leader")

        # 9. Leader AgentLoop
        loops["leader"] = AgentLoop(leader, comm_bus, blackboard)

        # 9. 存储
        self.comm_buses[session_id] = comm_bus
        self.blackboards[session_id] = blackboard
        self.agent_loops[session_id] = loops
        self.leader_instances[session_id] = leader
        if not hasattr(self, "agent_pools"):
            self.agent_pools = {}
        self.agent_pools[session_id] = pool

        print(f"[Team] 会话 {session_id} 团队已创建：Leader + AgentPool({list(pool.list_instances().keys())})")
        return leader, loops

    def cleanup_team(self, session_id: str):
        """停止所有 AgentLoop 并清理团队资源"""
        loops = self.agent_loops.pop(session_id, {})
        for agent_id, loop in loops.items():
            loop.stop()
        self.comm_buses.pop(session_id, None)
        self.blackboards.pop(session_id, None)
        print(f"[Team] 会话 {session_id} 团队已清理")

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

# 注册配置管理路由
app.include_router(config_router)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== HTTP 接口 ==============

def _check_provider_health(agent_type: str) -> dict:
    """检查单个 Agent 的 Provider 连通性（在 executor 中调用）"""
    import time
    try:
        provider = ProviderFactory.create_from_env(agent_type=agent_type)
        provider_type = getattr(provider, "PROVIDER_TYPE", "unknown")
        model = provider.model
        start = time.time()
        ok = provider.health_check()
        latency_ms = round((time.time() - start) * 1000)
        return {
            "agent": agent_type,
            "provider_type": provider_type,
            "model": model,
            "status": "ok" if ok else "error",
            "latency_ms": latency_ms,
        }
    except Exception as e:
        return {
            "agent": agent_type,
            "provider_type": "unknown",
            "model": "",
            "status": "error",
            "error": str(e),
        }


@app.get("/status")
async def root():
    """服务状态（含各 Agent Provider 连通性检查）"""
    db = get_database()
    stats = db.get_stats()

    main_loop = asyncio.get_running_loop()
    agent_types = ["leader", "attacker", "hawkeye", "analyst"]

    async def check_one(agent_type: str) -> dict:
        return await main_loop.run_in_executor(None, _check_provider_health, agent_type)

    results = await asyncio.gather(*[check_one(t) for t in agent_types])
    providers = {r.pop("agent"): r for r in results}

    return {
        "service": "Hunter Server",
        "status": "running",
        "version": "3.0.0",
        "mode": "persistent",
        "stats": stats,
        "providers": providers,
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


@app.get("/session/{session_id}/export")
async def export_session(session_id: str, format: str = "markdown"):
    """导出会话为 Markdown 或纯文本文件"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = session_manager.get_messages(session_id)

    if format == "markdown":
        content = _format_markdown(session, messages)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="session_{session_id}.md"'}
        )
    else:
        content = _format_text(session, messages)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="session_{session_id}.txt"'}
        )


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

                    # 提取步数配置（客户端可配）
                    max_steps = data.get("data", {}).get("max_steps", 50)
                    confirm_interval = data.get("data", {}).get("confirm_interval", 10)

                    # 启动任务执行
                    asyncio.create_task(run_session_task(
                        session_id, user_message,
                        max_steps=max_steps,
                        confirm_interval=confirm_interval
                    ))

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


async def run_session_task(session_id: str, command: str, max_steps: int = 50, confirm_interval: int = 10):
    """执行会话中的任务 — AgentLoop 异步协作模式"""
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
    leader = None
    loops = {}

    try:
        print(f"[执行任务] 会话 {session_id}, 命令: {command}")

        def is_cancelled():
            return session_manager.task_cancelled.get(session_id, False)

        # 回调：用户输入
        def on_need_input(prompt: str) -> Optional[str]:
            if is_cancelled():
                return None
            future = asyncio.run_coroutine_threadsafe(
                session_manager.wait_for_input(session_id, prompt),
                main_loop
            )
            return future.result(timeout=300)

        # 回调：用户确认
        def on_need_confirm(task_info: dict, message: str) -> bool:
            if is_cancelled():
                return False
            future = asyncio.run_coroutine_threadsafe(
                session_manager.wait_for_confirm(session_id, task_info, message),
                main_loop
            )
            return future.result(timeout=300)

        # 1. 创建团队（CommBus + Blackboard + 4 agents + 4 AgentLoops）
        leader, loops = session_manager.setup_team(
            session_id, main_loop, on_need_input, on_need_confirm,
            max_steps=max_steps, confirm_interval=confirm_interval
        )
        blackboard = session_manager.blackboards[session_id]

        # 2. 写入任务目标到黑板
        blackboard.write("mission", "objective", command)
        blackboard.write("mission", "status", "in_progress")
        blackboard.add_activity(f"收到任务: {command}")

        # 3. 启动所有 AgentLoop 线程
        for agent_id, loop in loops.items():
            loop.start()

        # 4. 在 executor 中等待 Leader 的 AgentLoop 完成
        leader_loop = loops.get("leader")
        if not leader_loop:
            raise RuntimeError("Leader AgentLoop not found")

        def wait_for_completion():
            leader_loop.mission_complete.wait()
            return leader_loop.get_result()

        result = await main_loop.run_in_executor(None, wait_for_completion)

        if is_cancelled():
            return

        # 5. 生成报告（前端需要 {status, report} 格式）
        report = _build_report_from_blackboard(blackboard)
        if result and result.get("type") == "complete":
            summary = result.get("summary", "")
            report["summary"] = summary
            reply_content = build_reply_content(report)
            session_manager.add_message(session_id, "assistant", reply_content,
                                        {"report": report})

        session_manager.update_session_status(session_id, "idle")

        await session_manager.send_message(session_id, "task_completed", {
            "status": "completed",
            "result": {
                "status": "completed",
                "report": report
            }
        })

        print(f"[任务完成] 会话 {session_id} 任务完成")

    except InterruptedError:
        print(f"[任务取消] 会话 {session_id} 任务已被用户取消")
        session_manager.update_session_status(session_id, "idle")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        session_manager.update_session_status(session_id, "idle")
        session_manager.add_message(session_id, "error", str(e))
        await session_manager.send_message(session_id, "error", {
            "message": str(e)
        })
        print(f"[任务错误] 会话 {session_id}: {e}")
        print(tb)
    finally:
        # 6. 停止所有 AgentLoop 线程
        for loop in loops.values():
            loop.stop()


def _build_report_from_blackboard(blackboard, leader_summary: str = "") -> dict:
    """从 Blackboard 状态生成任务报告。"""
    findings = blackboard.read("findings")
    mission = blackboard.read("mission")

    report = {
        "objective": mission.get("objective", ""),
        "summary": leader_summary or "任务已完成",
        "findings": findings,
    }

    # 统计
    parts = []
    subdomains = findings.get("subdomains", [])
    ports = findings.get("ports", {})
    vulnerabilities = findings.get("vulnerabilities", [])
    directories = findings.get("directories", [])
    credentials = findings.get("credentials", [])

    if subdomains:
        parts.append(f"发现 {len(subdomains)} 个子域名")
    if ports:
        parts.append(f"发现 {len(ports)} 个开放端口")
    if directories:
        parts.append(f"发现 {len(directories)} 个目录")
    if vulnerabilities:
        parts.append(f"发现 {len(vulnerabilities)} 个漏洞")
    if credentials:
        parts.append(f"获取 {len(credentials)} 组凭证")

    if parts:
        report["conclusion"] = "；".join(parts) + "。"

    return report


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


# ============== 会话导出 ==============

def _format_markdown(session: dict, messages: list) -> str:
    """将会话消息格式化为 Markdown"""
    lines = [
        f"# {session.get('name', 'Hunter Session')}",
        f"",
        f"**会话 ID**: `{session.get('id', 'N/A')}`",
        f"**状态**: {session.get('status', 'N/A')}",
        f"**创建时间**: {session.get('created_at', 'N/A')}",
        f"",
        f"---",
        f"",
    ]
    for msg in messages:
        role = msg.get("msg_type", "unknown")
        content = msg.get("content", "")
        ts = msg.get("created_at", "")[:19]  # 截断到秒
        if not content:
            continue

        if role == "user":
            lines.append(f"### 用户 ({ts})")
            lines.append(f"")
            lines.append(f"> {content}")
            lines.append(f"")
        elif role == "command":
            lines.append(f"### 命令 ({ts})")
            lines.append(f"")
            lines.append(f"```bash")
            lines.append(content)
            lines.append(f"```")
            lines.append(f"")
        elif role in ("reply", "assistant"):
            lines.append(f"### 助手 ({ts})")
            lines.append(f"")
            lines.append(content)
            lines.append(f"")
        elif role == "error":
            lines.append(f"### 错误 ({ts})")
            lines.append(f"")
            lines.append(f"> **错误**: {content}")
            lines.append(f"")
        elif role == "file":
            lines.append(f"### 文件 ({ts})")
            lines.append(f"")
            lines.append(f"> 文件已保存: `{content}`")
            lines.append(f"")
        elif role == "system":
            lines.append(f"### 系统 ({ts})")
            lines.append(f"")
            lines.append(f"> {content}")
            lines.append(f"")
        else:
            lines.append(f"### {role} ({ts})")
            lines.append(f"")
            lines.append(content)
            lines.append(f"")
    return "\n".join(lines)


def _format_text(session: dict, messages: list) -> str:
    """将会话消息格式化为纯文本"""
    lines = [
        f"{'='*60}",
        f"  {session.get('name', 'Hunter Session')}",
        f"{'='*60}",
        f"会话 ID: {session.get('id', 'N/A')}",
        f"状态: {session.get('status', 'N/A')}",
        f"创建时间: {session.get('created_at', 'N/A')}",
        f"{'='*60}",
        f"",
    ]
    for msg in messages:
        role = msg.get("msg_type", "unknown")
        content = msg.get("content", "")
        ts = msg.get("created_at", "")[:19]
        if not content:
            continue

        role_names = {
            "user": "用户", "command": "命令", "reply": "助手",
            "assistant": "助手", "error": "错误", "file": "文件",
            "system": "系统", "progress": "进度",
        }
        role_name = role_names.get(role, role)

        lines.append(f"[{role_name}] {ts}")
        lines.append(f"{'-'*40}")
        lines.append(content)
        lines.append(f"")
    return "\n".join(lines)


# ============== 静态文件服务 ==============

CLIENT_DIR = os.path.normpath(os.path.join(PROJECT_ROOT, "..", "hunter-clinet", "web"))
if os.path.isdir(CLIENT_DIR):
    app.mount("/", StaticFiles(directory=CLIENT_DIR, html=True), name="client")


# ============== 启动入口 ==============

if __name__ == "__main__":
    import uvicorn
    print(f"工作目录: {os.getcwd()}")
    print(f"项目根目录: {PROJECT_ROOT}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
