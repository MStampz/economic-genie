import json
from decimal import Decimal

import pytest

from app.ingestion.connectors.base import ParseError
from app.ingestion.connectors.generic_csv import (
    CsvMapping,
    GenericCsvConnector,
    parse_money,
    read_table,
    suggest_mapping,
)
from tests.conftest import FIXTURES, new_group, register

CBA = {
    "has_header": False,
    "date": "Column 1",
    "amount": "Column 2",
    "description": ["Column 3"],
    "balance": "Column 4",
    "account_name": "Everyday",
    "institution": "CBA",
}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1,234.56", "1234.56"),
        ("-12.00", "-12.00"),
        ("(12.00)", "-12.00"),
        ("$12", "12.00"),
        ("-$4.80", "-4.80"),
        ("12.00 DR", "-12.00"),
        ("12.00 CR", "12.00"),
        ("AUD 5.00", "5.00"),
        ("−3.10", "-3.10"),
        ("Woolworths 12", None),
        ("", None),
    ],
)
def test_parse_money(text, expected):
    got = parse_money(text)
    assert (str(got) if got is not None else None) == expected


def test_headerless_file_is_detected_and_guessed():
    data = (FIXTURES / "cba_noheader.csv").read_bytes()
    names, body, has_header = read_table(data)
    assert not has_header and len(body) == 3
    guess = suggest_mapping(names, body, has_header)
    assert guess["date"] == "Column 1" and guess["amount"] == "Column 2" and guess["description"] == ["Column 3"]
    assert guess["date_format"] == "DD/MM/YYYY"


def test_debit_credit_columns_and_semicolons():
    data = (FIXTURES / "two_columns.csv").read_bytes()
    names, body, has_header = read_table(data)
    assert has_header and names[0] == "Posting Date"
    guess = suggest_mapping(names, body, has_header)
    assert guess["debit"] == "Debit Amount" and guess["credit"] == "Credit Amount"
    rows = GenericCsvConnector(CsvMapping(**guess, account_name="Westpac Choice")).parse(data)
    assert [r.amount for r in rows] == [Decimal("-89.95"), Decimal("12.50")]
    assert rows[0].bank_category == "Home" and rows[0].description == "BUNNINGS 123 MOORABBIN"


def test_flip_sign_for_card_exports():
    m = CsvMapping(**{**CBA, "flip_sign": True})
    rows = GenericCsvConnector(m).parse((FIXTURES / "cba_noheader.csv").read_bytes())
    assert rows[0].amount == Decimal("45.00")


def test_mapping_needs_amount_and_account():
    with pytest.raises(ValueError):
        CsvMapping(date="Date", description=["Details"], account_name="X")
    with pytest.raises(ValueError):
        CsvMapping(date="Date", amount="Amount", description=["Details"])


def test_bad_date_is_reported_with_line():
    data = b"Date,Amount,Details\n31/02/2026,1.00,x\n"
    with pytest.raises(ParseError, match="Line 2"):
        GenericCsvConnector(CsvMapping(date="Date", amount="Amount", description=["Details"], account_name="A")).parse(
            data
        )


def _post(client, gid, path, fixture, **form):
    with open(FIXTURES / fixture, "rb") as f:
        return client.post(f"/api/groups/{gid}/{path}", files={"file": (fixture, f, "text/csv")}, data=form)


def test_unknown_layout_is_learned_once(client):
    register(client)
    gid = new_group(client)

    p = _post(client, gid, "imports/preview", "cba_noheader.csv").json()
    assert p["status"] == "needs_mapping" and p["parsed"] == []
    assert _post(client, gid, "imports", "cba_noheader.csv").status_code == 422

    p = _post(client, gid, "imports/preview", "cba_noheader.csv", mapping=json.dumps(CBA)).json()
    assert p["status"] == "mapping" and p["error"] is None
    assert p["parsed"][1] == {
        "date": "2026-11-12",
        "amount": "-2400.00",
        "description": "Transfer to Landlord RENT NOV",
        "account": "Everyday",
    }

    r = _post(client, gid, "imports", "cba_noheader.csv", mapping=json.dumps(CBA), save_as="CBA everyday")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["rows_new"] == 3 and body["accounts"] == ["CBA Everyday"] and body["format"] == "CBA everyday"

    # Next time the same layout is recognised without a mapping, and nothing is imported twice.
    p = _post(client, gid, "imports/preview", "cba_noheader.csv").json()
    assert p["status"] == "saved" and p["format"] == "CBA everyday" and len(p["parsed"]) == 3
    body = _post(client, gid, "imports", "cba_noheader.csv").json()
    assert body["rows_new"] == 0 and body["rows_duplicate"] == 3

    profiles = client.get(f"/api/groups/{gid}/import-profiles").json()
    assert [x["name"] for x in profiles] == ["CBA everyday"]
    assert client.delete(f"/api/groups/{gid}/import-profiles/{profiles[0]['id']}").status_code == 204


def test_nab_is_recognised_without_mapping(client):
    register(client)
    gid = new_group(client)
    p = _post(client, gid, "imports/preview", "nab_cards.csv").json()
    assert p["status"] == "recognised" and p["format"] == "NAB Internet Banking export" and len(p["parsed"]) == 8
    body = _post(client, gid, "imports", "nab_cards.csv").json()
    assert body["format"] == "NAB Internet Banking export" and body["filename"] == "nab_cards.csv"
    assert body["accounts"] == ["NAB Card ending 1111", "NAB Card ending 2222"]


def test_invalid_mapping_message(client):
    register(client)
    gid = new_group(client)
    bad = json.dumps({"date": "Column 1", "description": ["Column 3"], "account_name": "x"})
    r = _post(client, gid, "imports/preview", "cba_noheader.csv", mapping=bad)
    assert r.status_code == 422 and "amount column" in r.json()["detail"]
