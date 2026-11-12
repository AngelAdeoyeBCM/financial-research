"""Sources: construction rules and keys."""

import datetime as dt

import pytest

from incolor.ontology import AssetClass, BbgCommentary, Document, Email, Registry, Source, SourceKind
from incolor.ontology.theme import Theme

R = Registry.load_default().get
DAY = dt.date(2026, 10, 29)


def test_source_is_abstract_and_kinds_register():
    with pytest.raises(TypeError, match='abstract'):
        Source(date=DAY)
    assert Source.for_kind(SourceKind.EMAIL) is Email
    with pytest.raises(TypeError, match='unique kind'):
        class Forgot(Document):  # inherits DOCUMENT without declaring its own
            pass


def test_document():
    theme = Theme(theme_id='theme:fed_cuts', name='Fed cuts')
    doc = Document(
        document_id='929831', date=DAY, publisher=R('org:bofa'),
        authors=(R('person:jan_hatzius'),), themes=frozenset({theme}),
        asset_classes=('rates', AssetClass.FX), coverage=(R('geo:dm'), R('geo:em')),
    )
    assert doc.key == 'SRC:DOCUMENT[929831]'
    assert doc.asset_classes == (AssetClass.RATES, AssetClass.FX)
    assert doc.coverage == (R('geo:dm'), R('geo:em'))
    with pytest.raises(TypeError, match='Organization'):
        Document(document_id='1', date=DAY, publisher=R('person:jan_hatzius'))
    with pytest.raises(ValueError, match='duplicate'):
        Document(document_id='1', date=DAY, publisher=R('org:bofa'),
                 authors=(R('person:jan_hatzius'), R('person:jan_hatzius')))
    with pytest.raises(ValueError, match='duplicate'):
        Document(document_id='1', date=DAY, publisher=R('org:bofa'), coverage=(R('geo:global'), R('geo:global')))
    with pytest.raises(TypeError, match='Geography'):
        Document(document_id='1', date=DAY, publisher=R('org:bofa'), coverage=(R('bond:ust'),))
    with pytest.raises(ValueError):
        Document(document_id='1', date=DAY, publisher=R('org:bofa'), asset_classes=('macro',))
    with pytest.raises(TypeError, match='date'):
        Document(document_id='1', date='2026-10-29', publisher=R('org:bofa'))


def test_email():
    email = Email(message_id='abc', date=dt.datetime(2026, 9, 30, 13, 53), sender='ResWeb@MorganStanley.com')
    assert email.sender == 'resweb@morganstanley.com'
    assert email.key == 'SRC:EMAIL[abc]'
    with pytest.raises(ValueError, match='address'):
        Email(message_id='abc', date=DAY, sender='Morgan Stanley')


def test_bbg_commentary_not_modelled():
    with pytest.raises(NotImplementedError):
        BbgCommentary(date=DAY)
