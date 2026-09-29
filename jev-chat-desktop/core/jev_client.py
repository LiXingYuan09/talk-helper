"""talk helper 的通用错误、DeepSeek 密钥读取与脱敏工具。"""

from __future__ import annotations

import os


class JevError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def redact_secrets(text: str) -> str:
    """Strip every live key from any string before print or disk write."""
    if not isinstance(text, str):
        text = str(text)
    key = os.environ.get("DEEPSEEK_API_KEY") or ""
    return text.replace(key, "[REDACTED]") if key else text


def _api_key(env: str = "DEEPSEEK_API_KEY") -> str:
    if env != "DEEPSEEK_API_KEY":
        raise JevError("talk helper 仅允许使用 DEEPSEEK_API_KEY。")
    key = (os.environ.get(env) or "").strip()
    if not key:
        raise JevError(
            "DEEPSEEK_API_KEY 未配置，请在设置中填写 DeepSeek API Key。"
        )
    return key
