"""Hidden, OCR-free WeChat text reader and direct DeepSeek advice worker."""
from __future__ import annotations

import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from model import AdviceState, Snapshot, official_base


def load_settings(path):
    source = Path(__file__).resolve().parents[2] / "jev-chat-desktop"
    if source.is_dir():
        sys.path.insert(0, str(source))
    from app import settings
    settings._CONFIG = str(Path(path).resolve())
    refresh_key(settings)
    return settings


def refresh_key(settings):
    if getattr(settings,'_talkhelper_snapshot',False):return settings.deepseek_key()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = str(winreg.QueryValueEx(key, "DEEPSEEK_API_KEY")[0]).strip()
        if value:
            os.environ["DEEPSEEK_API_KEY"] = value
    except (OSError, ImportError):
        pass
    return settings.deepseek_key()


class DirectHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, request):
        url = urlsplit(request.full_url)
        if (url.scheme != "https" or url.hostname != "api.deepseek.com"
                or url.port not in (None, 443) or url.username or url.password
                or url.query or url.fragment
                or url.path not in ("/chat/completions", "/v1/chat/completions")):
            raise urllib.error.URLError("Official DeepSeek HTTPS only")
        return super().https_open(request)


class NoHTTP(urllib.request.HTTPHandler):
    def http_open(self, request):
        raise urllib.error.URLError("HTTP disabled")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise urllib.error.URLError("Redirect disabled")


def install_network_guard():
    urllib.request.install_opener(urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoHTTP(), DirectHTTPS(), NoRedirect()))


class RuntimeStatus:
    def __init__(self, config):
        self.path = Path(config).resolve().parent / "runtime-status.json"
        self.values = {"schema": 2, "worker_revision": "direct-2", "source": "wechat-db-uia",
                       "ocr_used": False, "stage": "starting", "api_ok": 0}
        self.last = 0.0

    def update(self, **fields):
        self.values.update(fields)
        now = time.monotonic()
        if now - self.last < 0.5:
            return
        self.last = now
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.values, ensure_ascii=True), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


class VisibleChat:
    """Read WeChat's accessible controls; no screenshot or OCR is taken."""
    def __init__(self, parent):
        import uiautomation as auto
        self.auto = auto
        self.parent = int(parent)
        auto.InitializeUIAutomationInCurrentThread()
        auto.SetGlobalSearchTimeout(1.0)
        self.user32 = c.WinDLL("user32")
        self.user32.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
        self.user32.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]

    def scan(self):
        root = self.auto.ControlFromHandle(self.parent)
        if root is None:
            return None
        chat_input = message_list = None
        stack = [(root, 0)]
        visited = 0
        while stack and visited < 600:
            node, depth = stack.pop()
            visited += 1
            try:
                aid = node.AutomationId or ""
                if aid.endswith("chat_input_field"):
                    chat_input = node
                elif aid.endswith("chat_message_list"):
                    message_list = node
                if chat_input and message_list:
                    break
                if depth < 30:
                    stack.extend((child, depth + 1) for child in node.GetChildren())
            except Exception:
                continue
        if not chat_input or not message_list:
            return None
        title = (chat_input.Name or "").strip()
        if not title:
            return None
        list_rect = message_list.BoundingRectangle
        rows = []
        for node in message_list.GetChildren():
            try:
                if "chat_bubble_item_view" not in (node.AutomationId or ""):
                    continue
                rect = node.BoundingRectangle
                if (rect.right <= rect.left or rect.bottom <= rect.top
                        or rect.bottom <= list_rect.top or rect.top >= list_rect.bottom):
                    continue
                rows.append((node, rect))
            except Exception:
                continue
        if not rows:
            return None
        origin = w.POINT(0, 0)
        client = w.RECT()
        if not self.user32.ClientToScreen(self.parent, c.byref(origin)):
            return None
        if not self.user32.GetClientRect(self.parent, c.byref(client)):
            return None
        area = (max(0, list_rect.left - origin.x), max(0, list_rect.top - origin.y),
                min(client.right, list_rect.right - origin.x),
                min(client.bottom, list_rect.bottom - origin.y))
        if area[2] - area[0] < 180 or area[3] - area[1] < 100:
            return None
        visible_rows = []
        for node, rect in sorted(rows, key=lambda entry: entry[1].bottom):
            # A clipped row can move beneath the card or refer to old history.
            if rect.top < list_rect.top or rect.bottom > list_rect.bottom:
                continue
            value = ""
            for name in ("GetValuePattern", "GetTextPattern"):
                try:
                    pattern = getattr(node, name)()
                    candidate = (pattern.Value if name == "GetValuePattern"
                                 else pattern.DocumentRange.GetText(-1)) if pattern else ""
                    if candidate and candidate.strip() and candidate.strip() != title:
                        value = candidate.strip()
                        break
                except Exception:
                    pass
            if not value:
                name = (node.Name or "").strip()
                if name and name != title:
                    value = name
            left = max(area[0] + 10, rect.left - origin.x + 64)
            right = min(area[2], left + 300)
            anchor = (left, max(area[1], rect.top - origin.y), right,
                      min(area[3], rect.bottom - origin.y))
            if anchor[2] <= anchor[0] or anchor[3] <= anchor[1]:
                continue
            try:
                runtime_id = tuple(node.GetRuntimeId())
            except Exception:
                runtime_id = ()
            signature = (runtime_id, node.ClassName or "", rect.left, rect.top,
                         rect.right, rect.bottom)
            visible_rows.append({"anchor": anchor, "row_text": value,
                                 "signature": signature})
        if not visible_rows:
            return None
        return {"title": title, "area": area, "rows": visible_rows,
                "row_count": len(visible_rows)}


def display(state, idle="等待可验证的对方消息"):
    payload = {"title": "talk helper", "paused": state.paused}
    if state.paused:
        return dict(payload, status="已暂停", body="点击继续后恢复直接读取")
    key, result = state.visible_key, state.result
    if not key:
        return dict(payload, status=idle, body="只读取微信原文；不使用 OCR")
    payload.update(anchor=state.snapshot.anchor, area=state.snapshot.area)
    if result:
        guidance = result["guidance"]
        count = len(result["candidates"])
        selected = (int(result.get("best_index", 0)) + state.selected) % count + 1
        lines = ["理解：" + guidance["summary"], "", f"可回复（{selected}/{count}）：", state.reply,
                 "", "可以这样做："]
        lines.extend(f"{i}. {action}" for i, action in enumerate(guidance["actions"], 1))
        lines += ["", "注意：" + guidance["avoid"]]
        return dict(payload, status="建议：" + guidance["actions"][0],
                    body="\r\n".join(lines), reply=state.reply)
    if key == state.pending_key:
        return dict(payload, status="DeepSeek 正在生成建议…", busy=True,
                    body="已直接读取微信原文，正在整理具体建议")
    if key in state.errors:
        return dict(payload, status="生成失败", body=state.errors[key], error=True)
    return dict(payload, status="等待新消息", body="消息文字已直接读取")


def safe_error(exc):
    message = str(exc).lower()
    if "401" in message or "api key" in message or "missing_key" in message:
        return "DeepSeek API Key 缺失或无效"
    if "402" in message or "balance" in message:
        return "DeepSeek 余额不足"
    if "429" in message:
        return "DeepSeek 请求过于频繁"
    if "timeout" in message or "timed out" in message:
        return "DeepSeek 请求超时"
    return "DeepSeek 生成失败；请稍后重试"


def normalized(value):
    return "".join(str(value or "").split())


def message_body(record, group=False):
    """Remove WeChat's group sender envelope only when it agrees with sender_id."""
    content = str(record.get("content") or "")
    if not group or record.get("sender_id") == 2:
        return content
    sender = record.get("sender_username") or ""
    if sender and content.startswith(sender + ":\n"):
        return content[len(sender) + 2:]
    return content


def matching_rows(row_text, records, group=False):
    """Match one visible UIA row to one decrypted record, never by position alone."""
    seen = normalized(row_text)
    if not seen:
        return []
    matches = []
    for index, record in enumerate(records):
        if record["type"] != "文本":
            continue
        content = normalized(message_body(record, group))
        if not content:
            continue
        if seen == content or (len(content) >= 8 and seen.endswith(content)):
            matches.append(index)
    return matches


def matched_visible_rows(visible_rows, records, group=False):
    matches = []
    for row in visible_rows:
        indices = matching_rows(row["row_text"], records, group)
        if len(indices) == 1:
            matches.append((row, indices[0]))
    incoming = [(row, index) for row, index in matches
                if records[index]["sender_id"] != 2]
    return matches, incoming


def profile_for_snapshot(settings,snapshot):
    profile=settings.profile() if hasattr(settings,'profile') else None
    if not isinstance(profile,dict):return None
    speaker=snapshot.messages[-1][2] if snapshot.messages and len(snapshot.messages[-1])>2 else None
    if speaker and profile.get('other_alias')!=speaker:
        # A group profile for one named person cannot describe another member.
        return {key:value for key,value in profile.items() if key.startswith('self_') or key in ('goal','feeling')}
    return profile

def analyze(settings, snapshot):
    from core.engine import analyze as engine
    from chat_time import time_context
    if not refresh_key(settings):
        raise ValueError("MISSING_KEY")
    timing=time_context(snapshot)
    result=engine(list(snapshot.messages), settings.relationship(),
                  model=settings.deepseek_model(), context=settings.context(),
                  timeout=35, provider="deepseek", style=settings.style(),
                  thinking=settings.thinking(), base_url=official_base(settings.deepseek_base_url()),timing=timing,
                  profile=profile_for_snapshot(settings,snapshot))
    result['timing']=timing
    return result


def run(args, settings):
    from direct_data import ConversationDB
    from ipc import NativePanel, RETRY, NEXT_REPLY, TOGGLE_PAUSE
    c.WinDLL("user32").SetProcessDpiAwarenessContext(c.c_void_p(-4))
    panel = NativePanel(args.parent, args.panel, args.parent_pid, args.token)
    status = RuntimeStatus(args.config)
    state = AdviceState()
    panel.update(**display(state, "正在直接读取微信消息…"))
    completed = queue.Queue()
    db_result = queue.Queue(maxsize=1)
    temporary = tempfile.TemporaryDirectory(prefix="talk-helper-direct-")

    def init_db():
        try:
            db = ConversationDB(wechat_pid=args.parent_pid, workdir=temporary.name,
                                keys_file=os.path.join(temporary.name, "no-key-cache.json"))
            db_result.put((db, None))
        except Exception:
            db_result.put((None, "无法直接读取微信数据库；请确认微信已登录"))

    threading.Thread(target=init_db, daemon=True, name="talk-helper-db").start()
    try:
        ui = VisibleChat(args.parent)
    except Exception:
        ui = None
    db = None
    force = False
    last_scan = 0.0
    last_extended = {}
    idle = "正在直接读取微信消息…"

    def start_api(request):
        key, snapshot = request
        def work():
            try:
                completed.put((key, analyze(settings, snapshot), None))
            except Exception as exc:
                completed.put((key, None, safe_error(exc)))
        threading.Thread(target=work, daemon=True, name="talk-helper-deepseek").start()

    try:
        while panel.alive():
            commands = panel.poll()
            if commands & TOGGLE_PAUSE:
                state.paused = not state.paused
                state.changing()
                panel.update(**display(state, idle))
            if commands & NEXT_REPLY:
                state.next_candidate()
                panel.update(**display(state, idle))
            if commands & RETRY:
                force = True
            while not db_result.empty():
                db, error = db_result.get_nowait()
                if error:
                    idle = error
                    status.update(stage="db_failed")
                else:
                    status.update(stage="db_ready", key_count=len(db._keys),
                                  db_count=len(db._db_files))
            while not completed.empty():
                key, result, error = completed.get_nowait()
                state.complete(key, result, error)
                if result:
                    status.update(api_ok=status.values["api_ok"] + 1)
                panel.update(**display(state, idle))
            if state.paused or panel.minimized() or not db or not ui:
                if not db and not state.paused:
                    panel.update(**display(state, idle))
                time.sleep(0.15)
                continue
            now = time.monotonic()
            if now - last_scan < 2.5:
                time.sleep(0.1)
                continue
            last_scan = now
            try:
                visible = ui.scan()
                if not visible:
                    state.observe(None)
                    idle = "当前聊天未暴露可定位的文字消息"
                    status.update(stage="no_uia_row")
                    panel.update(**display(state, idle))
                    continue
                title = visible["title"]
                username = db.resolve_chat(title)
                if not username:
                    state.observe(None)
                    idle = "无法唯一确认当前微信会话"
                    status.update(stage="unresolved_chat", uia_rows=visible["row_count"])
                    panel.update(**display(state, idle))
                    continue
                records = db.get_messages(username, limit=150)
                if not records:
                    state.observe(None)
                    continue
                group = username.endswith("@chatroom")
                matched, incoming_matches = matched_visible_rows(visible["rows"], records, group)
                if (not incoming_matches and any(row["row_text"] for row in visible["rows"])
                        and now - last_extended.get(username, 0) > 30):
                    last_extended[username] = now
                    records = db.get_messages(username, limit=1000)
                    matched, incoming_matches = matched_visible_rows(visible["rows"], records, group)
                if not incoming_matches:
                    state.observe(None)
                    idle = "可见消息中暂无可唯一确认的对方文字"
                    status.update(stage="await_verified_message", uia_rows=visible["row_count"],
                                  row_text_available=any(row["row_text"] for row in visible["rows"]),
                                  matched_record_count=len(matched),
                                  matched_incoming_count=0,
                                  direct_text_count=sum(r["type"] == "文本" for r in records))
                    panel.update(**display(state, idle))
                    continue
                row, target_index = incoming_matches[-1]
                context_records = records[target_index:target_index + max(12, settings.context())]
                messages = tuple(("me" if r["sender_id"] == 2 else "her", message_body(r, group),
                                  r.get("sender_username") or None)
                                 for r in reversed(context_records) if r["type"] == "文本")
                if not messages or messages[-1][0] != "her":
                    state.observe(None)
                    continue
                snapshot = Snapshot(title, messages, row["anchor"], visible["area"], len(messages)-1)
                state.observe(snapshot)
                status.update(stage="anchored", anchor_present=True, uia_rows=visible["row_count"],
                              row_text_available=True, exact_match=True,
                              matched_record_count=len(matched),
                              matched_incoming_count=len(incoming_matches),
                              matched_index=target_index)
                request = state.request(force=force)
                force = False
                panel.update(**display(state, idle))
                if request:
                    start_api(request)
            except Exception:
                state.observe(None)
                idle = "微信文字或位置暂不可读；稍后自动重试"
                status.update(stage="read_error")
                panel.update(**display(state, idle))
    finally:
        status.update(stage="stopped")
        temporary.cleanup()
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=int, required=True)
    parser.add_argument("--panel", type=int, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--token", type=int, required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    install_network_guard()
    return run(args, load_settings(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
