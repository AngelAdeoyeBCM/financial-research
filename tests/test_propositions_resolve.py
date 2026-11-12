import json

import pytest

from incolor.propositions.edits import annotate
from incolor.propositions.referents import check_decision, check_referent, find_candidates, run_references
from incolor.propositions.resolve import STAGE_PROMPTS, check_ellipsis, resolve
from incolor.propositions.rules import abbreviations, rule_edits, third_person
from incolor.propositions.staging import Doc


def resolved(source):
    return annotate(source, rule_edits(source)[0]).resolved(brackets=True)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Rates & curve + FX = risk, ~85% in Oct/Dec and/or later; S&P +25bps.",
         "Rates [and] curve [and] FX [is] risk, [approximately] 85% in Oct [or] Dec and/or later; S&P +25bps."),
        ("We think so. We also expect cuts. We might guess. We found it. In our view, US data help us.",
         "[The author thinks] so. [The author also expects] cuts. [The author] might guess. [The author] found it. "
         "In [the author's] view, US data help [the author]."),
        ("We're curious. He said “we see risk”.", "[The author is] curious. He said “we see risk”."),
        ("Exhibit 3: Our forecast & range\n\nSource: our estimates. We think so.",
         "Exhibit 3: Our forecast [and] range\n\nSource: our estimates. [The author thinks] so."),
        ("## Our view & JH\n\nWe see Warsh Jackson Hole (JH) speech. JH matters. Will we see JH Warsh?",
         "## Our view [and] [Jackson Hole]\n\n[The author sees] Warsh Jackson Hole (JH) speech. "
         "[Jackson Hole] matters. Will we see [Jackson Hole] Warsh?"),
    ],
)  # fmt: skip
def test_rules(source, expected):
    assert resolved(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("by Warsh Jackson Hole (JH) speech", {"JH": ("Jackson Hole", (9, 26))}),
        ("The contribution of Food, Alcohol and Tobacco (FAT) fell.", {"FAT": ("Food, Alcohol and Tobacco", (20, 51))}),
        ("the pace of quantitative tightening (QT) slows", {"QT": ("quantitative tightening", (12, 40))}),
        ("The SEP (Summary of Economic Projections) shows", {"SEP": ("Summary of Economic Projections", (4, 41))}),
        ("rates rose (bullish) and (Exhibit 2) (ABC)", {}),
    ],
)
def test_abbreviation_definitions(source, expected):
    assert abbreviations(source) == expected


@pytest.mark.parametrize(
    ("verb", "out"), [("think", "thinks"), ("guess", "guesses"), ("are", "is"), ("worry", "worries")]
)
def test_third_person(verb, out):
    assert third_person(verb) == out


def test_candidates_skip_quotes_time_figures_captions_and_rule_edits():
    source = (
        "Rates rose (Exhibit 2). This week it fell, as “they said”. These moves matter; that is clear. "
        "Rates that would rise. If right, its path holds. Exhibit 3: It rose. We saw it."
    )
    tokens = [c.token for c in find_candidates(Doc.build(source))]
    assert tokens == ["it", "These", "that", "that", "If right", "its", "it"]


class FakeBackend:
    """References replies are full answers ({referents, decisions, extra}); ellipsis replies are item lists."""

    def __init__(self, references, ellipsis=((),)):
        self.replies = {"references": list(references), "ellipsis": list(ellipsis)}
        self.usage = []
        self.prompts = []

    def generate(self, system_prompt, user_prompt, json_schema):
        stage = "ellipsis" if "left words out" in system_prompt else "references"
        self.prompts.append(user_prompt)
        reply = self.replies[stage].pop(0)
        return json.dumps(reply if stage == "references" else {"items": list(reply)})


RENDER_SOURCE = "Warsh said he may hike rates. His view held. This matters. If wrong, it fails. This tradeoff bites."
REFERENTS = [
    {"id": "R1", "type": "thing", "sid": "E001", "quote": "Warsh"},
    {"id": "R2", "type": "claim", "sid": "E001", "quote": "he may hike rates"},
]


def link(cid, rid, **kw):
    return {"candidate": cid, "action": "link", "referent": rid, **kw}


def test_rendering_is_written_from_the_referent():
    decisions = [
        link("C001", "R1"), link("C002", "R1"), link("C003", "R2"), link("C004", "R2"), link("C005", "R2"),
        link("C006", "R2", phrase="This tradeoff", connective="that"),
    ]  # fmt: skip
    answer = {"referents": REFERENTS, "decisions": decisions}
    doc = Doc.build(RENDER_SOURCE)
    result = run_references(doc, FakeBackend([answer]), STAGE_PROMPTS["references"])
    assert result.rejected == [[]]
    assert annotate(RENDER_SOURCE, result.edits).resolved() == (
        "Warsh said Warsh may hike rates. Warsh's view held. That Warsh may hike rates matters. "
        "If the author is wrong that Warsh may hike rates, that Warsh may hike rates fails. "
        "The tradeoff that Warsh may hike rates bites."
    )
    assert [e.kind for e in result.edits] == ["pronoun", "possessive", "proposition", "verdict", "proposition", "shell"]


def test_referents_and_decisions_are_checked():
    doc = Doc.build(RENDER_SOURCE)
    candidates = {c.id: c for c in find_candidates(doc)}
    refs = {r["id"]: check_referent(doc, r) for r in REFERENTS}
    assert "full clause" in check_referent(doc, {"id": "R3", "type": "claim", "sid": "E001", "quote": "hike rates"})
    bad_name = {"id": "R4", "type": "thing", "sid": "E001", "quote": "Warsh", "name": "Chair Warsh"}
    assert "not in the quote" in check_referent(doc, bad_name)
    assert "possessive" in check_decision(doc, link("C002", "R2"), candidates, refs)
    assert "claim" in check_decision(doc, link("C004", "R1"), candidates, refs)
    assert "must start" in check_decision(doc, link("C006", "R2", phrase="tradeoff bites"), candidates, refs)
    assert "two or more" in check_decision(doc, {"candidate": "C003", "action": "ambiguous", "referents": ["R1"]},
                                           candidates, refs)  # fmt: skip
    assert "reason" in check_decision(
        doc, {"candidate": "C003", "action": "leave", "reason": "unsure"}, candidates, refs
    )


SOURCE = (
    "The question is whether the Fed will incorporate the changes into its projections. We think it will. "
    "Gov. Waller might dissent, depending on his estimate. Transparency helps. Even without guidance. Will it last?"
)


def test_ellipsis_blocks_modal_leaks_and_places_fragments():
    doc = Doc.build(SOURCE)
    leak = {"sid": "E002", "kind": "vp", "remnant": "We think it will", "insert": "might dissent",
            "antecedent": {"sid": "E003", "quote": "Gov. Waller might dissent"}}  # fmt: skip
    assert "modal" in check_ellipsis(doc, leak)
    fragment = check_ellipsis(doc, {"sid": "E005", "kind": "fragment", "remnant": "Even without guidance.",
                                    "insert": "Transparency helps",
                                    "antecedent": {"sid": "E004", "quote": "Transparency helps"}})  # fmt: skip
    assert not isinstance(fragment, str)
    assert SOURCE[: fragment.at].endswith("Even without guidance")


def test_resolve_repairs_undecided_candidates_and_copies_strictly():
    referents = [
        {"id": "R1", "type": "thing", "sid": "E001", "quote": "the Fed"},
        {"id": "R2", "type": "thing", "sid": "E003", "quote": "Gov. Waller", "name": "Waller"},
    ]
    first = {"referents": referents, "decisions": [link("C001", "R1"), link("C002", "R1")]}
    second = {"decisions": [link("C003", "R2")]}
    copied = "incorporate the changes into its projections"
    gaps = [
        {"sid": "E002", "kind": "vp", "remnant": "We think it will", "insert": copied,
         "antecedent": {"sid": "E001", "quote": copied}},
        {"sid": "E005", "kind": "fragment", "remnant": "Even without guidance.", "insert": "Transparency helps",
         "antecedent": {"sid": "E004", "quote": "Transparency helps"}},
    ]  # fmt: skip
    backend = FakeBackend([first, second], [gaps])
    result = resolve(SOURCE, backend, workers=1)
    assert result.text is not None
    assert result.text.original() == SOURCE
    assert result.text.resolved() == (
        "The question is whether the Fed will incorporate the changes into the Fed's projections. "
        "The author thinks the Fed will incorporate the changes into the Fed's projections. "
        "Gov. Waller might dissent, depending on Waller's estimate. Transparency helps. "
        "Even without guidance, Transparency helps. Will it last?"
    )
    assert [len(u) for u in result.references.undecided] == [1, 0]
    assert "C003 E003 his" in backend.prompts[1]
    assert "R2 thing: Waller" in backend.prompts[1]
