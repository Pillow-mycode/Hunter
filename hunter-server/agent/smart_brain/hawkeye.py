#鹰眼模型
import json
import time

from agent.pojo.hawkeye_config import HawkeyeConfig


class Hawkeye:

    def __init__(self, config: HawkeyeConfig):
        self.config = config


    def get_response(self, messages):
        """获取 LLM 响应，带重试机制"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[鹰眼] 调用API，消息数: {len(messages)}")
                response = self.config.provider.chat(messages)
                print(f"[鹰眼] API返回: {response}")
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
            # 每次检查构建全新的消息列表，不累积历史
            messages = [
                {"role": "system", "content": self.config.prompt},
                {"role": "user", "content": result}
            ]

            json_string = self.get_response(messages)

            response_data = json.loads(json_string)
            res = response_data.get("result")

            print(f"[鹰眼] 解析结果: result={res}")

            if res == "true":
                return True
            return False
        except Exception as e:
            print(f"[鹰眼] 检查异常: {e}")
            return False
