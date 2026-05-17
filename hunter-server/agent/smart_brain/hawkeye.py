#鹰眼模型
import json
import time

from agent.pojo.hawkeye_config import HawkeyeConfig
from agent.team.agent_base import AgentBase
from llm.compat import parse_json_response
from agent.team.protocol import MSG_INPUT_ALERT


class Hawkeye(AgentBase):
    AGENT_ID = "hawkeye"

    def __init__(self, config: HawkeyeConfig, comm_bus=None, blackboard=None, agent_id: str = "", agent_pool=None):
        self.config = config
        self._last_check_output = ""
        if comm_bus and blackboard:
            super().__init__(comm_bus, blackboard, agent_id=agent_id, agent_pool=agent_pool)


    def get_response(self, messages):
        """获取 LLM 响应，带重试机制"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[鹰眼] 调用API，消息数: {len(messages)}")
                response = self.config.provider.chat(messages)
                print(f"[鹰眼] API返回: {response[:100]}")
                return response
            except Exception as e:
                print(f"[鹰眼] API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"[鹰眼] {wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"[鹰眼] API调用失败，跳过检查")
                    return json.dumps({"result": "false"})

    def check(self, result: str):
        """检查结果，带异常处理。每次检查使用独立的消息列表，避免历史堆积。"""
        try:
            messages = [
                {"role": "system", "content": self.config.prompt},
                {"role": "user", "content": result}
            ]
            json_string = self.get_response(messages)
            response_data = parse_json_response(json_string)
            res = response_data.get("result")
            print(f"[鹰眼] 解析结果: result={res}")
            if res == "true":
                return True
            return False
        except Exception as e:
            print(f"[鹰眼] 检查异常: {e}")
            return False

    def decide(self, context: dict) -> dict:
        if self._abort_event and self._abort_event.is_set():
            return {"type": "wait"}

        msgs = self.drain_inbox()
        if not msgs:
            self.release_to_pool()
            return {"type": "wait"}
        for msg in msgs:
            if self._abort_event and self._abort_event.is_set():
                break
            if msg.msg_type == "delegation" and msg.context_json:
                self.update_my_status("busy")
                output_snippet = msg.context_json.get("output", "")
                detected = self.check(output_snippet)
                if detected:
                    self.send_msg(
                        to=msg.from_agent,
                        msg_type=MSG_INPUT_ALERT,
                        content=f"[鹰眼] 检测到交互提示，进程可能等待输入",
                        reply_to=msg.msg_id,
                    )
                self.update_my_status("idle")
        return {"type": "wait"}
