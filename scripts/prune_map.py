"""Prune argument maps to the claims that lead to a market view, and report what survives.

Anchors are statements about a market variable: TRADE and RATING claims, valuation or positioning claims, and any
other non-SUPPOSITION statement whose text names a rate, curve, currency, spread or market pricing (a policy-rate
decision on its own is not an anchor). Edges follow the direction of support: a premise, assumption, warrant,
condition, qualifier, concession, risk, catalyst or alternative points to the argument's conclusion; the conclusion
points to its implications; a scenario's assumptions point to the scenario and the scenario to its implications. A
node is kept if it is an anchor or an anchor can be reached from it; everything else is dropped.

Usage::

    python scripts/prune_map.py <title>=<argument_map.yaml> ... --out <folder>
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from incolor.argumentation.diagram import ArgumentMapDiagram

POLICY = re.compile(
    r"\b(?:rate (?:hikes?|increases?|cuts?)|(?:hike|raise|lower|cut)s? rates|policy rate|(?:expected )?rate path|"
    r"unemployment[- ]rate|u-rate)\b",
    re.IGNORECASE,
)
MARKET = re.compile(
    r"\b(?:rates?|yields?|curve|front[- ]end|long[- ]end|belly|\d+Y|UST|Treasur(?:y|ies)|bonds?|USD|dollar|EUR|JPY|"
    r"GBP|CHF|FX|currenc(?:y|ies)|spreads?|asset swap|swaps?|priced|pricing|hike peak|risk assets?|equit(?:y|ies)|"
    r"\w*steepen\w*|\w*flatten\w*)\b",
    re.IGNORECASE,
)
ANCHOR_TYPES = {"TRADE", "RATING"}
ANCHOR_SUBKINDS = {"valuation", "positioning"}
SUPPORT_ROLES = (
    "premises", "assumptions", "warrants", "conditions", "qualifiers", "concessions", "risks", "catalysts",
    "alternatives", "supporting", "rationale",
)  # fmt: skip
ROLES = (*SUPPORT_ROLES, "implications")


def is_anchor(statement: dict[str, Any]) -> bool:
    """Return True if the statement is a claim about a market variable."""
    if statement["claim_type"] == "SUPPOSITION":
        return False
    if statement["claim_type"] in ANCHOR_TYPES or ANCHOR_SUBKINDS & set(statement.get("subkinds") or ()):
        return True
    return bool(MARKET.search(POLICY.sub(" ", statement["statement"])))


def prune(map_: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Return the pruned map and the set of anchor statement IDs."""
    conclusion = {a["id"]: a.get("conclusion") or a["core_claim"] for a in map_["arguments"]}

    def node(ref: str) -> str:
        return conclusion.get(ref, ref)

    edges: dict[str, set[str]] = defaultdict(set)
    for a in map_["arguments"]:
        core = conclusion[a["id"]]
        for role in SUPPORT_ROLES:
            for ref in a.get(role) or []:
                edges[node(ref)].add(core)
        for ref in a.get("implications") or []:
            edges[core].add(node(ref))
    for sc in map_.get("scenarios") or []:
        for ref in sc.get("assumptions") or []:
            edges[ref].add(sc["id"])
        for ref in [*(sc.get("implications") or sc.get("outcomes") or []), *(sc.get("recommendations") or [])]:
            edges[sc["id"]].add(ref)

    anchors = {s["id"] for s in map_["statements"] if is_anchor(s)}
    reverse: dict[str, set[str]] = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            reverse[target].add(source)
    keep, stack = set(anchors), list(anchors)
    while stack:
        for source in reverse[stack.pop()] - keep:
            keep.add(source)
            stack.append(source)

    arguments = []
    for a in map_["arguments"]:
        if conclusion[a["id"]] not in keep:
            continue
        pruned = {k: v for k, v in a.items() if k not in ROLES}
        for role in ROLES:
            members = [ref for ref in a.get(role) or [] if node(ref) in keep]
            if members:
                pruned[role] = members
        arguments.append(pruned)
    kept_args = {a["id"] for a in arguments}
    for a in arguments:
        for role in ROLES:
            if role in a:
                a[role] = [ref for ref in a[role] if not ref.startswith("A") or ref in kept_args]
    scenarios = []
    for sc in map_.get("scenarios") or []:
        if sc["id"] not in keep:
            continue
        pruned = dict(sc)
        for slot in ("assumptions", "implications", "outcomes", "recommendations"):
            if slot in sc:
                pruned[slot] = [ref for ref in sc[slot] if ref in keep]
        scenarios.append(pruned)
    used = {conclusion[a["id"]] for a in arguments}
    used |= {ref for a in arguments for role in ROLES for ref in a.get(role, []) if ref.startswith("S")}
    used |= {ref for sc in scenarios for slot in ("assumptions", "implications", "outcomes", "recommendations")
             for ref in sc.get(slot) or []}  # fmt: skip
    statements = [s for s in map_["statements"] if s["id"] in used]
    return {**map_, "statements": statements, "arguments": arguments, "scenarios": scenarios}, anchors


def report(title: str, full: dict[str, Any], pruned: dict[str, Any], anchors: set[str]) -> list[str]:
    """Return report lines: counts, then kept and dropped arguments by conclusion brief."""
    by_id = {s["id"]: s for s in full["statements"]}
    kept = {a["id"] for a in pruned["arguments"]}

    def line(a: dict[str, Any]) -> str:
        core = by_id[a.get("conclusion") or a["core_claim"]]
        mark = "*" if core["id"] in anchors else " "
        return f"  {mark} {a['id']}  {core['claim_type']:<11} {core.get('brief') or core['statement']}"

    kept_sc = {sc["id"] for sc in pruned["scenarios"]}
    lines = [
        f"== {title}",
        f"arguments {len(full['arguments'])} -> {len(pruned['arguments'])}, "
        f"statements {len(full['statements'])} -> {len(pruned['statements'])}, "
        f"scenarios {len(full.get('scenarios') or [])} -> {len(pruned['scenarios'])}, anchors {len(anchors)}",
        "kept (* = conclusion is itself a market claim):",
        *(line(a) for a in full["arguments"] if a["id"] in kept),
        *(f"    {sc['id']}  scenario    {sc['label']}" for sc in full.get("scenarios") or [] if sc["id"] in kept_sc),
        "dropped:",
        *(line(a) for a in full["arguments"] if a["id"] not in kept),
        *(
            f"    {sc['id']}  scenario    {sc['label']}"
            for sc in full.get("scenarios") or []
            if sc["id"] not in kept_sc
        ),
        "",
    ]
    return lines


def main() -> int:
    """Prune each map, write the pruned YAMLs, a report and one argument-view diagram per map."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("maps", nargs="+", help="title=path/to/argument_map.yaml")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for spec in args.maps:
        title, path = spec.split("=", 1)
        full = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        pruned, anchors = prune(full)
        slug = re.sub(r"\W+", "_", title).strip("_")
        (args.out / f"{slug}.yaml").write_text(yaml.safe_dump(pruned, sort_keys=False, allow_unicode=True), "utf-8")
        lines += report(title, full, pruned, anchors)
        ArgumentMapDiagram(pruned, show_observations=True).save(args.out / f"{slug}.mmd")
    text = "\n".join(lines)
    (args.out / "prune_report.txt").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
