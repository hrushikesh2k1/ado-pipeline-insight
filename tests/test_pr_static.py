"""The checks made in code, without the AI: unused variables and imports, a changed file encoding, broken Markdown tables."""
from __future__ import annotations

import pytest

from app.services import pr_static
from app.services.pr_diff import build_view
from app.services.pr_static import encoding_findings, markdown_tables, powershell_unused, python_unused, static_findings
from core.ado_client import AzureDevOpsClient
from pr_support import decoded


def ps_view(new, old=""):
    return build_view("tools/run.ps1", "PowerShell", "edit" if old else "add", old, new)


def py_view(new, old="", path="app/mod.py"):
    return build_view(path, "Python", "edit" if old else "add", old, new)


def md_view(new, old=""):
    return build_view("docs/guide.md", "Markdown", "edit" if old else "add", old, new)


class TestPowerShellUnusedVariables:
    def test_a_variable_that_is_set_and_never_read_is_found(self):
        found = powershell_unused(ps_view("$status = Get-Status\nWrite-Output 'done'\n"))
        assert len(found) == 1
        f = found[0]
        assert (f["title"], f["line_number"], f["severity"], f["category"], f["source"]) == ("$status is assigned and never used", 1, "suggestion", "maintainability", "static")
        assert "UseDeclaredVarsMoreThanAssignments" in f["comment"] and f["evidence"] == "$status = Get-Status" and f["verified"] is None

    def test_a_variable_that_is_read_is_not(self):
        assert powershell_unused(ps_view("$status = Get-Status\nWrite-Output $status\n")) == []

    @pytest.mark.parametrize("use", ['Write-Output "State: $status"', "Do-It @status", "Write-Output ${status}", "Write-Output $Status.Name", "if ($status) { 1 }"])
    def test_every_way_of_reading_it_counts(self, use):
        assert powershell_unused(ps_view(f"$status = @{{}}\n{use}\n")) == []

    def test_only_lines_this_pull_request_changed_are_judged(self):
        old = "$status = Get-Status\nWrite-Output 'a'\n"
        assert powershell_unused(ps_view(old + "Write-Output 'b'\n", old)) == []

    def test_a_parameter_with_a_default_is_not_an_assignment(self):
        code = "function Get-It {\n    param(\n        [string]$Name = 'x',\n        $Count = 3\n    )\n    'ok'\n}\n"
        assert powershell_unused(ps_view(code)) == []

    @pytest.mark.parametrize("line", ["$null = Do-It", "$ErrorActionPreference = 'Stop'", "$_ = 1", "$script:cache = 1", "$global:x = 1", "$env:PATH = 'x'"])
    def test_automatic_and_scoped_variables_are_not_flagged(self, line):
        assert powershell_unused(ps_view(line + "\n")) == []

    def test_a_compound_assignment_alone_is_still_unused(self):
        assert len(powershell_unused(ps_view("$total = 0\n$total += 5\n"))) == 1

    def test_a_variable_that_reads_itself_is_used(self):
        assert powershell_unused(ps_view("$n = 1\n$n = $n + 1\n")) == []

    def test_one_finding_per_variable_even_when_it_is_assigned_twice(self):
        assert len(powershell_unused(ps_view("$x = 1\n$x = 2\n"))) == 1

    @pytest.mark.parametrize("reader", ["Get-Variable -Name x", "Invoke-Expression $cmd", "iex $cmd", "Set-Variable y 1"])
    def test_a_file_that_reads_variables_by_name_is_left_alone(self, reader):
        assert powershell_unused(ps_view(f"$x = 1\n{reader}\n")) == []

    def test_a_typed_declaration_is_not_judged(self):
        assert powershell_unused(ps_view("[int]$count = 0\n")) == []


class TestPythonUnusedNames:
    def test_an_import_that_nothing_uses_is_found(self):
        found = python_unused(py_view("import os\nimport json\n\nprint(json.dumps({}))\n"))
        assert [(f["title"], f["line_number"]) for f in found] == [("os is imported and never used", 1)]
        assert found[0]["source"] == "static" and found[0]["evidence"] == "import os"

    def test_an_import_that_is_used_is_not(self):
        assert python_unused(py_view("import os.path\nfrom typing import Any\n\ndef f(x: Any):\n    return os.getcwd()\n")) == []

    def test_from_imports_and_aliases(self):
        found = python_unused(py_view("from collections import OrderedDict as OD, deque\n\nx = deque()\n"))
        assert [f["title"] for f in found] == ["OD is imported and never used"]

    @pytest.mark.parametrize("code", [
        "import os  # noqa: F401\n",
        "from __future__ import annotations\n",
        "try:\n    import ujson as json\nexcept ImportError:\n    import json\n\nprint(json)\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from a import B\n\nx = 1\n",
        "from a import *\n",
        "import os\n__all__ = ['os']\n",
        "from a import Thing\n\ndef f() -> 'Thing':\n    return None\n",
        "from a import (\n    B,\n    C,  # noqa: F401\n)\n",  # the author silenced it on another line of the same statement
        "from a import B as B\nfrom c import D as D\n",  # `x as x` says "re-exported"
        "import os as os\n",
        "import pkg.sub.registry\n",  # made for what it registers
        "import sys\n\nif sys.version_info[0] == 2:\n    from urllib2 import urlopen\nelse:\n    from urllib.request import urlopen\n\nprint(sys.argv)\n",  # a compatibility import
    ])
    def test_imports_that_are_deliberate_are_left_alone(self, code):
        assert python_unused(py_view(code)) == []

    def test_an_import_in_a_function_or_class_is_judged_like_any_other(self):
        found = python_unused(py_view("def f():\n    import json\n    return 1\n"))
        assert [f["title"] for f in found] == ["json is imported and never used"]

    def test_a_noqa_on_a_local_variable_is_respected_on_any_line_of_the_statement(self):
        assert python_unused(py_view("def run(items):\n    task = start(items)  # NOQA\n    return items\n")) == []
        assert python_unused(py_view("def run(items):\n    task = start(\n        items)  # noqa: F841\n    return items\n")) == []

    def test_an_init_file_re_exports_so_it_is_not_judged(self):
        assert python_unused(py_view("from .a import b\n", path="pkg/__init__.py")) == []

    def test_an_import_that_was_already_there_is_not_this_pull_requests_to_fix(self):
        old = "import os\nx = 1\n"
        assert python_unused(py_view(old + "y = 2\n", old)) == []

    def test_a_local_variable_that_nothing_reads_is_found(self):
        code = "def run(items):\n    count = len(items)\n    return items\n"
        found = python_unused(py_view(code))
        assert [(f["title"], f["line_number"]) for f in found] == [("count is assigned and never used", 2)]
        assert "in run()" in found[0]["comment"]

    @pytest.mark.parametrize("code", [
        "def run(items):\n    count = len(items)\n    return count\n",
        "def run(items):\n    count = 0\n    count += 1\n    return items\n",
        "def run(items):\n    _ignored = len(items)\n    return items\n",
        "def run(items):\n    n = 3\n    return [x * n for x in items]\n",
        "def run(items):\n    n = 3\n    def inner():\n        return n\n    return inner\n",
        "def run(items):\n    n = 3\n    return locals()\n",
        "def run(items):\n    global n\n    n = 3\n    return items\n",
        "def run(items):\n    a, b = items\n    return items\n",
        "def run(items):\n    n = 3\n    return f'{n}'\n",
    ])
    def test_variables_that_are_read_or_deliberate_are_left_alone(self, code):
        assert python_unused(py_view(code)) == []

    def test_a_module_level_name_may_be_used_by_other_files(self):
        assert python_unused(py_view("SETTING = 3\n")) == []

    def test_a_file_that_does_not_parse_is_left_alone(self):
        assert python_unused(py_view("def broken(:\n    pass\n")) == []


class TestFileEncoding:
    def test_a_file_that_was_valid_utf8_and_no_longer_is(self):
        view = py_view("a = 1\nb = 'caf�'\n", "a = 1\nb = 'café'\n")
        new, old = decoded("a = 1\nb = 'caf�'\n", bad_line=2, bad_count=1), decoded("a = 1\nb = 'café'\n")
        found = encoding_findings(view, old, new)
        assert len(found) == 1
        f = found[0]
        assert (f["title"], f["severity"], f["category"], f["line_number"], f["source"]) == ("The file is no longer valid UTF-8", "warning", "correctness", 2, "static")
        assert "line 2" in f["comment"] and "Windows-1252" in f["comment"] and "�" in f["evidence"]

    def test_a_file_that_was_already_not_valid_utf8_is_not_blamed(self):
        view = py_view("b = 'caf�'\nc = 2\n", "b = 'caf�'\n")
        assert encoding_findings(view, decoded("b = 'caf�'\n", bad_line=1, bad_count=1), decoded("b = 'caf�'\nc = 2\n", bad_line=1, bad_count=1)) == []

    def test_text_that_carries_no_encoding_facts_is_not_judged(self):
        assert encoding_findings(py_view("a = 1\n", "a = 2\n"), "a = 2\n", "a = 1\n") == []

    def test_a_new_file_has_no_earlier_encoding_to_change(self):
        assert encoding_findings(py_view("a = 'x�'\n"), "", decoded("a = 'x�'\n", bad_line=1, bad_count=1)) == []

    def test_a_script_that_lost_its_byte_order_mark_while_holding_non_ascii_text(self):
        old, new = decoded("Write-Output 'a'\nWrite-Output 'café'\n", has_bom=True), decoded("Write-Output 'b'\nWrite-Output 'café'\n")
        found = encoding_findings(ps_view(str(new), str(old)), old, new)
        assert len(found) == 1
        assert found[0]["title"].startswith("The script lost its UTF-8 byte order mark") and "ANSI" in found[0]["comment"] and "line 2" in found[0]["failing_case"]
        assert found[0]["line_number"] == 1  # the nearest changed line: line 2 itself did not change

    def test_the_mark_does_not_matter_when_the_script_is_plain_ascii(self):
        old, new = decoded("Write-Output 'a'\n", has_bom=True), decoded("Write-Output 'b'\n")
        assert encoding_findings(ps_view(str(new), str(old)), old, new) == []

    def test_the_mark_only_matters_to_powershell(self):
        old, new = decoded("a = 'a'\nb = 'café'\n", has_bom=True), decoded("a = 'b'\nb = 'café'\n")
        assert encoding_findings(py_view(str(new), str(old)), old, new) == []


class _Response:
    def __init__(self, data: bytes, status: int = 200):
        self.status_code, self.headers, self._data = status, {"Content-Length": str(len(data))}, data

    def iter_content(self, size):
        yield self._data

    def close(self):
        pass


class TestHowTheClientReadsAFile:
    read = staticmethod(AzureDevOpsClient._read_text)

    def test_valid_utf8_has_no_bad_byte(self):
        text, why = self.read(_Response("café\n".encode("utf-8")), 1000)
        assert why is None and text == "café\n" and (text.has_bom, text.bad_byte_line, text.bad_byte_count) == (False, None, 0)

    def test_a_byte_order_mark_is_noted_and_removed_from_the_text(self):
        text, _ = self.read(_Response(b"\xef\xbb\xbfabc\n"), 1000)
        assert text == "abc\n" and text.has_bom and text.bad_byte_line is None

    def test_windows_1252_text_is_noted_with_its_line(self):
        text, _ = self.read(_Response(b"line one\nline two\ncaf\xe9\nlast\n"), 1000)
        assert text.bad_byte_line == 3 and text.bad_byte_count == 1 and "caf�" in text and not text.has_bom

    def test_a_replacement_character_the_file_really_has_is_not_a_bad_byte(self):
        text, _ = self.read(_Response("ok � ok\n".encode("utf-8")), 1000)
        assert text.bad_byte_line is None and text.bad_byte_count == 0

    def test_a_real_one_next_to_a_bad_byte_is_not_counted_as_one(self):
        text, _ = self.read(_Response("�".encode("utf-8") + b" caf\xe9\n"), 1000)
        assert text.bad_byte_count == 1

    @pytest.mark.parametrize("response,max_bytes,expected", [(_Response(b"a\x00b"), 1000, "binary"), (_Response(b"x" * 50), 10, "too_large"), (_Response(b"x", 404), 1000, "unreadable")])
    def test_what_cannot_be_read(self, response, max_bytes, expected):
        assert self.read(response, max_bytes) == (None, expected)


class TestMarkdownTables:
    TABLE = "| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n"

    def test_a_row_with_a_cell_missing(self):
        found = markdown_tables(md_view(self.TABLE + "| 4 | 5 |\n"))
        assert [(f["title"], f["line_number"], f["severity"]) for f in found] == [("Table row has 2 cells, the header has 3", 4, "warning")]
        assert "empty cell" in found[0]["comment"] and found[0]["source"] == "static"

    def test_a_row_with_a_cell_too_many(self):
        found = markdown_tables(md_view(self.TABLE + "| 4 | 5 | 6 | 7 |\n"))
        assert len(found) == 1 and "extra cell is dropped" in found[0]["comment"]

    def test_a_table_whose_rows_all_match_is_fine(self):
        assert markdown_tables(md_view(self.TABLE + "| 4 | 5 | 6 |\n")) == []

    def test_a_row_without_its_leading_pipe_ends_the_table_so_it_is_not_judged(self):
        assert markdown_tables(md_view("| a | b |\n|--|--|\n1 | 2 | 3\n")) == []

    def test_pipes_in_code_or_escaped_are_not_cell_separators(self):
        assert markdown_tables(md_view("| a | b |\n|---|---|\n| `x | y` | 2 |\n| c \\| d | 2 |\n")) == []

    def test_a_table_inside_a_code_block_is_not_one(self):
        assert markdown_tables(md_view("```\n| a | b |\n|---|---|\n| 1 |\n```\n")) == []

    def test_lines_that_only_start_with_a_pipe_are_not_a_table(self):
        assert markdown_tables(md_view("| not a table\n| still not\n| nor this\n")) == []

    def test_only_rows_this_pull_request_added_are_judged(self):
        old = self.TABLE + "| 4 | 5 |\n"
        assert markdown_tables(md_view(old + "\ntext\n", old)) == []


class TestAllTheChecks:
    def test_each_language_gets_its_own_checks(self):
        assert [f["title"] for f in static_findings(ps_view("$x = 1\n"))] == ["$x is assigned and never used"]
        assert [f["title"] for f in static_findings(py_view("import os\n"))] == ["os is imported and never used"]
        assert [f["title"] for f in static_findings(md_view("| a |\n|--|\n| 1 | 2 |\n"))] == ["Table row has 2 cells, the header has 1"]
        assert static_findings(build_view("a.yml", "YAML", "add", "", "a: 1\n")) == []

    def test_a_check_that_fails_never_breaks_the_review(self, monkeypatch):
        def boom(view):
            raise RuntimeError("bug")

        monkeypatch.setattr(pr_static, "powershell_unused", boom)
        assert static_findings(ps_view("$x = 1\n")) == []

    def test_there_is_a_limit(self):
        code = "".join(f"$v{n} = {n}\n" for n in range(20))
        assert len(static_findings(ps_view(code))) == pr_static.MAX_STATIC_FINDINGS
