from decimal import Decimal

from tests.conftest import new_group, register, upload


def _setup(client):
    register(client)
    gid = new_group(client)
    upload(client, gid, "nab_cards.csv")
    upload(client, gid, "nab_everyday.csv")
    return gid


def _cats(client, gid):
    return {c["name"]: c["id"] for c in client.get(f"/api/groups/{gid}/categories").json()}


def _post(budget, name):
    return next(p for h in budget["headings"] for p in h["posts"] if p["name"] == name)


def test_starter_budget(client):
    gid = _setup(client)
    b = client.post(f"/api/groups/{gid}/budget/starter").json()
    assert [h["name"] for h in b["headings"]] == ["Bolig", "Faste udgifter", "Variable udgifter"]
    cats = _cats(client, gid)
    assert "Crosser" in cats  # created for the group
    assert _post(b, "Crosser")["category_ids"] == [cats["Crosser"], cats["Fuel"]]
    assert client.post(f"/api/groups/{gid}/budget/starter").status_code == 409


def test_category_lives_in_one_post(client):
    gid = _setup(client)
    b = client.post(f"/api/groups/{gid}/budget/starter").json()
    cats = _cats(client, gid)
    heading = b["headings"][0]["id"]
    b = client.post(
        f"/api/groups/{gid}/budget/posts",
        json={"heading_id": heading, "name": "Kaffe", "category_ids": [cats["Cafe & coffee"]], "monthly_amount": "100"},
    ).json()
    assert _post(b, "Kaffe")["category_ids"] == [cats["Cafe & coffee"]]
    assert cats["Cafe & coffee"] not in _post(b, "Restaurants og take away")["category_ids"]


def test_overview_totals_and_budget(client):
    gid = _setup(client)
    b = client.post(f"/api/groups/{gid}/budget/starter").json()
    groceries = _post(b, "Groceries og wine")
    client.patch(f"/api/groups/{gid}/budget/posts/{groceries['id']}", json={"monthly_amount": "50"})

    o = client.get(f"/api/groups/{gid}/overview", params={"period": "2026-11", "today": "2026-11-15"}).json()
    assert o["period"]["label"] == "November 2026" and o["months"][0]["key"] == "2026-11"
    # Card spending: 4.80 pending + 62.10 + 4.80 + 4.80 + 89 + 45 - 12.50 refund = 198.00.
    # Rent 2400 from the everyday account is spending too; the 500 card payment and both legs are not;
    # salary and the friend's transfer are uncategorised money in: income, not spending.
    assert Decimal(o["total"]) == Decimal("198.00") + Decimal("2400.00")
    g = next(p for p in o["posts"] if p["name"] == "Groceries og wine")
    assert Decimal(g["spent"]) == Decimal("62.10") and Decimal(g["budget"]) == Decimal("50.00")
    assert Decimal(g["pace"]) == Decimal("25.00")  # half way through November
    assert o["budgets_set"] == 1 and o["budgets_over"] == 1
    assert len(o["days"]) == 15 and o["days"][0]["date"] == "2026-11-01"
    assert o["insights"]["eating_out_count"] == 3
    assert o["merchants"][0]["spent"] is not None
    # Categories come biggest first, each with a colour that doesn't depend on the month shown.
    spent = [Decimal(c["spent"]) for c in o["categories"]]
    assert spent == sorted(spent, reverse=True) and o["categories"][0]["color"] == 1
    october = client.get(f"/api/groups/{gid}/overview", params={"period": "all"}).json()
    colours = {c["name"]: c["color"] for c in october["categories"]}
    assert all(colours[c["name"]] == c["color"] for c in o["categories"])


def test_overview_by_account_and_all(client):
    gid = _setup(client)
    accounts = {a["external_ref"]: a["id"] for a in client.get(f"/api/groups/{gid}/accounts").json()}
    o = client.get(
        f"/api/groups/{gid}/overview", params={"period": "all", "account_id": accounts["Card ending 2222"]}
    ).json()
    assert Decimal(o["total"]) == Decimal("121.50") and o["purchases"] == 2
    assert [a["name"] for a in o["accounts"]] == ["NAB Card ending 2222"]


def test_refund_in_spending_category_lowers_spending(client):
    gid = _setup(client)
    cats = _cats(client, gid)
    friend = client.get(f"/api/groups/{gid}/transactions", params={"q": "FRIEND"}).json()["items"][0]
    client.patch(f"/api/groups/{gid}/transactions/{friend['id']}", json={"category_id": cats["Groceries"]})
    o = client.get(f"/api/groups/{gid}/overview", params={"period": "2026-11"}).json()
    assert Decimal(o["total"]) == Decimal("2598.00") - Decimal("12.50")
    assert Decimal(o["refunds"]) == Decimal("25.00")  # the Kmart refund and the friend's


def test_budget_isolated_between_groups(client):
    gid = _setup(client)
    client.post("/api/auth/logout")
    register(client, email="other@example.com", name="Other")
    assert client.get(f"/api/groups/{gid}/budget").status_code == 404
    assert client.get(f"/api/groups/{gid}/overview").status_code == 404
