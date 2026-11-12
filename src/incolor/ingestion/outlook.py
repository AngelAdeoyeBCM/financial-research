from __future__ import annotations

from datetime import UTC

from ..classes import EmailMetadata
from .adapters import read_metadata


class OutlookClient:
    """Read email metadata from Outlook."""

    INTERNET_MESSAGE_ID_TAG = 'http://schemas.microsoft.com/mapi/proptag/0x1035001E'

    def __init__(self):
        import win32com.client as win32

        outlook = win32.Dispatch('Outlook.Application')
        self.namespace = outlook.GetNamespace('MAPI')

    def get_inbox(self):
        """Return the default Outlook Inbox."""
        return self.namespace.GetDefaultFolder(6)

    def get_folder(self, path: str | None = None, *, mailbox: str | None = None):
        """Resolve a folder without recursively scanning unrelated folders.

        Without mailbox, paths are relative to the default Inbox; an initial
        Inbox component is optional. With mailbox, paths start at that mailbox's
        root, for example Inbox/Research. Its default path is Inbox.
        """
        if mailbox is not None:
            folder = self.namespace.Folders.Item(mailbox)
            components = (path or 'Inbox').replace('\\\\', '/').split('/')
        else:
            folder = self.get_inbox()
            components = (path or '').replace('\\\\', '/').split('/')
            if components and components[0].casefold() == 'inbox':
                components = components[1:]
        for name in components:
            if name:
                folder = folder.Folders.Item(name)
        return folder

    def iter_messages(self, folder=None, *, since=None, until=None):
        """Yield MailItems newest first within [since, until).

        No watermark is persisted: a full scan also finds older mail moved
        into the folder. Naive cutoffs are interpreted in the local timezone.
        """
        from .adapters import is_email

        lower = since.astimezone(UTC) if since is not None else None
        upper = until.astimezone(UTC) if until is not None else None
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError('since must be earlier than until')
        folder = self.get_inbox() if folder is None else folder
        items = folder.Items
        items.Sort('[ReceivedTime]', True)
        for message in items:
            if not is_email(message):
                continue
            if lower is not None or upper is not None:
                received = message.ReceivedTime.astimezone(UTC)
                if upper is not None and received >= upper:
                    continue
                if lower is not None and received < lower:
                    # Items are sorted descending, so the remaining mail is older.
                    break
            yield message

    def get_items(self, folder):
        """Return Outlook items sorted by received time."""
        items = folder.Items
        items.Sort('[ReceivedTime]', False)
        return items

    def get_internet_message_id(self, message) -> str | None:
        import pywintypes

        try:
            return message.PropertyAccessor.GetProperty(self.INTERNET_MESSAGE_ID_TAG)
        except pywintypes.com_error:
            return None

    def extract_metadata(self, message) -> EmailMetadata:
        """Convert an Outlook message into our metadata representation."""
        return read_metadata(message)
