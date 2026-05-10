"""标准协作工作流 — InterAgentMessage 便利构造器

这些函数不替代 Agent LLM 的自主决策，只提供消息格式的规范化构造方法。
调用方负责通过 CommBus 发送消息。
"""

from __future__ import annotations

from typing import Optional

from .protocol import (
    AgentId,
    InterAgentMessage,
    MSG_DELEGATION,
    MSG_TASK_RESULT,
    MSG_INPUT_ALERT,
    MSG_FINDING_ALERT,
    MSG_ANALYSIS_REQUEST,
)


def delegate_leader_to_toolmaster(
    instruction: str,
    task_id: Optional[str] = None,
) -> InterAgentMessage:
    """构建 Leader→ToolMaster 派发消息"""
    return InterAgentMessage(
        from_agent="leader",
        to_agent="tool_master",
        msg_type=MSG_DELEGATION,
        content=f"请执行以下任务：{instruction}",
        task_id=task_id,
        expect_reply=True,
    )


def request_analysis(
    requester: AgentId,
    data_description: str,
    task_id: Optional[str] = None,
) -> InterAgentMessage:
    """构建请求 DataAnalyst 分析的消息"""
    return InterAgentMessage(
        from_agent=requester,
        to_agent="data_analyst",
        msg_type=MSG_ANALYSIS_REQUEST,
        content=f"请分析以下数据：{data_description}",
        task_id=task_id,
        expect_reply=True,
    )


def report_result(
    reporter: AgentId,
    task_id: Optional[str],
    findings_summary: str,
    context_json: Optional[dict] = None,
) -> InterAgentMessage:
    """构建任务完成汇报消息"""
    return InterAgentMessage(
        from_agent=reporter,
        to_agent="leader",
        msg_type=MSG_TASK_RESULT,
        content=f"任务完成。{findings_summary}",
        task_id=task_id,
        context_json=context_json,
    )


def alert_hawkeye_detection(
    prompt_text: str,
    detection_method: str = "pattern",
    confidence: float = 0.98,
    prompt_type: str = "generic_prompt",
    suggested_action: str = "",
) -> InterAgentMessage:
    """构建 Hawkeye 交互告警消息"""
    return InterAgentMessage(
        from_agent="hawkeye",
        to_agent="tool_master",
        msg_type=MSG_INPUT_ALERT,
        content=f"[鹰眼] 检测到交互提示：{prompt_text}",
        context_json={
            "detection_method": detection_method,
            "confidence": confidence,
            "prompt_type": prompt_type,
            "suggested_action": suggested_action,
        },
    )


def alert_finding(
    finder: AgentId,
    finding_description: str,
) -> InterAgentMessage:
    """构建发现告警消息（发给 Leader）"""
    return InterAgentMessage(
        from_agent=finder,
        to_agent="leader",
        msg_type=MSG_FINDING_ALERT,
        content=f"发现：{finding_description}",
    )
