"""AgentPool — 管理同类型 Agent 的多实例生命周期"""

import time
import threading
from collections import defaultdict


class AgentPool:
    def __init__(self, comm_bus, blackboard,
                 max_per_type: dict = None,
                 idle_timeout: float = 300):
        self.comm_bus = comm_bus
        self.blackboard = blackboard
        self.max_per_type = max_per_type or {
            "tool_master": 5, "data_analyst": 2, "hawkeye": 2,
        }
        self.idle_timeout = idle_timeout

        self._instances: dict[str, object] = {}       # iid → agent
        self._loops: dict[str, object] = {}            # iid → AgentLoop
        self._idle: dict[str, list[str]] = defaultdict(list)  # type → [iids]
        self._idle_since: dict[str, float] = {}         # iid → idle start timestamp
        self._busy: set[str] = set()
        self._counter: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._agent_factories: dict[str, callable] = {}
        self._on_new_instance: callable = None
        self._loop_factory: callable = None  # (agent, iid) → AgentLoop

    def register_factory(self, agent_type: str, factory: callable):
        self._agent_factories[agent_type] = factory

    def set_new_instance_callback(self, callback: callable):
        """新实例创建时自动调用 callback(instance_id, agent)"""
        self._on_new_instance = callback

    def set_loop_factory(self, factory: callable):
        """设置 AgentLoop 工厂：acquire 创建新实例时自动调用 factory(agent, iid) → AgentLoop"""
        self._loop_factory = factory

    def acquire(self, agent_type: str) -> tuple:
        """获取空闲实例。返回 (instance_id, agent) 或 (None, None)"""
        with self._lock:
            # 先检查空闲池
            if self._idle.get(agent_type):
                iid = self._idle[agent_type].pop()
                self._idle_since.pop(iid, None)
                self._busy.add(iid)
                return iid, self._instances[iid]

            # 创建新实例
            current_count = sum(
                1 for iid in self._instances
                if iid.startswith(f"{agent_type}_")
            )
            if current_count < self.max_per_type.get(agent_type, 5):
                self._counter[agent_type] += 1
                iid = f"{agent_type}_{self._counter[agent_type]}"
                factory = self._agent_factories.get(agent_type)
                if factory is None:
                    return None, None
                agent = factory(iid)
                self._instances[iid] = agent
                self._busy.add(iid)
                self.comm_bus.register_agent(iid)
                if self._on_new_instance:
                    self._on_new_instance(iid, agent)
                if self._loop_factory:
                    loop = self._loop_factory(agent, iid)
                    self._loops[iid] = loop
                    loop.start()
                return iid, agent

        return None, None

    def has_capacity(self, agent_type: str) -> bool:
        """检查是否有空闲实例或可创建新实例的余量"""
        with self._lock:
            if self._idle.get(agent_type):
                return True
            current_count = sum(
                1 for iid in self._instances
                if iid.startswith(f"{agent_type}_")
            )
            return current_count < self.max_per_type.get(agent_type, 5)

    def release(self, instance_id: str):
        with self._lock:
            self._busy.discard(instance_id)
            agent_type = instance_id.rsplit("_", 1)[0]
            if instance_id not in self._idle[agent_type]:
                self._idle[agent_type].append(instance_id)
                self._idle_since[instance_id] = time.time()

    def reap_idle(self) -> list[str]:
        """回收超时空闲实例，返回被清理的 iid 列表。"""
        now = time.time()
        removed = []
        with self._lock:
            for agent_type in list(self._idle.keys()):
                surviving = []
                for iid in self._idle[agent_type]:
                    idle_start = self._idle_since.get(iid, now)
                    if now - idle_start >= self.idle_timeout:
                        removed.append(iid)
                        self._instances.pop(iid, None)
                        loop = self._loops.pop(iid, None)
                        if loop:
                            loop.stop()
                        self.comm_bus.unregister_agent(iid)
                        self._idle_since.pop(iid, None)
                    else:
                        surviving.append(iid)
                if surviving:
                    self._idle[agent_type] = surviving
                else:
                    del self._idle[agent_type]
        return removed

    def register_loop(self, instance_id: str, loop):
        self._loops[instance_id] = loop

    def get_loop(self, instance_id: str):
        return self._loops.get(instance_id)

    def list_instances(self) -> dict[str, object]:
        """返回所有实例的只读视图。"""
        return dict(self._instances)

    def start_all(self):
        for loop in self._loops.values():
            loop.start()

    def stop_all(self):
        for loop in self._loops.values():
            loop.stop()

    def all_loops(self) -> dict:
        return dict(self._loops)
