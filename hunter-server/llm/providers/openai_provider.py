from llm.providers.openai_compat_provider import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    RECOMMENDED_MODELS = [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-4.1",
        "gpt-4.1-mini",
        "o3",
        "o4-mini",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 128000
