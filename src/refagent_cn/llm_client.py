from __future__ import annotations

import json
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib import request, error


_PROVIDER_DEFAULTS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "name": "DeepSeek",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "name": "OpenAI",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-R1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "name": "SiliconFlow",
    },
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
        "name": "Alibaba Cloud DashScope/Qwen",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "api_key_env": "ZHIPUAI_API_KEY",
        "name": "Zhipu AI/GLM",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "api_key_env": "MOONSHOT_API_KEY",
        "name": "Moonshot/Kimi",
    },
    "volcengine": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "",
        "api_key_env": "ARK_API_KEY",
        "name": "Volcengine Ark",
    },
    "custom": {
        "base_url": "",
        "model": "",
        "api_key_env": "CUSTOM_LLM_API_KEY",
        "name": "Custom OpenAI-compatible",
    },
}

FROZEN_TITLE_PROMPT = Path(__file__).resolve().parent / "PROMPT_TITLE_COMPLETION_v3.8.8.5.24_FINAL.md"
FROZEN_TITLE_PROMPT_SHA256 = "c52092bc2e0b6b8a02c20a34720df492372d0023343ae3d9d1108b6b53886e51"


def _text(value: Any, unknown: str = "Unknown") -> str:
    if isinstance(value, (list, tuple)):
        rendered = ", ".join(str(x).strip() for x in value if str(x).strip())
    else:
        rendered = str(value or "").strip()
    return rendered or unknown


def build_title_messages(context: Any, examples: Optional[Sequence[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """Build the sole production/development title-generation message pair."""
    system = FROZEN_TITLE_PROMPT.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(system.encode("utf-8")).hexdigest()
    if actual_hash != FROZEN_TITLE_PROMPT_SHA256:
        raise RuntimeError(f"Frozen title prompt SHA-256 mismatch: {actual_hash}")
    parts: List[str] = []
    for i, example in enumerate(examples or [], start=1):
        if not example.get("title_cn") or not example.get("title_en"):
            continue
        parts.extend([
            f"Verified example {i}:",
            f"Chinese title: {_text(example.get('title_cn'))}",
            f"English title: {_text(example.get('title_en'))}",
            f"Journal: {_text(example.get('journal_cn'))}",
            "",
        ])
    parts.extend([
        "Current record:",
        f"Original Chinese reference: {_text(getattr(context, 'raw_reference', None))}",
        f"Chinese explicitly visible authors: {_text(getattr(context, 'authors_cn', None))}",
        f"Chinese article title: {_text(getattr(context, 'title_cn', None))}",
        f"Chinese journal: {_text(getattr(context, 'journal_cn', None))}",
        f"Verified English journal: {_text(getattr(context, 'journal_en_verified', None))}",
        f"Year: {_text(getattr(context, 'year', None))}",
        f"Volume: {_text(getattr(context, 'volume', None))}",
        f"Issue: {_text(getattr(context, 'issue', None))}",
        f"Pages: {_text(getattr(context, 'pages', None))}",
        f"Disciplinary context: {_text(getattr(context, 'field_context', None))}",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


class LLMClient:
    """Small OpenAI-compatible chat client used only for English-title generation."""

    PROVIDER_DEFAULTS = _PROVIDER_DEFAULTS

    def __init__(self, config: Dict) -> None:
        self.config = config or {}
        self.last_error = ""
        self.last_response_meta: Dict[str, Any] = {}
        self.response_log: List[Dict[str, Any]] = []

    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def _provider(self) -> str:
        provider = (self.config.get("provider") or "deepseek").strip().lower()
        return provider if provider in _PROVIDER_DEFAULTS else "custom"

    def _provider_default(self, key: str, fallback: str = "") -> str:
        return str(_PROVIDER_DEFAULTS.get(self._provider(), {}).get(key, fallback) or fallback)

    def provider_display_name(self) -> str:
        return self._provider_default("name", self._provider())

    def get_api_key(self) -> str:
        # UI/config-injected key has priority. This avoids stale environment variables
        # overriding the key entered in the web interface.
        direct_key = (self.config.get("api_key") or "").strip()
        if direct_key:
            return direct_key

        api_key_env = self.config.get("api_key_env") or self._provider_default("api_key_env", "DEEPSEEK_API_KEY")
        return os.getenv(api_key_env, "").strip()

    def _model_name(self) -> str:
        return (self.config.get("model") or self._provider_default("model", "")).strip()

    def _chat_url(self) -> str:
        base_url = (self.config.get("base_url") or self._provider_default("base_url", "")).strip().rstrip("/")
        if not base_url:
            raise ValueError("LLM base_url is empty. Please set provider/base_url in the sidebar or config.json.")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _request_chat(self, messages: List[Dict[str, str]], temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Optional[str]:
        self.last_error = ""
        self.last_response_meta = {}
        if not self.is_enabled():
            self.last_error = "LLM disabled by configuration or --no-llm."
            return None

        api_key = self.get_api_key()
        if not api_key:
            env_name = self.config.get("api_key_env") or self._provider_default("api_key_env", "API_KEY")
            self.last_error = f"API key not found. Set llm.api_key in config.json, enter it in the Web UI, or set {env_name}."
            return None

        model = self._model_name()
        if not model:
            self.last_error = "LLM model is empty. Please set model in the sidebar or config.json."
            return None

        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.config.get("temperature", 0.2) if temperature is None else temperature,
            "max_tokens": self.config.get("max_tokens", 512) if max_tokens is None else max_tokens,
            "stream": False,
        }
        if messages and messages[0].get("role") == "system":
            system_hash = hashlib.sha256(messages[0].get("content", "").encode("utf-8")).hexdigest()
            self.last_response_meta["actual_system_message_sha256"] = system_hash
        timeout = int(self.config.get("timeout", 60))
        started = time.perf_counter()
        requested_at = datetime.now(timezone.utc).isoformat()
        try:
            req = request.Request(
                url=self._chat_url(),
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            choice = (data.get("choices") or [{}])[0]
            usage = data.get("usage") or {}
            self.last_response_meta = {
                "requested_model": model,
                "response_model": data.get("model"),
                "response_id": data.get("id"),
                "response_created": data.get("created"),
                "finish_reason": choice.get("finish_reason"),
                "usage_prompt_tokens": usage.get("prompt_tokens"),
                "usage_completion_tokens": usage.get("completion_tokens"),
                "usage_total_tokens": usage.get("total_tokens"),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "requested_at": requested_at,
                "temperature": payload["temperature"],
                "max_tokens": payload["max_tokens"],
                "stream": False,
                "endpoint": self._chat_url(),
                "success": True,
                "actual_system_message_sha256": hashlib.sha256(messages[0].get("content", "").encode("utf-8")).hexdigest() if messages else "",
            }
            self.response_log.append(dict(self.last_response_meta))
            return data["choices"][0]["message"]["content"].strip()
        except error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                detail = ""
            self.last_error = self._format_http_error(exc.code, detail)
            return None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.last_response_meta = {
                "requested_model": model, "response_model": None,
                "response_id": None, "response_created": None,
                "finish_reason": None, "usage_prompt_tokens": None,
                "usage_completion_tokens": None, "usage_total_tokens": None,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "requested_at": requested_at, "temperature": payload["temperature"],
                "max_tokens": payload["max_tokens"], "stream": False,
                "endpoint": self._chat_url(), "success": False,
                "error": self.last_error,
            }
            self.response_log.append(dict(self.last_response_meta))
            return None

    def generate_english_title(self, context: Any, examples: Optional[Sequence[Dict[str, Any]]] = None, temperature: Optional[float] = None) -> Optional[str]:
        messages = build_title_messages(context, examples=examples)
        content = self._request_chat(messages, temperature=temperature)
        if content is None:
            return None
        cleaned = self._clean_title(content)
        if not cleaned:
            self.last_error = "LLM returned empty content."
            return None
        return cleaned

    def generate_english_title_candidates(
        self,
        context: Any,
        examples: Optional[Sequence[Dict[str, str]]] = None,
        n: int = 5,
        temperature: float = 0.2,
    ) -> List[str]:
        # Preserve all K stochastic samples, including duplicates. Duplicate
        # frequency is itself evidence of generation stability and is required
        # for exact-agreement and consistency analysis.
        candidates: List[str] = []
        attempts = max(1, int(n or 1))
        for _ in range(attempts):
            title = self.generate_english_title(
                context=context,
                examples=examples,
                temperature=temperature,
            )
            if title:
                candidates.append(title)
        return candidates

    def score_english_title_candidates(
        self,
        title_cn: str,
        candidates: Sequence[str],
        journal_cn: str = "",
        field: str = "",
    ) -> List[Dict[str, Any]]:
        """Return critic-based A (adequacy) and T (terminology/entity fidelity).

        This is deliberately separated from the final confidence. The returned
        scores become observable features and are empirically calibrated later
        against human acceptance labels.
        """
        cands = [str(x or "").strip() for x in candidates if str(x or "").strip()]
        if not cands:
            return []
        system = (
            "你是学术题名跨语言质量评估员。请比较中文原题与多个英文候选题名。"
            "对每个候选分别给出两个0到100的整数分数："
            "adequacy表示核心语义、关系与限定范围是否完整保持；"
            "terminology表示学科术语、专名、缩写、数字与关键概念是否准确。"
            "不要因为英文流畅就提高adequacy；出现增译、漏译、概念替换或范围改变应扣分。"
            "只输出JSON数组，每项格式为 {\"index\":1,\"adequacy\":0,\"terminology\":0,\"note\":\"\"}，不要输出其他内容。"
        )
        lines = [
            f"中文原题：{title_cn}",
            f"中文期刊：{journal_cn or '未知'}",
            f"学科领域：{field or '未知'}",
            "英文候选：",
        ]
        for i, c in enumerate(cands, start=1):
            lines.append(f"{i}. {c}")
        content = self._request_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}],
            temperature=0.0,
            max_tokens=512,
        )
        if not content:
            return [{"adequacy": 0.5, "terminology": 0.5, "note": f"critic_failed: {self.last_error}"} for _ in cands]
        parsed = self._parse_json_array(content)
        out: List[Dict[str, Any]] = []
        by_index = {}
        for item in parsed:
            try:
                by_index[int(item.get("index"))] = item
            except Exception:
                continue
        for i in range(1, len(cands) + 1):
            item = by_index.get(i, {})
            try:
                a = max(0.0, min(1.0, float(item.get("adequacy", 50)) / 100.0))
            except Exception:
                a = 0.5
            try:
                t = max(0.0, min(1.0, float(item.get("terminology", 50)) / 100.0))
            except Exception:
                t = 0.5
            out.append({"adequacy": a, "terminology": t, "note": str(item.get("note", "") or "")})
        return out

    @staticmethod
    def _parse_json_array(text: str) -> List[Dict[str, Any]]:
        raw = str(text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            m = re.search(r"\[.*\]", raw, flags=re.DOTALL)
            if not m:
                return []
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, list) else []
            except Exception:
                return []

    def _format_http_error(self, code: int, detail: str) -> str:
        platform_name = self.provider_display_name()
        env_name = self.config.get("api_key_env") or self._provider_default("api_key_env", "API_KEY")
        detail = (detail or "").strip().replace("\n", " ")

        if code == 401:
            return (
                f"HTTPError 401: API key is invalid or missing. "
                f"请检查 {platform_name} API Key、config.json 的 llm.api_key，"
                f"或环境变量 {env_name}。{detail[:160]}"
            )
        if code == 403:
            return (
                f"HTTPError 403: API key has no permission for this model or endpoint. "
                f"请检查 {platform_name} 模型权限、账户额度与 model/base_url 配置。{detail[:180]}"
            )
        if code == 429:
            return f"HTTPError 429: Rate limit exceeded or quota insufficient. 请稍后重试或检查额度。{detail[:180]}"
        if code >= 500:
            return f"HTTPError {code}: API service error. 请稍后重试。{detail[:180]}"
        return f"HTTPError {code}: {detail[:300]}"

    def _clean_title(self, text: str) -> str:
        text = (text or "").strip().strip("\"'“”‘’`")
        text = text.replace("英文题名：", "").replace("英文标题：", "")
        text = text.replace("English title:", "").replace("English Title:", "").replace("Title:", "")
        lines = [x.strip().strip("\"'“”‘’`") for x in text.splitlines() if x.strip()]
        if not lines:
            return ""
        for line in lines:
            if any("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in line) and 8 < len(line) < 240:
                return self._postprocess_title(line.rstrip("."))
        return self._postprocess_title(lines[-1].rstrip("."))

    def _postprocess_title(self, title: str) -> str:
        title = (title or "").strip()
        replacements = {
            "Research on Research Data": "Research Data",
            "Research on Research": "A Study on",
            "Study on Study": "A Study on",
            "Analysis of Analysis": "An Analysis of",
        }
        for old, new in replacements.items():
            title = title.replace(old, new)
        title = re.sub(r"\s+", " ", title).strip()
        return title
