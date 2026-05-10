"""Token counter using tiktoken cl100k_base encoding.

Works for DeepSeek, OpenAI, and most OpenAI-compatible APIs.
"""

import tiktoken
from threading import Lock

_ENCODING = None
_ENCODING_LOCK = Lock()


def _get_encoding():
    """Lazy-load and cache the tiktoken encoding (thread-safe)."""
    global _ENCODING
    if _ENCODING is None:
        with _ENCODING_LOCK:
            if _ENCODING is None:
                _ENCODING = tiktoken.get_encoding("cl100k_base")
    return _ENCODING


class TokenCounter:
    """Token counting for LLM context management using cl100k_base."""

    def count_text(self, text: str) -> int:
        """Count tokens in a plain text string."""
        if not text:
            return 0
        enc = _get_encoding()
        return len(enc.encode(text))

    def count_messages(self, messages: list) -> int:
        """Count tokens in a list of chat messages.

        Follows OpenAI's formula: base tokens per message + name overhead
        + content tokens. Adds priming tokens for assistant reply.
        """
        enc = _get_encoding()
        total = 0
        for msg in messages:
            total += 3  # base tokens per message (role + formatting)
            for key, value in msg.items():
                if key == "name":
                    total += 1  # name field overhead
                if isinstance(value, str):
                    total += len(enc.encode(value))
                elif isinstance(value, list):
                    # multi-modal content parts
                    for part in value:
                        if isinstance(part, dict) and "text" in part:
                            total += len(enc.encode(part["text"]))
        total += 3  # assistant reply priming
        return total


# Module-level singleton
_counter = None


def get_token_counter() -> TokenCounter:
    global _counter
    if _counter is None:
        _counter = TokenCounter()
    return _counter
