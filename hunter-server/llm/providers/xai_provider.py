from llm.providers.openai_compat_provider import OpenAICompatProvider


class XAIProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "xai"
    DEFAULT_BASE_URL = "https://api.x.ai/v1"
    RECOMMENDED_MODELS = [
        "grok-4.3",
        "grok-4.20-reasoning",
        "grok-4.20-non-reasoning",
        "grok-4-1-fast-reasoning",
        "grok-4-1-fast-non-reasoning",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 131072
