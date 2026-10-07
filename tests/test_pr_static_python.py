"""Python patterns the review finds in code, not with the AI: all code in this file is made up."""
from __future__ import annotations

import pytest

from app.services.pr_diff import build_view
from app.services.pr_static import python_hazards, static_findings


def view(new, old=""):
    return build_view("app/tools.py", "Python", "edit" if old else "add", old, new)


def titles(new, old=""):
    return [f["title"] for f in python_hazards(view(new, old))]


class TestReturnAnnotationNarrowerThanJson:
    CODE = 'import json\n\n\ndef load_settings(path) -> dict:\n    with open(path) as handle:\n        return json.load(handle)\n'

    def test_a_dict_annotation_on_a_function_that_returns_json_is_found(self):
        found = python_hazards(view(self.CODE))
        assert [f["title"] for f in found] == ["load_settings() is annotated -> dict but returns whatever the JSON holds"]
        assert found[0]["line_number"] == 4 and found[0]["source"] == "static" and found[0]["category"] == "correctness" and "a list" in found[0]["failing_case"]

    @pytest.mark.parametrize("annotation", ["dict[str, int]", "Dict[str, int]", "typing.Dict", "list", "List[str]"])
    def test_the_usual_spellings_count(self, annotation):
        assert len(titles(self.CODE.replace("-> dict", f"-> {annotation}"))) == 1

    @pytest.mark.parametrize("annotation", ["Any", "object", "dict | list", "str", ""])
    def test_a_wide_annotation_or_none_is_fine(self, annotation):
        code = self.CODE.replace(" -> dict", f" -> {annotation}" if annotation else "")
        assert titles(code) == []

    def test_a_function_that_does_not_return_json_directly_is_fine(self):
        assert titles("import json\n\n\ndef count(path) -> dict:\n    data = json.load(open(path))\n    return {'n': len(data)}\n") == []

    def test_json_loads_counts_and_the_other_json_like_modules_do_not(self):
        assert len(titles("import json\n\n\ndef parse(text) -> dict:\n    return json.loads(text)\n")) == 1
        assert titles("import yaml\n\n\ndef parse(text) -> dict:\n    return yaml.safe_load(text)\n") == []

    def test_a_function_this_pull_request_did_not_touch_is_not_judged(self):
        assert titles(self.CODE + "\nX = 1\n", old=self.CODE) == []


class TestDefaultValueThatIsChanged:
    def test_a_default_list_that_the_function_appends_to_is_found(self):
        found = python_hazards(view("def add_row(row, rows=[]):\n    rows.append(row)\n    return rows\n"))
        assert [(f["title"], f["severity"], f["line_number"]) for f in found] == [("Default value of rows is one object shared by every call", "warning", 1)]
        assert ".append()" in found[0]["comment"]

    @pytest.mark.parametrize("default,body", [
        ("{}", "    seen['a'] = 1\n"), ("set()", "    seen.add(1)\n"), ("dict()", "    seen.update(x=1)\n"), ("[]", "    seen += [1]\n    seen.sort()\n"), ("[]", "    del seen[0]\n"),
    ])
    def test_every_way_of_changing_it(self, default, body):
        assert len(titles(f"def run(seen={default}):\n{body}    return seen\n")) == 1

    def test_a_default_that_is_only_read_is_fine(self):
        assert titles("def total(values=[]):\n    return sum(values)\n") == []

    def test_a_function_that_replaces_the_default_first_is_fine(self):
        assert titles("def add_row(row, rows=[]):\n    rows = list(rows)\n    rows.append(row)\n    return rows\n") == []

    def test_a_default_of_none_and_a_tuple_are_fine(self):
        assert titles("def add_row(row, rows=None, kinds=()):\n    rows = rows or []\n    rows.append(row)\n    return rows\n") == []

    def test_a_keyword_only_default_counts_too(self):
        assert len(titles("def add_row(row, *, rows=[]):\n    rows.append(row)\n")) == 1

    def test_the_second_of_two_defaults_is_the_one_named(self):
        found = python_hazards(view("def add(a=1, b=[]):\n    b.append(a)\n"))
        assert "Default value of b" in found[0]["title"]

    def test_a_change_made_inside_a_nested_function_is_not_this_functions(self):
        assert titles("def outer(rows=[]):\n    def inner(rows):\n        rows.append(1)\n    return inner\n") == []


class TestSwallowedErrors:
    @pytest.mark.parametrize("handler", ["except:", "except Exception:", "except BaseException:"])
    def test_a_broad_handler_that_does_nothing_is_found(self, handler):
        found = python_hazards(view(f"try:\n    send()\n{handler}\n    pass\n"))
        assert [(f["title"], f["line_number"]) for f in found] == [("Every error is swallowed without a trace", 3)]

    def test_an_ellipsis_body_is_the_same(self):
        assert len(titles("try:\n    send()\nexcept Exception:\n    ...\n")) == 1

    @pytest.mark.parametrize("code", [
        "try:\n    send()\nexcept ValueError:\n    pass\n",                   # a specific error
        "try:\n    send()\nexcept Exception:\n    log.warning('x')\n",         # it does something
        "try:\n    send()\nexcept Exception:  # best effort, the file may be gone\n    pass\n",  # the author said why
        "try:\n    send()\nexcept Exception:\n    # best effort\n    pass\n",
    ])
    def test_other_handlers_are_fine(self, code):
        assert titles(code) == []


class TestShellCommands:
    @pytest.mark.parametrize("call", [
        'subprocess.run(f"git checkout {branch}", shell=True)', 'subprocess.check_output("git log " + name, shell=True)', 'subprocess.Popen("ls %s" % folder, shell=True)',
        'subprocess.call("echo {}".format(text), shell=True)', 'os.system(f"rm {path}")',
    ])
    def test_a_command_built_from_values_is_found(self, call):
        found = python_hazards(view(f"import os\nimport subprocess\n\n{call}\n"))
        assert [(f["title"], f["severity"], f["category"]) for f in found] == [("Shell command built from values", "warning", "security")]

    @pytest.mark.parametrize("call", [
        'subprocess.run(["git", "checkout", branch])', 'subprocess.run(f"git checkout {branch}")', 'subprocess.run("git status", shell=True)', 'subprocess.run(["git", branch], shell=True)',
        'os.system("cls")', 'subprocess.run("git " + "status", shell=True)',
    ])
    def test_the_safe_forms_are_fine(self, call):
        assert titles(f"import os\nimport subprocess\n\n{call}\n") == []


class TestWebRequestsWithoutTimeout:
    @pytest.mark.parametrize("verb", ["get", "post", "put", "patch", "delete", "head"])
    def test_a_request_without_a_timeout_is_found(self, verb):
        found = python_hazards(view(f"import requests\n\nrequests.{verb}(url)\n"))
        assert [(f["title"], f["severity"]) for f in found] == [("Web request without a timeout", "warning")]

    @pytest.mark.parametrize("call", ["requests.get(url, timeout=30)", "requests.get(url, timeout=None)", "requests.get(url, **options)", "session.get(url)", "client.get(url)"])
    def test_a_timeout_or_an_object_that_may_hold_one_is_fine(self, call):
        assert titles(f"import requests\n\n{call}\n") == []


class TestNoqaMeansTheAuthorMeantIt:
    @pytest.mark.parametrize("code", [
        'import json\n\n\ndef load(path) -> dict:  # noqa\n    return json.load(open(path))\n',
        'import json\n\n\ndef load(path) -> dict:\n    return json.load(open(path))  # noqa: ANN\n',
        "def add_row(row, rows=[]):  # noqa: B006\n    rows.append(row)\n",
        'import subprocess\n\nsubprocess.run(f"git checkout {branch}", shell=True)  # noqa: S602\n',
        "import requests\n\nrequests.get(url)  # noqa: S113\n",
    ])
    def test_a_noqa_on_the_line_silences_the_check(self, code):
        assert titles(code) == []


class TestOnlyAddedLinesAndSafeRunning:
    def test_a_hazard_that_was_already_there_is_not_this_pull_requests(self):
        code = "import requests\n\nrequests.get(url)\n"
        assert titles(code + "x = 1\n", old=code) == []

    def test_a_file_that_does_not_parse_is_left_alone(self):
        assert python_hazards(view("def broken(:\n    requests.get(url)\n")) == []

    def test_the_checks_run_with_the_others_for_python_only(self):
        code = "import requests\n\nrequests.get(url)\n"
        assert [f["title"] for f in static_findings(view(code))] == ["Web request without a timeout"]
        assert static_findings(build_view("a.ps1", "PowerShell", "add", "", "Invoke-RestMethod $url\n")) == []
