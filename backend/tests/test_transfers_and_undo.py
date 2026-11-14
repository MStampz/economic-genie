"""Transfer matching between the group's own accounts, marking transfers by hand, and undoing mistakes."""

import io
import json

from tests.conftest import new_group, register, upload

NAB_HEADER = (
    "Date,Amount,Account Number,,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
)


def _setup(client):
    register(client)
    return new_group(client)


def _all(client, gid, **params):
    return client.get(f"/api/groups/{gid}/transactions", params={"limit": 500, **params}).json()["items"]


def _by_desc(client, gid):
    return {t["description"]: t for t in _all(client, gid)}


def _file(client, gid, text: str, name="f.csv", **form):
    data = io.BytesIO(text.encode())
    return client.post(f"/api/groups/{gid}/imports", files={"file": (name, data, "text/csv")}, data=form)


def _spent(client, gid):
    return client.get(f"/api/groups/{gid}/overview", params={"period": "2026-11"}).json()["total"]


# ---- H3: matching needs more than an equal amount


def test_equal_amount_alone_does_not_hide_rent(client):
    gid = _setup(client)
    upload(client, gid, "nab_everyday.csv")
    # A partner tops up a second account with the same amount the day before rent goes out.
    top_up = (
        NAB_HEADER + "02 Nov 26,2400.00,08-999-0000,,TRANSFER CREDIT,FROM PARTNER SHARE OF HOLIDAY,1.00,,,02 Nov 26\n"
    )
    assert _file(client, gid, top_up).json()["transfers_paired"] == 0
    assert not _by_desc(client, gid)["ONLINE RENT NOVEMBER"]["is_internal_transfer"]


def test_description_naming_the_other_account_pairs(client):
    gid = _setup(client)
    upload(client, gid, "nab_everyday.csv")
    savings = NAB_HEADER + "03 Nov 26,2400.00,08-999-0000,,TRANSFER CREDIT,TRANSFER FROM 08-123-4567,1.00,,,03 Nov 26\n"
    assert _file(client, gid, savings).json()["transfers_paired"] == 1
    assert _by_desc(client, gid)["ONLINE RENT NOVEMBER"]["is_internal_transfer"]


def test_not_a_transfer_by_hand_splits_the_pair_and_sticks(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    upload(client, gid, "nab_everyday.csv")
    out = _by_desc(client, gid)["ONLINE PAYMENT TO CARD 1111"]
    assert out["is_internal_transfer"]
    before = _spent(client, gid)

    t = client.patch(f"/api/groups/{gid}/transactions/{out['id']}", json={"is_transfer": False}).json()
    assert not t["is_internal_transfer"] and t["transfer_user"] is False
    assert float(_spent(client, gid)) == float(before) + 500
    # The card side stays a transfer: NAB itself says it is a card payment.
    assert _by_desc(client, gid)["PAYMENT RECEIVED THANK YOU"]["is_internal_transfer"]

    # Importing again does not pair it back.
    assert upload(client, gid, "nab_everyday.csv").json()["transfers_paired"] == 0
    assert not _by_desc(client, gid)["ONLINE PAYMENT TO CARD 1111"]["is_internal_transfer"]

    # Back to automatic: it pairs again.
    t = client.patch(f"/api/groups/{gid}/transactions/{out['id']}", json={"is_transfer": None}).json()
    assert t["is_internal_transfer"] and t["transfer_user"] is None


def test_mark_as_transfer_by_hand(client):
    gid = _setup(client)
    upload(client, gid, "nab_everyday.csv")
    rent = _by_desc(client, gid)["ONLINE RENT NOVEMBER"]
    t = client.patch(f"/api/groups/{gid}/transactions/{rent['id']}", json={"is_transfer": True}).json()
    assert t["is_internal_transfer"]
    cats = {c["id"]: c["name"] for c in client.get(f"/api/groups/{gid}/categories").json()}
    assert cats[t["category_id"]] == "Internal transfers"
    # Changing the category alone leaves the transfer choice as it is.
    groceries = next(k for k, v in cats.items() if v == "Groceries")
    t = client.patch(f"/api/groups/{gid}/transactions/{rent['id']}", json={"category_id": groceries}).json()
    assert t["is_internal_transfer"] and t["category_id"] == groceries


# ---- H4: card payments from any bank


CARD_LAYOUT = {
    "date": "Date",
    "amount": "Amount",
    "description": ["Description"],
    "account_name": "Visa",
    "account_kind": "credit_card",
    "institution": "Westpac",
}
BANK_LAYOUT = {**CARD_LAYOUT, "account_name": "Everyday", "account_kind": "transaction", "institution": "ING"}


def test_card_payment_between_two_other_banks_is_matched(client):
    gid = _setup(client)
    card = "Date,Amount,Description\n05/11/2026,-80.00,COLES 123\n06/11/2026,500.00,PAYMENT RECEIVED - THANK YOU\n"
    bank = "Date,Amount,Description\n04/11/2026,-500.00,BPAY WESTPAC CARDS\n04/11/2026,-80.00,COLES 456\n"
    assert _file(client, gid, card, mapping=json.dumps(CARD_LAYOUT)).status_code == 201
    r = _file(
        client,
        gid,
        bank.replace("Description", "Details"),
        mapping=json.dumps({**BANK_LAYOUT, "description": ["Details"]}),
    )
    assert r.status_code == 201, r.text
    assert r.json()["transfers_paired"] == 1
    # Spending is the two Coles purchases, not the card payment on top.
    assert float(_spent(client, gid)) == 160.0


# ---- H2: undo an import, delete a transaction or an account


def test_undo_import(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    batch = upload(client, gid, "nab_everyday.csv").json()["batch_id"]
    imports = client.get(f"/api/groups/{gid}/imports").json()
    assert [i["remaining"] for i in imports] == [4, 8] and imports[0]["accounts"] == ["NAB 08-123-4567"]

    r = client.delete(f"/api/groups/{gid}/imports/{batch}").json()
    assert r == {"removed": 4, "accounts_removed": ["NAB 08-123-4567"]}
    assert all(a["external_ref"] != "08-123-4567" for a in client.get(f"/api/groups/{gid}/accounts").json())
    # The card payment's pair is split; it stays a transfer because NAB says so.
    payment = _by_desc(client, gid)["PAYMENT RECEIVED THANK YOU"]
    assert payment["is_internal_transfer"]
    assert len(client.get(f"/api/groups/{gid}/imports").json()) == 1
    # The same file can be imported again afterwards.
    assert upload(client, gid, "nab_everyday.csv").json()["rows_new"] == 4


def test_delete_transaction_splits_pair(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    upload(client, gid, "nab_everyday.csv")
    out = _by_desc(client, gid)["ONLINE PAYMENT TO CARD 1111"]
    assert client.delete(f"/api/groups/{gid}/transactions/{out['id']}").status_code == 204
    items = _by_desc(client, gid)
    assert "ONLINE PAYMENT TO CARD 1111" not in items
    assert client.delete(f"/api/groups/{gid}/transactions/{out['id']}").status_code == 404


def test_delete_account_is_for_owners(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards.csv")
    upload(client, gid, "nab_everyday.csv")
    account = next(a for a in client.get(f"/api/groups/{gid}/accounts").json() if a["external_ref"] == "08-123-4567")
    code = client.post(f"/api/groups/{gid}/invites").json()["code"]

    client.post("/api/auth/logout")
    register(client, email="partner@example.com", name="Partner")
    client.post("/api/groups/join", json={"code": code})
    assert client.delete(f"/api/groups/{gid}/accounts/{account['id']}").status_code == 403

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "martin@example.com", "password": "correct horse battery"})
    assert client.delete(f"/api/groups/{gid}/accounts/{account['id']}").status_code == 204
    assert all(t["account_id"] != account["id"] for t in _all(client, gid))
    assert _by_desc(client, gid)["PAYMENT RECEIVED THANK YOU"]["is_internal_transfer"]


def test_other_groups_cannot_undo_or_delete(client):
    gid = _setup(client)
    batch = upload(client, gid, "nab_cards.csv").json()["batch_id"]
    tx = _all(client, gid)[0]
    client.post("/api/auth/logout")
    register(client, email="stranger@example.com", name="Stranger")
    other = new_group(client, "Other")
    assert client.delete(f"/api/groups/{other}/imports/{batch}").status_code == 404
    assert client.delete(f"/api/groups/{other}/transactions/{tx['id']}").status_code == 404
    assert client.delete(f"/api/groups/{gid}/imports/{batch}").status_code == 404
