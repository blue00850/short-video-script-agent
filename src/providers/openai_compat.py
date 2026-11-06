"""OpenAI-compatible chat-completions provider (standard library only)."""

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import Provider, ProviderError


Transport = Callable[[str, Dict[str, str], bytes, int], Tuple[int, bytes]]


def _default_transport(
    url: str, headers: Dict[str, str], body: bytes, timeout: int
) -> Tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class OpenAICompatProvider(Provider):
    name = "openai-compatible"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        timeout: int = 90,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        json_mode: bool = True,
        transport: Optional[Transport] = None,
    ):
        if not api_key:
            raise ProviderError("missing_api_key", "未配置 LLM_API_KEY", retryable=False)
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self.transport = transport or _default_transport

    def _endpoint(self) -> str:
        url = self.base_url.rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return url + "/chat/completions"
        # A bare host is treated as an OpenAI-compatible root.
        if "://" in url and url.split("://", 1)[1].count("/") == 0:
            return url + "/v1/chat/completions"
        return url + "/chat/completions"

    def _body(self, system: str, messages: List[Dict[str, str]], json_mode: bool) -> bytes:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def generate(
        self,
        system: str,
        messages: List[Dict[str, str]],
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }
        url = self._endpoint()
        attempts = [self.json_mode]
        if self.json_mode:
            attempts.append(False)
        last_error: Optional[ProviderError] = None
        for json_mode in attempts:
            body = self._body(system, messages, json_mode)
            try:
                status, raw = self.transport(url, headers, body, self.timeout)
            except (socket.timeout, TimeoutError):
                raise ProviderError("timeout", "模型请求超时（%ss）" % self.timeout, retryable=True)
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                raise ProviderError("network_error", "模型网络错误：%s" % reason, retryable=True)
            except OSError as exc:
                raise ProviderError("network_error", "模型网络错误：%s" % exc, retryable=True)

            text = raw.decode("utf-8", errors="replace")
            if status >= 400:
                message = text[:500]
                if status in (401, 403):
                    raise ProviderError("auth_error", "模型鉴权失败（HTTP %d）：%s" % (status, message))
                if status == 429:
                    raise ProviderError("rate_limit", "模型限流（HTTP 429）：%s" % message, retryable=True)
                if status >= 500:
                    last_error = ProviderError("server_error", "模型服务错误（HTTP %d）：%s" % (status, message), retryable=True)
                    continue
                if "response_format" in text and json_mode:
                    # Some compatible servers do not support JSON mode; retry
                    # once without it before giving up.
                    last_error = ProviderError("bad_request", message, retryable=False)
                    continue
                raise ProviderError("bad_request", "模型请求失败（HTTP %d）：%s" % (status, message))
            try:
                data = json.loads(text)
            except ValueError:
                raise ProviderError("bad_response", "模型返回的不是 JSON：%s" % text[:300])
            choices = data.get("choices") or []
            if not choices:
                raise ProviderError("bad_response", "模型响应缺少 choices：%s" % text[:300])
            choice = choices[0]
            content = (choice.get("message") or {}).get("content")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            finish_reason = choice.get("finish_reason")
            if not isinstance(content, str) or not content.strip():
                raise ProviderError(
                    "empty_content",
                    "模型返回空内容（finish_reason=%s）" % (finish_reason or "unknown"),
                )
            return {
                "text": content,
                "usage": data.get("usage", {}),
                "model": data.get("model", self.model),
                "finish_reason": finish_reason,
            }
        if last_error:
            raise last_error
        raise ProviderError("bad_request", "模型请求失败")
