"""Ask Claude Haiku whether each author string is a person, a team/title, or a fragment.

Uses the same backend as incolor.argumentation (Claude Agent SDK, single turn, no tools; needs
ANTHROPIC_API_KEY or a Claude Code login and `pip install 'claude-agent-sdk'`).

usage (notebook):
    from haiku_name_check import check_names
    verdicts = check_names(sorted(all_names))          # {name: 'person' | 'team' | 'other' | 'unchecked'}
    people = [n for n, v in verdicts.items() if v == 'person']

Results are cached in CACHE so a name is only ever sent once.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError
from tqdm.auto import tqdm

from incolor.argumentation.backends.claude_agent import ClaudeAgentBackend

MODEL = "claude-haiku-5-5"
BATCH = 100
RETRIES = 1
CACHE = Path(__file__).with_name("haiku_name_check_cache.json")


class Verdict(BaseModel):
    name: str
    kind: Literal["person", "team", "other"]


class Batch(BaseModel):
    results: list[Verdict]


SYSTEM = (
    "You clean author metadata extracted from sell-side bank research reports. Each input is a string taken from "
    "an author line after rough splitting. Classify every string as exactly one of:\n"
    "- person: the name of one individual (any nationality; initials and particles like 'de', 'van', 'El' are fine)\n"
    "- team: a desk, team, department, bank, publication or job title (e.g. 'Global Economics Team', "
    "'Chief Economist', 'BofA Euro Economics', 'Morgan Stanley Research')\n"
    "- other: a fragment or something that is not a name (a single first name or surname on its own, a country, "
    "a stray word like 'including')\n"
    "Judge only the string itself. The user message is a JSON array of strings. Return one result per input, in the "
    "same order, copying the input string exactly.\n\n"
    "Return **one JSON object only**: no prose and no code fences. It must validate against this JSON Schema:\n"
    + json.dumps(Batch.model_json_schema())
)


def _extract_json(raw: str) -> str:
    """Return the substring from the first ``{`` to the last ``}``, so stray code fences are tolerated."""
    start, end = raw.find("{"), raw.rfind("}")
    return raw[start : end + 1] if start != -1 and end > start else raw


def _generate(backend: ClaudeAgentBackend, user: str) -> str:
    """Call the backend, on a worker thread when an event loop is already running (Jupyter).

    ``backend.generate`` uses ``asyncio.run``, which cannot start inside a running loop; a fresh thread has none.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return backend.generate(SYSTEM, user, Batch.model_json_schema())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(backend.generate, SYSTEM, user, Batch.model_json_schema()).result()


def _classify(backend: ClaudeAgentBackend, chunk: list[str]) -> dict[str, str]:
    user = json.dumps(chunk, ensure_ascii=False)
    for attempt in range(RETRIES + 1):
        raw = _generate(backend, user)
        try:
            batch = Batch.model_validate(json.loads(_extract_json(raw)))
            return {v.name: v.kind for v in batch.results}
        except (json.JSONDecodeError, ValidationError):
            if attempt == RETRIES:
                return {}
    return {}


def _load() -> dict[str, str]:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def check_names(names, backend: ClaudeAgentBackend | None = None) -> dict[str, str]:
    """Return ``{name: kind}``; a name the model dropped, altered or could not be parsed is ``'unchecked'``."""
    backend = backend or ClaudeAgentBackend(model=MODEL)
    cache = _load()
    todo = [n for n in dict.fromkeys(names) if n not in cache]
    with tqdm(total=len(todo), desc="checking names", unit="name") as bar:
        for i in range(0, len(todo), BATCH):
            chunk = todo[i : i + BATCH]
            got = _classify(backend, chunk)
            for n in chunk:
                cache[n] = got.get(n, "unchecked")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            bar.update(len(chunk))
            bar.set_postfix(cost=f"${sum(u.get('cost_usd') or 0 for u in backend.usage):.4f}")
    return {n: cache[n] for n in names}
