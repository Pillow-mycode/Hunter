import os

from dotenv import load_dotenv
load_dotenv(override=True)

from openai import OpenAI


# 中文提示词
HAWKEYE_PROMPT_ZH = """
你是一个乐于助人的终端助手, 专用于判断用户的终端是否到了需要用户交互的时候, 也就是说, 如果终端需要用户输入了, 你返回true, 否则返回false。
返回格式为json格式:
{
    "result": "true/false"
}"""

# 英文提示词
HAWKEYE_PROMPT_EN = """
You are a helpful terminal assistant, specialized in determining whether the user's terminal has reached a point where user interaction is needed. That is, if the terminal requires user input, return true, otherwise return false.
Return format is JSON:
{
    "result": "true/false"
}"""


class HawkeyeConfig:
    def __init__(self, prompt=None, language=None):
        # 在实例化时读取环境变量，确保 .env 已加载
        self.hawkeye_client = OpenAI(
            api_key=os.getenv("HAWKEYE_API_KEY") or os.getenv("DEFAULT_API_KEY"),
            base_url=os.getenv("HAWKEYE_BASE_URL") or os.getenv("DEFAULT_BASE_URL")
        )
        self.model = os.getenv("HAWKEYE_MODEL") or os.getenv("DEFAULT_MODEL")

        # 语言配置：优先使用参数，其次使用环境变量，默认中文
        self.language = language or os.getenv("LANGUAGE", "zh").lower()

        if prompt is None:
            # 根据语言选择提示词
            prompt = HAWKEYE_PROMPT_EN if self.language == "en" else HAWKEYE_PROMPT_ZH
        self.prompt = prompt
