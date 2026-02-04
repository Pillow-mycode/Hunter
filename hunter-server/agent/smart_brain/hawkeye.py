#鹰眼模型
import json
import time

from agent.pojo.hawkeye_config import HawkeyeConfig


class Hawkeye:

    def __init__(self, config: HawkeyeConfig):
        self.config = config
        self.messages = []
        self.client = self.config.hawkeye_client


    def get_response(self, result):
        """获取 LLM 响应，带重试机制"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                completion = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=self.messages,
                    response_format={"type": "json_object"},
                    timeout=180  # 3分钟超时
                )
                return completion.choices[0].message.content
            except Exception as e:
                print(f"Hawkeye API 调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"Hawkeye: {wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    # 最后一次尝试也失败，返回默认值
                    print(f"Hawkeye: API 调用失败，跳过检查")
                    return json.dumps({"result": "false"})

    def check(self, result: str):
        """检查结果，带异常处理"""
        try:
            self.messages.append({"role": "system", "content": self.config.prompt})
            self.messages.append({"role": "user", "content": result})

            json_string = self.get_response(result)

            response_data = json.loads(json_string)
            res = response_data.get("result")

            if res == "true":
                return True
            return False
        except Exception as e:
            print(f"Hawkeye 检查异常: {e}")
            return False  # 出错时默认返回 False
