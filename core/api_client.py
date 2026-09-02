# -*- coding: utf-8 -*-
"""大模型 API 客户端：零第三方依赖（urllib），支持流式输出与随时中断。

已适配三种接入方式：
  * openai    —— OpenAI 及一切兼容 /chat/completions 的中转、本地模型（vLLM / Ollama / 硅基流动 / DeepSeek 等）
  * anthropic —— Claude 原生 Messages API
  * custom    —— 完全自定义地址（同样按 OpenAI 兼容协议发，方便自搭网关）
"""
from __future__ import annotations

import json
import ssl
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

DEFAULT_HEADERS = {"Content-Type": "application/json"}
ANTHROPIC_VERSION = "2023-06-01"


class AIError(Exception):
    """所有 API 相关错误的统一类型，UI 层直接展示 str(e)。"""


def parse_kv_lines(text: str) -> Dict[str, str]:
    """把 "Key: Value" 多行文本解析成字典，容错空行与注释行(#)。"""
    out: Dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


class AIClient:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg or {}

    # -- 公开配置 ---------------------------------------------------------
    @property
    def provider(self) -> str:
        return (self.cfg.get("provider") or "openai").lower()

    @property
    def model(self) -> str:
        return (self.cfg.get("model") or "").strip()

    def endpoint(self, kind: str = "chat") -> str:
        base = (self.cfg.get("base_url") or "").strip().rstrip("/")
        if not base:
            raise AIError("未填写 API 地址（Base URL）")
        if self.provider == "anthropic":
            if base.endswith("/messages"):
                return base
            if base.endswith("/v1"):
                return base + "/messages"
            return base + "/v1/messages"
        # OpenAI 兼容
        if kind == "models":
            if base.endswith("/models"):
                return base
            return base + "/models"
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1") or base.endswith("/v1/"):
            return base.rstrip("/") + "/chat/completions"
        return base + "/v1/chat/completions"

    def headers(self) -> Dict[str, str]:
        h = dict(DEFAULT_HEADERS)
        key = (self.cfg.get("api_key") or "").strip()
        if self.provider == "anthropic":
            if key:
                h["x-api-key"] = key
            h["anthropic-version"] = ANTHROPIC_VERSION
        else:
            if key:
                h["Authorization"] = "Bearer " + key
        h.update(parse_kv_lines(self.cfg.get("extra_headers", "")))
        return h

    def extra_body(self) -> Dict[str, Any]:
        raw = (self.cfg.get("extra_body") or "").strip()
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except ValueError as e:
            raise AIError("附加请求参数（extra_body）不是合法 JSON：%s" % e)

    # -- 请求体 -----------------------------------------------------------
    def build_payload(self, messages: List[Dict[str, str]], system: str = "",
                      stream: bool = True) -> Dict[str, Any]:
        cfg = self.cfg
        if self.provider == "anthropic":
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                "max_tokens": int(cfg.get("max_tokens") or 4096),
                "stream": stream,
            }
            try:
                payload["temperature"] = float(cfg.get("temperature", 1.0))
            except (TypeError, ValueError):
                pass
            if system:
                payload["system"] = system
        else:
            msgs: List[Dict[str, str]] = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.extend({"role": m["role"], "content": m["content"]} for m in messages)
            payload = {
                "model": self.model,
                "messages": msgs,
                "stream": stream,
            }
            # 部分推理模型不接受 temperature / top_p，按需下发
            try:
                payload["temperature"] = float(cfg.get("temperature", 1.0))
                payload["top_p"] = float(cfg.get("top_p", 1.0))
            except (TypeError, ValueError):
                pass
            try:
                payload["max_tokens"] = int(cfg.get("max_tokens") or 4096)
            except (TypeError, ValueError):
                pass
        payload.update(self.extra_body())
        return payload

    @staticmethod
    def sanitize_messages(messages: List[Dict[str, str]], system: str = "") -> List[Dict[str, str]]:
        """保证消息序列合法：角色只有 user/assistant，且 user 开头。"""
        out: List[Dict[str, str]] = []
        for m in messages or []:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            out.append({"role": "assistant" if role == "assistant" else "user", "content": content})
        # 多轮历史若以 assistant 开头，直接丢弃前面的 assistant，而不是硬塞一条占位 user
        start = 0
        while start < len(out) and out[start]["role"] != "user":
            start += 1
        out = out[start:]
        if not out:
            out = [{"role": "user", "content": system or "你好"}]
        return out

    # -- 底层请求 ---------------------------------------------------------
    def _request(self, url: str, payload: Dict[str, Any], stream: bool,
                 on_delta: Optional[Callable[[str], None]],
                 cancel: Optional[threading.Event],
                 on_raw: Optional[Callable[[str], None]] = None) -> str:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self.headers(), method="POST")
        timeout = int(self.cfg.get("timeout") or 180)
        ctx = ssl.create_default_context()
        try:
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")[:600]
            except Exception:
                pass
            raise AIError("HTTP %s %s\n%s" % (e.code, e.reason, _pretty_error(body)))
        except urllib.error.URLError as e:
            raise AIError("无法连接 API（%s）\n请检查网络、代理或 Base URL 是否正确。\n细节：%s"
                          % (url, e.reason))
        except Exception as e:  # noqa: BLE001
            raise AIError("请求失败：%r" % e)

        full: List[str] = []
        try:
            charset = resp.headers.get_content_charset() or "utf-8"
            if stream:
                buf = b""
                while True:
                    if cancel is not None and cancel.is_set():
                        break
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        piece = self._parse_sse(line.decode(charset, "ignore"), on_raw)
                        if piece:
                            full.append(piece)
                            if on_delta:
                                on_delta(piece)
                rest = buf.decode(charset, "ignore")
                if rest.strip():
                    piece = self._parse_sse(rest, on_raw)
                    if piece:
                        full.append(piece)
                        if on_delta:
                            on_delta(piece)
            else:
                raw = resp.read().decode(charset, "ignore")
                if on_raw:
                    on_raw(raw[:4000])
                text = self._parse_non_stream(raw)
                full.append(text)
                if on_delta:
                    on_delta(text)
        finally:
            try:
                resp.close()
            except Exception:
                pass
        return "".join(full)

    def _parse_sse(self, line: str, on_raw: Optional[Callable[[str], None]] = None) -> str:
        line = line.strip()
        if not line:
            return ""
        if line.startswith(":"):       # 心跳注释
            return ""
        if not line.startswith("data:"):
            if on_raw and line.startswith("event:"):
                pass
            return ""
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return ""
        try:
            obj = json.loads(data)
        except ValueError:
            return ""
        if self.provider == "anthropic":
            etype = obj.get("type")
            if etype == "content_block_delta":
                return obj.get("delta", {}).get("text", "") or ""
            if etype == "error":
                raise AIError("Anthropic 返回错误：%s" % obj.get("error", {}).get("message", obj))
            return ""
        # OpenAI 兼容
        if obj.get("error"):
            raise AIError("API 返回错误：%s" % obj["error"].get("message", obj["error"]))
        choices = obj.get("choices") or []
        if not choices:
            return ""
        ch = choices[0]
        delta = ch.get("delta")
        if isinstance(delta, dict):
            return delta.get("content", "") or ""
        msg = ch.get("message")
        if isinstance(msg, dict):
            return msg.get("content", "") or ""
        return ch.get("text", "") or ""

    def _parse_non_stream(self, raw: str) -> str:
        try:
            obj = json.loads(raw)
        except ValueError:
            return raw
        if isinstance(obj, dict) and obj.get("error"):
            raise AIError("API 返回错误：%s" % obj["error"].get("message", obj["error"]))
        if self.provider == "anthropic":
            blocks = obj.get("content") or []
            return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        choices = obj.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        return msg.get("content", "") or ""

    # -- 高层接口（供工作线程调用，本身是阻塞的） --------------------------
    def chat(self, messages: List[Dict[str, str]], system: str = "",
             stream: bool = True, on_delta: Optional[Callable[[str], None]] = None,
             cancel: Optional[threading.Event] = None,
             on_raw: Optional[Callable[[str], None]] = None) -> str:
        if not self.model:
            raise AIError("未填写模型名称（Model）")
        messages = self.sanitize_messages(messages, system)
        payload = self.build_payload(messages, system=system, stream=stream)
        url = self.endpoint("chat")
        return self._request(url, payload, stream, on_delta, cancel, on_raw)

    def list_models(self, limit: int = 200) -> List[str]:
        """拉取模型列表（OpenAI 兼容协议）。Anthropic 用内置列表兜底。"""
        if self.provider == "anthropic":
            return ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest",
                    "claude-3-5-haiku-latest"]
        url = self.endpoint("models")
        req = urllib.request.Request(url, headers=self.headers(), method="GET")
        timeout = int(self.cfg.get("timeout") or 60)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode(resp.headers.get_content_charset() or "utf-8", "ignore")
            obj = json.loads(raw)
            items = obj.get("data") or []
            names = [i.get("id", "") for i in items if isinstance(i, dict) and i.get("id")]
            return sorted(names)[:limit]
        except Exception as e:  # noqa: BLE001
            raise AIError("获取模型列表失败：%s" % e)

    def test(self) -> str:
        """连通性自检：发一个极短请求，返回模型回复文本。"""
        return self.chat([{"role": "user", "content": "只回复两个字：正常"}],
                         system="你是连通性测试助手。", stream=False)


def _pretty_error(body: str) -> str:
    """尽量把各家错误提成人话。"""
    if not body:
        return ""
    try:
        obj = json.loads(body)
    except ValueError:
        return body[:400]
    if isinstance(obj, dict):
        err = obj.get("error")
        if isinstance(err, dict):
            return "%s（type=%s）" % (err.get("message", ""), err.get("type", ""))
        if isinstance(err, str):
            return err
        return json.dumps(obj, ensure_ascii=False)[:400]
    return body[:400]
