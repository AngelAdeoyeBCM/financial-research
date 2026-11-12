"""Parse four real emails (two image-heavy, two text-only) and save the cleaned results.

Checks that headers, footers and disclaimers are removed, that author signatures are kept,
and that chart images (but not logos/photos) are flagged through ``has_image_content``.

Run from the project root:
    python -m unittest discover -s tests -p test_email_parser_samples.py -v

The report is regenerated at tests/email_parser_samples_output.txt (plus an .html preview).
"""

import json
import unittest
from html import escape
from pathlib import Path
from types import SimpleNamespace

from incolor.parsing import EmailParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = PROJECT_ROOT / 'research_emails_20260930_14d' / 'candidates.jsonl'
OUTPUT = Path(__file__).with_name('email_parser_samples_output.txt')

# Subject prefix + received time identify exactly one email in candidates.jsonl.
SAMPLES = [
    {
        'label': 'image-heavy: Deutsche Bank chart-pack (9 inline PNG attachments)',
        'subject': 'CEEMEA & LatAm Local Markets Chart-Pack:',
        'received': '2026-09-24T16:02:19',
        'min_figures': 9,
        'phrases': ['We have enhanced our frontier market bond models', 'Kazakhstan local bond table'],
        'signature': ['Christian Wietoska', 'Ankit Jain'],
        'absent': ['Privacy of communications', 'research.db.com'],
    },
    {
        'label': 'image-heavy: J.P. Morgan Oil Markets Weekly (cid images, UUID attachment names)',
        'subject': 'Oil Markets Weekly: Dry powder',
        'received': '2026-09-17T12:03:59',
        'min_figures': 10,
        'phrases': ['Dry powder', 'Table 32: Global refinery runs 2027F'],
        'signature': ['Natasha Kaneva', 'Lyuba Savinova', 'Artem Fakhretdinov'],
        'absent': ['By Natasha Kaneva'],
    },
    {
        'label': 'text-only: UBS Brazil elections note',
        'subject': 'UBS: Brazil 2026 Elections: What to watch in the first round',
        'received': '2026-09-28T10:47:11',
        'min_figures': 0,
        'phrases': ['Brazil elects a new president'],
        'signature': ['Roque Montero, Strategist', 'Rodrigo Martins, Economist'],
        'absent': [],
    },
    {
        'label': 'text-only: Morgan Stanley D1 Sales note',
        'subject': 'MS D1 Sales: Clients are weary',
        'received': '2026-09-28T08:54:46',
        'min_figures': 0,
        'phrases': ['Please let us know how we can help.'],
        'signature': ['Kind regards,', 'Ruth Borland, Executive Director'],
        'absent': ['Not a product of MS Research', '+44', '@morganstanley.com'],
    },
]

BOILERPLATE = [
    'This message originated from an external source',
    'REPLY TO address does not match',
    'Unsubscribe',
    'Manage your',
    'Copyright',
    '©',
    'Disclaimer',
    'Disclosures',
    'Analyst Certification',
    'http://',
    'https://',
]


def load_candidates():
    emails, attachments = [], {}
    with CANDIDATES.open(encoding='utf-8-sig') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get('kind') == 'attachment':
                attachments.setdefault(record['message_id'], []).append(record)
            elif record.get('kind') == 'email' and str(record.get('html_body') or '').strip():
                emails.append((line_number, record))
    return emails, attachments


class EmailParserSampleTests(unittest.TestCase):
    def test_four_samples(self):
        emails, attachments = load_candidates()
        parser = EmailParser(attachment_root=CANDIDATES.parent)

        report = [
            'EMAIL PARSER SAMPLE RESULTS',
            f'Input: {CANDIDATES}',
            'Samples: 2 image-heavy, 2 text-only. Headers, footers and disclaimers removed; '
            'author signatures kept; only chart/exhibit images counted.',
            'Each input is parsed independently; all output text is untruncated.',
        ]
        preview = ['<html><meta charset="utf-8"><title>Email parser samples</title><body>']
        results = []

        for number, sample in enumerate(SAMPLES, 1):
            matches = [
                (line_number, record)
                for line_number, record in emails
                if record['subject'].startswith(sample['subject']) and record['received'] == sample['received']
            ]
            self.assertEqual(len(matches), 1, f'sample {number} must match exactly one email')
            line_number, record = matches[0]
            message = SimpleNamespace(
                HTMLBody=record['html_body'],
                Subject=record['subject'],
                SenderEmailAddress=record['sender'],
                ReceivedTime=record['received'],
            )
            linked = attachments.get(record['message_id'], [])
            parsed = parser.parse(message, attachments=linked)
            results.append((number, sample, record, parsed))

            report.extend(
                [
                    '',
                    '=' * 80,
                    f'RESULT {number} / {len(SAMPLES)} - {sample["label"]}',
                    '=' * 80,
                    f'JSONL line: {line_number}',
                    f'Message ID: {record.get("message_id", record.get("id", ""))}',
                    f'has_image_content: {parsed.has_image_content}',
                    f'Content figures kept: {len(parsed.figures)}   Attachments on message: {len(linked)}',
                    f'Body chars: {len(parsed.body)}   Signature lines: {len(parsed.signature.splitlines())}',
                    '',
                    'FIGURES',
                    '-' * 80,
                ]
            )
            report.extend(
                f'{f.marker}  [{f.reason}]  {f.attachment_path or f.source[:60]}  w={f.width} h={f.height}'
                for f in parsed.figures
            )
            report.extend(['(none)'] if not parsed.figures else [])
            report.extend(
                [
                    '',
                    'SIGNATURE',
                    '-' * 80,
                    parsed.signature or '(none)',
                    '',
                    'PARSED EMAIL',
                    '-' * 80,
                    parsed.as_text,
                    '',
                ]
            )

            preview.append(f'<h1>Sample {number}</h1><h2>{escape(record["subject"])}</h2>')
            rendered = escape(parsed.as_text)
            for figure in parsed.figures:
                if figure.attachment_path:
                    image_path = '../research_emails_20260930_14d/' + figure.attachment_path
                    rendered = rendered.replace(
                        escape(figure.marker),
                        escape(figure.marker)
                        + f'<br><img style="max-width:100%" src="{escape(image_path, quote=True)}"><br>',
                    )
            preview.append(f'<div style="white-space:pre-wrap">{rendered}</div>')

        # Save everything before asserting so failed checks can be inspected.
        OUTPUT.write_text('\n'.join(report) + '\n', encoding='utf-8')
        OUTPUT.with_suffix('.html').write_text('\n'.join(preview) + '</body></html>', encoding='utf-8')

        for number, sample, record, parsed in results:
            with self.subTest(sample=number, label=sample['label']):
                self.assertTrue(parsed.body.strip())
                for text in BOILERPLATE:
                    self.assertNotIn(text, parsed.as_text)
                for phrase in sample['phrases']:
                    self.assertIn(phrase, parsed.body)
                for name in sample['signature']:
                    self.assertIn(name, parsed.signature)
                    self.assertNotIn(name, parsed.body)
                for text in sample['absent']:
                    self.assertNotIn(text, parsed.body + '\n' + parsed.signature)

                markers = [f.marker for f in parsed.figures]
                self.assertEqual(markers, [f'[Inline figure {i}]' for i in range(1, len(markers) + 1)])
                for marker in markers:
                    self.assertEqual(parsed.body.count(marker), 1)
                self.assertEqual(parsed.body.count('[Inline figure '), len(markers))
                if sample['min_figures']:
                    self.assertTrue(parsed.has_image_content)
                    self.assertGreaterEqual(len(markers), sample['min_figures'])
                    for figure in parsed.figures:
                        self.assertTrue(figure.is_content)
                        if figure.attachment_path:
                            self.assertTrue((CANDIDATES.parent / figure.attachment_path).is_file())
                else:
                    self.assertFalse(parsed.has_image_content)
                    self.assertEqual(markers, [])
                    self.assertTrue(parsed.signature.strip(), 'author signature should be preserved')

        chart_pack = results[0][3]
        self.assertEqual(len(chart_pack.figures), 9)
        self.assertTrue(all(f.attachment_path for f in chart_pack.figures))
        self.assertEqual(OUTPUT.read_text(encoding='utf-8').count('RESULT '), len(SAMPLES))


if __name__ == '__main__':
    unittest.main()
