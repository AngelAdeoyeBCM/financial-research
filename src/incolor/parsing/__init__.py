from .email import EmailParser, InlineFigure, ParsedEmail

__all__ = ['EmailParser', 'ParsedEmail', 'InlineFigure']

# TODO. The parser does not handle duplicates well.
# Consider methods of HTML extraction that are less heuristic and more robust.
# Investigate the use of libraries like BeautifulSoup or lxml for more reliable HTML parsing.
# Additionally, consider small fine-tuned models that can assist in accurate pre-processing of HTML content.
# It's important that the knowledge graph isn't polluted with duplicate or incorrect entries.
# Ensure that any improvements to parsing and duplicate handling are thoroughly tested.

# Consider implementing a mechanism to detect and merge duplicate entries.
