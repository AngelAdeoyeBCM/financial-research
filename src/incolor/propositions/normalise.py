"""Stage 1 normalisation, validated by ``original() == source``.

``normalise`` rewrites the whole document in one call; ``normalise_sections`` splits it at headings and rewrites the
sections in parallel, each call seeing the whole document as context but outputting only its section. On any error,
or a warning in ``REPAIR_WARNINGS``, the model gets its previous answer plus the issue list and is asked again, up to
``max_repairs`` times. Only errors make the result fail. Quote and dash variants copied in the
wrong style, and a title or blank lines dropped at either end, are restored from the source before checking;
resolving must not change the sentence count.
"""

import json
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .annotated import (
    LOG_SEPARATOR,
    AnnotatedText,
    clean_response,
    precheck,
    restore_edges,
    snap_typography,
    split_response,
)
from .interpolation import Backend, Issue
from .sentences import split_sentences

PROMPT_PATH = Path(__file__).parent / "prompts" / "normalise_v20.md"
# Warnings that also trigger a retry; they still do not fail the result.
REPAIR_WARNINGS: set[str] = {"UNGROUNDED_WORD"}
REVIEW_REQUEST = (
    "Below is your marked-up document. Review it against every rule in the instructions, reading one statement at a "
    "time as a stranger who sees only that sentence. Add marks for anything that still points outside its sentence; "
    "fix or remove marks that rephrase, explain more than they name, change the meaning, or sit inside a heading or "
    "question. Return the complete corrected document."
)
SECTION_MIN_CHARS = 1500
HEADING_LINE = re.compile(r"^#", re.MULTILINE)


@dataclass
class NormaliseResult:
    """Best attempt (fewest errors), its issues and every raw response; ``ok`` only if the best has no errors."""

    text: AnnotatedText | None
    issues: list[Issue]
    raw_outputs: list[str]
    reviewed: bool = False
    section_raws: list[list[str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True if the best attempt passed every check."""
        return self.text is not None and not _errors(self.issues)


def _errors(issues: Sequence[Issue]) -> int:
    return sum(i.severity == "error" for i in issues)


def _blocking(issues: Sequence[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error" or i.code in REPAIR_WARNINGS]


def _rank(issues: Sequence[Issue]) -> tuple[int, int]:
    return _errors(issues), len(_blocking(issues))


def render_user_prompt(source: str) -> str:
    """Return the user prompt for ``source``."""
    return f"Input:\n{source}\n"


def repair_prompt(user_prompt: str, previous: str, issues: Sequence[Issue]) -> str:
    """Return a follow-up prompt with the previous answer and the issues it must fix."""
    errors = "\n".join(f"- {i.code} ({i.segment or 'document'}): {i.message}" for i in _blocking(issues))
    return (
        f"{user_prompt}\nYour previous answer:\n\n{previous}\n\n"
        f"It failed these checks:\n{errors}\n\n"
        "Return the complete corrected document, following every rule in the instructions."
    )


def check(
    source: str, raw: str, with_log: bool = False, context: str | None = None
) -> tuple[AnnotatedText, list[Issue]]:
    """Parse one raw response (and its log, if ``with_log``) and return it with its issues against ``source``.

    ``context`` is the whole document when ``source`` is a section of it.
    """
    if with_log:
        marked, log, problem = split_response(raw)
    else:
        marked, log, problem = clean_response(raw), None, None
    text = snap_typography(restore_edges(AnnotatedText(marked, log=log), source), source)
    issues = text.issues(source, context)
    if problem:
        issues.append(Issue("error", "LOG_MISSING", None, problem))
    if text.original() == source:
        issues.extend(_sentence_count_issues(source, text))
    return text, issues


def _sentence_count_issues(source: str, text: AnnotatedText) -> list[Issue]:
    before = split_sentences(AnnotatedText(source))
    after = split_sentences(text)
    if len(before) == len(after):
        return []
    spans = {(s.src_start, s.src_end) for s in before}
    changed = next((s for s in after if (s.src_start, s.src_end) not in spans), None)
    where = f"src {changed.src_start}" if changed else None
    detail = f"; first changed: {changed.text_brackets!r}" if changed else ""
    message = f"{len(before)} sentences in the input, {len(after)} after resolving{detail}"
    return [Issue("error", "SENTENCE_COUNT_CHANGED", where, message)]


def best_of(
    source: str, raw_outputs: Sequence[str], with_log: bool = False, context: str | None = None
) -> NormaliseResult:
    """Re-validate saved responses and keep the best: fewest errors, then fewest repairable warnings."""
    best: tuple[AnnotatedText, list[Issue]] | None = None
    for raw in raw_outputs:
        text, issues = check(source, raw, with_log, context)
        if best is None or _rank(issues) < _rank(best[1]):
            best = (text, issues)
    if best is None:
        return NormaliseResult(None, [Issue("error", "NO_RESPONSE", None, "no responses")], list(raw_outputs))
    return NormaliseResult(best[0], best[1], list(raw_outputs))


def normalise(
    source: str, backend: Backend, max_repairs: int = 2, prompt_path: Path = PROMPT_PATH, review: bool = False
) -> NormaliseResult:
    """Normalise ``source`` with retries on blocking issues, then optionally one self-review pass.

    The reviewed version replaces the result only if it ranks no worse (errors, then repairable warnings).
    """
    blocked = precheck(source)
    if blocked:
        return NormaliseResult(None, blocked, [])
    system_prompt = prompt_path.read_text(encoding="utf-8")
    with_log = LOG_SEPARATOR in system_prompt
    user_prompt = prompt = render_user_prompt(source)
    raw_outputs: list[str] = []
    for _ in range(max_repairs + 1):
        raw = backend.generate(system_prompt, prompt, {})
        raw_outputs.append(raw)
        _, issues = check(source, raw, with_log)
        if not _blocking(issues):
            break
        prompt = repair_prompt(user_prompt, raw, issues)
    result = best_of(source, raw_outputs, with_log)
    if not review or result.text is None or not result.ok:
        return result
    previous = result.text.marked
    if with_log:
        previous += f"\n\n{LOG_SEPARATOR}\n{json.dumps(result.text.log, ensure_ascii=False)}"
    raw = backend.generate(system_prompt, f"{user_prompt}\n{REVIEW_REQUEST}\n\n{previous}\n", {})
    text, issues = check(source, raw, with_log)
    if _rank(issues) <= _rank(result.issues):
        return NormaliseResult(text, issues, [*raw_outputs, raw], reviewed=True)
    return NormaliseResult(result.text, result.issues, [*raw_outputs, raw])


def split_sections(source: str, min_chars: int = SECTION_MIN_CHARS) -> list[tuple[int, int]]:
    """Return spans of the sections' text (surrounding whitespace excluded), cut at heading lines.

    Consecutive headings are merged until a section reaches ``min_chars``; a short final section joins the one before.
    """
    cuts = [m.start() for m in HEADING_LINE.finditer(source) if m.start() > 0]
    spans: list[tuple[int, int]] = []
    start = 0
    for end in [*cuts, len(source)]:
        if end - start >= min_chars or end == len(source):
            spans.append((start, end))
            start = end
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] < min_chars // 2:
        spans[-2:] = [(spans[-2][0], spans[-1][1])]
    stripped = []
    for a, b in spans:
        part = source[a:b]
        lead, trail = len(part) - len(part.lstrip()), len(part) - len(part.rstrip())
        if b - trail > a + lead:
            stripped.append((a + lead, b - trail))
    return stripped


def render_section_prompt(source: str, part: str) -> str:
    """Return the user prompt that gives the whole document as context and asks for one section only."""
    return (
        f"Document (context only, do not output it):\n{source}\n\n"
        f"Rewrite only this part of the document and output only the rewritten part:\nInput:\n{part}\n"
    )


def normalise_sections(
    source: str,
    backend: Backend,
    max_repairs: int = 1,
    prompt_path: Path = PROMPT_PATH,
    workers: int = 6,
    min_chars: int = SECTION_MIN_CHARS,
) -> NormaliseResult:
    """Normalise ``source`` section by section in parallel, retrying only the sections that fail their checks.

    A section that still fails keeps its source text unmarked (``SECTION_UNRESOLVED`` warning), so the document as a
    whole stays valid; the combined text is then checked against the whole source.
    """
    blocked = precheck(source)
    if blocked:
        return NormaliseResult(None, blocked, [])
    system_prompt = prompt_path.read_text(encoding="utf-8")
    if LOG_SEPARATOR in system_prompt:
        raise ValueError("sectioned normalisation does not support log prompts; use normalise()")
    spans = split_sections(source, min_chars)

    def run(span: tuple[int, int]) -> tuple[NormaliseResult, list[str]]:
        part = source[span[0] : span[1]]
        user_prompt = prompt = render_section_prompt(source, part)
        raws: list[str] = []
        for _ in range(max_repairs + 1):
            raw = backend.generate(system_prompt, prompt, {})
            raws.append(raw)
            _, issues = check(part, raw, context=source)
            if not _blocking(issues):
                break
            prompt = repair_prompt(user_prompt, raw, issues)
        return best_of(part, raws, context=source), raws

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(run, spans))
    pieces: list[str] = []
    unresolved: list[Issue] = []
    pos = 0
    for (a, b), (section, _) in zip(spans, results, strict=True):
        pieces.append(source[pos:a])
        if section.ok and section.text is not None:
            pieces.append(section.text.marked)
        else:
            pieces.append(source[a:b])
            codes = sorted({i.code for i in section.issues if i.severity == "error"})
            unresolved.append(Issue("warning", "SECTION_UNRESOLVED", f"src {a}", f"left unmarked after {codes}"))
        pos = b
    pieces.append(source[pos:])
    combined = "".join(pieces)
    text, issues = check(source, combined)
    return NormaliseResult(text, [*issues, *unresolved], [combined], section_raws=[raws for _, raws in results])
