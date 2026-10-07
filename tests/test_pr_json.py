"""JSON files in a pull request: where a change sits, the exact checks, and the review of a JSON file. All names, hosts and values here are made up."""
from __future__ import annotations

import pytest

from app.services import pr_json, pr_knowledge
from app.services.pr_diff import build_view
from app.services.pr_json import JsonMap, mask, outline, parse, secrets_in
from app.services.pr_static import json_findings, static_findings
from pr_support import FakeAdo, FakePrModel, change, finding

OLD = """{
  "info": { "name": "Demo API" },
  "item": [
    {
      "name": "Orders",
      "item": [
        {
          "name": "Get orders",
          "request": {
            "method": "GET",
            "url": "{{baseUrl}}/orders"
          }
        }
      ]
    }
  ]
}
"""
NEW = """{
  "info": { "name": "Demo API" },
  "item": [
    {
      "name": "Orders",
      "item": [
        {
          "name": "Get orders",
          "request": {
            "method": "GET",
            "url": "{{baseUrl}}/orders"
          }
        },
        {
          "name": "Get one order",
          "request": {
            "method": "GET",
            "url": "https://demo.example.test/orders/1"
          }
        }
      ]
    }
  ]
}
"""
PATH = "tests/orders.collection.json"


def line_of(text: str, part: str) -> int:
    return next(n for n, line in enumerate(text.splitlines(), 1) if part in line)


def view(new: str = NEW, old: str = OLD):
    return build_view(PATH, "JSON", "edit", old, new)


class TestWhereAChangeSits:
    def test_each_line_knows_the_object_it_is_in(self):
        where = JsonMap(NEW)
        assert where.where(line_of(NEW, '"url": "https://demo')) == 'item[0] "Orders" > item[1] "Get one order" > request'
        assert where.where(line_of(NEW, '"method": "GET"')) == 'item[0] "Orders" > item[0] "Get orders" > request'
        assert where.where(2) == "the top level"

    def test_the_name_may_come_after_the_line_asked_about(self):
        text = '{\n  "item": [\n    {\n      "request": { "method": "GET" },\n      "name": "Late name"\n    }\n  ]\n}\n'
        assert JsonMap(text).where(4) == 'item[0] "Late name"'

    def test_the_changed_parts_are_listed_with_their_path(self):
        added = set(range(line_of(NEW, '"name": "Get one order"') - 1, line_of(NEW, '"url": "https://demo') + 3))
        text = outline(NEW, added)
        assert text.startswith("lines ") and 'item[0] "Orders" > item[]' in text.splitlines()[0]
        assert outline(NEW, set()) == ""

    def test_far_apart_changes_are_listed_one_by_one(self):
        lines = outline(NEW, {7, 20}).splitlines()
        assert [line.split(":")[0] for line in lines] == ["line 7", "line 20"]

    def test_a_long_name_is_cut(self):
        where = JsonMap('{"item": [{"name": "%s",\n"x": 1}]}' % ("n" * 200)).where(2)
        assert where == 'item[0] "%s"' % ("n" * pr_json.MAX_NAME_CHARS)

    def test_comments_trailing_commas_and_broken_files_do_not_stop_it(self):
        text = '{\n  // a comment with "quotes" and { braces\n  "a": [1, 2,],\n  /* a block\n  comment */\n  "b": { "name": "B", "c": 1, },\n'
        where = JsonMap(text)
        assert where.where(3) == "the top level" and where.where(6) == "the top level"  # the braces and quotes inside the comments did not open anything
        assert JsonMap(text + '  "c": [ { "name": "C",\n "d": 1 } ]\n').where(8) == 'c[0] "C"'
        for broken in ("", "{", '{"a": ', "]]]}}}", '"just a string"', "[1, 2", '{"a": "unterminated'):
            JsonMap(broken).where(1)  # never raises

    def test_a_key_written_twice_in_one_object_is_found_with_both_lines(self):
        text = '{\n  "name": "a",\n  "url": "u",\n  "name": "b"\n}\n'
        assert JsonMap(text).duplicates == [("name", 2, 4)]

    def test_the_same_key_in_different_objects_is_not_a_duplicate(self):
        assert JsonMap('{"a": {"name": 1}, "b": {"name": 2}, "c": [{"name": 3}, {"name": 4}]}').duplicates == []

    def test_a_key_written_with_an_escape_is_the_same_key(self):
        assert JsonMap('{"na\\u006de": 1, "name": 2}').duplicates == [("name", 1, 1)]

    def test_a_value_that_looks_like_a_key_is_not_one(self):
        assert JsonMap('{"a": "x", "b": "x", "c": ["x", "x"]}').duplicates == []


class TestIsItValidJson:
    @pytest.mark.parametrize("text", ['{"a": 1}', '{\n // note\n "a": 1,\n}', '﻿{"a": [1, 2,]}', "[]", "null", '{"a": "x,}"}'])
    def test_valid_files_and_the_tolerated_extras(self, text):
        assert parse(text)[1] is None

    @pytest.mark.parametrize("text", ['{"a": 1', '{"a": 1 "b": 2}', "{'a': 1}", '{"a": }', "{"])
    def test_broken_files(self, text):
        assert parse(text)[1] is not None


class TestSecrets:
    JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXRoYXQtaXMtbm90LXJlYWw"

    def test_a_token_in_a_header_is_found_once(self):
        found = secrets_in(f'"value": "Bearer {self.JWT}"')
        assert [(what, severity) for what, _, severity in found] == [("a JSON Web Token (an access token)", "warning")]

    def test_other_kinds(self):
        assert [w for w, _, _ in secrets_in('"value": "-----BEGIN RSA PRIVATE KEY-----"')] == ["a private key"]
        assert [w for w, _, _ in secrets_in('"Authorization": "Basic dXNlcjpwYXNzd29yZC1vZi1taW5l"')] == ["an authorization header value"]
        assert [w for w, _, _ in secrets_in('"cs": "Server=db;User Id=app;Password=Sup3rSecretValue;"')] == ["a password or account key in a connection string"]
        found = secrets_in('"password": "hunter2hunter2"')
        assert [(w, s) for w, _, s in found] == [('the value of "password"', "suggestion")]

    @pytest.mark.parametrize("line", [
        '"value": "Bearer {{token}}"', '"token": "{{token}}"', '"password": "${DB_PASSWORD}"', '"apiKey": "<your key>"', '"secret": "[parameters(\'secret\')]"', '"password": "short"',
        '"clientSecret": "@Microsoft.KeyVault(SecretUri=https://v.example.test/secrets/s)"', '"tokenUrl": "https://login.example.test/oauth2/token"', '"cs": "Password={{pwd}};"',
        '"description": "the password policy is in the wiki"', '"password": "changeme"', '"value": "Bearer $(token)"',
    ])
    def test_variables_placeholders_and_ordinary_text_are_not_secrets(self, line):
        assert secrets_in(line) == []

    def test_the_review_never_repeats_a_secret(self):
        line = f'      "value": "Bearer {self.JWT}"'
        (_, secret, _), = secrets_in(line)
        assert self.JWT not in mask(line, secret) and "eyJh…" in mask(line, secret)


class TestExactChecksForJson:
    def titles(self, new: str, old: str = OLD):
        return [f["title"] for f in json_findings(view(new, old), old, new)]

    def test_a_file_that_was_valid_and_is_not_now_is_found_on_a_changed_line(self):
        new = NEW.replace('"method": "GET",\n            "url": "https://demo', '"method": "GET"\n            "url": "https://demo')
        found = json_findings(view(new), OLD, new)
        assert [f["title"] for f in found] == ["The file is no longer valid JSON"] and found[0]["source"] == "static" and found[0]["severity"] == "warning"
        assert found[0]["line_number"] in view(new).added and "Expecting ',' delimiter" in found[0]["comment"]

    def test_a_file_that_was_never_valid_is_not_blamed_and_neither_is_a_new_file(self):
        assert self.titles('{"a": 1', old='{"a": ') == []
        assert json_findings(build_view(PATH, "JSON", "add", "", "{\n  broken\n}\n"), "", "{\n  broken\n}\n") == []

    def test_comments_and_trailing_commas_are_not_a_reason(self):
        assert self.titles(NEW.replace('"method": "GET",\n            "url": "https://demo', '"method": "GET", // note\n            "url": "https://demo').replace('}\n      ]', '},\n      ]')) == []

    def test_a_key_written_twice_on_a_changed_line_is_found(self):
        new = NEW.replace('"method": "GET",\n            "url": "https://demo', '"method": "GET",\n            "method": "POST",\n            "url": "https://demo')
        found = json_findings(view(new), OLD, new)
        assert [f["title"] for f in found] == ['"method" is written twice in the same object']
        assert found[0]["line_number"] == line_of(new, '"method": "POST"') and found[0]["failing_case"].startswith("Reading this file gives the value from line")

    def test_a_duplicate_that_was_already_there_is_not_this_pull_requests(self):
        both = OLD.replace('"method": "GET",', '"method": "GET",\n            "method": "POST",')
        assert self.titles(both + "\n", old=both) == []

    def test_a_secret_on_a_changed_line_is_found_and_masked(self):
        token = TestSecrets.JWT
        new = NEW.replace('"method": "GET",\n            "url": "https://demo', f'"method": "GET",\n            "auth": "Bearer {token}",\n            "url": "https://demo')
        found = json_findings(view(new), OLD, new)
        assert [(f["title"], f["severity"], f["category"]) for f in found] == [("A JSON Web Token (an access token) is written in the file", "warning", "security")]
        assert token not in found[0]["evidence"] and token not in found[0]["comment"] and "eyJh…" in found[0]["evidence"]

    def test_a_secret_that_was_already_there_is_not_this_pull_requests(self):
        old = OLD.replace('"method": "GET",', f'"method": "GET",\n            "auth": "Bearer {TestSecrets.JWT}",')
        assert self.titles(old + "\n", old=old) == []

    def test_there_is_a_limit_on_secrets(self):
        lines = ",\n".join(f'    "token{n}": "Bearer {TestSecrets.JWT}"' for n in range(10))
        new = "{\n" + lines + "\n}\n"
        assert len(json_findings(build_view(PATH, "JSON", "add", "", new), "", new)) == pr_json_limit()

    def test_the_checks_run_for_json_and_for_arm_templates_only(self):
        both = NEW.replace('"method": "GET",\n            "url": "https://demo', '"method": "GET",\n            "method": "POST",\n            "url": "https://demo')
        assert [f["title"] for f in static_findings(build_view(PATH, "JSON", "edit", OLD, both), OLD, both)] == ['"method" is written twice in the same object']
        assert [f["title"] for f in static_findings(build_view(PATH, "ARM template", "edit", OLD, both), OLD, both)] == ['"method" is written twice in the same object']
        assert static_findings(build_view("a.md", "Markdown", "edit", OLD, both), OLD, both) == []


def pr_json_limit() -> int:
    from app.services.pr_static import MAX_SECRET_FINDINGS
    return MAX_SECRET_FINDINGS


REPO = {"src/orders.py": "def get_orders():\n    return []  # never None\n", "src/make_collection.py": "# writes tests/orders.collection.json\n"}


def json_pr(new: str = NEW, old: str = OLD, **over):
    blobs = {f"new-/{PATH}": new, f"old-/{PATH}": old}
    return FakeAdo(changes=[change(f"/{PATH}")], blobs=blobs, description="Adds a request.", repo_files=REPO, **over)


def review(model: FakePrModel | None = None, ado: FakeAdo | None = None):
    from app.services.pr_review import PullRequestReviewService
    model = model or FakePrModel()
    return PullRequestReviewService(ado or json_pr(), model).review("proj", "repo", 7), model


class TestReviewingAJsonFile:
    def test_it_is_reviewed_as_json_not_skipped(self):
        result, _ = review()
        row = {f["path"]: f for f in result["files"]}[PATH]
        assert (row["status"], row["language"], row["reason"]) == ("reviewed", "JSON", None)
        assert "Reviewed 1 of 1 changed files (1 JSON)" in result["summary"]

    def test_the_reviewer_is_told_where_each_changed_part_sits(self):
        _, model = review()
        prompt = model.calls_of("file")[0]
        assert "Where each changed part sits in the JSON structure:" in prompt and 'item[0] "Orders"' in prompt
        assert "What the alert rules in this template are" not in prompt

    def test_the_reviewer_gets_the_json_guidance_and_checklist_not_the_alert_ones(self):
        _, model = review()
        system, prompt = model.system_of("file")[0], model.calls_of("file")[0]
        assert "JSON (settings, test collections, data)" in system and "Azure Monitor alerts in an ARM template" not in system
        assert "An entry copied from a neighbor that still carries" in prompt and "A file produced by a script of the repository" in prompt

    def test_the_first_read_may_look_things_up_for_json_and_says_how(self):
        _, model = review()
        assert model.first_tools_offered == [True]
        assert "You can look things up before you answer" in model.system_of("file")[0] and "Never report what you did not look up" in model.system_of("file")[0]

    def test_other_languages_are_read_without_tools(self):
        ado = FakeAdo(changes=[change("/src/a.py", "add")], blobs={"new-/src/a.py": "x = 1\n"}, description="", repo_files=REPO)
        from app.services.pr_review import PullRequestReviewService
        model = FakePrModel()
        PullRequestReviewService(ado, model).review("proj", "repo", 7)
        assert model.first_tools_offered == [False] and "You can look things up before you answer" not in model.system_of("file")[0]

    def test_without_a_repository_to_read_there_are_no_tools_even_for_json(self):
        ado = json_pr()
        ado.get_pull_request_iterations = lambda *args: [{"id": 1, "sourceRefCommit": {}, "commonRefCommit": {"commitId": "b" * 40}}]
        _, model = review(ado=ado)
        assert model.first_tools_offered == [False] and "You can look things up before you answer" not in model.system_of("file")[0]

    def test_what_the_first_read_looked_up_is_shown(self):
        url = line_of(NEW, '"url": "https://demo')
        model = FakePrModel({PATH: [finding(url, "A host written into the request", comment="The request calls one host, so it cannot run against another environment. Use {{baseUrl}} like the first request.",
                                            failing_case="Running the collection against the test environment still calls demo.example.test.", evidence='"url": "https://demo.example.test/orders/1"')]},
                            first_lookups={PATH: [("read_file", {"path": "src/orders.py"})]})
        result, model = review(model)
        assert model.first_tool_results and "def get_orders" in model.first_tool_results[0]
        assert "While reviewing, the AI read 1 file(s) of the repository: src/orders.py." in result["notes"]
        assert [c["title"] for c in result["comments"]] == ["A host written into the request"] and result["comments"][0]["checked_with"] == ["read src/orders.py"]

    def test_an_exact_check_finds_a_duplicate_key_without_the_ai(self):
        both = NEW.replace('"method": "GET",\n            "url": "https://demo', '"method": "GET",\n            "method": "POST",\n            "url": "https://demo')
        result, _ = review(ado=json_pr(new=both))
        assert [(c["title"], c["source"]) for c in result["comments"]] == [('"method" is written twice in the same object', "static")]

    def test_a_finding_about_code_this_pull_request_did_not_change_is_still_removed(self):
        model = FakePrModel({PATH: [finding(line_of(NEW, '"name": "Orders"'), "Old entry", comment="The name of the first folder is vague. Rename it.")]})
        result, _ = review(model)
        assert result["comments"] == []

    def test_a_new_json_file_is_reviewed_too(self):
        ado = FakeAdo(changes=[change(f"/{PATH}", "add")], blobs={f"new-/{PATH}": NEW}, description="", repo_files=REPO)
        result, model = review(ado=ado)
        assert {f["path"]: f["status"] for f in result["files"]}[PATH] == "reviewed" and len(model.calls_of("file")) == 1

    def test_a_long_line_is_not_cut(self):
        long_value = "x" * 1500
        new = NEW.replace('"url": "https://demo.example.test/orders/1"', f'"url": "https://demo.example.test/orders/1", "body": "{long_value}"')
        _, model = review(ado=json_pr(new=new))
        assert long_value in model.calls_of("file")[0]


class TestKnowledgeBaseScopes:
    @pytest.mark.parametrize("tag", ["json", "JSON", "postman"])
    def test_a_check_can_be_limited_to_json_files(self, tag):
        item = pr_knowledge.parse(f"[{tag}] Every request uses {{{{baseUrl}}}}")[0]
        assert item["scopes"] == ["JSON"] and pr_knowledge.applies(item, "JSON") and not pr_knowledge.applies(item, "YAML")
