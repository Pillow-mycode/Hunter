"""上下文管理 — 分层上下文构建 + 智能截断 + 历史检索"""

from __future__ import annotations

from typing import Optional

from agent.manager.database_manager import get_database


class ContextManager:
    """会话级上下文管理器。

    提供三层上下文构建策略：
      Layer 1（永不过期）：任务目标 + 团队角色定义
      Layer 2（工作窗口）：最近 N 条 Agent 消息 + 黑板摘要
      Layer 3（按需检索）：search_history() 从 SQLite 检索
    """

    # 团队角色描述（Layer 1，所有 Agent 共享）
    TEAM_ROLES = {
        "leader": "渗透专家 — 负责制定攻击策略、解析用户需求、协调团队、做出决策",
        "tool_master": "武器大师 — 负责选择工具、生成并执行 shell 命令、汇报结果",
        "data_analyst": "数据分析员 — 负责分析长命令输出、提取关键发现、生成分析报告",
        "hawkeye": "鹰眼 — 负责监控进程交互提示、检测异常时长、主动告警",
    }

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self._db = get_database()

    # ─── Layer 1-3: build_context ─────────────────────────────────

    def build_context(
        self,
        agent_id: str,
        blackboard,
        outstanding_tasks: str,
        inbox_msgs: list,
    ) -> dict:
        """构建传给 Agent LLM 的决策上下文。"""
        context = {
            # Layer 1: 永不过期
            "mission": blackboard.read("mission"),
            "team_roles": self._format_team_roles(),
            # Layer 2: 工作窗口
            "outstanding_tasks": outstanding_tasks,
            "new_inbox": self._summarize_inbox(inbox_msgs),
            "blackboard_summary": blackboard.get_summary(),
            "team_status": blackboard.read("agent_status"),
            "recent_history": self._get_recent_history(limit=10),
            # Layer 3: 提示可按需检索
            "search_hint": (
                "如需检索更多历史消息，可使用 search_history(keyword) 按关键词搜索"
            ),
        }
        # 注入 Agent 专属提示
        context["my_role"] = self.TEAM_ROLES.get(agent_id, "")
        return context

    def _format_team_roles(self) -> str:
        lines = ["## 你的团队"]
        for agent_id, role_desc in self.TEAM_ROLES.items():
            lines.append(f"- {agent_id}: {role_desc}")
        lines.append(
            "通信方式：通过 CommBus 收发 InterAgentMessage，"
            "消息类型包括 delegation / task_result / analysis_request / "
            "input_alert / finding_alert 等。"
        )
        return "\n".join(lines)

    def _summarize_inbox(self, inbox_msgs: list) -> str:
        if not inbox_msgs:
            return "（无新消息）"
        lines = []
        for msg in inbox_msgs[-5:]:
            lines.append(
                f"[{msg.from_agent} → {msg.to_agent}] {msg.msg_type}: {msg.content[:120]}"
            )
        return "\n".join(lines)

    def _get_recent_history(self, limit: int = 10) -> list:
        if not self.session_id:
            return []
        raw = self._db.get_agent_messages(self.session_id, limit=limit)
        return [
            {
                "from": m.get("sender", ""),
                "to": m.get("receiver", ""),
                "type": m.get("msg_type", ""),
                "content": m.get("content", ""),
                "timestamp": m.get("created_at", ""),
            }
            for m in reversed(raw)
        ]

    # ─── Layer 3: search_history ──────────────────────────────────

    def search_history(self, keyword: str, limit: int = 20) -> list:
        """按关键词搜索 agent_messages 历史。

        遍历最近消息并在 Python 侧匹配（避免直接操作 SQLite cursor）。
        """
        if not self.session_id:
            return []
        all_msgs = self._db.get_agent_messages(self.session_id, limit=500)
        results = []
        kw = keyword.lower()
        for m in all_msgs:
            content = m.get("content", "")
            msg_type = m.get("msg_type", "")
            if kw in content.lower() or kw in msg_type.lower():
                results.append(
                    {
                        "msg_id": m.get("msg_id", ""),
                        "sender": m.get("sender", ""),
                        "receiver": m.get("receiver", ""),
                        "msg_type": msg_type,
                        "content": content[:300],
                        "created_at": m.get("created_at", ""),
                    }
                )
                if len(results) >= limit:
                    break
        return results

    # ─── 阶段摘要 ─────────────────────────────────────────────────

    def generate_phase_summary(self, step_range: tuple) -> str:
        """生成阶段性自然语言摘要。

        step_range: (start_step, end_step)，如 (1, 5)。
        基于黑板快照和 Agent 消息统计生成。
        """
        start, end = step_range
        snapshot = self._db.get_latest_snapshot(self.session_id)
        agent_msgs = self._db.get_agent_messages(self.session_id, limit=100)

        # 统计消息类型
        type_counts = {}
        for m in agent_msgs:
            t = m.get("msg_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        delegation_count = type_counts.get("delegation", 0)
        result_count = type_counts.get("task_result", 0)
        alert_count = type_counts.get("input_alert", 0) + type_counts.get(
            "timeout_alert", 0
        )

        # 从快照中提取发现
        findings = {}
        if snapshot:
            findings = snapshot.get("findings", {})

        # 构建摘要
        parts = [f"步骤 {start}-{end} 阶段总结："]

        parts.append(f"共执行 {delegation_count} 次任务委派，收到 {result_count} 次结果汇报。")
        if alert_count:
            parts.append(f"触发 {alert_count} 次告警。")

        # 发现统计
        finding_parts = []
        subdomains = findings.get("subdomains", [])
        ports = findings.get("ports", {})
        vulnerabilities = findings.get("vulnerabilities", [])
        directories = findings.get("directories", [])
        credentials = findings.get("credentials", [])

        if subdomains:
            samples = subdomains[:3]
            finding_parts.append(
                f"子域名 {len(subdomains)} 个（{', '.join(samples)}"
                + ("..." if len(subdomains) > 3 else "")
                + "）"
            )
        if ports:
            port_list = [f"{p}/{s}" for p, s in ports.items()]
            samples = port_list[:5]
            finding_parts.append(
                f"开放端口 {len(ports)} 个（{', '.join(samples)}"
                + ("..." if len(ports) > 5 else "")
                + "）"
            )
        if directories:
            samples = directories[:3]
            finding_parts.append(
                f"目录 {len(directories)} 个（{', '.join(samples)}"
                + ("..." if len(directories) > 3 else "")
                + "）"
            )
        if vulnerabilities:
            finding_parts.append(f"漏洞 {len(vulnerabilities)} 个")
        if credentials:
            finding_parts.append(f"凭证 {len(credentials)} 组")

        if finding_parts:
            parts.append("发现：" + "；".join(finding_parts) + "。")
        else:
            parts.append("本阶段暂未发现关键信息。")

        return "".join(parts)

    # ─── 智能截断 ──────────────────────────────────────────────────

    def smart_truncate(self, messages: list, max_tokens: int) -> list:
        """智能截断消息列表，确保估算 token 数不超过 max_tokens。

        策略：
          1. system 消息永不丢弃
          2. Agent 间通信消息优先级高
          3. 长内容（>2000 字符）优先丢弃
          4. 从中间丢弃低价值消息，保留头尾
          5. 在截断处插入摘要说明
        """
        if not messages:
            return messages

        total = sum(self._estimate_tokens(m["content"]) for m in messages)
        if total <= max_tokens:
            return messages

        # 给每条消息分配优先级
        indexed = []
        for i, m in enumerate(messages):
            priority = self._message_priority(m, i, len(messages))
            indexed.append((priority, i, m))

        # 按优先级排序（低优先级在前，先丢弃）
        indexed.sort(key=lambda x: (x[0], -x[1]))

        # 逐步丢弃低优先级消息
        dropped_indices = set()
        for priority, idx, msg in indexed:
            if priority == 0:
                continue  # 永不丢弃 system 消息
            if total <= max_tokens:
                break
            dropped_indices.add(idx)
            total -= self._estimate_tokens(msg["content"])

        if not dropped_indices:
            # 如果只靠丢弃不够，截断最老的非 system 消息内容
            return self._truncate_content(messages, max_tokens)

        # 构建结果：保留未丢弃的消息，在第一个缺口处插入摘要
        result = []
        dropped_count = 0
        notice_inserted = False
        for i, m in enumerate(messages):
            if i in dropped_indices:
                dropped_count += 1
                if not notice_inserted and dropped_count == 1:
                    result.append(
                        {
                            "role": "system",
                            "content": (
                                f"[系统] 上下文过长，已省略中间 {len(dropped_indices)} "
                                f"条低价值消息（执行日志等）。"
                            ),
                        }
                    )
                    notice_inserted = True
                continue
            result.append(m)

        return result

    def _message_priority(
        self, msg: dict, index: int, total: int
    ) -> int:
        """计算消息的保留优先级。0=永不丢弃，数字越大越先丢弃。"""
        role = msg.get("role", "")
        content = msg.get("content", "")

        # 0: system 消息永不丢弃
        if role == "system":
            return 0

        # 1: Agent 间通信消息（高价值）
        if role in ("delegation", "task_result", "analysis_request",
                     "analysis_result", "input_alert", "finding_alert"):
            return 1

        # 1: 最后 5 条消息（高价值，保留对话结尾）
        if index >= total - 5:
            return 1

        # 2: 普通 user/assistant 对话
        if role in ("user", "assistant"):
            # 长内容降低优先级
            if len(content) > 2000:
                return 3
            return 2

        # 3: 超长内容优先丢弃
        if len(content) > 2000:
            return 3

        return 2

    def _truncate_content(self, messages: list, max_tokens: int) -> list:
        """当丢弃消息不够时，截断最长消息的内容。"""
        result = []
        remaining = max_tokens
        # 先为 system 消息保留空间
        system_tokens = sum(
            self._estimate_tokens(m["content"])
            for m in messages
            if m.get("role") == "system"
        )
        remaining -= system_tokens

        for m in messages:
            if m.get("role") == "system":
                result.append(m)
                continue
            tokens = self._estimate_tokens(m["content"])
            if tokens <= remaining:
                result.append(m)
                remaining -= tokens
            else:
                # 截断此消息内容
                max_chars = remaining * 2
                truncated = m["content"][:max_chars] + "...[已截断]"
                result.append({**m, "content": truncated})
                remaining = 0
        return result

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """使用 tiktoken 精确计算文本 token 数。"""
        from llm.token_counter import get_token_counter
        return get_token_counter().count_text(text)
