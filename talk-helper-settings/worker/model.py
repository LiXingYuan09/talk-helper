"""Pure state for a suggestion tied to one visible incoming chat bubble."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit


def official_base(value: str) -> str:
    """Only the direct official HTTPS endpoint may receive conversation text."""
    parsed = urlsplit(str(value or "https://api.deepseek.com").strip())
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    if (parsed.scheme != "https" or parsed.hostname != "api.deepseek.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or path not in ("", "/v1")):
        raise ValueError("仅允许 DeepSeek 官方直连：https://api.deepseek.com（可加 /v1）")
    return "https://api.deepseek.com" + path


def clipped_rect(rect, width: int, height: int):
    if rect is None:
        return None
    left, top, right, bottom = (int(v) for v in rect)
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    return (left, top, right, bottom) if right > left and bottom > top else None


@dataclass(frozen=True)
class Snapshot:
    title: str
    messages: tuple  # (who, text, speaker); visible order, oldest first
    anchor: tuple  # left, top, right, bottom in parent client physical pixels
    area: tuple  # left, top, right, bottom in parent client physical pixels
    incoming_index: int
    timestamps: tuple = ()  # aligned trusted create_time values, never UI/image text

    @property
    def identity(self):
        # Include prior visible context to distinguish repeated short messages.
        prior = self.messages[max(0, self.incoming_index - 5):self.incoming_index + 1]
        raw = json.dumps((self.title, prior, self.timestamps), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def latest_is_incoming(self):
        return bool(self.messages) and self.messages[-1][0] == "her"


@dataclass(frozen=True)
class SemanticView:
    """Exact recognized visible conversation and positions; never persisted."""
    title: str
    lines: tuple  # (who, name, text, left, top, right, bottom), capture coordinates
    header: tuple
    region: tuple

    @property
    def guards(self):
        # Include padding around text/bubbles so nearby glyph/layout movement
        # cannot get folded into a learned animation tile.
        return (self.header,) + tuple((line[3] - 3, line[4] - 3, line[5] + 3, line[6] + 3)
                                      for line in self.lines)

    def matches(self, other):
        return isinstance(other, SemanticView) and bool(self.title) and self == other


class AdviceState:
    """Never expose an answer against an unverified or different conversation."""
    def __init__(self):
        self.snapshot = None
        self.verified = False
        self.paused = False
        self.pending_key = None
        self.cache = OrderedDict()
        self.errors = {}
        self.attempted = set()
        self.selected = 0

    def changing(self):
        self.verified = False

    def observe(self, snapshot):
        previous = self.snapshot.identity if self.snapshot else None
        self.snapshot = snapshot
        self.verified = snapshot is not None
        if snapshot is None or previous != snapshot.identity:
            self.selected = 0

    def request(self, force=False):
        snapshot = self.snapshot
        if (self.paused or not self.verified or snapshot is None
                or (not snapshot.latest_is_incoming and not force) or self.pending_key is not None):
            return None
        key = snapshot.identity
        if not force and key in self.attempted:
            return None
        self.attempted.add(key)
        if len(self.attempted) > 200:
            self.attempted = set(self.cache) | {key}
        self.errors.pop(key, None)
        if force:
            self.cache.pop(key, None)
        self.pending_key = key
        return key, snapshot

    def complete(self, key, result=None, error=None):
        if key != self.pending_key:
            return False
        self.pending_key = None
        if error:
            self.errors[key] = str(error)
        elif result:
            self.cache[key] = result
            self.cache.move_to_end(key)
            while len(self.cache) > 20:
                self.cache.popitem(last=False)
        return self.visible_key == key

    @property
    def visible_key(self):
        if self.paused or not self.verified or self.snapshot is None:
            return None
        return self.snapshot.identity

    @property
    def result(self):
        return self.cache.get(self.visible_key)

    def next_candidate(self):
        result = self.result
        if result:
            self.selected = (self.selected + 1) % len(result["candidates"])

    @property
    def reply(self):
        result = self.result
        if result:
            candidates = result["candidates"]
            # Start on the ranked best; next cycles all distinct alternatives.
            index = (int(result.get("best_index", 0)) + self.selected) % len(candidates)
            return candidates[index]
        return ""
