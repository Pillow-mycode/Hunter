"""AgentPool — 管理同类型 Agent 的多实例生命周期"""

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
        self._busy: set[str] = set()
        self._counter: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._agent_factories: dict[str, callable] = {}

    def register_factory(self, agent_type: str, factory: callable):
        self._agent_factories[agent_type] = factory

    def acquire(self, agent_type: str) -> tuple:
        """获取空闲实例。返回 (instance_id, agent) 或 (None, None)"""
        with self._lock:
            # 先检查空闲池
            if self._idle.get(agent_type):
                iid = self._idle[agent_type].pop()
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
                return iid, agent

        return None, None

    def release(self, instance_id: str):
        with self._lock:
            self._busy.discard(instance_id)
            agent_type = instance_id.rsplit("_", 1)[0]
            self._idle[agent_type].append(instance_id)

    def register_loop(self, instance_id: str, loop):
        self._loops[instance_id] = loop

    def get_loop(self, instance_id: str):
        return self._loops.get(instance_id)

    def start_all(self):
        for loop in self._loops.values():
            loop.start()

    def stop_all(self):
        for loop in self._loops.values():
            loop.stop()

    def all_loops(self) -> dict:
        return dict(self._loops)
