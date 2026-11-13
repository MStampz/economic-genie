import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
from app.config import get_settings
from app.core.categories import ensure_default_categories

FIXTURES = Path(__file__).parent / "fixtures"
HEADERS = {"X-Genie-Client": "tests"}


@pytest.fixture()
def client(tmp_path):
    """A fresh database per test. Set GENIE_TEST_DATABASE_URL to run against Postgres instead of SQLite."""
    get_settings.cache_clear()
    url = os.environ.get("GENIE_TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/test.db"
    engine = dbmod.init_engine(url)
    dbmod.Base.metadata.drop_all(engine)
    dbmod.Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        ensure_default_categories(s)
    from app.main import create_app

    with TestClient(create_app(seed=False), headers=HEADERS) as c:
        yield c
    dbmod.Base.metadata.drop_all(engine)
    engine.dispose()


def register(client, email="martin@example.com", name="Martin", password="correct horse battery"):
    r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def new_group(client, name="Family"):
    r = client.post("/api/groups", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, group_id, fixture):
    with open(FIXTURES / fixture, "rb") as f:
        return client.post(f"/api/groups/{group_id}/imports", files={"file": (fixture, f, "text/csv")})
