import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.repositories.work_item_insights_repository as store


class TestScopeKey:
    def test_it_is_stable_and_ignores_case_and_spaces(self):
        assert store.scope_key("Org", "Proj", "Team", "Tag") == store.scope_key(" org ", "PROJ", "team", " tag")

    def test_a_different_team_or_tag_is_a_different_scope(self):
        keys = {store.scope_key("o", "p"), store.scope_key("o", "p", "t"), store.scope_key("o", "p", "", "x"), store.scope_key("o", "p", "t", "x")}
        assert len(keys) == 4

    def test_fields_cannot_run_together(self):
        assert store.scope_key("ab", "c") != store.scope_key("a", "bc")

    def test_it_has_a_fixed_length_that_fits_the_column(self):
        assert len(store.scope_key("o" * 64, "p" * 256, "t" * 256, "g" * 256)) == 64


class TestInMemory:
    def test_nothing_saved_is_none(self):
        assert store.get("missing") is None

    def test_save_creates_with_defaults_and_updates_only_what_is_given(self):
        store.save("k", organization="o", project="p", items=[{"id": 1}], areas=[{"name": "VPN"}])
        store.save("k", inventory={"alerts": [{"name": "a"}]})
        record = store.get("k")
        assert record["items"] == [{"id": 1}] and record["inventory"] == {"alerts": [{"name": "a"}]}
        assert record["months"] == 6 and record["notes"] == [] and record["refreshed_at"] is None

    def test_a_copy_is_returned_so_callers_cannot_change_the_saved_data(self):
        store.save("k", items=[{"id": 1}])
        store.get("k")["items"].append({"id": 2})
        assert store.get("k")["items"] == [{"id": 1}]

    def test_an_unknown_field_is_an_error(self):
        with pytest.raises(ValueError, match="Unknown field"):
            store.save("k", bogus=1)

    def test_a_field_can_be_cleared(self):
        store.save("k", inventory={"alerts": []})
        store.save("k", inventory=None)
        assert store.get("k")["inventory"] is None


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 0

    def execute(self, sql, *params):
        self.conn.statements.append((" ".join(sql.split()), params))
        if sql.lstrip().startswith("UPDATE"):
            self.rowcount = 1 if self.conn.row_exists else 0
        elif sql.lstrip().startswith("INSERT"):
            self.conn.row_exists = True


class FakeConn:
    def __init__(self, row_exists=False):
        self.statements, self.row_exists, self.commits = [], row_exists, 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


@pytest.fixture
def sql(monkeypatch):
    """Pretends SQL is configured and records what would be sent to it."""
    conn = FakeConn()
    ddl = []

    @contextmanager
    def connection():
        yield conn

    monkeypatch.setattr(store, "get_settings", lambda: SimpleNamespace(sql_connection_string="Server=fake"))
    monkeypatch.setattr(store, "get_connection", connection)
    monkeypatch.setattr(store, "execute_commit", lambda statement, params=(): ddl.append(statement))
    monkeypatch.setattr(store, "_table_ready", False)
    return SimpleNamespace(conn=conn, ddl=ddl)


class TestSql:
    def test_the_table_is_created_once(self, sql, monkeypatch):
        monkeypatch.setattr(store, "fetch_one", lambda q, p=(): None)
        store.get("k")
        store.get("k")
        assert len(sql.ddl) == 1 and "CREATE TABLE dbo.wi_insight_scopes" in sql.ddl[0] and "scope_key NVARCHAR(64)" in sql.ddl[0]

    def test_a_new_scope_is_inserted_with_json_columns(self, sql):
        store.save("k", organization="o", project="p", items=[{"id": 1, "title": "Café"}], months=6)
        update, insert = sql.conn.statements
        assert update[0].startswith("UPDATE dbo.wi_insight_scopes SET organization = ?, project = ?, items_json = ?, months = ?")
        assert insert[0].startswith("INSERT INTO dbo.wi_insight_scopes (scope_key, organization, project, items_json, months)")
        assert insert[1][0] == "k" and json.loads(insert[1][3]) == [{"id": 1, "title": "Café"}]
        assert sql.conn.commits == 1

    def test_an_existing_scope_is_only_updated(self, sql):
        sql.conn.row_exists = True
        store.save("k", inventory={"alerts": []})
        assert [s[0].split()[0] for s in sql.conn.statements] == ["UPDATE"]
        assert sql.conn.statements[0][1][-1] == "k"  # the key is the last parameter (WHERE scope_key = ?)

    def test_clearing_a_field_sets_the_column_to_null(self, sql):
        sql.conn.row_exists = True
        store.save("k", inventory=None)
        assert sql.conn.statements[0][1][0] is None

    def test_a_saved_row_is_read_back_into_a_record(self, sql, monkeypatch):
        row = {"scope_key": "k", "organization": "o", "project": "p", "team": "", "tag": "monitoring", "months": 6,
               "areas_json": json.dumps([{"name": "VPN"}]), "areas_version": 2, "area_source": "ai",
               "items_json": json.dumps([{"id": 1}]), "inventory_json": None, "notes_json": None, "refreshed_at": "2026-10-05T10:00:00Z"}
        monkeypatch.setattr(store, "fetch_one", lambda q, p=(): row)
        record = store.get("k")
        assert record["areas"] == [{"name": "VPN"}] and record["items"] == [{"id": 1}] and record["areas_version"] == 2
        assert record["inventory"] is None and record["notes"] == [] and record["tag"] == "monitoring"

    def test_a_database_failure_is_raised_not_hidden(self, sql, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("database down")

        monkeypatch.setattr(store, "fetch_one", boom)
        with pytest.raises(RuntimeError, match="database down"):
            store.get("k")
