from llm.providers.openai_compat_provider import OpenAICompatProvider


class GroqProvider(OpenAICompatProvider):
    PROVIDER_TYPE = "groq"
    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
    RECOMMENDED_MODELS = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "qwen/qwen3-32b",
    ]
    SUPPORTS_JSON_MODE = True
    DEFAULT_CONTEXT_LIMIT = 131072
