# 渗透分析专家
import json
import threading
from typing import Callable, Optional

from agent.pojo.leader_config import AttackLeaderConfig
from agent.pojo.attack_config import AttackToolMasterConfig
from agent.smart_brain.hardcoded_rules import HardcodedRules, RuleResult
from agent.team.agent_base import AgentBase
from agent.system.system_command import write_to_logs
from agent.team.protocol import MSG_TASK_RESULT, MSG_ANALYSIS_RESULT, MSG_INPUT_ALERT
from llm.token_counter import get_token_counter

"""
渗透专家模型
负责接收用户任务、持续决策、协调团队完成渗透测试
"""

MESSAGES = {
    "zh": {
        # get_response
        "msg_truncating": "[LLM] 消息过长，正在截断...",
        "msg_calling_model": "[LLM] 正在调用模型 {model}... (尝试 {attempt}/{max_retries})",
        "msg_model_complete": "[LLM] 模型响应完成",
        "msg_api_retry": "[LLM] API 调用失败，{wait_time}秒后重试...",
        "msg_api_failed": "[LLM] API 调用失败: {error}",
        # _notify_message
        "msg_reply": "[回复] {message}",
        # init_context
        "init_parse_request": "请解析以下用户请求，提取目标和范围信息。",
        "init_user_request": "用户请求",
        "init_return_json": "返回 JSON 格式",
        "init_target_desc": "主要目标（域名或 IP，若无则空字符串）",
        "init_scope_desc": "目标范围列表",
        "init_request_type_desc": "请求类型（full_pentest/vulnerability_scan/specific_test）",
        "init_specific_requirements_desc": "特殊要求列表",
        # _summarize_findings
        "msg_no_findings": "暂无发现",
        # _format_recent_history
        "msg_none": "无",
        "msg_step": "步骤{step}",
        "msg_result": "结果",
        # _format_conversation_history
        "msg_first_conversation": "（这是第一次对话）",
        "msg_user_label": "用户",
        "msg_me_label": "我",
        # _format_team_status
        "decision_team_status": "团队状态",
        # decide_next_action prompt
        "msg_target_unspecified": "未指定",
        "decision_no_outstanding": "（无）",
        # decide
        "msg_weapon_complete": "[武器大师] 任务完成: {status}",
        # decide_next_action error
        "msg_decision_error": "决策异常，终止执行",
    },
}


class AttackLeader(AgentBase):
    AGENT_ID = "leader"

    def __init__(self, config: AttackLeaderConfig, comm_bus=None, blackboard=None, agent_pool=None):
        self.config = config
        self.system_prompt = config.system_prompt
        self.messages = []
        self.messages_lock = threading.Lock()

        # 加载工具能力摘要（仅用 config 解析工具列表，不需要完整 WeaponMaster 实例）
        tool_config = AttackToolMasterConfig()
        self._tool_categories = tool_config.tool_categories

        self.context = {
            "target": "",
            "scope": [],
            "user_request": "",
            "action_count": 0,
            "history": [],
            "conversation_history": [],
            "last_result_summary": "",
            "no_progress_count": 0,
            "findings": {
                "subdomains": [],
                "ports": {},
                "directories": [],
                "vulnerabilities": [],
                "credentials": [],
                "other": []
            },
            "consecutive_failures": 0
        }

        self.rules = HardcodedRules()

        self.agent_pool = agent_pool
        self._last_dispatched_instruction = ""
        self._last_confirmed_step = -1  # 防止 check_loop_limit 重复确认

        # 回调
        self._on_progress: Optional[Callable] = None
        self.on_need_confirm: Optional[Callable] = None
        self._on_need_input: Optional[Callable] = None
        self._stream_callback: Optional[Callable] = None

        if comm_bus and blackboard:
            super().__init__(comm_bus, blackboard, agent_pool=agent_pool)

    def _msg(self, key: str, **kwargs) -> str:
        template = MESSAGES["zh"].get(key, key)
        return template.format(**kwargs) if kwargs else template

    @property
    def on_progress(self) -> Optional[Callable]:
        return self._on_progress

    @on_progress.setter
    def on_progress(self, callback: Optional[Callable]):
        self._on_progress = callback

    @property
    def stream_callback(self) -> Optional[Callable]:
        return self._stream_callback

    @stream_callback.setter
    def stream_callback(self, callback: Optional[Callable]):
        self._stream_callback = callback

    @property
    def on_need_input(self) -> Optional[Callable]:
        return self._on_need_input

    @on_need_input.setter
    def on_need_input(self, callback: Optional[Callable]):
        self._on_need_input = callback

    # ── LLM 调用 ────────────────────────────────────────────

    def get_response(self) -> str:
        """获取 LLM 响应，带截断和重试机制"""
        token_counter = get_token_counter()
        context_limit = self.config.provider.get_context_limit()
        max_tokens = int(context_limit * 0.9)
        messages = self.messages.copy()
        current_tokens = token_counter.count_messages(messages)

        if current_tokens > max_tokens:
            self._notify_progress(self._msg("msg_truncating"))
            system_messages = [msg for msg in messages if msg["role"] == "system"]
            other_messages = [msg for msg in messages if msg["role"] != "system"]
            truncated_messages = []
            accumulated_tokens = token_counter.count_messages(system_messages)
            for msg in reversed(other_messages):
                msg_tokens = token_counter.count_messages([msg])
                if accumulated_tokens + msg_tokens > max_tokens:
                    break
                truncated_messages.append(msg)
                accumulated_tokens += msg_tokens
            messages = system_messages + list(reversed(truncated_messages))

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._notify_progress(self._msg("msg_calling_model", model=self.config.model, attempt=attempt + 1, max_retries=max_retries))
                if self._stream_callback:
                    response_text = ""
                    for chunk in self.config.provider.chat_stream(messages):
                        self._stream_callback(chunk)
                        response_text += chunk
                else:
                    response_text = self.config.provider.chat(messages)
                self._notify_progress(self._msg("msg_model_complete"))
                return response_text
            except Exception as e:
                error_msg = str(e)
                write_to_logs(f"LLM API 调用失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")

                if attempt < max_retries - 1:
                    import time
                    wait_time = (attempt + 1) * 2
                    self._notify_progress(self._msg("msg_api_retry", wait_time=wait_time))
                    time.sleep(wait_time)
                else:
                    self._notify_progress(self._msg("msg_api_failed", error=error_msg))
                    raise Exception(f"LLM API 调用失败（已重试{max_retries}次）: {error_msg}")

    def _notify_progress(self, message: str):
        if self.on_progress:
            self.on_progress(message)
        print(message)

    def _notify_message(self, message: str):
        if self.on_progress:
            self.on_progress(self._msg("msg_reply", message=message))
        print(self._msg("msg_reply", message=message))

    # ── 上下文初始化 ─────────────────────────────────────────

    def init_context(self, user_request: str):
        """初始化上下文：解析用户请求得到 target、scope 等"""
        self.context["user_request"] = user_request

        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""
{self._msg("init_parse_request")}

{self._msg("init_user_request")}: {user_request}

{self._msg("init_return_json")}:
{{
    "target": "{self._msg("init_target_desc")}",
    "scope": ["{self._msg("init_scope_desc")}"],
    "request_type": "{self._msg("init_request_type_desc")}",
    "specific_requirements": ["{self._msg("init_specific_requirements_desc")}"]
}}
"""}
        ]

        try:
            response = self.get_response()
            parsed = json.loads(response)
            self.context["target"] = parsed.get("target") or ""
            self.context["scope"] = parsed.get("scope") or []
            self.context["request_type"] = parsed.get("request_type") or "full_pentest"
            self.context["specific_requirements"] = parsed.get("specific_requirements") or []
        except (json.JSONDecodeError, Exception):
            self.context["target"] = user_request.strip() or ""
            self.context["scope"] = [user_request.strip()] if user_request.strip() else []
            self.context["request_type"] = "full_pentest"
            self.context["specific_requirements"] = []

    # ── 格式化辅助 ───────────────────────────────────────────

    def _summarize_findings(self) -> str:
        f = self.context["findings"]
        parts = []
        for key, val in f.items():
            if isinstance(val, list) and val:
                parts.append(f"{key}: {len(val)} 项")
            elif isinstance(val, dict) and val:
                parts.append(f"{key}: {len(val)} 项")
        return "; ".join(parts) if parts else self._msg("msg_no_findings")

    def _format_task_state(self, outstanding_dict: dict) -> str:
        """构建结构化任务状态反馈，按 已完成/运行中/超时 分组"""
        from datetime import datetime

        if not outstanding_dict:
            return "当前无任务。"

        completed, pending, timeout = [], [], []
        for task_id, task in outstanding_dict.items():
            elapsed = (datetime.now() - task.sent_at).total_seconds()
            instr = task.instruction[:100]
            if task.status == "COMPLETED":
                completed.append(f"  ✅ {instr} (耗时 {elapsed:.0f}s)")
            elif task.status == "TIMEOUT":
                timeout.append(f"  ❌ {instr} (超时 {elapsed:.0f}s)")
            else:
                pending.append(f"  ⏳ {instr} (运行中 {elapsed:.0f}s)")

        parts = []
        if completed:
            parts.append("### 已完成\n" + "\n".join(completed))
        if pending:
            parts.append("### 运行中\n" + "\n".join(pending))
        if timeout:
            parts.append("### 超时/失败\n" + "\n".join(timeout))
        return "\n\n".join(parts) if parts else "当前无任务。"

    def _get_available_capabilities(self) -> str:
        """获取武器大师的能力摘要（类别级别）"""
        categories = self._tool_categories
        if not categories:
            return "武器大师可执行各类 Kali 安全工具和自定义脚本。"

        lines = ["武器大师可处理以下类型的任务："]
        for cat_name, tools in categories.items():
            lines.append(f"- {cat_name}（{len(tools)} 个工具）")
        lines.append("")
        lines.append("你不需要指定具体工具。用自然语言描述你想完成什么，武器大师会选择最佳工具。")
        return "\n".join(lines)

    def _format_recent_history(self, n: int = 5) -> str:
        history = self.context.get("history", [])
        if not history:
            return self._msg("msg_none")

        recent = history[-n:]
        lines = []
        for h in recent:
            instruction = h.get('instruction', '未知操作')
            status = h.get('status', 'unknown')
            summary = h.get('summary', '')[:100]
            lines.append(f"{self._msg('msg_step', step=h['step'])}: [{status}] {instruction}\n  {self._msg('msg_result')}: {summary}")
        return "\n".join(lines)

    def _format_conversation_history(self) -> str:
        conversation_history = self.context.get("conversation_history", [])
        if not conversation_history:
            return self._msg("msg_first_conversation")

        lines = []
        for msg in conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"{self._msg('msg_user_label')}: {content}")
            elif role == "assistant":
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"{self._msg('msg_me_label')}: {content}")
        return "\n".join(lines)

    def _format_team_status(self, team_status: dict) -> str:
        if not team_status:
            return ""
        name_map = {
            "leader": "渗透专家",
            "tool_master": "武器大师",
            "data_analyst": "数据分析员",
            "hawkeye": "鹰眼",
        }
        lines = []
        for aid, qsize in team_status.items():
            name = name_map.get(aid, aid)
            busy = qsize > 0
            status = "busy" if busy else "idle"
            lines.append(f"- {name} ({aid}): {status}")
        return f"## {self._msg('decision_team_status')}\n" + "\n".join(lines) if lines else ""

    # ── 上下文更新 ───────────────────────────────────────────

    def update_context_with_result(self, result: dict, instruction: str = ""):
        """根据任务结果更新上下文（含去重）"""
        self.context["action_count"] = self.context.get("action_count", 0) + 1

        if "history" not in self.context:
            self.context["history"] = []

        self.context["history"].append({
            "step": self.context["action_count"],
            "task_id": result.get("task_id"),
            "instruction": instruction,
            "status": result.get("status"),
            "summary": result.get("summary", "")[:200],
            "content": result.get("raw_output", "") or result.get("content", ""),
            "timestamp": str(self.context["action_count"])
        })

        content = result.get("raw_output", "") or result.get("content", "")
        summary = result.get("summary", "")
        self.context["last_result_summary"] = (content or summary)[:500]

        if result.get("status") == "success":
            self.context["consecutive_failures"] = 0
            self.context["no_progress_count"] = 0

            findings = result.get("findings") or {}
            for k, v in findings.items():
                if k in self.context["findings"]:
                    existing = self.context["findings"][k]
                    if isinstance(existing, list):
                        # 去重：逐项检查不在列表中才添加
                        new_items = v if isinstance(v, list) else [v]
                        for item in new_items:
                            if item not in existing:
                                existing.append(item)
                    elif isinstance(existing, dict):
                        new_dict = v if isinstance(v, dict) else {}
                        existing.update(new_dict)

        elif result.get("status") == "failed":
            self.context["consecutive_failures"] = self.context.get("consecutive_failures", 0) + 1
            if not result.get("findings") or not any(result.get("findings", {}).values()):
                self.context["no_progress_count"] = self.context.get("no_progress_count", 0) + 1

    # ── 核心决策 ─────────────────────────────────────────────

    def decide_next_action(self, outstanding_tasks: str = "", team_status: dict = None,
                           wakeup_text: str = "") -> dict:
        """根据当前上下文决定下一步行动（纯 LLM 决策，不做规则检查）"""
        team_status = team_status or {}

        user_request = self.context.get("user_request", "")
        findings_summary = self._summarize_findings()
        available_tools = self._get_available_capabilities()
        team_status_text = self._format_team_status(team_status)
        recent_history = self._format_recent_history(5)
        last_result = self.context.get('last_result_summary', '')[:500]

        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""## 用户请求
"{user_request}"

{wakeup_text}
## 当前状态
- 目标: {self.context['target'] or self._msg("msg_target_unspecified")}
- 已执行: {self.context['action_count']} 步
- 发现: {findings_summary}

{team_status_text}

## 任务状态
{outstanding_tasks or self._msg("decision_no_outstanding")}

{f"## 已执行操作{chr(10)}{recent_history}" if self.context['action_count'] > 0 else ""}
{f"## 上一步结果{chr(10)}{last_result}" if last_result else ""}

## 能力
{available_tools}

---
返回 JSON:

{{
    "type": "complete",
    "reason": "对用户说的话（汇报结果）"
}}

{{
    "type": "execute_task",
    "target": "tool_master",
    "instruction": "告诉武器大师要做什么",
    "reason": "为什么要这么做"
}}

{{
    "type": "wait",
    "reason": "为什么等待（例如：端口扫描进行中，等结果出来再决定下一步）"
}}
"""}
        ]

        try:
            response = self.get_response()
            decision = json.loads(response)
            return decision
        except (json.JSONDecodeError, Exception) as e:
            write_to_logs(f"渗透专家: 决策失败 - {e}")
            return {"type": "complete", "reason": self._msg("msg_decision_error")}

    def decide(self, context: dict) -> dict:
        """AgentLoop 入口：每轮实时单步决策，LLM 自主选择 wait/execute/complete"""
        # 1. 同步用户请求
        mission = context.get("mission", {})
        if isinstance(mission, dict):
            user_request = mission.get("objective", "")
            if user_request:
                self.context["user_request"] = user_request

        # 2. 收集收件箱中的已完成结果
        new_msgs = self.drain_inbox()
        outstanding_dict = context.get("outstanding_dict", {})
        completed_parts = []
        for msg in new_msgs:
            if msg.msg_type == MSG_TASK_RESULT and msg.context_json:
                result = msg.context_json
                self.update_context_with_result(result, msg.content)
                self._notify_progress(self._msg("msg_weapon_complete", status=result.get("status", "unknown")))
                if self.agent_pool and msg.from_agent != self.AGENT_ID:
                    self.agent_pool.release(msg.from_agent)
                instr = msg.content[:80]
                summary = result.get("summary", "")[:100]
                status = result.get("status", "success")
                if status == "success":
                    completed_parts.append(f"  ✅ {instr} — {summary}")
                else:
                    completed_parts.append(f"  ❌ {instr}({status}) — {summary}")
            elif msg.msg_type == MSG_ANALYSIS_RESULT:
                self.update_context_with_result(
                    msg.context_json or {}, msg.content
                )
                if self.agent_pool and msg.from_agent != self.AGENT_ID:
                    self.agent_pool.release(msg.from_agent)
            elif msg.msg_type == MSG_INPUT_ALERT:
                self._notify_progress(f"[鹰眼] 检测到交互提示: {msg.content[:120]}")

        # 3. 首次调用时初始化上下文
        if self.context.get("action_count", 0) == 0 and self.context.get("user_request", ""):
            self.init_context(self.context["user_request"])

        # 4. 硬编码规则检查（终止/确认）
        rule_result = self.rules.check_loop_limit(self.context)
        if rule_result.should_abort:
            return {"type": "complete", "summary": rule_result.reason}

        if rule_result.need_confirm:
            current_step = self.context.get("action_count", 0)
            if current_step != self._last_confirmed_step:
                if self.on_need_confirm:
                    confirmed = self.on_need_confirm(None, rule_result.message)
                    if not confirmed:
                        return {"type": "complete", "summary": "用户终止"}
                self._last_confirmed_step = current_step
            # 确认后继续，让 LLM 决策下一行动

        # 5. 构建状态更新（已派发 + 已完成）
        wakeup_parts = []
        if self._last_dispatched_instruction:
            wakeup_parts.append(f"已派发: {self._last_dispatched_instruction}")
            self._last_dispatched_instruction = ""
        if completed_parts:
            wakeup_parts.append("已完成:")
            wakeup_parts.extend(completed_parts)
        wakeup_text = ""
        if wakeup_parts:
            wakeup_text = "## 状态更新\n" + "\n".join(wakeup_parts) + "\n"

        # 6. 构建任务状态
        task_state_text = self._format_task_state(outstanding_dict)

        # 7. 获取团队状态
        team_status = self.comm_bus.get_team_status() if self.comm_bus else {}

        # 8. LLM 决策
        decision = self.decide_next_action(
            outstanding_tasks=task_state_text,
            team_status=team_status,
            wakeup_text=wakeup_text,
        )

        # 9. 映射到 AgentLoop 格式
        return self._map_decision_to_action(decision)

    def _map_decision_to_action(self, decision: dict) -> dict:
        """将 decide_next_action() 输出映射为 AgentLoop 的 ACT 格式"""
        dtype = decision.get("type", "")
        if dtype == "complete":
            return {
                "type": "complete",
                "summary": decision.get("reason", "任务完成"),
            }
        elif dtype == "execute_task":
            target_type = decision.get("target", "tool_master")
            instruction = decision.get("instruction", "")

            self._last_dispatched_instruction = instruction

            target = target_type
            if self.agent_pool:
                iid, _agent = self.agent_pool.acquire(target_type)
                if iid:
                    target = iid
            if target == target_type and self.comm_bus:
                # 池满或无池，回退到名称前缀匹配
                agents = self.comm_bus.list_agents()
                for aid in agents:
                    if aid.startswith(f"{target_type}_"):
                        target = aid
                        break

            result = {
                "type": "delegate",
                "target": target,
                "content": instruction,
            }
            step_id = decision.get("step_id", "")
            if step_id:
                result["step_id"] = step_id
            return result
        elif dtype == "wait":
            return {"type": "wait"}
        elif dtype == "need_user_decision":
            # 用户确认：有回调则询问，拒绝→complete，确认→wait 重新决策
            if self.on_need_confirm:
                confirmed = self.on_need_confirm(
                    None,
                    decision.get("message", decision.get("reason", ""))
                )
                if not confirmed:
                    return {
                        "type": "complete",
                        "summary": decision.get("reason", decision.get("message", "")),
                    }
            return {"type": "wait"}
        return {"type": "wait"}
