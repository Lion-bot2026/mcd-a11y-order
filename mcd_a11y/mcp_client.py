# -*- coding: utf-8 -*-
"""麦当劳 MCP 客户端 —— 仅用 Python 标准库。

协议：Streamable HTTP，版本 2025-06-18
端点：https://mcp.mcd.cn
鉴权：Authorization: Bearer <TOKEN>（32 位，只从环境变量读取）
限流：600 次/分钟

实测要点：
  * 服务端无状态 —— tools/list 与 tools/call 不依赖 session id；
    Mcp-Session-Id 有则回传，无则不发。
  * 请求头必须同时声明 application/json 与 text/event-stream。
  * 每进程握手一次即可，不要每次调用都 initialize（浪费配额）。
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any

from .parser import extract_json

MCP_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
ACCEPT = "application/json, text/event-stream"

RETRYABLE_HTTP = {429, 500, 502, 503, 504}

# 写操作绝不缓存，也绝不进离线快照
WRITE_TOOLS = frozenset({
    "create-order", "cancel-order", "auto-bind-coupons",
    "draw-lottery", "mall-create-order", "party-order-create",
})

# 官方业务错误码 → 人类可读
ERROR_HINTS = {
    600057: "该门店当前已打烊或不在营业时间，请换一家门店或稍后再试。",
    600058: "城市名与关键词必须同时提供。",
    600046: "该查询仅支持到店自取（beType=1）与得来速（beType=5）。",
    600042: "缺少取餐方式，请先调用 calculate-price 获取 takeWayCode。",
}


class McpError(RuntimeError):
    def __init__(self, msg: str, *, code: Any = None, retryable: bool = False):
        super().__init__(msg)
        self.code = code
        self.retryable = retryable

    def human(self) -> str:
        if self.code in ERROR_HINTS:
            return ERROR_HINTS[self.code]
        return str(self)


class McdMcpClient:
    def __init__(self, token: str | None = None, url: str = MCP_URL,
                 timeout: int = 30, max_retries: int = 4,
                 client_name: str = "mcd-a11y-order") -> None:
        self.token = (token or os.environ.get("MCD_MCP_TOKEN", "")).strip()
        if not self.token:
            raise McpError(
                "未设置 MCD_MCP_TOKEN。\n"
                "请到 https://open.mcd.cn/mcp 用手机号登录后申请，然后：\n"
                "    export MCD_MCP_TOKEN=你的Token\n"
                "Token 只从环境变量读取，禁止写入代码或提交到仓库。"
            )
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries
        self.client_name = client_name
        self._id = 0
        self._session: str | None = None
        self.state = "INIT"

    # ---------------- 传输层 ----------------

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": ACCEPT,
            "Authorization": f"Bearer {self.token}",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session:
            h["Mcp-Session-Id"] = self._session
        return h

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _backoff(self, err: urllib.error.HTTPError | None, attempt: int) -> float:
        """429 优先遵守 Retry-After，否则指数退避 + 抖动（防惊群）。"""
        ra = err.headers.get("Retry-After") if err is not None and err.headers else None
        if ra and str(ra).isdigit():
            return min(int(ra), 60) + random.uniform(0, 0.5)
        return min(2 ** attempt, 30) + random.uniform(0, 1.0)

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(self.url, data=body,
                                         headers=self._headers(), method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    sid = resp.headers.get("Mcp-Session-Id")
                    if sid:
                        self._session = sid
                    ctype = resp.headers.get("Content-Type", "") or ""
                    raw = resp.read().decode("utf-8", errors="replace")
                return self._parse_body(raw, ctype, payload.get("id"))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise McpError(
                        f"Token 无效或已过期（HTTP {e.code}），请到 open.mcd.cn/mcp 重新申请。",
                        code=e.code) from e
                if e.code not in RETRYABLE_HTTP:
                    detail = ""
                    try:
                        detail = e.read().decode("utf-8", errors="replace")[:300]
                    except Exception:
                        pass
                    raise McpError(f"HTTP {e.code}: {detail}", code=e.code) from e
                last = e
                time.sleep(self._backoff(e, attempt))
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                time.sleep(self._backoff(None, attempt))
        raise McpError(f"请求失败（已重试 {self.max_retries} 次）：{last}", retryable=True)

    @staticmethod
    def _parse_body(raw: str, ctype: str, want_id: Any) -> dict:
        """Streamable HTTP 可能返回 application/json 或 text/event-stream。

        比「取第一个能 parse 的事件」更稳的做法：收集全部 data: 事件，
        优先取 id 匹配的那一个 —— 服务端可能先发 progress 通知。
        """
        is_sse = ("text/event-stream" in ctype) or raw.lstrip().startswith("event:") \
            or "\ndata:" in raw
        if not is_sse:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                obj = extract_json(raw)
                if obj is None:
                    raise McpError(f"无法解析响应：{raw[:200]!r}")
                return obj if isinstance(obj, dict) else {"result": obj}

        events: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                ev = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                events.append(ev)
        if not events:
            raise McpError(f"无法从 SSE 响应解析 JSON：{raw[:200]!r}")
        if want_id is not None:
            for ev in events:
                if ev.get("id") == want_id:
                    return ev
        return events[-1]

    # ---------------- 握手 ----------------

    def initialize(self) -> dict:
        r = self._post({
            "jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION,
                       "capabilities": {},
                       "clientInfo": {"name": self.client_name, "version": "1.0.0"}},
        })
        self.state = "HANDSHAKED"
        return r

    def notify_initialized(self) -> None:
        """notifications/* 是通知（无 id），服务端通常返回 202 且 body 为空。"""
        body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized",
                           "params": {}}).encode("utf-8")
        req = urllib.request.Request(self.url, data=body,
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session = sid
        except urllib.error.HTTPError as e:
            # 部分服务端对通知返回 202/204，body 为空也算成功
            if e.code not in (200, 202, 204):
                raise McpError(f"notifications/initialized 失败：HTTP {e.code}") from e
        self.state = "READY"

    def _ensure_ready(self) -> None:
        if self.state == "READY":
            return
        if self.state == "INIT":
            self.initialize()
        self.notify_initialized()

    # ---------------- 工具调用 ----------------

    def list_tools(self) -> list[dict]:
        self._ensure_ready()
        r = self._post({"jsonrpc": "2.0", "id": self._next_id(),
                        "method": "tools/list", "params": {}})
        return r.get("result", {}).get("tools", []) or []

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self._ensure_ready()
        r = self._post({"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
                        "params": {"name": name, "arguments": arguments or {}}})
        if "error" in r:
            err = r["error"]
            raise McpError(f"MCP 业务错误 [{err.get('code')}]：{err.get('message')}",
                           code=err.get("code"))
        return r.get("result", {}) or {}

    def call_business(self, name: str, arguments: dict | None = None) -> Any:
        """取业务数据。三级降级：

        L1 structuredContent —— 服务端预解析，最稳
        L2 从文本里抠 JSON（strict=False，data 字段含裸换行）
        L3 抛可见错误，绝不静默返回空
        """
        res = self.call_tool(name, arguments)

        obj = None
        if isinstance(res, dict) and res.get("structuredContent") is not None:
            obj = res["structuredContent"]
        if obj is None:
            text = self._text_of(res)
            obj = extract_json(text)
            if obj is None:
                raise McpError(f"{name} 未返回可解析 JSON（前 200 字符：{text[:200]!r}）")

        # 实测：服务端对全部工具都返回同一层信封
        # {success, code, message, datetime, traceId, data}，
        # structuredContent 也指向这层信封 —— 必须统一剥掉，否则下游解析会静默拿到 0 条。
        if isinstance(obj, dict) and "data" in obj and set(obj) & {"success", "code"}:
            if obj.get("success") is False:
                raise McpError(
                    f"{name} 业务失败（code={obj.get('code')}，"
                    f"message={obj.get('message')}）。"
                    f"常见原因：门店不在营业时间。请换一家营业中的门店重试。")
            return obj["data"]
        return obj

    @staticmethod
    def _text_of(result: Any) -> str:
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                return "\n".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text")
            if "text" in result:
                return str(result["text"])
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
