"""Where a stripped span sat in a document; recorded as ``section`` in the extract manifest."""

from enum import StrEnum


class Section(StrEnum):
    """Email-style regions removed from the body text."""

    HEADER = "header"
    FOOTER = "footer"
    DISCLAIMER = "disclaimer"
    SIGNATURE = "signature"
    PROMOTION = "promotion"
    ARTEFACT = "artefact"
