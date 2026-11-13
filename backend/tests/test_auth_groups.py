from fastapi.testclient import TestClient

from tests.conftest import new_group, register


def test_register_login_logout(client):
    me = register(client)
    assert me["user"]["email"] == "martin@example.com"
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    r = client.post("/api/auth/login", json={"email": "MARTIN@example.com ", "password": "correct horse battery"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_session_cookie_is_http_only(client):
    r = client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": "correct horse battery", "display_name": "A"}
    )
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_weak_password_and_duplicate_email(client):
    r = client.post("/api/auth/register", json={"email": "a@example.com", "password": "short", "display_name": "A"})
    assert r.status_code == 422
    register(client, email="a@example.com")
    r = client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": "another long one", "display_name": "B"}
    )
    assert r.status_code == 409


def test_login_throttling(client):
    register(client)
    client.post("/api/auth/logout")
    for _ in range(8):
        r = client.post("/api/auth/login", json={"email": "martin@example.com", "password": "wrong password!"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "martin@example.com", "password": "correct horse battery"})
    assert r.status_code == 429


def test_unknown_email_gives_same_message(client):
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Email or password is incorrect."


def test_writes_need_client_header(client):
    bare = TestClient(client.app)
    r = bare.post("/api/auth/register", json={"email": "a@example.com", "password": "x" * 12, "display_name": "A"})
    assert r.status_code == 403


def test_invite_flow_and_roles(client):
    register(client)
    gid = new_group(client)
    code = client.post(f"/api/groups/{gid}/invites").json()["code"]
    client.post("/api/auth/logout")

    register(client, email="partner@example.com", name="Partner")
    # Codes are forgiving about case and dashes.
    r = client.post("/api/groups/join", json={"code": code.lower().replace("-", " ")})
    assert r.status_code == 200, r.text
    members = client.get(f"/api/groups/{gid}/members").json()
    assert {m["role"] for m in members} == {"owner", "member"}
    # A member cannot create invites.
    assert client.post(f"/api/groups/{gid}/invites").status_code == 403
    # The code works only once.
    client.post("/api/auth/logout")
    register(client, email="third@example.com", name="Third")
    assert client.post("/api/groups/join", json={"code": code}).status_code == 404


def test_last_owner_cannot_leave(client):
    me = register(client)
    gid = new_group(client)
    r = client.delete(f"/api/groups/{gid}/members/{me['user']['id']}")
    assert r.status_code == 409


def test_groups_are_isolated(client):
    register(client)
    gid = new_group(client)
    client.post("/api/auth/logout")
    register(client, email="stranger@example.com", name="Stranger")
    for path in ("", "/members", "/accounts", "/transactions", "/rules", "/activity"):
        assert client.get(f"/api/groups/{gid}{path}").status_code == 404, path
