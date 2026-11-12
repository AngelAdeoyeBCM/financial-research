"""Text that remembers what was stripped from it and logs every edit made to it."""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

Replacement = str | Callable[[re.Match[str]], str]
Kind = str | Callable[[str], str]
_TOKEN_RE = re.compile(r"\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_EDGE_SPACE_RE = re.compile(r"\A | \Z")


@dataclass(frozen=True)
class IgnoredText:
    """Text removed from the content but kept for review (rendered as an ignore block)."""

    rule: str
    kind: str
    text: str


@dataclass(frozen=True)
class Edit:
    """One normalisation change: ``before`` became ``after``."""

    rule: str
    before: str
    after: str


@dataclass(frozen=True)
class Anchor:
    """Where ignored text sat in the current content; ``seq`` keeps stripping order for equal positions."""

    pos: int
    seq: int
    item: IgnoredText


class EditableText:
    """Content string plus anchors for stripped text; every change goes through ``apply`` and is logged."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.edits: list[Edit] = []
        self._anchors: list[Anchor] = []
        self._seq = 0

    @property
    def anchors(self) -> list[Anchor]:
        """Anchors in content order."""
        return sorted(self._anchors, key=lambda a: (a.pos, a.seq))

    @property
    def ignored(self) -> list[IgnoredText]:
        """Everything stripped so far, in content order."""
        return [a.item for a in self.anchors]

    def tokens(self) -> list[re.Match[str]]:
        """Whitespace-separated tokens of the current content."""
        return list(_TOKEN_RE.finditer(self.text))

    def apply(
        self, rule: str, spans: Iterable[tuple[int, int, str]], *, ignore_kind: Kind | None = None, log: bool = True
    ) -> int:
        """Replace non-overlapping ``(start, end, replacement)`` spans; returns how many changed the text.

        With ``ignore_kind`` (a kind, or a function of the removed text) the removed text is kept as an anchor at the
        start of its replacement; otherwise each change is logged as an ``Edit`` unless ``log`` is False.
        """
        old = self.text
        ordered = sorted((s, e, r) for s, e, r in spans if old[s:e] != r)
        if not ordered:
            return 0
        pieces: list[str] = []
        new_starts: list[int] = []
        added: list[Anchor] = []
        cursor = shift = 0
        for s, e, r in ordered:
            if s < cursor:
                raise ValueError(f"{rule}: overlapping edits at offset {s}")
            pieces += [old[cursor:s], r]
            new_starts.append(s + shift)
            if ignore_kind:
                if removed := old[s:e].strip():
                    kind = ignore_kind(removed) if callable(ignore_kind) else ignore_kind
                    added.append(Anchor(s + shift, self._seq, IgnoredText(rule, str(kind), removed)))
                    self._seq += 1
            elif log:
                self.edits.append(Edit(rule, old[s:e], r))
            shift += len(r) - (e - s)
            cursor = e
        pieces.append(old[cursor:])
        self._anchors = [self._remap(a, ordered, new_starts) for a in self._anchors] + added
        self.text = "".join(pieces)
        return len(ordered)

    def sub(
        self,
        rule: str,
        pattern: re.Pattern[str],
        repl: Replacement,
        *,
        ignore_kind: Kind | None = None,
        log: bool = True,
    ) -> int:
        """``re.sub`` that records what it removed or changed."""
        if callable(repl):
            render = repl
        elif "\\" in repl:
            render = lambda m: m.expand(repl)  # noqa: E731
        else:
            render = lambda _m: repl  # noqa: E731
        spans = [(m.start(), m.end(), render(m)) for m in pattern.finditer(self.text)]
        return self.apply(rule, spans, ignore_kind=ignore_kind, log=log)

    def drop_tokens(self, rule: str, drop: Sequence[bool], *, ignore_kind: str) -> int:
        """Remove the flagged tokens (each contiguous run becomes one ignored span), then collapse whitespace."""
        tokens = self.tokens()
        spans: list[tuple[int, int, str]] = []
        i = 0
        while i < len(tokens):
            if not drop[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(tokens) and drop[j + 1]:
                j += 1
            spans.append((tokens[i].start(), tokens[j].end(), " "))
            i = j + 1
        changed = self.apply(rule, spans, ignore_kind=ignore_kind)
        self.collapse_whitespace()
        return changed

    def collapse_whitespace(self) -> None:
        """Single spaces between tokens and none at the ends, as ``" ".join(text.split())``."""
        self.sub("whitespace", _WHITESPACE_RE, " ", log=False)
        self.sub("whitespace", _EDGE_SPACE_RE, "", log=False)

    def note(self, rule: str, before: str, after: str) -> None:
        """Log a change made through a log-free ``apply`` (e.g. a dropped empty bullet inside a layout pass)."""
        self.edits.append(Edit(rule, before, after))

    @staticmethod
    def _remap(anchor: Anchor, spans: list[tuple[int, int, str]], new_starts: list[int]) -> Anchor:
        # Anchors inside or at the start of a replaced span move to its start; at its end they follow it.
        p, shift = anchor.pos, 0
        for (s, e, r), new_start in zip(spans, new_starts, strict=True):
            if e < p or (e == p and s < p):
                shift += len(r) - (e - s)
            elif s <= p:
                return Anchor(new_start, anchor.seq, anchor.item)
            else:
                break
        return Anchor(p + shift, anchor.seq, anchor.item)
