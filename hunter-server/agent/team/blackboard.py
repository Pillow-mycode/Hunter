"""Blackboard — 线程安全的 Agent 共享状态存储"""

import copy
import threading


class Blackboard:
    """线程安全的共享黑板，所有 Agent 可读写。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "mission": {
                "objective": "",
                "target": "",
                "scope": [],
                "status": "idle",
            },
            "task_queue": [],
            "findings": {
                "subdomains": [],
                "ports": {},
                "directories": [],
                "vulnerabilities": [],
                "credentials": [],
                "other": [],
            },
            "activity_feed": [],
            "agent_status": {},
        }

    def write(self, section: str, key: str, value) -> None:
        with self._lock:
            self._data[section][key] = value

    def read(self, section: str, key: str = None):
        with self._lock:
            if key is None:
                return copy.deepcopy(self._data[section])
            val = self._data[section][key]
            if isinstance(val, (list, dict)):
                return copy.deepcopy(val)
            return val

    def add_activity(self, description: str) -> None:
        with self._lock:
            feed = self._data["activity_feed"]
            feed.append(description)
            if len(feed) > 50:
                self._data["activity_feed"] = feed[-50:]

    def update_agent_status(self, agent_id: str, status: str) -> None:
        with self._lock:
            self._data["agent_status"][agent_id] = status

    def get_summary(self) -> str:
        with self._lock:
            m = self._data["mission"]
            f = self._data["findings"]
            feed = self._data["activity_feed"]
            agents = self._data["agent_status"]

        lines = [
            f"任务: {m['objective']} (目标: {m['target']}, 范围: {m['scope']})",
            f"状态: {m['status']}",
            f"发现: 子域名{len(f['subdomains'])}个, 端口{len(f['ports'])}个, "
            f"目录{len(f['directories'])}个, 漏洞{len(f['vulnerabilities'])}个, "
            f"凭据{len(f['credentials'])}个",
        ]

        if feed:
            recent = feed[-3:]
            lines.append(f"最近活动: {'; '.join(recent)}")

        status_str = ", ".join(f"{k}={v}" for k, v in agents.items())
        lines.append(f"团队: {status_str}")

        return "\n".join(lines)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)
