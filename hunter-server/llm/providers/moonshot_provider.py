from llm.providers.openai_compat_provider import OpenAICompatProvider


class MoonshotProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "moonshot"
    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
    RECOMMENDED_MODELS = [
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2.5-thinking",
        "kimi-k2-instruct",
        "kimi-k2-0905",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 131072
