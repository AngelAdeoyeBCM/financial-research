"""Which documents belong in the corpus."""

from collections.abc import Iterable

from .chunks import ResearchDocument

DEFAULT_ASSET_CLASSES = ("FX", "Rates")


class AssetClassFilter:
    """Keeps documents with at least one chunk tagged with one of ``classes``."""

    def __init__(self, classes: Iterable[str] = DEFAULT_ASSET_CLASSES) -> None:
        self.classes = frozenset(classes)

    def matches(self, doc: ResearchDocument) -> bool:
        """True when any chunk's ``Asset.Class`` is in scope."""
        return any(c in self.classes for c in doc.asset_classes())

    def share(self, doc: ResearchDocument) -> float:
        """Share of the document's asset tags that are in scope."""
        tags = doc.asset_classes()
        return sum(c in self.classes for c in tags) / len(tags) if tags else 0.0
