import argparse
import html
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import yaml

DEFAULT_THEME_PATH = Path(__file__).resolve().parents[3] / "config" / "theme" / "argument_map.json"
FACTUAL_TYPES = frozenset({"DATA_POINT", "OBSERVATION"})
SCENARIO_SLOTS = ("assumptions", "implications", "recommendations")
# Keys used by maps written before v0.12.
_LEGACY_KEYS = {"conclusion": "core_claim", "implications": "outcomes"}
View = Literal["argument", "list"]


def load_theme(path: str | Path = DEFAULT_THEME_PATH) -> dict[str, Any]:
    """Load the argument-map theme (colours, role and modality labels) shared with the front end."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get(item: dict[str, Any], key: str) -> Any:
    """Read ``key`` from a map item, falling back to its pre-v0.12 name."""
    if key in item:
        return item[key]
    return item.get(_LEGACY_KEYS.get(key, key))


class ArgumentMapDiagram:
    """Render a Phase 1 argument-map YAML as a Mermaid flowchart.

    Each argument is one node: a header, the conclusion box, then one rounded box per component. Components that are
    the conclusion of another argument, or another argument's ID, are shown as a reference to that argument, and an
    edge is drawn between them.
    Each scenario is a node in the same design (its assumptions, implications and recommendations); an argument role
    that references a scenario is shown as a reference box, and an edge is drawn from the scenario to the argument.
    Statements may carry an optional ``brief`` field used as the display text; otherwise the full statement is shown.
    Each box ends with a marker: the subkind abbreviations (v0.10), else the proposition-kind abbreviation (v0.9,
    plus the scenario if the statement is in one), else the modality abbreviation.
    OBSERVATION components are hidden unless ``show_observations`` is set.
    ``view="argument"`` draws the edges between arguments; ``view="list"`` stacks the arguments vertically in order
    without connections.
    Colours and labels come from ``config/theme/argument_map.json``. A box is coloured by its claim type unless a
    ``subkind_styles`` rule matches its subkinds (first match wins), e.g. a valuation claim takes the VALUATION colour.
    """

    def __init__(
        self,
        argument_map: dict[str, Any],
        node_width: int = 330,
        theme: dict[str, Any] | None = None,
        show_observations: bool = False,
        view: View = "argument",
    ) -> None:
        if view not in ("argument", "list"):
            raise ValueError(f"Unknown view: {view!r}")
        self.node_width = node_width
        self.theme = theme or load_theme()
        self.show_observations = show_observations
        self.view = view
        self.statements: dict[str, dict[str, Any]] = {s["id"]: s for s in argument_map["statements"]}
        self.arguments: list[dict[str, Any]] = argument_map["arguments"]
        self.scenarios: list[dict[str, Any]] = argument_map.get("scenarios") or []
        self.scenario_by_id: dict[str, dict[str, Any]] = {s["id"]: s for s in self.scenarios}
        self.core_of: dict[str, dict[str, Any]] = {_get(a, "conclusion"): a for a in self.arguments}
        self.argument_by_id: dict[str, dict[str, Any]] = {a["id"]: a for a in self.arguments}
        self.scenario_of: dict[str, str] = {
            sid: f"SC{int(scenario['id'][2:])}"
            for scenario in self.scenarios
            for field in SCENARIO_SLOTS
            for sid in _get(scenario, field) or []
        }

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        node_width: int = 330,
        theme: dict[str, Any] | None = None,
        show_observations: bool = False,
        view: View = "argument",
    ) -> "ArgumentMapDiagram":
        """Load an argument map from a YAML file."""
        with open(path, encoding="utf-8") as f:
            return cls(
                yaml.safe_load(f),
                node_width=node_width,
                theme=theme,
                show_observations=show_observations,
                view=view,
            )

    def to_mermaid(self) -> str:
        """Return the Mermaid source for the diagram in the configured view."""
        is_list = self.view == "list"
        lines = [self._init_directive(), "flowchart TB" if is_list else "flowchart LR"]
        lines += [f"    {line}" for line in self._nodes()]
        lines.append("")
        lines += [f"    {line}" for line in (self._stack() if is_list else self._edges())]
        lines.append("")
        lines += [f"    {line}" for line in self._class_lines(self._node_types(), self._scenario_ids())]
        if not is_list:
            # An inline linkStyle would make the invisible stacking links visible, so only apply it to real edges.
            edge = self.theme["edge"]
            lines.append(f"    linkStyle default stroke:{edge['stroke']},stroke-width:2px,color:{edge['label']}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Return the diagram wrapped in a Markdown ``mermaid`` code fence."""
        return f"```mermaid\n{self.to_mermaid()}\n```\n"

    def save(self, path: str | Path) -> Path:
        """Write the raw Mermaid source to ``path`` with a ``.mmd`` suffix and return the written path."""
        path = Path(path).with_suffix(".mmd")
        path.write_text(self.to_mermaid(), encoding="utf-8")
        return path

    def _nodes(self, prefix: str = "") -> list[str]:
        nodes = [f'{prefix}{a["id"]}["{self._argument_label(a)}"]' for a in self.arguments]
        return nodes + [f'{prefix}{s["id"]}["{self._scenario_label(s)}"]' for s in self.scenarios]

    def _stack(self, prefix: str = "") -> list[str]:
        # Invisible links keep the nodes in order top to bottom without drawing a connection.
        ids = [a["id"] for a in self.arguments] + [s["id"] for s in self.scenarios]
        if len(ids) < 2:
            return []
        return [" ~~~ ".join(f"{prefix}{node}" for node in ids)]

    def _node_types(self, prefix: str = "") -> list[tuple[str, str]]:
        return [(f"{prefix}{a['id']}", self._style(self.statements[_get(a, 'conclusion')])) for a in self.arguments]

    def _scenario_ids(self, prefix: str = "") -> list[str]:
        return [f"{prefix}{s['id']}" for s in self.scenarios]

    def _class_lines(self, node_types: list[tuple[str, str]], scenario_ids: Sequence[str] = ()) -> list[str]:
        text = self.theme["text"]
        used = sorted({style for _, style in node_types}, key=self._type_key)
        lines = []
        for style in used:
            t = self.theme["claim_types"][style]
            lines.append(
                f"classDef {t['key']} fill:{t['container_fill']},stroke:{t['stroke']},stroke-width:2px,color:{text}"
            )
        scenario = self.theme.get("scenario")
        if scenario_ids and scenario:
            lines.append(
                f"classDef {scenario['key']} fill:{scenario['container_fill']},stroke:{scenario['stroke']},"
                f"stroke-width:2px,color:{text}"
            )
        for style in used:
            ids = ",".join(node for node, node_style in node_types if node_style == style)
            lines.append(f"class {ids} {self._type_key(style)}")
        if scenario_ids and scenario:
            lines.append(f"class {','.join(scenario_ids)} {scenario['key']}")
        return lines

    def _init_directive(self) -> str:
        text, edge = self.theme["text"], self.theme["edge"]
        types = self.theme["claim_types"]
        type_css = " ".join(f".{t['key']}{{background:{t['fill']};border-color:{t['stroke']}}}" for t in types.values())
        if "scenario" in self.theme:
            s = self.theme["scenario"]
            type_css += f" .{s['key']}{{background:{s['fill']};border-color:{s['stroke']}}}"
        css = (
            f".arg{{width:{self.node_width}px;text-align:left;color:{text}}} "
            ".core,.c{display:flex;justify-content:space-between;align-items:flex-end;gap:8px;margin-top:4px;"
            f"padding:3px 6px;color:{text}}} "
            ".core{border:2px solid} .c{border:1.5px solid;border-radius:10px} "
            f"{type_css} "
            f"mark{{background:{types['OBSERVATION']['fill']};color:{text};padding:0 2px}} "
            f".edgeLabel,.edgeLabel *{{color:{edge['label']} !important;fill:{edge['label']} !important}}"
        )
        return (
            '%%{init: {"flowchart": {"htmlLabels": true, "nodeSpacing": 20, "rankSpacing": 60}, '
            f'"themeCSS": "{css}"}}}}%%'
        )

    def _argument_label(self, argument: dict[str, Any]) -> str:
        core = self.statements[_get(argument, "conclusion")]
        kind = self._kind_abbrev(core)
        header = f"{argument['id']} · {core['claim_type']}" + (f" · {kind}" if kind else "")
        parts = [
            f"<div class='arg'><b>{header}</b>",
            self._box("core", core, self._text(core)),
        ]
        for role, spec in self.theme["roles"].items():
            for sid in argument.get(role, []):
                if sid in self.scenario_by_id:
                    parts.append(self._scenario_ref_box(spec["abbrev"], self.scenario_by_id[sid]))
                    continue
                if sid in self.argument_by_id:
                    parts.append(self._argument_ref_box(spec["abbrev"], self.argument_by_id[sid]))
                    continue
                statement = self.statements[sid]
                if statement["claim_type"] == "OBSERVATION" and not self.show_observations:
                    continue
                parts.append(self._box("c", statement, f"<b>{spec['abbrev']}:</b> {self._component_text(statement)}"))
        parts.append("</div>")
        return "".join(parts)

    def _scenario_label(self, scenario: dict[str, Any]) -> str:
        label = html.escape(scenario["label"], quote=False).replace('"', "#quot;")
        parts = [f"<div class='arg'><b>{scenario['id']} · Scenario · {label}</b>"]
        slots = self.theme.get("scenario_slots", {})
        for slot in SCENARIO_SLOTS:
            abbrev = slots.get(slot, {}).get("abbrev", slot)
            for sid in _get(scenario, slot) or []:
                statement = self.statements[sid]
                text = f"<b>{abbrev}:</b> {self._component_text(statement)}"
                parts.append(self._box("c", statement, text, in_scenario=True))
        parts.append("</div>")
        return "".join(parts)

    def _scenario_ref_box(self, abbrev: str, scenario: dict[str, Any]) -> str:
        key = self.theme.get("scenario", {}).get("key", "scn")
        label = html.escape(scenario["label"], quote=False).replace('"', "#quot;")
        return f"<div class='c {key}'><span><b>{abbrev}:</b> <b>{scenario['id']} - {label}</b></span></div>"

    def _argument_ref_box(self, abbrev: str, argument: dict[str, Any]) -> str:
        conclusion = self.statements[_get(argument, "conclusion")]
        key = self._type_key(self._style(conclusion))
        return (
            f"<div class='c {key}'><span><b>{abbrev}:</b> <b>{argument['id']} - {conclusion['claim_type']}</b></span>"
            "</div>"
        )

    def _component_text(self, statement: dict[str, Any]) -> str:
        linked = self.core_of.get(statement["id"])
        if linked is not None:
            return f"<b>{linked['id']} - {statement['claim_type']}</b>"
        if statement["claim_type"] in FACTUAL_TYPES:
            return f"<mark>{self._text(statement)}</mark>"
        return self._text(statement)

    def _box(self, kind: str, statement: dict[str, Any], content: str, in_scenario: bool = False) -> str:
        return (
            f"<div class='{kind} {self._type_key(self._style(statement))}'>"
            f"<span>{content}</span><b>[{self._marker(statement, in_scenario)}]</b></div>"
        )

    def _kind_abbrev(self, statement: dict[str, Any]) -> str | None:
        subkinds = statement.get("subkinds")
        if subkinds:
            abbrevs = self.theme.get("subkinds", {})
            return "+".join(abbrevs.get(value, {}).get("abbrev", value) for value in subkinds)
        kind = statement.get("proposition_kind")
        if not kind:
            return None
        return self.theme.get("proposition_kinds", {}).get(kind, {}).get("abbrev", kind)

    def _marker(self, statement: dict[str, Any], in_scenario: bool = False) -> str:
        kind = self._kind_abbrev(statement)
        if kind is None:
            return self.theme["modalities"][statement["modality"]]["abbrev"]
        scenario = None if in_scenario else self.scenario_of.get(statement["id"])
        return f"{kind}·{scenario}" if scenario else kind

    def _edges(self) -> list[str]:
        edges = []
        for argument in self.arguments:
            for role, spec in self.theme["roles"].items():
                if not spec["edge_label"]:
                    continue
                for sid in argument.get(role, []):
                    source = self.scenario_by_id.get(sid) or self.argument_by_id.get(sid) or self.core_of.get(sid)
                    if source is None:
                        continue
                    label = spec["edge_label"]
                    arrow = f"-. {label} .->" if spec["edge_style"] == "dashed" else f"-- {label} -->"
                    edges.append(f"{source['id']} {arrow} {argument['id']}")
        return edges

    def _style(self, statement: dict[str, Any]) -> str:
        """Return the ``claim_types`` theme entry that colours the statement."""
        claim_type = statement["claim_type"]
        subkinds = set(statement.get("subkinds") or ())
        for rule in self.theme.get("subkind_styles", []):
            if rule["subkind"] in subkinds and rule.get("claim_type", claim_type) == claim_type:
                return rule["style"]
        return claim_type

    def _type_key(self, claim_type: str) -> str:
        return self.theme["claim_types"][claim_type]["key"]

    def _text(self, statement: dict[str, Any]) -> str:
        # Double quotes would terminate the Mermaid label string.
        return html.escape(statement.get("brief") or statement["statement"], quote=False).replace('"', "#quot;")


def side_by_side_mermaid(diagrams: Sequence[ArgumentMapDiagram], titles: Sequence[str] | None = None) -> str:
    """Return Mermaid source showing several argument maps side by side, each in list view.

    Each map is a column (subgraph) titled from ``titles``; theme and node width are taken from the first diagram.
    """
    if not diagrams:
        raise ValueError("At least one diagram is required.")
    if titles is None:
        titles = [f"Map {i + 1}" for i in range(len(diagrams))]
    if len(titles) != len(diagrams):
        raise ValueError("titles must have the same length as diagrams.")
    first = diagrams[0]
    lines = [first._init_directive(), "flowchart TB"]
    node_types: list[tuple[str, str]] = []
    scenario_ids: list[str] = []
    for i, (diagram, title) in enumerate(zip(diagrams, titles)):
        prefix = f"m{i}_"
        safe_title = html.escape(title, quote=False).replace('"', "#quot;")
        lines.append(f'    subgraph m{i}["{safe_title}"]')
        lines.append("        direction TB")
        lines += [f"        {line}" for line in diagram._nodes(prefix)]
        lines += [f"        {line}" for line in diagram._stack(prefix)]
        lines.append("    end")
        node_types += diagram._node_types(prefix)
        scenario_ids += diagram._scenario_ids(prefix)
    lines.append("")
    lines += [f"    {line}" for line in first._class_lines(node_types, scenario_ids)]
    return "\n".join(lines)


def main() -> None:
    """Render one or more argument-map YAMLs to Mermaid from the command line."""
    parser = argparse.ArgumentParser(description="Render argument-map YAMLs as a Mermaid diagram.")
    parser.add_argument("yaml_paths", type=Path, nargs="+", help="Several paths are shown side by side in list view.")
    parser.add_argument("-o", "--output", type=Path, help="Output file; written as .mmd.")
    parser.add_argument("--width", type=int, default=330, help="Node width in pixels.")
    parser.add_argument("--theme", type=Path, default=DEFAULT_THEME_PATH, help="Theme JSON path.")
    parser.add_argument("--show-observations", action="store_true", help="Show OBSERVATION components.")
    parser.add_argument("--view", choices=["argument", "list"], default="argument", help="Single-map view.")
    args = parser.parse_args()
    theme = load_theme(args.theme)
    diagrams = [
        ArgumentMapDiagram.from_yaml(
            path,
            node_width=args.width,
            theme=theme,
            show_observations=args.show_observations,
            view=args.view if len(args.yaml_paths) == 1 else "list",
        )
        for path in args.yaml_paths
    ]
    if len(diagrams) == 1:
        source = diagrams[0].to_mermaid()
    else:
        source = side_by_side_mermaid(diagrams, [path.stem for path in args.yaml_paths])
    if args.output:
        args.output.with_suffix(".mmd").write_text(source, encoding="utf-8")
    else:
        print(f"```mermaid\n{source}\n```\n")


if __name__ == "__main__":
    main()
