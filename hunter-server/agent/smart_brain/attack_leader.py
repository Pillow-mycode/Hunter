# 渗透分析专家
import json
import threading
from typing import Callable, Optional

from agent.pojo.leader_config import (
    AttackLeaderConfig,
    SYSTEM_CLASSIFY_PROMPT,
    SYSTEM_PLAN_PROMPT,
    SYSTEM_REVIEW_PROMPT,
)
from agent.pojo.attack_config import AttackToolMasterConfig
from agent.smart_brain.attack_tool_master import AttackToolMaster
from agent.smart_brain.hardcoded_rules import HardcodedRules, RuleResult
from agent.team.agent_base import AgentBase
from agent.team.plan import Plan, PlanStep
from agent.system.system_command import write_to_logs
from agent.team.protocol import MSG_DELEGATION, MSG_TASK_RESULT, MSG_ANALYSIS_RESULT, MSG_INPUT_ALERT
from llm.token_counter import get_token_counter

"""
渗透专家模型
负责规划和协调整个渗透测试流程
"""

# 本地化消息
MESSAGES = {
    "zh": {
        "msg_truncating": "[LLM] 消息过长，正在截断...",
        "msg_calling_model": "[LLM] 正在调用模型 {model}... (尝试 {attempt}/{max_retries})",
        "msg_model_complete": "[LLM] 模型响应完成",
        "msg_api_retry": "[LLM] API 调用失败，{wait_time}秒后重试...",
        "msg_api_failed": "[LLM] API 调用失败: {error}",
        "msg_reply": "[回复] {message}",
        "msg_received_request": "[渗透专家] 收到请求: {request}",
        "msg_parsing_target": "[渗透专家] 正在解析目标...",
        "msg_target": "[渗透专家] 目标: {target}",
        "msg_target_unspecified": "未指定",
        "msg_start_decision": "[渗透专家] 开始动态决策流程...",
        "msg_decision": "[渗透专家] 决策: {reason}",
        "msg_instruction": "[渗透专家] 指令: {instruction}",
        "msg_task_complete": "[渗透专家] 任务完成: {reason}",
        "msg_task_done": "[渗透专家] 任务完成",
        "msg_pentest_complete": "[渗透专家] 渗透测试完成",
        "msg_max_steps": "[渗透专家] 达到最大步数限制",
        "msg_too_many_failures": "[渗透专家] 连续失败次数过多",
        "msg_no_progress": "[渗透专家] 连续多步无新发现",
        "msg_weapon_received": "[武器大师] 收到指令: {instruction}",
        "msg_weapon_skipped": "[武器大师] 任务被跳过: {reason}",
        "msg_weapon_aborted": "[武器大师] 任务被中止: {reason}",
        "msg_weapon_complete": "[武器大师] 任务完成: {status}",
        "msg_weapon_result": "[武器大师] 结果: {summary}",
        "msg_weapon_executing": "[武器大师] 执行任务 {task_id}: {action} -> {target}",
        "msg_weapon_task_skipped": "[武器大师] 任务 {task_id} 被跳过: {reason}",
        "msg_weapon_task_aborted": "[武器大师] 任务 {task_id} 被中止: {reason}",
        "msg_weapon_task_complete": "[武器大师] 任务 {task_id} 完成: {status}",
        "msg_weapon_task_result": "[武器大师] 结果: {summary}",
        "msg_need_confirm": "需要确认",
        "msg_user_skipped": "用户跳过",
        "msg_user_skipped_input": "用户跳过输入",
        "msg_scan_complete_findings": "扫描完成，发现以上信息。",
        "msg_scan_complete_no_findings": "扫描完成，未发现明显问题。",
        "msg_fix_vulnerabilities": "建议修复发现的漏洞",
        "msg_close_ports": "建议关闭不必要的开放端口",
        "msg_no_findings": "暂无发现",
        "msg_first_conversation": "（这是第一次对话）",
        "msg_user_label": "用户",
        "msg_me_label": "我",
        "msg_no_tools": "无可用工具",
        "msg_custom_tools_header": "### 自定义工具（需要先阅读文档）",
        "msg_kali_tools_header": "### Kali 自带工具（可直接使用）",
        "msg_scan_done": "已执行扫描",
        "msg_none": "无",
        "msg_step": "步骤{step}",
        "msg_result": "结果",
        "msg_decision_error": "决策异常，终止执行",
        "msg_need_info": "武器大师需要信息",
        "msg_input_skip": "请输入 (输入 'skip' 跳过此任务)",
        "msg_continue_confirm": "是否继续? (y/n)",
        "msg_task_label": "任务",
        # 决策提示词
        "decision_user_request": "用户原始请求",
        "decision_conversation_history": "对话历史",
        "decision_current_status": "当前状态",
        "decision_target": "目标",
        "decision_steps_executed": "已执行步骤",
        "decision_current_findings": "当前发现",
        "decision_executed_operations": "已执行的操作",
        "decision_last_result": "上一步详细结果",
        "decision_available_tools": "可用工具",
        "decision_think_like_human": "请像人一样思考",
        "decision_q1": "用户想要什么？",
        "decision_q2": "我已经做了什么？得到了什么结果？",
        "decision_q3": "用户的需求满足了吗？",
        "decision_important_principles": "重要原则",
        "decision_no_repeat": "不要重复执行已经做过的操作（查看'已执行的操作'）",
        "decision_no_same_retry": "如果某个操作失败了，不要用相同的方法重试，要换一种方法或放弃",
        "decision_stop_if_stuck": "如果已经尽力尝试但无法获取更多信息，就停止并汇报当前结果",
        "decision_return_json": "返回 JSON",
        "decision_complete_desc": "需求已满足，或无法继续",
        "decision_complete_reason": "对用户说的话（汇报结果）",
        "decision_continue_desc": "需求未满足，继续执行新操作",
        "decision_instruction_desc": "告诉武器大师要做什么（必须是之前没做过的操作）",
        "decision_reason_desc": "为什么要这么做",
        "decision_outstanding_tasks": "未完成的任务",
        "decision_team_status": "团队状态",
        "decision_no_outstanding": "（无）",
        "decision_parallel_hint": "提示：你可以同时向不同 Agent 派发任务。武器大师忙时，可以先让数据分析员处理已有结果，或让鹰眼监控终端。不要向同一个忙碌的 Agent 重复派发任务。",
        # 初始化上下文提示词
        "init_parse_request": "请解析以下用户请求，提取目标和范围信息。",
        "init_user_request": "用户请求",
        "init_return_json": "返回 JSON 格式",
        "init_target_desc": "主要目标（域名或 IP，若无则空字符串）",
        "init_scope_desc": "目标范围列表",
        "init_request_type_desc": "请求类型（full_pentest/vulnerability_scan/specific_test）",
        "init_specific_requirements_desc": "特殊要求列表",
    },
}


class AttackLeader(AgentBase):
    AGENT_ID = "leader"

    def __init__(self, config: AttackLeaderConfig, comm_bus=None, blackboard=None):
        self.config = config
        self.system_prompt = config.system_prompt
        self.messages = []
        self.messages_lock = threading.Lock()

        weapon_config = AttackToolMasterConfig()
        self.weapon_master = AttackToolMaster(weapon_config)

        self.context = {
            "target": "",
            "scope": [],
            "user_request": "",
            "action_count": 0,  # 执行步骤计数
            "history": [],  # 执行历史
            "conversation_history": [],  # 对话历史（用户和渗透专家的对话）
            "last_result_summary": "",  # 上一步结果摘要
            "no_progress_count": 0,  # 无进展计数
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

        # 状态机（AgentLoop decide() 路径使用）
        self.state = "idle"  # idle | executing | reviewing | complete
        self.active_plan: Optional[Plan] = None
        self.agent_pool = None  # P3: AgentPool 引用，None 时回退到串行模式

        # 回调函数
        self._on_progress: Optional[Callable] = None
        self.on_need_confirm: Optional[Callable] = None
        self._on_need_input: Optional[Callable] = None
        self._stream_callback: Optional[Callable] = None

        if comm_bus and blackboard:
            super().__init__(comm_bus, blackboard)

    def _msg(self, key: str, **kwargs) -> str:
        """获取本地化消息"""
        template = MESSAGES["zh"].get(key, key)
        return template.format(**kwargs) if kwargs else template

    @property
    def on_progress(self) -> Optional[Callable]:
        return self._on_progress

    @on_progress.setter
    def on_progress(self, callback: Optional[Callable]):
        """设置进度回调，同时传递给武器大师"""
        self._on_progress = callback
        self.weapon_master.on_progress = callback

    @property
    def stream_callback(self) -> Optional[Callable]:
        return self._stream_callback

    @stream_callback.setter
    def stream_callback(self, callback: Optional[Callable]):
        """设置流式回调，同时传递给武器大师"""
        self._stream_callback = callback
        self.weapon_master.stream_callback = callback

    @property
    def on_need_input(self) -> Optional[Callable]:
        return self._on_need_input

    @on_need_input.setter
    def on_need_input(self, callback: Optional[Callable]):
        """设置输入回调，同时传递给武器大师"""
        self._on_need_input = callback
        self.weapon_master.on_need_input = callback

    def get_response(self) -> str:
        """获取 LLM 响应，带重试机制"""
        token_counter = get_token_counter()
        context_limit = self.config.provider.get_context_limit()
        max_tokens = int(context_limit * 0.9)  # 留 10% 给响应
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

        # 重试机制
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
                    # 还有重试机会
                    import time
                    wait_time = (attempt + 1) * 2  # 递增等待时间：2秒、4秒、6秒
                    self._notify_progress(self._msg("msg_api_retry", wait_time=wait_time))
                    time.sleep(wait_time)
                else:
                    # 最后一次尝试也失败了
                    self._notify_progress(self._msg("msg_api_failed", error=error_msg))
                    raise Exception(f"LLM API 调用失败（已重试{max_retries}次）: {error_msg}")

    def _notify_progress(self, message: str):
        """发送进度通知"""
        if self.on_progress:
            self.on_progress(message)
        print(message)

    def _reset_operation_state(self):
        """重置操作相关的状态，保留对话历史"""
        # 保存对话历史
        conversation_history = self.context.get("conversation_history", [])

        # 重置操作状态
        self.context["target"] = ""
        self.context["scope"] = []
        self.context["user_request"] = ""
        self.context["action_count"] = 0
        self.context["history"] = []
        self.context["last_result_summary"] = ""
        self.context["no_progress_count"] = 0
        self.context["findings"] = {
            "subdomains": [],
            "ports": {},
            "directories": [],
            "vulnerabilities": [],
            "credentials": [],
            "other": []
        }
        self.context["consecutive_failures"] = 0

        # 恢复对话历史
        self.context["conversation_history"] = conversation_history

        # 清空消息历史（LLM 对话）
        self.messages = []

    def _notify_message(self, message: str):
        """发送对话消息（显示给用户的回复）"""
        if self.on_progress:
            # 用特殊前缀标记这是对话消息
            self.on_progress(self._msg("msg_reply", message=message))
        print(self._msg("msg_reply", message=message))

    def run(self, user_request: str) -> dict:
        """执行渗透测试，返回报告字典"""
        write_to_logs(f"渗透专家: 收到用户请求 - {user_request}")
        self._notify_progress(self._msg("msg_received_request", request=user_request))

        # 保存用户消息到对话历史
        self.context["conversation_history"].append({
            "role": "user",
            "content": user_request
        })

        # 重置操作相关的状态（保留 conversation_history）
        # 这确保每个新请求都是独立的扫描任务
        self._reset_operation_state()

        # 初始化上下文
        self._notify_progress(self._msg("msg_parsing_target"))
        self.init_context(user_request)

        target = self.context.get("target") or ""
        self._notify_progress(self._msg("msg_target", target=target or self._msg("msg_target_unspecified")))

        # 授权检查
        auth_result = self.rules.check_target_authorization(target)
        if auth_result.should_abort:
            return {
                "status": "aborted",
                "reason": auth_result.reason,
                "report": None
            }

        # 动态决策循环
        self._notify_progress(self._msg("msg_start_decision"))
        while not self.is_mission_complete():
            # 决定下一步行动
            decision = self.decide_next_action()

            if decision["type"] == "execute_task":
                # 执行任务 - 使用自然语言指令
                instruction = decision.get("instruction", "")
                self._notify_progress(self._msg("msg_decision", reason=decision.get('reason', '')))
                self._notify_progress(self._msg("msg_instruction", instruction=instruction))
                result = self.execute_task_with_instruction(instruction)

                # 更新上下文（传入指令用于历史记录）
                self.update_context_with_result(result, instruction)

            elif decision["type"] == "complete":
                reason = decision.get('reason', '')
                self._notify_progress(self._msg("msg_task_complete", reason=reason))
                # 保存决策原因，用于生成简洁的报告
                self.context["last_decision_reason"] = reason

                # 保存渗透专家的回复到对话历史
                self.context["conversation_history"].append({
                    "role": "assistant",
                    "content": reason
                })
                break

            elif decision["type"] == "need_user_decision":
                confirmed = self.wait_for_confirm(None, decision.get("message", self._msg("msg_need_confirm")))
                if not confirmed:
                    break

        # 生成报告
        action_count = self.context.get("action_count", 0)

        # 如果没有执行任何操作，说明是简单对话或LLM直接回答的问题
        if action_count == 0:
            # 检查是否有决策记录
            last_decision_reason = self.context.get("last_decision_reason", "")
            if last_decision_reason:
                # LLM直接给出了答案（如MD5破解）
                self._notify_progress(self._msg("msg_task_done"))
                return {
                    "status": "completed",
                    "report": {
                        "summary": last_decision_reason,
                        "conclusion": "",
                        "findings": {},
                        "recommendations": []
                    }
                }

        # 正常的渗透测试报告
        self._notify_progress(self._msg("msg_pentest_complete"))
        summary = self._generate_summary()
        conclusion = self._generate_conclusion()
        recommendations = self._generate_recommendations()

        return self._report_completed(summary, conclusion, recommendations)

    def _report_completed(self, summary: str, conclusion: str, recommendations: list) -> dict:
        return {
            "status": "completed",
            "report": {
                "summary": summary,
                "conclusion": conclusion,
                "findings": self.context["findings"],
                "recommendations": recommendations
            }
        }

    def _generate_conclusion(self) -> str:
        """根据执行情况生成结论"""
        action_count = self.context.get("action_count", 0)
        findings = self.context["findings"]
        has_findings = any(
            isinstance(v, list) and len(v) > 0 or isinstance(v, dict) and len(v) > 0
            for v in findings.values()
        )

        # 如果执行了操作且有发现
        if action_count > 0 and has_findings:
            return self._msg("msg_scan_complete_findings")

        # 如果执行了操作但没有发现
        if action_count > 0:
            return self._msg("msg_scan_complete_no_findings")

        # 如果没有执行操作
        return ""

    def _generate_recommendations(self) -> list:
        """生成建议列表"""
        action_count = self.context.get("action_count", 0)

        # 如果没有执行操作，不生成建议
        if action_count == 0:
            return []

        rec = []
        if self.context["findings"].get("vulnerabilities"):
            rec.append(self._msg("msg_fix_vulnerabilities"))
        if self.context["findings"].get("ports"):
            rec.append(self._msg("msg_close_ports"))

        return rec

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

    def _summarize_findings(self) -> str:
        """汇总当前发现，供后续提示使用"""
        f = self.context["findings"]
        parts = []
        for key, val in f.items():
            if isinstance(val, list) and val:
                parts.append(f"{key}: {len(val)} 项")
            elif isinstance(val, dict) and val:
                parts.append(f"{key}: {len(val)} 项")
        return "; ".join(parts) if parts else self._msg("msg_no_findings")

    def _get_available_tools_summary(self) -> str:
        """获取可用工具摘要（包含详细描述）"""
        tools = self.weapon_master.tools
        if not tools:
            return self._msg("msg_no_tools")

        # 按类型分组
        kali_tools = []
        custom_tools = []

        for tool in tools:
            tool_type = tool.get("type", "KALI")
            tool_name = tool.get("name", "")
            tool_desc = tool.get("description", "")

            # 格式化工具信息
            tool_info = f"  - {tool_name}: {tool_desc}"

            if tool_type == "CUSTOM":
                custom_tools.append(tool_info)
            else:
                kali_tools.append(tool_info)

        result = []

        if custom_tools:
            result.append(self._msg("msg_custom_tools_header"))
            result.extend(custom_tools)
            result.append("")

        if kali_tools:
            result.append(self._msg("msg_kali_tools_header"))
            result.extend(kali_tools)

        return "\n".join(result)

    def wait_for_input(self, prompt: str) -> Optional[str]:
        """等待用户输入"""
        if self._on_need_input:
            return self._on_need_input(prompt)

        # CLI 模式
        print(f"\n{'='*50}")
        print(f"{self._msg('msg_need_info')}: {prompt}")
        print(f"{'='*50}")
        response = input(self._msg("msg_input_skip") + ": ").strip()
        if response.lower() == 'skip':
            return None
        return response

    def _format_recent_history(self, n: int = 5) -> str:
        """格式化最近N步的历史记录"""
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
        """格式化对话历史"""
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
                # 截断过长的回复
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"{self._msg('msg_me_label')}: {content}")

        return "\n".join(lines)

    def _format_team_status(self, team_status: dict) -> str:
        """格式化团队状态为提示词文本"""
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

    def _generate_summary(self) -> str:
        """生成执行摘要"""
        history = self.context.get("history", [])
        if not history:
            return ""

        summaries = []
        for h in history:
            if h.get("status") == "success":
                # 优先使用详细内容（content），如果没有则使用摘要（summary）
                content = h.get('content', '')
                summary = h.get('summary', '')

                # 使用详细内容，如果太长则截断
                if content:
                    result_text = content[:500] if len(content) > 500 else content
                elif summary:
                    result_text = summary[:200]
                else:
                    result_text = self._msg("msg_scan_done")

                summaries.append(result_text)

        return "\n".join(summaries) if summaries else self._msg("msg_scan_done")

    def is_mission_complete(self) -> bool:
        """
        判断任务是否完成

        Returns:
            True 如果任务完成，False 否则
        """
        # 检查是否达到最大步数
        if self.context.get("action_count", 0) >= 50:
            self._notify_progress(self._msg("msg_max_steps"))
            return True

        # 检查连续失败次数
        if self.context.get("consecutive_failures", 0) >= 5:
            self._notify_progress(self._msg("msg_too_many_failures"))
            return True

        # 检查无进展次数（相同输出重复出现）
        if self.context.get("no_progress_count", 0) >= 5:
            self._notify_progress(self._msg("msg_no_progress"))
            return True

        return False

    def update_context_with_result(self, result: dict, instruction: str = ""):
        """
        根据任务结果更新上下文

        Args:
            result: 任务执行结果
            instruction: 执行的指令
        """
        # 增加执行计数
        self.context["action_count"] = self.context.get("action_count", 0) + 1

        # 记录历史
        if "history" not in self.context:
            self.context["history"] = []

        self.context["history"].append({
            "step": self.context["action_count"],
            "task_id": result.get("task_id"),
            "instruction": instruction,  # 保存执行的指令
            "status": result.get("status"),
            "summary": result.get("summary", "")[:200],
            "content": result.get("raw_output", "") or result.get("content", ""),
            "timestamp": str(self.context["action_count"])
        })

        # 保存上一步结果（优先使用详细内容）
        content = result.get("raw_output", "") or result.get("content", "")
        summary = result.get("summary", "")
        self.context["last_result_summary"] = (content or summary)[:500]

        # 更新发现
        if result.get("status") == "success":
            self.context["consecutive_failures"] = 0

            self.context["no_progress_count"] = 0

            findings = result.get("findings") or {}
            for k, v in findings.items():
                if k in self.context["findings"]:
                    if isinstance(self.context["findings"][k], list):
                        new_items = v if isinstance(v, list) else [v]
                        self.context["findings"][k].extend(new_items)
                    elif isinstance(self.context["findings"][k], dict):
                        new_dict = v if isinstance(v, dict) else {}
                        self.context["findings"][k].update(new_dict)

        elif result.get("status") == "failed":
            self.context["consecutive_failures"] = self.context.get("consecutive_failures", 0) + 1

            # 检查是否有新发现
            if not result.get("findings") or not any(result.get("findings", {}).values()):
                self.context["no_progress_count"] = self.context.get("no_progress_count", 0) + 1

    def execute_task_with_instruction(self, instruction: str) -> dict:
        """
        使用自然语言指令执行任务

        Args:
            instruction: 自然语言指令，例如 "使用 nmap 扫描 example.com 的端口"

        Returns:
            任务执行结果
        """
        task_id = f"task_{self.context.get('action_count', 0) + 1}"
        self._notify_progress(self._msg("msg_weapon_received", instruction=instruction))

        # 构造简化的任务结构
        task = {
            "task_id": task_id,
            "action": "execute_instruction",  # 通用 action
            "target": self.context.get("target", ""),
            "params": {"instruction": instruction}
        }

        # 硬编码规则检查（基于指令内容）
        rule_result = self.rules.check_instruction(instruction, self.context)
        if rule_result.should_skip:
            self._notify_progress(self._msg("msg_weapon_skipped", reason=rule_result.reason))
            return {
                "task_id": task_id,
                "status": "skipped",
                "summary": rule_result.reason,
                "findings": {}
            }

        if rule_result.should_abort:
            self._notify_progress(self._msg("msg_weapon_aborted", reason=rule_result.reason))
            return {
                "task_id": task_id,
                "status": "aborted",
                "summary": rule_result.reason,
                "findings": {}
            }

        if rule_result.need_confirm:
            confirmed = self.wait_for_confirm(None, rule_result.message)
            if not confirmed:
                return {
                    "task_id": task_id,
                    "status": "skipped",
                    "summary": self._msg("msg_user_skipped"),
                    "findings": {}
                }

        # 调用武器大师执行
        try:
            result = self.weapon_master.run(task)

            # 处理需要用户输入的情况
            max_input_rounds = 5
            input_round = 0
            while result.get("status") == "need_input" and input_round < max_input_rounds:
                input_round += 1
                required_input = result.get("required_input") or result.get("summary", "请提供信息")
                user_input = self.wait_for_input(required_input)

                if user_input is None:
                    result = {
                        "task_id": task_id,
                        "status": "skipped",
                        "summary": self._msg("msg_user_skipped_input"),
                        "findings": {}
                    }
                    break
                else:
                    result = self.weapon_master.continue_with_input(user_input)

            task_status = result.get("status", "unknown")
            task_summary = result.get("summary", "")[:100]
            self._notify_progress(self._msg("msg_weapon_complete", status=task_status))
            if task_summary:
                self._notify_progress(self._msg("msg_weapon_result", summary=task_summary))

            return result

        except Exception as e:
            write_to_logs(f"渗透专家: 任务执行异常 - {e}")
            return {
                "task_id": task_id,
                "status": "failed",
                "summary": str(e),
                "findings": {}
            }

    def execute_single_task(self, task: dict) -> dict:
        """
        执行单个任务

        Args:
            task: 任务字典

        Returns:
            任务执行结果
        """
        task_id = task.get("task_id", "unknown")
        action = task.get("action", "unknown")
        target = task.get("target", "")

        self._notify_progress(self._msg("msg_weapon_executing", task_id=task_id, action=action, target=target))

        # 硬编码规则检查
        rule_result = self.rules.check(task, self.context)
        if rule_result.should_skip:
            self._notify_progress(self._msg("msg_weapon_task_skipped", task_id=task_id, reason=rule_result.reason))
            return {
                "task_id": task_id,
                "status": "skipped",
                "summary": rule_result.reason,
                "findings": {}
            }

        if rule_result.should_abort:
            self._notify_progress(self._msg("msg_weapon_task_aborted", task_id=task_id, reason=rule_result.reason))
            return {
                "task_id": task_id,
                "status": "aborted",
                "summary": rule_result.reason,
                "findings": {}
            }

        if rule_result.need_confirm:
            confirmed = self.wait_for_confirm(task, rule_result.message)
            if not confirmed:
                return {
                    "task_id": task_id,
                    "status": "skipped",
                    "summary": self._msg("msg_user_skipped"),
                    "findings": {}
                }

        # 调用武器大师执行
        try:
            result = self.weapon_master.run(task)

            # 处理需要用户输入的情况
            max_input_rounds = 5
            input_round = 0
            while result.get("status") == "need_input" and input_round < max_input_rounds:
                input_round += 1
                required_input = result.get("required_input") or result.get("summary", "请提供信息")
                user_input = self.wait_for_input(required_input)

                if user_input is None:
                    result = {
                        "task_id": task_id,
                        "status": "skipped",
                        "summary": self._msg("msg_user_skipped_input"),
                        "findings": {}
                    }
                    break
                else:
                    result = self.weapon_master.continue_with_input(user_input)

            task_status = result.get("status", "unknown")
            task_summary = result.get("summary", "")[:100]
            self._notify_progress(self._msg("msg_weapon_task_complete", task_id=task_id, status=task_status))
            if task_summary:
                self._notify_progress(self._msg("msg_weapon_task_result", summary=task_summary))

            return result

        except Exception as e:
            write_to_logs(f"渗透专家: 任务执行异常 - {e}")
            return {
                "task_id": task_id,
                "status": "failed",
                "summary": str(e),
                "findings": {}
            }

    def decide_next_action(self, outstanding_tasks: str = "", team_status: dict = None) -> dict:
        """
        根据当前上下文决定下一步行动

        Args:
            outstanding_tasks: 格式化后的未完成任务列表字符串
            team_status: 各 Agent 收件箱队列深度 {"leader": 0, "tool_master": 2, ...}

        Returns:
            {
                "type": "execute_task" / "complete" / "need_user_decision",
                "task": {...},  # 如果是 execute_task
                "reason": "决策理由",
                "message": "消息"  # 如果是 need_user_decision
            }
        """
        team_status = team_status or {}
        # 1. 硬编码规则检查
        rule_result = self.rules.check_loop_limit(self.context)
        if rule_result.should_abort:
            return {"type": "complete", "reason": rule_result.reason}

        if rule_result.need_confirm:
            return {
                "type": "need_user_decision",
                "message": rule_result.message,
                "reason": rule_result.reason
            }

        # 2. 构造决策提示词
        recent_history = self._format_recent_history(5)
        findings_summary = self._summarize_findings()

        # 获取可用工具列表
        available_tools = self._get_available_tools_summary()

        # 格式化对话历史
        conversation_context = self._format_conversation_history()

        # 获取用户原始请求
        user_request = self.context.get("user_request", "")

        # 构建团队状态文本
        team_status_text = self._format_team_status(team_status)

        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""
## {self._msg("decision_user_request")}
"{user_request}"

## {self._msg("decision_conversation_history")}
{conversation_context}

## {self._msg("decision_current_status")}
- {self._msg("decision_target")}: {self.context['target'] or self._msg("msg_target_unspecified")}
- {self._msg("decision_steps_executed")}: {self.context['action_count']}
- {self._msg("decision_current_findings")}: {findings_summary}

{team_status_text}

## {self._msg("decision_outstanding_tasks")}
{outstanding_tasks or self._msg("decision_no_outstanding")}

{f"## {self._msg('decision_executed_operations')}{chr(10)}{recent_history}" if self.context['action_count'] > 0 else ""}

{f"## {self._msg('decision_last_result')}{chr(10)}{self.context.get('last_result_summary', '')[:500]}" if self.context.get('last_result_summary') else ""}

## {self._msg("decision_available_tools")}
{available_tools}

---

{self._msg("decision_think_like_human")}:

1. {self._msg("decision_q1")}
2. {self._msg("decision_q2")}
3. {self._msg("decision_q3")}
4. 用户问的具体问题已经得到答案了吗？如果上一步结果直接回答了用户的问题，就应该 complete，不要再继续。

**{self._msg("decision_important_principles")}:**
- {self._msg("decision_no_repeat")}
- {self._msg("decision_no_same_retry")}
- {self._msg("decision_stop_if_stuck")}
- 用户问什么就答什么。如果用户问"IP是多少"，拿到IP就完成。不要画蛇添足继续扫描。
- {self._msg("decision_parallel_hint")}

{self._msg("decision_return_json")}:

{self._msg("decision_complete_desc")}:
{{
    "type": "complete",
    "reason": "{self._msg("decision_complete_reason")}"
}}

{self._msg("decision_continue_desc")}:
{{
    "type": "execute_task",
    "target": "tool_master",
    "instruction": "{self._msg("decision_instruction_desc")}",
    "reason": "{self._msg("decision_reason_desc")}"
}}
（target 可选: tool_master（执行工具命令）、data_analyst（分析长输出）、hawkeye（监控终端交互））
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
        # 从 AgentLoop 上下文同步用户请求
        mission = context.get("mission", {})
        if isinstance(mission, dict):
            user_request = mission.get("objective", "")
            if user_request:
                self.context["user_request"] = user_request

        # 处理收件箱
        new_msgs = self.drain_inbox()
        for msg in new_msgs:
            if msg.msg_type == MSG_TASK_RESULT and msg.context_json:
                result = msg.context_json
                self.update_context_with_result(result, msg.content)
                self._notify_progress(self._msg("msg_weapon_complete", status=result.get("status", "unknown")))
            elif msg.msg_type == MSG_ANALYSIS_RESULT:
                self.update_context_with_result(
                    msg.context_json or {}, msg.content
                )
            elif msg.msg_type == MSG_INPUT_ALERT:
                self._notify_progress(f"[鹰眼] 检测到交互提示: {msg.content[:120]}")

        # P1 守卫：无新消息 + 有未完成任务 → wait
        has_new_info = len(new_msgs) > 0
        outstanding_dict = context.get("outstanding_dict", {})
        has_pending_tasks = any(
            t.status not in ("COMPLETED", "TIMEOUT")
            for t in outstanding_dict.values()
        ) if outstanding_dict else False
        if not has_new_info and has_pending_tasks:
            return {"type": "wait"}

        # 状态分发
        if self.state == "executing":
            return self._handle_executing(context, new_msgs)
        elif self.state == "reviewing":
            return self._handle_reviewing(context)

        # idle 或未知状态 → 重新分类
        self.state = "idle"
        return self._handle_idle(context, new_msgs)

    # ── 状态处理器 ──────────────────────────────────────────

    def _handle_idle(self, context: dict, new_msgs: list) -> dict:
        user_request = self.context.get("user_request", "")
        if not user_request:
            return {"type": "wait"}

        classification = self._classify_request(user_request)
        req_type = classification.get("type", "simple_query")

        if req_type in ("simple_query", "chat"):
            return self._handle_simple_request(classification, user_request)

        # 渗透任务 → 生成计划
        plan = self._generate_plan(user_request)
        if plan is None or not plan.steps:
            self.state = "complete"
            return {"type": "complete", "summary": classification.get("reason", "无法生成有效计划")}

        self.active_plan = plan
        self.state = "executing"
        return self._dispatch_ready_steps()

    def _handle_simple_request(self, classification: dict, user_request: str) -> dict:
        req_type = classification.get("type", "simple_query")
        reason = classification.get("reason", "")

        if req_type == "chat":
            self.state = "complete"
            return {"type": "complete", "summary": reason or "你好！有什么可以帮您的吗？"}

        # simple_query: 生成一个 1 步计划
        plan = self._generate_plan(user_request, max_steps=1)
        if plan and plan.steps:
            self.active_plan = plan
            self.state = "executing"
            return self._dispatch_ready_steps()

        # 无法生成计划 → 直接 complete
        self.state = "complete"
        return {"type": "complete", "summary": reason or "查询完成"}

    def _handle_executing(self, context: dict, new_msgs: list) -> dict:
        plan = self.active_plan
        if plan is None:
            self.state = "idle"
            return {"type": "wait"}

        # 处理结果 → 通过 reply_to 精确匹配 OutstandingTask → step_id
        outstanding_dict = context.get("outstanding_dict", {})
        for msg in new_msgs:
            if msg.msg_type == MSG_TASK_RESULT:
                result = msg.context_json or {}
                reply_id = msg.reply_to or ""
                task = outstanding_dict.get(reply_id)
                step_id = task.step_id if task else ""
                step = plan.find_step(step_id) if step_id else None
                if step is None:
                    for s in plan.steps:
                        if s.status == "DISPATCHED":
                            step = s
                            break
                if step:
                    # 处理 need_input：向用户询问，拿到输入后继续
                    if result.get("status") == "need_input":
                        prompt = result.get("required_input") or result.get("summary", "请提供信息")
                        user_input = self.wait_for_input(prompt)
                        if user_input:
                            step.instruction = f"{step.instruction}\n[用户提供的输入: {user_input}]"
                            step.status = "PENDING"  # 重置状态以便重新派发
                            if task:
                                task.status = "COMPLETED"
                            if self.agent_pool and step.dispatched_to:
                                self.agent_pool.release(step.dispatched_to)
                                step.dispatched_to = None
                            continue  # 下一轮会重新派发
                        else:
                            # 用户跳过 → 标记失败
                            step.status = "FAILED"
                            step.result_summary = "用户跳过输入"
                    else:
                        step.status = "DONE" if result.get("status") == "success" else "FAILED"
                    step.result_summary = (result.get("summary", "")
                                           or result.get("raw_output", "")
                                           or "")[:200]
                    if self.agent_pool and step.dispatched_to:
                        self.agent_pool.release(step.dispatched_to)
                        step.dispatched_to = None
                # 同步 OutstandingTask 状态
                if task:
                    task.status = "COMPLETED"

        # 超时检测：将 TIMEOUT 的 task 对应步骤标记为 FAILED
        for task_id, task in outstanding_dict.items():
            task_step_id = getattr(task, "step_id", "") if hasattr(task, "step_id") else task.get("step_id", "")
            if task.status == "TIMEOUT" and task_step_id:
                step = plan.find_step(task_step_id)
                if step and step.status == "DISPATCHED":
                    step.status = "FAILED"
                    step.result_summary = f"执行超时 ({int(task.timeout)}s)"
                    if self.agent_pool and step.dispatched_to:
                        self.agent_pool.release(step.dispatched_to)
                        step.dispatched_to = None
                    task.status = "COMPLETED"  # 防止 AgentLoop 继续等待

        # 有未完成任务 → 等待所有 agent 完成，不追加派发
        has_pending = any(
            t.status not in ("COMPLETED", "TIMEOUT")
            for t in outstanding_dict.values()
        ) if outstanding_dict else False
        if has_pending:
            return {"type": "wait"}

        # 没有未完成任务 + 计划耗尽 → 回顾
        if plan.is_exhausted():
            self.state = "reviewing"
            return self._handle_reviewing(context)

        # 没有未完成任务 + 有计划就绪 → 派发下一批
        return self._dispatch_ready_steps()

    def _handle_reviewing(self, context: dict) -> dict:
        plan = self.active_plan
        user_request = self.context.get("user_request", "")
        review = self._review_results(user_request, plan) if plan else {"done": True, "summary": "任务完成"}

        if review.get("done", True):
            self.state = "complete"
            return {"type": "complete", "summary": review.get("summary", "任务完成")}

        # 需要更多 → 重新规划，但不立即派发
        new_plan = self._generate_plan(user_request, previous_plan=plan, additional_context=review.get("reason", ""))
        if new_plan and new_plan.steps:
            self.active_plan = new_plan
            self.state = "executing"
            return {"type": "wait"}

        self.state = "complete"
        return {"type": "complete", "summary": review.get("summary", "任务完成")}

    def _dispatch_ready_steps(self) -> dict:
        """派发所有就绪步骤（使用 AgentPool 获取空闲实例）。

        返回单个 delegation、或多个 delegation 的列表（批量派发时）。
        无 agent 可用时返回 wait。
        """
        plan = self.active_plan
        if plan is None:
            self.state = "idle"
            return {"type": "wait"}

        ready = plan.get_ready_steps()
        if not ready:
            self.state = "reviewing"
            return {"type": "wait"}

        delegations = []
        for step in ready:
            target = step.target_agent
            if self.agent_pool:
                iid, _ = self.agent_pool.acquire(step.target_agent)
                if iid is None:
                    continue  # 没有空闲实例，跳过这个步骤
                target = iid
                step.dispatched_to = iid

            step.status = "DISPATCHED"
            delegations.append({
                "type": "delegate",
                "target": target,
                "content": step.instruction,
                "step_id": step.id,
            })

        if not delegations:
            return {"type": "wait"}

        return delegations if len(delegations) > 1 else delegations[0]

    # ── LLM 调用 ────────────────────────────────────────────

    def _classify_request(self, user_request: str) -> dict:
        prompt = (
            f'分析以下用户请求，判断它属于哪种类型。\n\n'
            f'用户请求："{user_request}"\n\n'
            f'类型定义：\n'
            f'- simple_query: 信息查询（"我的IP是多少"、"显示文件"、"当前时间"）。\n'
            f'- pentest_task: 安全/渗透测试（"扫描端口"、"检测漏洞"、"爆破密码"）。\n'
            f'- chat: 闲聊/问候（"你好"、"你是谁"）。\n\n'
            f'返回 JSON：\n'
            f'{{"type": "simple_query|pentest_task|chat", "reason": "判断依据"}}'
        )
        self.messages = [
            {"role": "system", "content": SYSTEM_CLASSIFY_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            return json.loads(self.get_response())
        except Exception:
            return {"type": "simple_query", "reason": "分类失败，默认简单查询"}

    def _generate_plan(self, user_request: str, previous_plan: Plan = None,
                       additional_context: str = "", max_steps: int = 8) -> Optional[Plan]:
        parts = [f'## 用户请求\n"{user_request}"']

        # 包含对话历史，让 LLM 知道之前已获得的信息
        conversation_context = self._format_conversation_history()
        if conversation_context and conversation_context != self._msg("msg_first_conversation"):
            parts.append(f"\n## 之前的对话\n{conversation_context}")

        if previous_plan:
            parts.append(f"\n## 之前的计划\n目标: {previous_plan.goal}")
            for s in previous_plan.steps:
                icon = "✓" if s.status == "DONE" else "✗"
                parts.append(f"- {icon} {s.instruction[:80]}: {s.result_summary[:60]}")
            if additional_context:
                parts.append(f"\n{additional_context}")

        findings = self._summarize_findings()
        parts.append(f"\n## 当前发现\n{findings}")

        tools = self._get_available_tools_summary()
        parts.append(f"\n## 可用工具\n{tools}")

        parts.append(
            f'\n---\n请生成一个执行计划，包含 1-{max_steps} 个步骤。每步给出完整的自然语言指令。'
            '如果之前的对话中已经知道了目标信息（如IP地址），直接在指令中使用具体值，不要再重新获取。'
            '步骤之间尽量独立。返回 JSON：\n'
            '{"goal": "计划目标", "steps": ['
            '{"id":"s1","instruction":"...","target_agent":"tool_master","depends_on":[]},'
            '...]}'
        )

        max_retries = 2
        for attempt in range(max_retries):
            self.messages = [
                {"role": "system", "content": SYSTEM_PLAN_PROMPT},
                {"role": "user", "content": "\n".join(parts)},
            ]
            try:
                data = json.loads(self.get_response())
                steps = [PlanStep(**s) for s in data.get("steps", [])]
                plan = Plan(
                    goal=data.get("goal", ""),
                    complexity="simple" if len(steps) <= 1 else "complex",
                    steps=steps,
                )
                if plan.validate_dag():
                    return plan
                # DAG 校验失败：追加错误信息后重试
                parts.append(
                    "\n⚠️ 上次生成的计划存在循环依赖或引用了不存在的步骤ID，"
                    "请检查 depends_on 字段后重新生成。"
                )
            except Exception:
                if attempt == max_retries - 1:
                    return None
        return None

    def _review_results(self, user_request: str, plan: Plan) -> dict:
        status_icon = {
            "DONE": "✓", "FAILED": "✗", "DISPATCHED": "⏳",
            "PENDING": "○", "SKIPPED": "⊘",
        }
        lines = []
        for s in plan.steps:
            icon = status_icon.get(s.status, "?")
            result = s.result_summary[:100] if s.result_summary else "(无结果)"
            lines.append(f"- {icon} [{s.status}] {s.instruction[:80]}: {result}")

        prompt = (
            f'审视以下计划的执行结果，判断用户需求是否满足。\n\n'
            f'用户请求："{user_request}"\n'
            f'计划目标：{plan.goal}\n\n'
            f'执行结果：\n' + "\n".join(lines) + '\n\n'
            f'返回 JSON：\n'
            f'{{"done": true/false, "summary": "对用户说的话", "reason": "为什么"}}'
        )
        self.messages = [
            {"role": "system", "content": SYSTEM_REVIEW_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            return json.loads(self.get_response())
        except Exception:
            return {"done": True, "summary": "执行完成"}

    def wait_for_confirm(self, task: dict, message: str) -> bool:
        """等待用户确认"""
        if self.on_need_confirm:
            return self.on_need_confirm(task, message)

        # CLI 模式
        print(f"\n{'='*50}")
        print(f"{self._msg('msg_need_confirm')}: {message}")
        if task:
            print(f"{self._msg('msg_task_label')}: {task.get('action', '')} -> {task.get('target', '')}")
        print(f"{'='*50}")
        response = input(self._msg("msg_continue_confirm") + " ").strip().lower()
        return response in ['y', 'yes', '是']

    def handle_user_request(self, request: str):
        """兼容旧接口：直接调用 run"""
        self.run(request)
