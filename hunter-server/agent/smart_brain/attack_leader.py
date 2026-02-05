# 渗透分析专家
import json
import threading
from typing import Callable, Optional

from agent.pojo.leader_config import AttackLeaderConfig
from agent.pojo.attack_config import AttackToolMasterConfig
from agent.smart_brain.attack_tool_master import AttackToolMaster
from agent.smart_brain.hardcoded_rules import HardcodedRules, RuleResult
from agent.system.system_command import write_to_logs

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
        # 初始化上下文提示词
        "init_parse_request": "请解析以下用户请求，提取目标和范围信息。",
        "init_user_request": "用户请求",
        "init_return_json": "返回 JSON 格式",
        "init_target_desc": "主要目标（域名或 IP，若无则空字符串）",
        "init_scope_desc": "目标范围列表",
        "init_request_type_desc": "请求类型（full_pentest/vulnerability_scan/specific_test）",
        "init_specific_requirements_desc": "特殊要求列表",
    },
    "en": {
        "msg_truncating": "[LLM] Message too long, truncating...",
        "msg_calling_model": "[LLM] Calling model {model}... (attempt {attempt}/{max_retries})",
        "msg_model_complete": "[LLM] Model response complete",
        "msg_api_retry": "[LLM] API call failed, retrying in {wait_time} seconds...",
        "msg_api_failed": "[LLM] API call failed: {error}",
        "msg_reply": "[Reply] {message}",
        "msg_received_request": "[Penetration Expert] Received request: {request}",
        "msg_parsing_target": "[Penetration Expert] Parsing target...",
        "msg_target": "[Penetration Expert] Target: {target}",
        "msg_target_unspecified": "Not specified",
        "msg_start_decision": "[Penetration Expert] Starting dynamic decision process...",
        "msg_decision": "[Penetration Expert] Decision: {reason}",
        "msg_instruction": "[Penetration Expert] Instruction: {instruction}",
        "msg_task_complete": "[Penetration Expert] Task complete: {reason}",
        "msg_task_done": "[Penetration Expert] Task complete",
        "msg_pentest_complete": "[Penetration Expert] Penetration test complete",
        "msg_max_steps": "[Penetration Expert] Maximum step limit reached",
        "msg_too_many_failures": "[Penetration Expert] Too many consecutive failures",
        "msg_no_progress": "[Penetration Expert] No progress for multiple steps",
        "msg_weapon_received": "[Weapon Master] Received instruction: {instruction}",
        "msg_weapon_skipped": "[Weapon Master] Task skipped: {reason}",
        "msg_weapon_aborted": "[Weapon Master] Task aborted: {reason}",
        "msg_weapon_complete": "[Weapon Master] Task complete: {status}",
        "msg_weapon_result": "[Weapon Master] Result: {summary}",
        "msg_weapon_executing": "[Weapon Master] Executing task {task_id}: {action} -> {target}",
        "msg_weapon_task_skipped": "[Weapon Master] Task {task_id} skipped: {reason}",
        "msg_weapon_task_aborted": "[Weapon Master] Task {task_id} aborted: {reason}",
        "msg_weapon_task_complete": "[Weapon Master] Task {task_id} complete: {status}",
        "msg_weapon_task_result": "[Weapon Master] Result: {summary}",
        "msg_need_confirm": "Confirmation needed",
        "msg_user_skipped": "User skipped",
        "msg_user_skipped_input": "User skipped input",
        "msg_scan_complete_findings": "Scan complete, findings above.",
        "msg_scan_complete_no_findings": "Scan complete, no obvious issues found.",
        "msg_fix_vulnerabilities": "Recommend fixing discovered vulnerabilities",
        "msg_close_ports": "Recommend closing unnecessary open ports",
        "msg_no_findings": "No findings yet",
        "msg_first_conversation": "(This is the first conversation)",
        "msg_user_label": "User",
        "msg_me_label": "Me",
        "msg_no_tools": "No tools available",
        "msg_custom_tools_header": "### Custom Tools (read documentation first)",
        "msg_kali_tools_header": "### Kali Built-in Tools (can use directly)",
        "msg_scan_done": "Scan executed",
        "msg_none": "None",
        "msg_step": "Step {step}",
        "msg_result": "Result",
        "msg_decision_error": "Decision error, terminating execution",
        "msg_need_info": "Weapon Master needs information",
        "msg_input_skip": "Please enter (enter 'skip' to skip this task)",
        "msg_continue_confirm": "Continue? (y/n)",
        "msg_task_label": "Task",
        # Decision prompts
        "decision_user_request": "User Original Request",
        "decision_conversation_history": "Conversation History",
        "decision_current_status": "Current Status",
        "decision_target": "Target",
        "decision_steps_executed": "Steps Executed",
        "decision_current_findings": "Current Findings",
        "decision_executed_operations": "Executed Operations",
        "decision_last_result": "Last Step Detailed Result",
        "decision_available_tools": "Available Tools",
        "decision_think_like_human": "Think like a human",
        "decision_q1": "What does the user want?",
        "decision_q2": "What have I done? What results did I get?",
        "decision_q3": "Is the user's need satisfied?",
        "decision_important_principles": "Important Principles",
        "decision_no_repeat": "Don't repeat operations already done (check 'Executed Operations')",
        "decision_no_same_retry": "If an operation failed, don't retry with the same method, try a different approach or give up",
        "decision_stop_if_stuck": "If you've tried your best but can't get more information, stop and report current results",
        "decision_return_json": "Return JSON",
        "decision_complete_desc": "Need satisfied, or cannot continue",
        "decision_complete_reason": "What to say to user (report results)",
        "decision_continue_desc": "Need not satisfied, continue with new operation",
        "decision_instruction_desc": "Tell Weapon Master what to do (must be an operation not done before)",
        "decision_reason_desc": "Why do this",
        # Init context prompts
        "init_parse_request": "Please parse the following user request and extract target and scope information.",
        "init_user_request": "User Request",
        "init_return_json": "Return JSON format",
        "init_target_desc": "Main target (domain or IP, empty string if none)",
        "init_scope_desc": "Target scope list",
        "init_request_type_desc": "Request type (full_pentest/vulnerability_scan/specific_test)",
        "init_specific_requirements_desc": "Special requirements list",
    }
}


class AttackLeader:
    def __init__(self, config: AttackLeaderConfig):
        self.client = config.leader_client
        self.model = config.model
        self.system_prompt = config.system_prompt
        self.language = getattr(config, 'language', 'zh')  # 获取语言配置
        self.messages = []
        self.messages_lock = threading.Lock()

        # 传递语言配置给武器大师
        weapon_config = AttackToolMasterConfig(language=self.language)
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

        # 回调函数
        self._on_progress: Optional[Callable] = None
        self.on_need_confirm: Optional[Callable] = None
        self.on_need_input: Optional[Callable] = None

    def _msg(self, key: str, **kwargs) -> str:
        """获取本地化消息"""
        lang = self.language if self.language in MESSAGES else "zh"
        template = MESSAGES[lang].get(key, MESSAGES["zh"].get(key, key))
        return template.format(**kwargs) if kwargs else template

    @property
    def on_progress(self) -> Optional[Callable]:
        return self._on_progress

    @on_progress.setter
    def on_progress(self, callback: Optional[Callable]):
        """设置进度回调，同时传递给武器大师"""
        self._on_progress = callback
        self.weapon_master.on_progress = callback

    def get_response(self) -> str:
        """获取 LLM 响应，带重试机制"""
        max_total_length = 150000
        messages = self.messages.copy()
        current_length = sum(len(str(msg.get("content", ""))) for msg in messages)

        if current_length > max_total_length:
            self._notify_progress(self._msg("msg_truncating"))
            system_messages = [msg for msg in messages if msg["role"] == "system"]
            other_messages = [msg for msg in messages if msg["role"] != "system"]
            truncated_messages = []
            accumulated_length = sum(len(str(msg.get("content", ""))) for msg in system_messages)
            for msg in reversed(other_messages):
                msg_length = len(str(msg.get("content", "")))
                if accumulated_length + msg_length > max_total_length:
                    break
                truncated_messages.append(msg)
                accumulated_length += msg_length
            messages = system_messages + list(reversed(truncated_messages))

        # 重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._notify_progress(self._msg("msg_calling_model", model=self.model, attempt=attempt + 1, max_retries=max_retries))
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    timeout=180  # 3分钟超时
                )
                self._notify_progress(self._msg("msg_model_complete"))
                return completion.choices[0].message.content
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
        if self.on_need_input:
            return self.on_need_input(prompt)

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

        # 检查无进展次数
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

    def decide_next_action(self) -> dict:
        """
        根据当前上下文决定下一步行动

        Returns:
            {
                "type": "execute_task" / "complete" / "need_user_decision",
                "task": {...},  # 如果是 execute_task
                "reason": "决策理由",
                "message": "消息"  # 如果是 need_user_decision
            }
        """
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

{f"## {self._msg('decision_executed_operations')}{chr(10)}{recent_history}" if self.context['action_count'] > 0 else ""}

{f"## {self._msg('decision_last_result')}{chr(10)}{self.context.get('last_result_summary', '')[:500]}" if self.context.get('last_result_summary') else ""}

## {self._msg("decision_available_tools")}
{available_tools}

---

{self._msg("decision_think_like_human")}:

1. {self._msg("decision_q1")}
2. {self._msg("decision_q2")}
3. {self._msg("decision_q3")}

**{self._msg("decision_important_principles")}:**
- {self._msg("decision_no_repeat")}
- {self._msg("decision_no_same_retry")}
- {self._msg("decision_stop_if_stuck")}

{self._msg("decision_return_json")}:

{self._msg("decision_complete_desc")}:
{{
    "type": "complete",
    "reason": "{self._msg("decision_complete_reason")}"
}}

{self._msg("decision_continue_desc")}:
{{
    "type": "execute_task",
    "instruction": "{self._msg("decision_instruction_desc")}",
    "reason": "{self._msg("decision_reason_desc")}"
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
