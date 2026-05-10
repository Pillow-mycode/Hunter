"""AgentBase — 所有 Agent 的统一基类，封装 CommBus + Blackboard 访问"""

from agent.team.protocol import InterAgentMessage


class AgentBase:
    AGENT_ID: str = ""

    def __init__(self, comm_bus, blackboard, agent_id: str = ""):
        self.comm_bus = comm_bus
        self.blackboard = blackboard
        if agent_id:
            self.AGENT_ID = agent_id  # 实例级覆盖类属性，支持多实例
        self._abort_event = None  # Set by AgentLoop to allow checking stop flag

    def send_msg(self, to: str, msg_type: str, content: str, **ctx) -> InterAgentMessage:
        msg = InterAgentMessage(
            from_agent=self.AGENT_ID,
            to_agent=to,
            msg_type=msg_type,
            content=content,
            task_id=ctx.get("task_id"),
            context_json=ctx.get("context_json"),
            expect_reply=ctx.get("expect_reply", False),
            reply_to=ctx.get("reply_to"),
        )
        self.comm_bus.send(msg)
        return msg

    def drain_inbox(self) -> list[InterAgentMessage]:
        return self.comm_bus.drain_inbox(self.AGENT_ID)

    def read_blackboard_summary(self) -> str:
        return self.blackboard.get_summary()

    def write_finding(self, category: str, data) -> None:
        self.blackboard.write("findings", category, data)

    def update_my_status(self, status: str) -> None:
        self.blackboard.update_agent_status(self.AGENT_ID, status)
