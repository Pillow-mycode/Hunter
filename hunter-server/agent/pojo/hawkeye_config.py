import os

from openai import OpenAI


class HawkeyeConfig:
    hawkeye_client = OpenAI(
        api_key=os.getenv("HAWKEYE_API_KEY"),
        base_url=os.getenv("HAWKEYE_BASE_URL"))
    # 使用的模型
    model = os.getenv("HAWKEYE_MODEL")
    def __init__(self, prompt = """
        你是一个乐于助人的终端助手, 专用于判断用户的终端是否到了需要用户交互的时候, 也就是说, 如果终端需要用户输入了, 你返回true, 否则返回false。 
        返回格式为json格式:
        {
            "result": "true/false"
        }"""):
        self.prompt = prompt
