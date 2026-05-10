from llm.providers.openai_compat_provider import OpenAICompatProvider


class DeepSeekProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "deepseek"
    DEFAULT_BASE_URL = "https://api.deepseek.com"
    RECOMMENDED_MODELS = [
        "deepseek-v4-flash",
        "deepseek-v4",
        "deepseek-v3.1",
        "deepseek-r1",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 131072
