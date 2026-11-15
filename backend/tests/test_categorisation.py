from app.core.categorisation.text import payee_key, similar
from tests.conftest import new_group, register, upload


def _setup(client):
    register(client)
    return new_group(client)


def _by_desc(client, gid):
    cats = {c["id"]: c["name"] for c in client.get(f"/api/groups/{gid}/categories").json()}
    items = client.get(f"/api/groups/{gid}/transactions", params={"limit": 500}).json()["items"]
    return {t["description"]: {**t, "category": cats.get(t["category_id"])} for t in items}, {
        v: k for k, v in cats.items()
    }


def test_payee_key_strips_bank_noise():
    assert payee_key("V2526 01/11 TELMORE KOEBENHAVN 74383766305") == "telmore koebenhavn"
    assert payee_key("ON POINT F5751231187 Invoice 9236") == "on point"
    assert payee_key("on point Y6194652969 8369") == "on point"
    assert payee_key("INTERNET TRANSFER RENT") == "rent"
    assert payee_key("turnkey R2794682122 Deal number U-3759") == "turnkey"
    assert payee_key("EZYPAYID_114734221 Revo Fitness Sou A Person") == "revo fitness sou a person"
    assert payee_key("EFTPOS 02/01 16:36SANDRINGHAM UNCORKED 7D BAY RD") == "sandringham uncorked 7d bay rd"
    assert payee_key("anything", "Amazon (Marketplace)") == "amazon"
    assert similar("kintamani bike tours bangli", "kintamani bike tours") >= 0.9
    assert similar("sandringham hotel", "sandringham uncorked") < 0.86


def test_text_and_bank_hints_categorise_transaction_account(client):
    gid = _setup(client)
    assert upload(client, gid, "nab_everyday_text.csv").status_code == 201
    tx, _ = _by_desc(client, gid)

    rent = tx["INTERNET TRANSFER RENT"]
    assert (rent["category"], rent["category_source"]) == ("Rent", "auto")
    assert "rent" in rent["category_reason"]
    assert tx["EZYPAYID_114734221 Revo Fitness Sou A Person"]["category"] == "Personal care"
    assert tx["V2526 01/10 TELMORE KOEBENHAVN 74383766305"]["category"] == "Phone & internet"
    # The bank's own names that mean one of ours
    assert tx["SALARY ACME PTY LTD"]["category"] == "Salary"
    assert tx["INTERNET BPAY QANTAS 123456"]["category"] == "Travel expenses"
    assert tx["S P & K M FRIEND"]["category"] == "Other income"
    # Paying the NAB card from the transaction account is a transfer, not spending
    card = tx["INTERNET BPAY nab cards 4715276702956867"]
    assert card["is_internal_transfer"] and card["category"] == "Internal transfers"
    # No hint at all: stays for a person to sort
    assert tx["G GEORGIADES X1032662281"]["category"] == "Uncategorised"
    assert tx["ON POINT W3985308287 Invoice 9257"]["category"] == "Uncategorised"


def test_rules_win_over_built_in_knowledge(client):
    gid = _setup(client)
    r = client.post(
        f"/api/groups/{gid}/rules/import",
        json={"rules": [{"pattern": "on ?point", "is_regex": True, "category": "Crosser"}]},
    )
    assert r.status_code == 200
    upload(client, gid, "nab_everyday_text.csv")
    tx, _ = _by_desc(client, gid)
    op = tx["ON POINT W3985308287 Invoice 9257"]
    assert (op["category"], op["category_source"]) == ("Crosser", "rule")
    assert op["category_reason"] == 'Your rule "on ?point"'


def test_similar_payee_on_another_account(client):
    gid = _setup(client)
    upload(client, gid, "nab_cards_tours.csv")
    upload(client, gid, "nab_everyday_text.csv")
    tx, _ = _by_desc(client, gid)
    t = tx["V2500 29/09 KINTAMANI BIKE TOURS BANGLI 74105046272"]
    assert (t["category"], t["category_source"]) == ("Attractions & events", "auto")
    assert "kintamani bike tours" in t["category_reason"]


def test_hand_pick_is_remembered_for_the_payee(client):
    gid = _setup(client)
    upload(client, gid, "nab_everyday_text.csv")
    tx, ids = _by_desc(client, gid)
    first = tx["G GEORGIADES X1032662281"]
    other = tx["G GEORGIADES Q7032662999"]
    r = client.patch(f"/api/groups/{gid}/transactions/{first['id']}", json={"category_id": ids["Gifts"]})
    assert r.status_code == 200, r.text
    assert r.json()["also_updated"] == [other["id"]]
    tx, _ = _by_desc(client, gid)
    assert (tx["G GEORGIADES Q7032662999"]["category"], tx["G GEORGIADES Q7032662999"]["category_source"]) == (
        "Gifts",
        "auto",
    )
    # Re-running everything keeps it, because the hand pick is remembered
    assert client.post(f"/api/groups/{gid}/rules/apply").status_code == 200
    tx, _ = _by_desc(client, gid)
    assert tx["G GEORGIADES Q7032662999"]["category"] == "Gifts"

    # Handing the first one back to the app forgets it again: nothing is learned from the row itself
    r = client.patch(f"/api/groups/{gid}/transactions/{first['id']}", json={"category_id": None})
    assert r.json()["category_source"] != "user"
    client.post(f"/api/groups/{gid}/rules/apply")
    tx, _ = _by_desc(client, gid)
    assert tx["G GEORGIADES X1032662281"]["category"] == "Uncategorised"
    assert tx["G GEORGIADES Q7032662999"]["category"] == "Uncategorised"
