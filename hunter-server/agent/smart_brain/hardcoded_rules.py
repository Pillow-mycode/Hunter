from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuleResult:
    """硬编码规则检查结果"""
    need_confirm: bool = False
    should_abort: bool = False
    should_skip: bool = False
    message: str = ""
    reason: str = ""


class HardcodedRules:
    """硬编码规则检查器"""

    # 高风险操作列表
    HIGH_RISK_ACTIONS = [
        "exploit",
        "brute_force",
        "password_crack",
        "reverse_shell",
        "bind_shell",
        "upload_file",
        "upload_webshell",
        "execute_command",
        "privilege_escalation",
        "lateral_movement",
        "data_exfiltration",
        "persistence"
    ]

    # 中风险操作列表
    MEDIUM_RISK_ACTIONS = [
        "sql_injection_exploit",
        "xss_exploit",
        "file_inclusion",
        "directory_traversal"
    ]

    # 敏感目标后缀
    SENSITIVE_TARGETS = [
        ".gov",
        ".gov.cn",
        ".edu",
        ".edu.cn",
        ".mil",
        ".police",
        ".bank"
    ]

    # 敏感关键词
    SENSITIVE_KEYWORDS = [
        "government",
        "military",
        "police",
        "bank",
        "hospital"
    ]

    def check(self, task: dict, context: dict) -> RuleResult:
        """
        检查任务是否需要特殊处理

        Args:
            task: 任务信息 {"action": "", "target": "", "risk_level": "", ...}
            context: 上下文信息 {"consecutive_failures": 0, ...}

        Returns:
            RuleResult: 检查结果
        """
        # 规则1: 高风险操作需确认
        action = (task.get("action") or "").lower()
        risk_level = (task.get("risk_level") or "low").lower()

        if risk_level == "high" or action in self.HIGH_RISK_ACTIONS:
            return RuleResult(
                need_confirm=True,
                message=f"即将执行高风险操作: {task.get('action')}\n目标: {task.get('target')}\n是否继续？"
            )

        # 规则2: 中风险操作提示
        if risk_level == "medium" or action in self.MEDIUM_RISK_ACTIONS:
            return RuleResult(
                need_confirm=True,
                message=f"即将执行中风险操作: {task.get('action')}\n目标: {task.get('target')}\n是否继续？"
            )

        # 规则3: 敏感目标拦截
        target = (task.get("target") or "").lower()
        for suffix in self.SENSITIVE_TARGETS:
            if suffix in target:
                return RuleResult(
                    should_abort=True,
                    reason=f"目标 {task.get('target')} 包含敏感域名后缀 {suffix}，已拦截"
                )

        # 规则4: 敏感关键词检查
        for keyword in self.SENSITIVE_KEYWORDS:
            if keyword in target:
                return RuleResult(
                    need_confirm=True,
                    message=f"目标 {task.get('target')} 包含敏感关键词 {keyword}，请确认是否有授权？"
                )

        # 规则5: 连续失败检查
        consecutive_failures = context.get("consecutive_failures", 0)
        if consecutive_failures >= 3:
            return RuleResult(
                need_confirm=True,
                message=f"已连续失败 {consecutive_failures} 次，是否继续执行？"
            )

        # 规则6: 超时检查
        if context.get("is_timeout", False):
            return RuleResult(
                need_confirm=True,
                message="上一个任务执行超时，是否继续？"
            )

        # 无特殊处理
        return RuleResult()

    def check_target_authorization(self, target: str) -> RuleResult:
        """
        检查目标是否在授权范围内

        Args:
            target: 目标地址

        Returns:
            RuleResult: 检查结果
        """
        target_lower = (target or "").lower()

        # 检查敏感后缀
        for suffix in self.SENSITIVE_TARGETS:
            if suffix in target_lower:
                return RuleResult(
                    should_abort=True,
                    reason=f"目标 {target} 属于敏感域名，请确保已获得合法授权"
                )

        return RuleResult()

    def check_loop_limit(self, context: dict, max_steps: int = 50, confirm_interval: int = 10) -> RuleResult:
        """
        检查循环限制，防止无限循环

        Args:
            context: 当前上下文
            max_steps: 最大步数（0 表示不限制）
            confirm_interval: 确认间隔步数（0 表示不确认）

        Returns:
            RuleResult
        """
        action_count = context.get("action_count", 0)

        # 1. 最大步数限制
        if max_steps > 0 and action_count >= max_steps:
            return RuleResult(
                should_abort=True,
                reason=f"达到最大步数限制（{max_steps}步）"
            )

        # 2. 无进展检测
        no_progress_count = context.get("no_progress_count", 0)
        if no_progress_count >= 5:
            return RuleResult(
                should_abort=True,
                reason="连续5步无新发现"
            )

        # 3. 连续失败检测
        consecutive_failures = context.get("consecutive_failures", 0)
        if consecutive_failures >= 5:
            return RuleResult(
                should_abort=True,
                reason="连续5次任务失败"
            )

        # 4. 定期确认
        if confirm_interval > 0 and action_count > 0 and action_count % confirm_interval == 0:
            return RuleResult(
                need_confirm=True,
                message=f"已执行{action_count}步操作，是否继续？"
            )

        return RuleResult()

    def check_instruction(self, instruction: str, context: dict) -> RuleResult:
        """
        检查自然语言指令是否需要特殊处理

        Args:
            instruction: 自然语言指令
            context: 上下文信息

        Returns:
            RuleResult: 检查结果
        """
        instruction_lower = instruction.lower()

        # 规则1: 高风险关键词检查
        high_risk_keywords = [
            "exploit", "攻击", "入侵", "破坏", "删除", "格式化",
            "reverse shell", "bind shell", "webshell", "后门",
            "privilege escalation", "提权", "横向移动"
        ]

        for keyword in high_risk_keywords:
            if keyword in instruction_lower:
                return RuleResult(
                    need_confirm=True,
                    message=f"即将执行高风险操作: {instruction}\n是否继续？"
                )

        # 规则2: 中风险关键词检查
        medium_risk_keywords = [
            "brute", "爆破", "暴力", "crack", "破解",
            "password", "密码"
        ]

        for keyword in medium_risk_keywords:
            if keyword in instruction_lower:
                return RuleResult(
                    need_confirm=True,
                    message=f"即将执行中风险操作: {instruction}\n是否继续？"
                )

        # 规则3: 敏感目标检查
        for suffix in self.SENSITIVE_TARGETS:
            if suffix in instruction_lower:
                return RuleResult(
                    should_abort=True,
                    reason=f"指令涉及敏感目标（{suffix}），已拦截"
                )

        # 规则4: 连续失败检查
        consecutive_failures = context.get("consecutive_failures", 0)
        if consecutive_failures >= 3:
            return RuleResult(
                need_confirm=True,
                message=f"已连续失败 {consecutive_failures} 次，是否继续执行？"
            )

        return RuleResult()
