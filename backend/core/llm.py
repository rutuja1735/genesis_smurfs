"""OpenRouter-only LLM client with durable spend control and temperature-zero caching."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError

from .audit import JsonlAuditLog
from .logstore import LogStore
from .types import LLMClient

OPENROUTER_URL = "https://openrouter.ai/api/v1"


class LLMError(RuntimeError):
    pass


class LLMJsonError(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass(frozen=True)
class LLMResult:
    text: str
    tool_calls: tuple[dict[str, Any], ...]
    usage: dict[str, int]
    cost: float
    model: str
    request_id: str | None
    cached: bool = False


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str
    base_url: str = OPENROUTER_URL
    site_url: str | None = None
    app_name: str = "Agentgaurd"
    temperature: float = 0.0
    max_budget_usd: float = 4.0
    price_in_per_m: float = 0.15
    price_out_per_m: float = 0.60
    cache: bool = True
    max_retries: int = 3
    timeout_s: float = 60.0
    log_prompts: bool = False

    @classmethod
    def from_env(cls) -> "OpenRouterConfig":
        load_dotenv()
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise LLMError("OPENROUTER_API_KEY is missing; add it to backend/.env")
        base_url = os.getenv("OPENROUTER_BASE_URL", OPENROUTER_URL).rstrip("/")
        if base_url != OPENROUTER_URL:
            raise LLMError("Only the official OpenRouter API base URL is supported")
        model = os.getenv("OPENROUTER_MODEL", "").strip()
        if not model:
            raise LLMError("OPENROUTER_MODEL is missing; choose an OpenRouter model id")
        return cls(
            api_key=key, model=model, base_url=base_url,
            site_url=os.getenv("OPENROUTER_SITE_URL") or None,
            app_name=os.getenv("OPENROUTER_APP_NAME", "Agentgaurd"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            max_budget_usd=float(os.getenv("MAX_BUDGET_USD", "4.00")),
            price_in_per_m=float(os.getenv("PRICE_IN_PER_M", "0.15")),
            price_out_per_m=float(os.getenv("PRICE_OUT_PER_M", "0.60")),
            cache=os.getenv("LLM_CACHE", "1").strip().lower() not in {"0", "false", "off"},
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
            timeout_s=float(os.getenv("LLM_TIMEOUT_S", "60")),
            log_prompts=os.getenv("LOG_PROMPTS", "0").strip().lower() in {"1", "true", "yes"},
        )


class OpenRouterClient(LLMClient):
    def __init__(self, config: OpenRouterConfig | None = None, *, store: LogStore | None = None,
                 audit: JsonlAuditLog | None = None, client: Any | None = None,
                 run_id: str | None = None) -> None:
        self.config = config or OpenRouterConfig.from_env()
        if not self.config.api_key:
            raise LLMError("OPENROUTER_API_KEY is missing")
        if self.config.base_url.rstrip("/") != OPENROUTER_URL:
            raise LLMError("Only the official OpenRouter API base URL is supported")
        self.store = store or LogStore()
        self.audit = audit
        self.run_id = run_id
        headers = {"X-Title": self.config.app_name}
        if self.config.site_url:
            headers["HTTP-Referer"] = self.config.site_url
        self.client = client or OpenAI(api_key=self.config.api_key, base_url=OPENROUTER_URL,
                                       default_headers=headers, timeout=self.config.timeout_s,
                                       max_retries=0)

    def complete(self, role: str, prompt: str, *, json_mode: bool = False) -> str:
        return self.chat([{"role": "user", "content": prompt}], role=role, json_mode=json_mode).text

    def complete_with_system(self, system_prompt: str, prompt: str, *, role: str,
                             json_mode: bool = False) -> str:
        """Run isolated classification prompts with policy in the system message."""
        return self.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ], role=role, json_mode=json_mode, temperature=0).text

    def chat(self, messages: list[dict[str, Any]], *, role: str = "baseline", json_mode: bool = False,
             tools: list[dict[str, Any]] | None = None, temperature: float | None = None,
             retry_json: bool = True) -> LLMResult:
        temp = self.config.temperature if temperature is None else temperature
        params: dict[str, Any] = {"model": self.config.model, "messages": messages, "temperature": temp}
        if json_mode:
            params["response_format"] = {"type": "json_object"}
            params["extra_body"] = {"usage": {"include": True}}
        else:
            params["extra_body"] = {"usage": {"include": True}}
        if tools:
            params["tools"] = tools
        key = hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        if self.config.cache and temp == 0:
            cached = self.store.get_cached(key)
            if cached:
                if self.audit:
                    self.audit.write("LLM_CACHE_HIT", role=role, model=self.config.model, cache_key=key)
                return LLMResult(**{**cached, "cached": True})
        self._check_budget()
        started = time.monotonic()
        response = self._request_with_retries(params)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        result = self._normalize(response)
        self._record_call(result, role, elapsed_ms, messages)
        if json_mode:
            try:
                result = LLMResult(**{**asdict(result), "text": self._repair_json(result.text)})
            except (ValueError, json.JSONDecodeError) as exc:
                if retry_json:
                    retry_messages = [*messages, {"role": "assistant", "content": result.text},
                                      {"role": "user", "content": f"Return only a valid JSON object. Fix this parse error: {exc}"}]
                    return self.chat(retry_messages, role=role, json_mode=True, tools=tools,
                                     temperature=temp, retry_json=False)
                raise LLMJsonError(f"OpenRouter returned invalid JSON after repair: {exc}") from exc
        if self.config.cache and temp == 0:
            self.store.put_cached(key, asdict(result))
        return result

    def _record_call(self, result: LLMResult, role: str, elapsed_ms: int,
                     messages: list[dict[str, Any]]) -> None:
        # Account for every completed provider response, including malformed JSON
        # that triggers a repair call. Otherwise retries could escape the cap.
        self.store.record_spend(role=role, model=result.model,
                                tokens_in=result.usage["prompt_tokens"],
                                tokens_out=result.usage["completion_tokens"],
                                cost_usd=result.cost, run_id=self.run_id)
        if self.audit:
            event = {"role": role, "model": result.model,
                     "tokens_in": result.usage["prompt_tokens"],
                     "tokens_out": result.usage["completion_tokens"],
                     "cost_usd": result.cost, "latency_ms": elapsed_ms,
                     "request_id": result.request_id}
            if self.config.log_prompts:
                event["messages"] = messages
            self.audit.write("LLM_CALL", **event)

    def _check_budget(self) -> None:
        spent = self.store.total_spend()
        if spent >= self.config.max_budget_usd:
            raise BudgetExceeded(f"LLM budget exhausted: spent ${spent:.4f} of ${self.config.max_budget_usd:.2f}")

    def _request_with_retries(self, params: dict[str, Any]) -> Any:
        for attempt in range(self.config.max_retries + 1):
            try:
                return self.client.chat.completions.create(**params)
            except APIStatusError as exc:
                status = getattr(exc, "status_code", None)
                if status not in {429, 500, 502, 503, 504} or attempt >= self.config.max_retries:
                    raise LLMError(f"OpenRouter request failed (HTTP {status}): {exc}") from exc
                retry_after = None
                try:
                    retry_after = float(exc.response.headers.get("Retry-After"))
                except (AttributeError, TypeError, ValueError):
                    pass
                time.sleep(min(retry_after if retry_after is not None else 0.5 * (2 ** attempt) + random.random() * 0.1, 30))
            except (APITimeoutError, APIConnectionError) as exc:
                if attempt >= self.config.max_retries:
                    raise LLMError(f"OpenRouter request failed after retries: {exc}") from exc
                time.sleep(min(0.5 * (2 ** attempt) + random.random() * 0.1, 30))
        raise LLMError("OpenRouter request failed")

    def _normalize(self, response: Any) -> LLMResult:
        choice = response.choices[0]
        message = choice.message
        text = message.content or ""
        usage_obj = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
        cost = getattr(usage_obj, "cost", None)
        if cost is None:
            cost = (prompt_tokens * self.config.price_in_per_m + completion_tokens * self.config.price_out_per_m) / 1_000_000
        tool_calls = tuple({"id": call.id, "type": call.type,
                            "function": {"name": call.function.name, "arguments": call.function.arguments}}
                           for call in (getattr(message, "tool_calls", None) or []))
        return LLMResult(text=text, tool_calls=tool_calls,
                         usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
                         cost=float(cost or 0.0), model=getattr(response, "model", self.config.model),
                         request_id=getattr(response, "id", None))

    @staticmethod
    def _repair_json(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.I | re.S).strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            start, end = stripped.find("{"), stripped.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(stripped[start:end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        return json.dumps(parsed, ensure_ascii=False)
