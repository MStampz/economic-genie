from decimal import Decimal

from app.ingestion.connectors.base import ParseError
from app.ingestion.connectors.nab_csv import NabCsvConnector
from tests.conftest import FIXTURES, new_group, register, upload


def _setup(client):
    register(client)
    return new_group(client)


def _all(client, gid, **params):
    return client.get(f"/api/groups/{gid}/transactions", params={"limit": 500, **params}).json()


def test_parse_nab_csv():
    rows = NabCsvConnector().parse((FIXTURES / "nab_cards.csv").read_bytes())
    assert len(rows) == 8
    assert rows[0].is_pending and not rows[1].is_pending
    assert rows[1].amount == Decimal("-62.10")
    assert rows[1].merchant == "Woolworths"


def test_parse_rejects_other_files():
    try:
        NabCsvConnector().parse(b"foo,bar\n1,2\n")
    except ParseError as e:
        assert "NAB" in str(e)
    else:
        raise AssertionError("expected ParseError")


def test_import_and_duplicates(client):
    gid = _setup(client)
    r = upload(client, gid, "nab_cards.csv")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["rows_new"] == 8 and body["rows_duplicate"] == 0
    assert sorted(body["accounts_created"]) == ["NAB Card ending 1111", "NAB Card ending 2222"]
    kinds = {a["kind"] for a in client.get(f"/api/groups/{gid}/accounts").json()}
    assert kinds == {"credit_card"}

    # Importing the same file again adds nothing, but the pending row is replaced, not duplicated.
    body = upload(client, gid, "nab_cards.csv").json()
    assert body["rows_new"] == 1 and body["rows_duplicate"] == 7 and body["rows_pending_replaced"] == 1
    page = _all(client, gid)
    assert page["total"] == 8
    # The two identical coffees on the same day are both kept.
    coffees = [t for t in page["items"] if t["merchant"] == "Corner Cafe" and not t["is_pending"]]
    assert len(coffees) == 2


def test_bank_categories_and_card_payment(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    cats = {c["id"]: c["name"] for c in client.get(f"/api/groups/{gid}/categories").json()}
    items = _all(client, gid)["items"]
    by_desc = {t["description"]: t for t in items}
    assert cats[by_desc["WOOLWORTHS 1234 BRIGHTON AUS"]["category_id"]] == "Groceries"
    payment = by_desc["PAYMENT RECEIVED THANK YOU"]
    assert payment["is_internal_transfer"] and cats[payment["category_id"]] == "Internal transfers"
    spending = _all(client, gid, include_transfers=False)
    assert spending["total"] == 7


def test_transfers_pair_across_accounts(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    body = upload(client, gid, "nab_everyday.csv").json()
    assert body["transfers_paired"] == 1
    items = {t["description"]: t for t in _all(client, gid)["items"]}
    assert items["ONLINE PAYMENT TO CARD 1111"]["is_internal_transfer"]
    # Rent leaves the group, so it is spending; a refund matching a card refund is not paired.
    assert not items["ONLINE RENT NOVEMBER"]["is_internal_transfer"]
    assert not items["REFUND FROM FRIEND"]["is_internal_transfer"]
    assert not items["KMART CHELTENHAM AUS"]["is_internal_transfer"]
    accounts = {a["external_ref"]: a["kind"] for a in client.get(f"/api/groups/{gid}/accounts").json()}
    assert accounts["08-123-4567"] == "transaction"


def test_bad_file_gives_friendly_error(client):
    gid = _setup(client)
    r = client.post(f"/api/groups/{gid}/imports", files={"file": ("x.csv", b"hello,world\n1,2\n", "text/csv")})
    assert r.status_code == 422
    assert "NAB" in r.json()["detail"]


def test_rules_and_manual_category(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    cats = {c["name"]: c["id"] for c in client.get(f"/api/groups/{gid}/categories").json()}
    crosser = client.post(f"/api/groups/{gid}/categories", json={"name": "Crosser"}).json()
    assert client.post(f"/api/groups/{gid}/categories", json={"name": "crosser"}).status_code == 409

    r = client.post(f"/api/groups/{gid}/rules", json={"pattern": "mx store", "category_id": crosser["id"]})
    assert r.status_code == 201
    bad = client.post(
        f"/api/groups/{gid}/rules", json={"pattern": "([", "is_regex": True, "category_id": crosser["id"]}
    )
    assert bad.status_code == 422

    # Hand-pick a category for the Amazon purchase; rules must never override it.
    amazon = next(t for t in _all(client, gid)["items"] if t["merchant"] == "Amazon")
    client.patch(f"/api/groups/{gid}/transactions/{amazon['id']}", json={"category_id": crosser["id"]})
    client.post(f"/api/groups/{gid}/rules", json={"pattern": "amazon", "category_id": cats["Clothing & accessories"]})

    assert client.post(f"/api/groups/{gid}/rules/apply").json()["updated"] == 1
    items = {t["merchant"]: t for t in _all(client, gid)["items"]}
    assert items["MX Store"]["category_id"] == crosser["id"] and items["MX Store"]["category_source"] == "rule"
    assert items["Amazon"]["category_id"] == crosser["id"] and items["Amazon"]["category_source"] == "user"

    # Clearing the manual choice hands it back to the rules.
    t = client.patch(f"/api/groups/{gid}/transactions/{amazon['id']}", json={"category_id": None}).json()
    assert t["category_id"] == cats["Clothing & accessories"] and t["category_source"] == "rule"


def test_rule_import_creates_categories(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    rules = {"rules": [{"pattern": "MX STORE", "category": "Crosser"}, {"pattern": "mx store", "category": "Crosser"}]}
    assert client.post(f"/api/groups/{gid}/rules/import", json=rules).json()["updated"] == 1
    assert any(c["name"] == "Crosser" for c in client.get(f"/api/groups/{gid}/categories").json())
    assert client.post(f"/api/groups/{gid}/rules/apply").json()["updated"] == 1


def test_activity_log_has_no_secrets(client):
    gid = _setup(client)
    code = client.post(f"/api/groups/{gid}/invites").json()["code"]
    upload(client, gid, "nab_cards.csv")
    events = client.get(f"/api/groups/{gid}/activity").json()
    actions = {e["action"] for e in events}
    assert {"group.created", "invite.created", "import.completed"} <= actions
    assert code not in str(events)
