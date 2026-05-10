from llm.providers.openai_compat_provider import OpenAICompatProvider


class QwenProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "qwen"
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    RECOMMENDED_MODELS = [
        "qwen3-max",
        "qwen3.6-plus",
        "qwen3.6-flash",
        "qwen-plus",
        "qwen-flash",
        "qwq-plus",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 131072
