# gemini_util.py
# MARK XXV — quota-resilient AI text generation (Gemini + free fallbacks)
"""
Every AI call in this project used a single hard-coded model
(`gemini-2.5-flash-lite`). The Gemini free tier limits each model
*separately, per day*, and on this account flash-lite is capped at a tiny
number of requests, so the API answers:

    429 RESOURCE_EXHAUSTED
    quotaId   : GenerateRequestsPerDayPerProjectPerModel-FreeTier
    quotaValue: 20              (requests/day for gemini-2.5-flash-lite)
    retryDelay: 23892s          (~6.6 hours)

Once that bucket is empty the whole assistant degrades silently: memory stops
updating, the planner/executor and the natural-language command parsers all
fail, because they share the same dead model.

What this module does
---------------------
1. Keeps an ordered fallback chain of models (each with its own daily bucket).
2. Walks the chain when a call fails for a *retryable* reason: 429 quota,
   503 high-demand, 5xx, timeouts, and stale/unknown model names.
3. Remembers which models are exhausted and *until when* (taken from the
   server's `retryDelay`), so later calls skip them instead of paying a
   round trip each time.
4. `install_quota_fallback()` patches the `generate_content` entry point of
   BOTH Gemini SDKs, so every existing call site gets the fallback without
   editing a dozen files.
5. Tier-2 (optional): if EVERY Gemini model is exhausted and the request is a
   plain-text prompt, it also falls over to the providers listed in
   `config/providers.json` — free OpenAI-compatible cloud APIs (Groq,
   OpenRouter) and/or a local Ollama server, which needs no key and never runs
   out of quota. Requests that need Gemini-only features — image input or
   `google_search` grounding — stay on Gemini. Tier-2 adds no dependencies; it
   uses urllib from the stdlib.

It is deliberately best-effort: non-retryable errors (bad request, empty
response, unsupported parameter) are re-raised untouched, and if the whole
chain is exhausted the original error is raised, so behaviour is never worse
than before this module existed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

# --------------------------------------------------------------------------
# Fallback chain — tried in order. Each entry is a separate free-tier bucket.
# --------------------------------------------------------------------------
DEFAULT_CHAIN: tuple[str, ...] = (
    "gemini-2.5-flash",          # verified working, ~1 s, largest free quota
    "gemini-3.5-flash",          # verified working (newer bucket)
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-flash-lite-latest",  # rolling alias -> newest lite
    "gemini-flash-latest",       # rolling alias -> newest flash
    "gemini-2.5-flash-lite",     # project's old default; only ~20 req/day
)

TRANSIENT_COOLDOWN_S = 60.0          # avoid a model briefly after a 5xx blip
MODEL_COOLDOWN_S = 24 * 3600.0       # model name unknown / not permitted
MAX_COOLDOWN_S = 24 * 3600.0

_RETRYABLE_CODES = {403, 404, 408, 409, 429, 500, 502, 503, 504}
_RETRYABLE_NAMES = {
    "ResourceExhausted",
    "TooManyRequests",
    "ServiceUnavailable",
    "Unavailable",
    "DeadlineExceeded",
    "InternalServerError",
    "Internal",
    "GatewayTimeout",
    "BadGateway",
    "Aborted",
    "NotFound",
    "PermissionDenied",
}

_lock = threading.RLock()
_cooldown_until: dict[str, float] = {}
_served: dict[str, int] = {}
_failed: dict[str, int] = {}
_chain: tuple[str, ...] = DEFAULT_CHAIN
_verbose = True
_client = None
_installed = False


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _norm(model: Any) -> str:
    """'models/gemini-2.5-flash' -> 'gemini-2.5-flash'."""
    m = str(model or "").strip()
    if m.startswith("models/"):
        m = m[len("models/"):]
    return m


def _log(msg: str) -> None:
    if _verbose:
        try:
            print(f"[Quota] {msg}")
        except Exception:
            pass


def _short(err: BaseException, limit: int = 140) -> str:
    first = str(err).strip().splitlines()[0] if str(err).strip() else type(err).__name__
    return first[:limit]


def _error_code(err: BaseException) -> Optional[int]:
    for attr in ("code", "status_code", "http_status"):
        v = getattr(err, attr, None)
        if isinstance(v, int):
            return v
    m = re.search(r"\b(400|403|404|408|409|429|500|502|503|504)\b", str(err))
    return int(m.group(1)) if m else None


def _looks_like_missing_model(text: str) -> bool:
    t = (text or "").lower()
    if "not found" in t or "does not exist" in t or "unknown model" in t:
        return True
    if "model" in t and ("is not supported" in t or "not supported for" in t):
        return True
    return False


def _is_retryable(err: BaseException) -> bool:
    """Should we try the next model instead of giving up?"""
    if isinstance(err, (KeyboardInterrupt, SystemExit)):
        return False
    names = {c.__name__ for c in type(err).__mro__}
    if names & _RETRYABLE_NAMES:
        return True
    if _error_code(err) in _RETRYABLE_CODES:
        return True
    return _looks_like_missing_model(str(err))


def _retry_delay(err: BaseException) -> Optional[float]:
    s = str(err)
    m = re.search(r"retryDelay'?\s*[:=]\s*'?([\d.]+)s", s)
    if m:
        return float(m.group(1))
    m = re.search(r"retry in ([\d.]+)s", s)
    if m:
        return float(m.group(1))
    return None


def _cooldown_for(err: BaseException) -> float:
    code = _error_code(err)
    if code == 429:
        d = _retry_delay(err)
        return min(d, MAX_COOLDOWN_S) if d else TRANSIENT_COOLDOWN_S
    if code in (403, 404) or _looks_like_missing_model(str(err)):
        return MODEL_COOLDOWN_S
    return TRANSIENT_COOLDOWN_S


def _build_chain(requested: Optional[str],
                 extra: Optional[Sequence[str]] = None) -> list[str]:
    now = time.monotonic()
    ordered: list[str] = []
    for candidate in ([requested] if requested else []) + list(extra or ()) + list(_chain):
        n = _norm(candidate)
        if n and n not in ordered:
            ordered.append(n)
    fresh = [m for m in ordered if _cooldown_until.get(m, 0.0) <= now]
    # If every model is cooling down we still return the full list so the
    # caller receives the real 429 instead of a confusing local error.
    return fresh or ordered


def _record_failure(model: str, err: BaseException) -> float:
    cooldown = _cooldown_for(err)
    with _lock:
        _failed[model] = _failed.get(model, 0) + 1
        _cooldown_until[model] = time.monotonic() + cooldown
    _log(f"{model} unavailable ({_short(err)}) — skipping for {cooldown:.0f}s")
    return cooldown


def _record_success(model: str, requested: Optional[str]) -> None:
    with _lock:
        _served[model] = _served.get(model, 0) + 1
    if requested and _norm(requested) != model:
        _log(f"served by fallback model {model!r}")


# --------------------------------------------------------------------------
# tier-2: free OpenAI-compatible providers (config/providers.json)
# --------------------------------------------------------------------------
_PROVIDERS_PATH = Path(__file__).resolve().parent / "config" / "providers.json"
_providers_cache: Optional[list] = None
_providers_mtime: float = -1.0
_provider_warned: set = set()

_PROVIDER_SKIP_CODES = {400, 401, 403, 404, 408, 409, 413, 422, 429, 500, 502, 503, 504}

# Cloudflare (which fronts Groq) rejects the default urllib User-Agent with
# "403 error code: 1010", so every tier-2 request has to identify itself.
_USER_AGENT = "JARVIS/1.0 (Windows; OpenAI-compatible client)"


def _api_keys() -> dict:
    path = Path(__file__).resolve().parent / "config" / "api_keys.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _providers() -> list:
    """Providers from config/providers.json, re-read whenever the file changes."""
    global _providers_cache, _providers_mtime
    try:
        mtime = _PROVIDERS_PATH.stat().st_mtime
    except OSError:
        return []
    with _lock:
        if _providers_cache is not None and mtime == _providers_mtime:
            return _providers_cache
    try:
        with open(_PROVIDERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        _log(f"providers.json unreadable ({e}) — tier-2 disabled")
        with _lock:
            _providers_cache, _providers_mtime = [], mtime
        return []
    providers = []
    for p in (data.get("openai_compatible") or []):
        if not isinstance(p, dict) or not p.get("base_url"):
            continue
        if not p.get("models") and not p.get("discover"):
            continue                                   # nothing to try
        pid = str(p.get("id") or "provider")
        try:
            timeout = float(p.get("timeout") or 60)
        except (TypeError, ValueError):
            timeout = 60.0
        providers.append({
            "id": pid,
            "base_url": str(p["base_url"]).rstrip("/"),
            "key_env": p.get("key_env"),
            "key_field": str(p.get("key_field") or f"{pid}_api_key"),
            "requires_key": bool(p.get("requires_key", True)),
            "discover": bool(p.get("discover", False)),
            "timeout": timeout,
            "models": [str(m) for m in (p.get("models") or [])],
        })
    with _lock:
        _providers_cache, _providers_mtime = providers, mtime
    return providers


def _provider_key(provider: dict) -> Optional[str]:
    """Env var first, then config/api_keys.json."""
    env = provider.get("key_env")
    if env:
        v = os.environ.get(str(env))
        if v and v.strip():
            return v.strip()
    v = _api_keys().get(provider.get("key_field") or "")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _provider_ready(provider: dict) -> bool:
    """A local server (requires_key=false) is usable even with no key at all."""
    if not provider.get("requires_key", True):
        return True
    return bool(_provider_key(provider))


# Local servers get new models via `ollama pull`, so rather than making the user
# keep providers.json in sync we ask the server which models it actually has.
_DISCOVER_TTL = 300.0
_discover_cache: dict = {}          # provider id -> (expires_at, [model ids])
_DISCOVER_SKIP = ("embed", "bge", "rerank", "whisper")


def _discover_models(provider: dict) -> list:
    pid = provider["id"]
    now = time.monotonic()
    with _lock:
        hit = _discover_cache.get(pid)
        if hit and hit[0] > now:
            return hit[1]

    headers = {"User-Agent": _USER_AGENT}
    key = _provider_key(provider)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    ids: list = []
    try:
        req = urllib.request.Request(provider["base_url"] + "/models",
                                     headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        ids = [str(m.get("id")) for m in (payload.get("data") or [])
               if isinstance(m, dict) and m.get("id")]
    except Exception as e:
        if pid not in _provider_warned:
            _provider_warned.add(pid)
            _log(f"{pid}: not reachable for model discovery ({_short(e)})")

    ids = [i for i in ids if not any(b in i.lower() for b in _DISCOVER_SKIP)][:3]
    with _lock:
        _discover_cache[pid] = (now + _DISCOVER_TTL, ids)
    return ids


def _provider_models(provider: dict) -> list:
    if provider.get("discover"):
        found = _discover_models(provider)
        if found:
            return found
    return list(provider.get("models") or [])


def _as_text(value: Any) -> Optional[str]:
    """Best-effort flatten of a system_instruction (plain str or types.Content)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    parts = getattr(value, "parts", None)
    if parts:
        try:
            joined = "".join(getattr(p, "text", "") or "" for p in parts)
            if joined:
                return joined
        except Exception:
            pass
    return str(value) or None


def _cfg_get(config: Any, key: str) -> Any:
    if config is None:
        return None
    if isinstance(config, dict):
        return config.get(key)
    return getattr(config, key, None)


def _text_plan(contents: Any, config: Any) -> Optional[tuple]:
    """
    Return (prompt, system, json_mode) when the request could run on ANY chat
    model, else None. Multimodal input and tool/grounding requests must stay on
    Gemini, because free OpenAI-compatible providers cannot satisfy them.
    """
    if isinstance(contents, str):
        prompt = contents
    elif (isinstance(contents, (list, tuple)) and contents
          and all(isinstance(c, str) for c in contents)):
        prompt = "\n".join(contents)
    else:
        return None                                    # images / Parts -> Gemini only
    if _cfg_get(config, "tools"):
        return None                                    # google_search -> Gemini only
    system = _as_text(_cfg_get(config, "system_instruction"))
    json_mode = str(_cfg_get(config, "response_mime_type") or "") == "application/json"
    return (prompt, system, json_mode)


def _safe_plan(contents: Any, config: Any) -> Optional[tuple]:
    try:
        return _text_plan(contents, config)
    except Exception:
        return None


def _provider_cooldown(err: BaseException) -> float:
    # A free model that hangs for the full timeout is almost always just slow;
    # don't pay that 60s penalty again on the next request.
    if isinstance(err, TimeoutError) or "timed out" in str(err).lower():
        return 1800.0
    code = _error_code(err)
    if code == 429:
        d = _retry_delay(err)
        return min(d, MAX_COOLDOWN_S) if d else TRANSIENT_COOLDOWN_S
    if code in (401, 403):
        return 6 * 3600.0          # bad/absent key, or not permitted
    if code in (400, 404, 422):
        return 3600.0              # this provider won't accept the request/model
    return TRANSIENT_COOLDOWN_S


def _provider_skippable(err: BaseException) -> bool:
    if isinstance(err, (KeyboardInterrupt, SystemExit)):
        return False
    if isinstance(err, (OSError, TimeoutError, ValueError, KeyError)):
        return True                # network/HTTP failure or unparseable reply
    return _error_code(err) in _PROVIDER_SKIP_CODES or _is_retryable(err)


def _record_provider_failure(key: str, err: BaseException) -> None:
    cooldown = _provider_cooldown(err)
    with _lock:
        _failed[key] = _failed.get(key, 0) + 1
        _cooldown_until[key] = time.monotonic() + cooldown
    _log(f"{key} unavailable ({_short(err)}) — skipping for {cooldown:.0f}s")


class _Part:                       # response shims so callers can keep using
    def __init__(self, text: str):  # .text / .candidates[0].content.parts
        self.text = text


class _TextResponse:
    def __init__(self, text: str):
        self.text = text
        self.candidates = [type("_Candidate", (), {
            "content": type("_Content", (), {"parts": [_Part(text)]})(),
        })()]


def _openai_chat(provider: dict, model: str, prompt: str,
                 system: Optional[str], json_mode: bool) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if json_mode:
        prompt += "\n\nReturn ONLY a valid JSON object. No prose, no markdown fences."
    messages.append({"role": "user", "content": prompt})

    headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    key = _provider_key(provider)
    if key:                                    # local servers (Ollama) want none
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(
        provider["base_url"] + "/chat/completions",
        data=json.dumps({"model": model, "messages": messages}).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=provider.get("timeout") or 60) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return (payload["choices"][0]["message"].get("content") or "").strip()


def _external_candidates():
    """(provider, model) pairs whose cooldown has elapsed, in config order."""
    now = time.monotonic()
    for provider in _providers():
        if not _provider_ready(provider):
            if provider["id"] not in _provider_warned:
                _provider_warned.add(provider["id"])
                _log(f"{provider['id']}: no API key — tier-2 off for it "
                     f"(add \"{provider['key_field']}\" to config/api_keys.json)")
            continue
        for model in _provider_models(provider):
            if _cooldown_until.get(f"{provider['id']}:{model}", 0.0) <= now:
                yield provider, model


def _external_run(plan: tuple, requested: Optional[str]) -> Optional[Any]:
    """Tier-2 fallback for a plain-text request. None when nothing is configured."""
    prompt, system, json_mode = plan
    last: Optional[BaseException] = None
    tried = False
    for provider, model in _external_candidates():
        tried = True
        key = f"{provider['id']}:{model}"
        try:
            text = _openai_chat(provider, model, prompt, system, json_mode)
        except BaseException as err:  # noqa: BLE001 - re-raised below
            if not _provider_skippable(err):
                raise
            _record_provider_failure(key, err)
            last = err
            continue
        if not text:
            _record_provider_failure(key, ValueError("empty response"))
            last = ValueError(f"{key}: empty response")
            continue
        _record_success(key, requested)
        return _TextResponse(text)
    if last is not None:
        raise last
    return None


# --------------------------------------------------------------------------
# core: run a callable over the chain
# --------------------------------------------------------------------------
def _run(call: Callable[[str], Any], requested: Optional[str],
         extra: Optional[Sequence[str]] = None,
         plan: Optional[tuple] = None) -> Any:
    last: Optional[BaseException] = None
    for model in _build_chain(requested, extra):
        try:
            result = call(model)
        except BaseException as err:  # noqa: BLE001 - re-raised below
            if not _is_retryable(err):
                raise
            _record_failure(model, err)
            last = err
            continue
        _record_success(model, requested)
        return result

    # Every Gemini model is exhausted (or cooling). If this was a plain-text
    # request, try the free OpenAI-compatible providers before giving up.
    if plan is not None:
        external = _external_run(plan, requested)
        if external is not None:
            return external

    if last is not None:
        raise last
    raise RuntimeError("gemini_util: no candidate models")


async def _arun(call: Callable[[str], Any], requested: Optional[str],
                extra: Optional[Sequence[str]] = None,
                plan: Optional[tuple] = None) -> Any:
    last: Optional[BaseException] = None
    for model in _build_chain(requested, extra):
        try:
            result = await call(model)
        except BaseException as err:  # noqa: BLE001 - re-raised below
            if not _is_retryable(err):
                raise
            _record_failure(model, err)
            last = err
            continue
        _record_success(model, requested)
        return result

    if plan is not None:
        external = await asyncio.to_thread(_external_run, plan, requested)
        if external is not None:
            return external

    if last is not None:
        raise last
    raise RuntimeError("gemini_util: no candidate models")


# --------------------------------------------------------------------------
# public API (for new code)
# --------------------------------------------------------------------------
def api_key() -> str:
    path = Path(__file__).resolve().parent / "config" / "api_keys.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def get_client():
    """Cached google-genai client (creating one per call lets it be GC'd)."""
    global _client
    with _lock:
        if _client is None:
            from google import genai
            _client = genai.Client(api_key=api_key())
        return _client


def generate(contents: Any, *, models: Optional[Sequence[str]] = None,
             config: Any = None, system_instruction: Optional[str] = None,
             json_mode: bool = False) -> Any:
    """`client.models.generate_content` with model fallback. Returns response."""
    if config is None and (system_instruction or json_mode):
        from google.genai import types
        kw: dict = {}
        if system_instruction:
            kw["system_instruction"] = system_instruction
        if json_mode:
            kw["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**kw)

    client = get_client()
    chain = tuple(models) if models else None
    requested = chain[0] if chain else None
    return _run(
        lambda m: client.models.generate_content(model=m, contents=contents, config=config),
        requested,
        extra=chain[1:] if chain else None,
        plan=_safe_plan(contents, config),
    )


def generate_text(contents: Any, **kwargs: Any) -> str:
    """Like `generate` but returns the stripped text ('' on empty)."""
    response = generate(contents, **kwargs)
    return (getattr(response, "text", None) or "").strip()


def stats() -> dict:
    """Diagnostics: which models served calls, which are cooling down."""
    now = time.monotonic()
    # Read providers first: _providers() takes _lock, and _lock is not reentrant.
    providers = _providers()
    with _lock:
        return {
            "chain": list(_chain),
            "served": dict(_served),
            "failed": dict(_failed),
            "cooling": {
                m: round(until - now, 1)
                for m, until in _cooldown_until.items()
                if until > now
            },
            "tier2": [
                {
                    "id": p["id"],
                    "ready": _provider_ready(p),
                    "discover": p.get("discover", False),
                    "models": list(p.get("models") or []),
                }
                for p in providers
            ],
        }


def reset() -> None:
    with _lock:
        _cooldown_until.clear()
        _served.clear()
        _failed.clear()
        _discover_cache.clear()


# --------------------------------------------------------------------------
# SDK patches — makes every existing call site quota-resilient
# --------------------------------------------------------------------------
def _patch_new_sdk() -> bool:
    try:
        from google.genai import models as genai_models
    except Exception:
        return False

    patched = False

    cls = getattr(genai_models, "Models", None)
    if cls is not None and not getattr(cls.generate_content, "_jarvis_quota", False):
        original = cls.generate_content

        def generate_content(self, *, model=None, contents=None, config=None, **kwargs):
            return _run(
                lambda m: original(self, model=m, contents=contents, config=config, **kwargs),
                model,
                plan=_safe_plan(contents, config),
            )

        generate_content._jarvis_quota = True      # type: ignore[attr-defined]
        generate_content.__wrapped__ = original    # type: ignore[attr-defined]
        cls.generate_content = generate_content
        patched = True

    acls = getattr(genai_models, "AsyncModels", None)
    if acls is not None and not getattr(acls.generate_content, "_jarvis_quota", False):
        aoriginal = acls.generate_content

        async def agenerate_content(self, *, model=None, contents=None, config=None, **kwargs):
            return await _arun(
                lambda m: aoriginal(self, model=m, contents=contents, config=config, **kwargs),
                model,
                plan=_safe_plan(contents, config),
            )

        agenerate_content._jarvis_quota = True     # type: ignore[attr-defined]
        agenerate_content.__wrapped__ = aoriginal  # type: ignore[attr-defined]
        acls.generate_content = agenerate_content
        patched = True

    return patched


def _patch_old_sdk() -> bool:
    # google.generativeai is deprecated and prints a loud banner on import;
    # silence it while we import it eagerly so every legacy call site is
    # covered from the very first request.
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import google.generativeai as old_genai
    except Exception:
        return False

    # Safety net: some old-SDK call sites rely on genai.configure() having run
    # already; doing it here means the shim works on its own too.
    try:
        old_genai.configure(api_key=api_key())
    except Exception:
        pass

    cls = getattr(old_genai, "GenerativeModel", None)
    if cls is None or getattr(cls.generate_content, "_jarvis_quota", False):
        return False

    original = cls.generate_content

    def generate_content(self, contents, *args, **kwargs):
        requested = getattr(self, "_model_name", None)

        # Recover the parts of the request the old SDK keeps on the instance,
        # so tier-2 can be told whether this is a plain-text prompt.
        gen_cfg = getattr(self, "_generation_config", None)
        plan = _safe_plan(contents, {
            "system_instruction": getattr(self, "_system_instruction", None),
            "response_mime_type": gen_cfg.get("response_mime_type") if isinstance(gen_cfg, dict) else None,
            "tools": getattr(self, "_tools", None),
        })

        def call(model: str):
            self._model_name = model if model.startswith("models/") else "models/" + model
            return original(self, contents, *args, **kwargs)

        try:
            return _run(call, requested, plan=plan)
        finally:
            try:
                if requested is not None:
                    self._model_name = requested
            except Exception:
                pass

    generate_content._jarvis_quota = True      # type: ignore[attr-defined]
    generate_content.__wrapped__ = original    # type: ignore[attr-defined]
    cls.generate_content = generate_content
    return True


def install_quota_fallback(chain: Optional[Sequence[str]] = None) -> bool:
    """Patch both Gemini SDKs. Safe to call more than once."""
    global _installed, _chain
    if chain:
        with _lock:
            _chain = tuple(chain)
    if _installed:
        return True
    _installed = True

    new_ok = False
    old_ok = False
    try:
        new_ok = _patch_new_sdk()
    except Exception as e:
        _log(f"google.genai patch failed: {e}")
    try:
        old_ok = _patch_old_sdk()
    except Exception as e:
        _log(f"google.generativeai patch failed: {e}")

    _log(f"quota fallback active -> {', '.join(_chain)}")
    if not (new_ok or old_ok):
        _log("no SDK could be patched; falling back to plain behaviour")

    providers = _providers()
    if not providers:
        _log("tier-2 disabled (no readable config/providers.json)")
    else:
        ready = []
        for p in providers:
            if not _provider_ready(p):
                _log(f"tier-2 [{p['id']}] waiting for \"{p['key_field']}\" "
                     f"in config/api_keys.json (or env {p.get('key_env')})")
                continue
            how = "auto models" if p.get("discover") else f"{len(p.get('models') or [])} models"
            ready.append(f"{p['id']} ({how})")
        if ready:
            _log(f"tier-2 ready -> {', '.join(ready)}")

    return new_ok or old_ok


__all__ = [
    "DEFAULT_CHAIN",
    "install_quota_fallback",
    "generate",
    "generate_text",
    "get_client",
    "api_key",
    "stats",
    "reset",
]
