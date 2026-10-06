"""What the second check may look up in the repository, the C# version a project states, and the chat that can call tools."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app.services import pr_lookup
from app.services.llm_util import chat_json_with_tools
from app.services.pr_lookup import TOOLS, RepoReader, ToolBelt, csharp_facts, default_csharp
from pr_support import CSPROJ, FakeAdo


def reader(files=None, changed=(), **kwargs):
    ado = FakeAdo(repo_files=files or {}, **kwargs)
    return RepoReader(ado, "proj", "repo", "c" * 40, list(changed)), ado


class TestDefaultCSharpVersion:
    """Microsoft, Language versioning - C# reference, section Defaults."""

    @pytest.mark.parametrize("framework,version", [
        ("net11.0", "15"), ("net10.0", "14"), ("net9.0", "13"), ("net8.0", "12"), ("net7.0", "11"), ("net6.0", "10"), ("net5.0", "9.0"),
        ("net8.0-windows", "12"), ("NET8.0", "12"),
        ("netcoreapp3.1", "8.0"), ("netcoreapp2.1", "7.3"), ("netstandard2.1", "8.0"), ("netstandard2.0", "7.3"), ("netstandard1.6", "7.3"),
        ("net48", "7.3"), ("net472", "7.3"), ("net461", "7.3"),
    ])
    def test_the_table(self, framework, version):
        assert default_csharp(framework) == version

    @pytest.mark.parametrize("framework", ["net12.0", "monoandroid", "", "$(Tfm)"])
    def test_what_the_docs_do_not_list(self, framework):
        assert default_csharp(framework) is None


class TestProjectFacts:
    def test_net8_means_c12_and_newer_syntax_is_valid(self):
        r, _ = reader({"src/Api/Api.csproj": CSPROJ.format(tfm="net8.0"), "src/Api/Models/Item.cs": "class Item {}"})
        facts = csharp_facts(r, "src/Api/Models/Item.cs")
        assert "src/Api/Api.csproj" in facts and "net8.0 (C# 12)" in facts and "default C# language version follows the target framework" in facts
        assert "collection expressions" in facts and "do not report them as invalid" in facts

    def test_an_older_framework_does_not_claim_newer_syntax_is_valid(self):
        r, _ = reader({"Api.csproj": CSPROJ.format(tfm="net6.0")})
        facts = csharp_facts(r, "Models/Item.cs")
        assert "net6.0 (C# 10)" in facts and "C# 10 or earlier is valid" in facts and "collection expressions" not in facts

    def test_several_target_frameworks_are_all_listed_and_the_oldest_decides(self):
        r, _ = reader({"Lib/Lib.csproj": CSPROJ.format(tfm="net8.0;netstandard2.0")})
        facts = csharp_facts(r, "Lib/A.cs")
        assert "net8.0 (C# 12)" in facts and "netstandard2.0 (C# 7.3)" in facts and "C# 7.3 or earlier is valid" in facts and "collection expressions" not in facts

    def test_a_language_version_set_in_the_project_overrides_the_default(self):
        r, _ = reader({"Api.csproj": CSPROJ.format(tfm="net8.0").replace("</PropertyGroup>", "<LangVersion>10.0</LangVersion></PropertyGroup>")})
        facts = csharp_facts(r, "A.cs")
        assert "LangVersion to 10.0, which overrides that default" in facts and "collection expressions" not in facts

    def test_the_nearest_project_above_the_file_is_used(self):
        r, _ = reader({"A/A.csproj": CSPROJ.format(tfm="net6.0"), "A/B/B.csproj": CSPROJ.format(tfm="net8.0")})
        assert "A/B/B.csproj" in csharp_facts(r, "A/B/C/x.cs") and "A/A.csproj" in csharp_facts(r, "A/y.cs")

    def test_a_framework_set_by_a_property_is_not_guessed(self):
        r, _ = reader({"Api.csproj": CSPROJ.format(tfm="$(AppTfm)")})
        assert "set by a property" in csharp_facts(r, "A.cs") and "C# 1" not in csharp_facts(r, "A.cs")

    def test_a_directory_build_props_can_supply_what_the_project_leaves_out(self):
        r, _ = reader({"src/Api/Api.csproj": "<Project Sdk=\"x\"></Project>", "Directory.Build.props": CSPROJ.format(tfm="net9.0")})
        facts = csharp_facts(r, "src/Api/A.cs")
        assert "net9.0 (C# 13)" in facts and "set in Directory.Build.props" in facts

    def test_a_project_with_no_framework_anywhere_says_it_does_not_know(self):
        r, _ = reader({"Api.csproj": "<Project Sdk=\"x\"></Project>"})
        assert "does not state a target framework" in csharp_facts(r, "A.cs")

    def test_no_project_file_means_no_facts(self):
        r, _ = reader({"readme.md": "x"})
        assert csharp_facts(r, "A.cs") == ""

    def test_a_project_that_cannot_be_read_means_no_facts(self):
        r, _ = reader({"Api.csproj": {"reason": "unreadable"}})
        assert csharp_facts(r, "A.cs") == ""


class TestFindingAndReadingFiles:
    FILES = {"src/Api/Api.csproj": "<x/>", "src/Api/appsettings.json": '{\n  "Refresh": {\n    "Seconds": 60\n  }\n}\n', "src/Api/Program.cs": "\n".join(f"line {n}" for n in range(1, 401)), "docs/readme.md": "hello"}

    def test_find_lists_the_paths_that_contain_the_text(self):
        r, _ = reader(self.FILES)
        text = r.find("APPSETTINGS")
        assert "1 file(s)" in text and "src/Api/appsettings.json" in text and "Api.csproj" not in text

    def test_find_says_when_nothing_matches_and_when_the_tree_is_unknown(self):
        assert "No file path contains 'zzz'" in reader(self.FILES)[0].find("zzz")
        r, _ = reader(self.FILES, changed=["src/Api/Program.cs"], tree_unreadable=True)
        assert "could not be read" in r.find("Program") and "src/Api/Program.cs" in r.find("Program")

    def test_find_is_limited(self):
        r, _ = reader({f"f{n:03d}.txt": "x" for n in range(100)})
        text = r.find("f")
        assert "100 file(s)" in text and "and 60 more" in text

    def test_read_numbers_the_lines_and_says_where_to_go_on(self):
        r, _ = reader(self.FILES)
        text = r.read_lines("src/Api/Program.cs")
        assert text.startswith("src/Api/Program.cs:") and "    1 | line 1" in text and "  150 | line 150" in text and "line 151" not in text
        assert "lines 1-150 of 400" in text and "from_line=151" in text
        assert "  151 | line 151" in r.read_lines("src/Api/Program.cs", 151)
        assert "lines 391-400 of 400" in r.read_lines("/src/Api/Program.cs", "391")  # a leading slash and a number given as text are understood

    def test_read_of_a_missing_file_or_a_line_past_the_end(self):
        r, _ = reader(self.FILES)
        assert "does not exist at this commit" in r.read_lines("nope.cs")
        assert "has 400 line(s); nothing from line 999" in r.read_lines("src/Api/Program.cs", 999)
        assert r.read_lines("src/Api/Program.cs", "abc").count("line 1") >= 1  # nonsense start line falls back to the first line

    def test_why_a_file_cannot_be_read_is_said(self):
        r, _ = reader({"big.bin": {"reason": "too_large"}, "img.dat": {"reason": "binary"}})
        assert "larger than the limit" in r.read_lines("big.bin") and "not a text file" in r.read_lines("img.dat")

    def test_each_file_is_fetched_once(self):
        r, ado = reader(self.FILES)
        for _ in range(3):
            r.read_lines("src/Api/Api.csproj")
        assert ado.item_calls == ["/src/Api/Api.csproj"]

    def test_the_number_of_reads_for_one_review_is_capped(self, monkeypatch):
        monkeypatch.setattr(pr_lookup, "MAX_FETCHES", 2)
        r, _ = reader({"a.cs": "1", "b.cs": "2", "c.cs": "3"})
        assert "1" in r.read_lines("a.cs") and "2" in r.read_lines("b.cs")
        assert "limit of file reads" in r.read_lines("c.cs")
        assert "1" in r.read_lines("a.cs")  # what was read before is still there


class TestSearching:
    FILES = {
        "src/Api/appsettings.json": '{\n  "Widgets": {\n    "PollSeconds": 60\n  }\n}\n',
        "src/Api/Options.cs": "public int PollSeconds { get; set; }\n",
        "src/Other/Thing.cs": "// unrelated\n",
        "node_modules/pkg/index.js": "PollSeconds",
        "src/Api/bin/Debug/x.json": "PollSeconds",
        "src/logo.png": "PollSeconds",
    }

    def test_matching_lines_come_back_with_path_and_line_number_and_the_coverage(self):
        r, _ = reader(self.FILES)
        text = r.search("pollseconds")  # the search ignores case
        assert "src/Api/appsettings.json:3:" in text and "src/Api/Options.cs:1:" in text and "2 file(s) contain it" in text
        assert "Searched 3 of 3 candidate file(s)" in text and "does not show that the text is absent" not in text

    def test_folders_that_are_build_output_and_non_text_files_are_not_searched(self):
        text = reader(self.FILES)[0].search("PollSeconds")
        assert "node_modules" not in text and "/bin/" not in text and "logo.png" not in text

    def test_no_match_in_a_complete_search_says_so_plainly(self):
        text = reader(self.FILES)[0].search("OldName")
        assert "no line contains 'OldName'" in text and "does not show that the text is absent" not in text

    def test_no_match_in_a_partial_search_does_not_claim_absence(self, monkeypatch):
        monkeypatch.setattr(pr_lookup, "MAX_SEARCH_FILES", 2)
        r, _ = reader({f"src/f{n}.cs": "x" for n in range(5)})
        text = r.search("OldName")
        assert "Searched 2 of 5 candidate file(s)" in text and "does not show that the text is absent" in text

    def test_when_the_tree_cannot_be_read_only_the_pull_requests_files_are_searched_and_it_says_so(self):
        r, _ = reader({"src/Api/Options.cs": "PollSeconds"}, changed=["src/Api/Options.cs"], tree_unreadable=True)
        text = r.search("OldName")
        assert "file list could not be read" in text and "does not show that the text is absent" in text
        assert "Options.cs:1" in r.search("PollSeconds")

    def test_the_files_of_the_pull_request_and_the_nearest_ones_come_first(self, monkeypatch):
        monkeypatch.setattr(pr_lookup, "MAX_SEARCH_FILES", 1)
        files = {"far/away/a.cs": "needle", "src/Api/near.cs": "needle", "src/Other/changed.cs": "needle"}
        r, _ = reader(files, changed=["src/Other/changed.cs"])
        assert "changed.cs:1" in r.search("needle", near="src/Api/Options.cs")
        r2, _ = reader(files)
        assert "near.cs:1" in r2.search("needle", near="src/Api/Options.cs")

    def test_path_filter(self):
        text = reader(self.FILES)[0].search("PollSeconds", path_contains="appsettings")
        assert "appsettings.json:3" in text and "Options.cs" not in text and "Searched 1 of 1" in text

    def test_files_already_read_are_searched_without_another_fetch(self):
        r, ado = reader(self.FILES)
        r.search("PollSeconds")
        calls = len(ado.item_calls)
        r.search("get; set")
        assert len(ado.item_calls) == calls

    def test_the_number_of_matches_shown_is_limited(self, monkeypatch):
        r, _ = reader({"a.cs": "\n".join("hit" for _ in range(40))})
        text = r.search("hit")
        assert text.count("a.cs:") == pr_lookup.MAX_MATCHES and f"only the first {pr_lookup.MAX_MATCHES} matches" in text

    def test_a_search_needs_something_to_search_for(self):
        assert "at least two characters" in reader(self.FILES)[0].search(" ")


class TestTheTools:
    def test_the_three_tools_are_offered_and_only_read(self):
        assert [t["function"]["name"] for t in TOOLS] == ["find_files", "read_file", "search_code"]
        assert all(t["function"]["parameters"]["required"] for t in TOOLS)
        assert not any(word in json.dumps(TOOLS).lower() for word in ("write", "delete", "post", "comment on"))

    def test_what_was_looked_at_is_noted_once_each(self):
        r, _ = reader({"a.cs": "x", "b/Api.csproj": "y"})
        belt = ToolBelt(r)
        belt.run("read_file", {"path": "a.cs"})
        belt.run("read_file", {"path": "/a.cs"})
        belt.run("search_code", {"text": "needle"})
        belt.run("find_files", {"contains": "csproj"})
        assert belt.looked == ["read a.cs", 'searched the code for "needle"', 'searched file names for "csproj"']

    def test_an_unknown_tool_or_bad_arguments_get_an_answer_not_a_crash(self):
        belt = ToolBelt(reader({"a.cs": "x"})[0])
        assert "Unknown tool 'delete_file'" in belt.run("delete_file", {"path": "a.cs"})
        assert "Give some text" in belt.run("find_files", {})
        assert "does not exist" in belt.run("read_file", {"path": None}) or "Give" in belt.run("read_file", {"path": None})
        assert "Give at least two" in belt.run("search_code", "not a dict")

    def test_a_failing_lookup_is_reported_without_details(self, monkeypatch):
        r, _ = reader({"a.cs": "x"})
        monkeypatch.setattr(r, "find", lambda text: (_ for _ in ()).throw(RuntimeError("secret internals")))
        assert ToolBelt(r).run("find_files", {"contains": "a"}) == "That lookup failed."

    def test_a_long_answer_is_cut(self):
        r, _ = reader({"a.cs": "\n".join("x" * 300 for _ in range(100))})
        text = ToolBelt(r).run("read_file", {"path": "a.cs"})
        assert len(text) <= pr_lookup.MAX_RESULT_CHARS + 20 and text.endswith("(cut)")

    def test_after_the_deadline_no_lookup_is_made(self):
        r, ado = reader({"a.cs": "x"})
        belt = ToolBelt(r, deadline=time.monotonic() - 1)
        assert "no more lookups are possible" in belt.run("read_file", {"path": "a.cs"})
        assert ado.item_calls == [] and belt.looked == []


def message(content=None, calls=()):
    tool_calls = [SimpleNamespace(id=f"c{n}", function=SimpleNamespace(name=name, arguments=arguments)) for n, (name, arguments) in enumerate(calls, 1)]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or None))])


class ScriptedModel:
    """A client that answers from a list and remembers what it was asked."""

    def __init__(self, replies):
        self.deployment, self.replies, self.requests = "fake", list(replies), []
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        return self.replies.pop(0)


class TestChatThatCallsTools:
    def test_a_tool_is_called_and_its_answer_goes_back_to_the_model(self):
        model = ScriptedModel([message(calls=[("read_file", '{"path": "a.cs"}')]), message('{"ok": true}')])
        seen = []
        answer = chat_json_with_tools(model, "system", "user", TOOLS, lambda name, args: seen.append((name, args)) or "FILE TEXT")
        assert answer == {"ok": True} and seen == [("read_file", {"path": "a.cs"})]
        second = model.requests[1]["messages"]
        assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
        assert second[2]["tool_calls"][0]["function"]["name"] == "read_file" and second[3] == {"role": "tool", "tool_call_id": "c1", "content": "FILE TEXT"}
        assert model.requests[0]["tools"] == TOOLS and "tool_choice" not in model.requests[0]

    def test_an_answer_with_no_tool_call_is_returned_at_once(self):
        model = ScriptedModel([message('{"a": 1}')])
        assert chat_json_with_tools(model, "s", "u", TOOLS, lambda n, a: "") == {"a": 1} and len(model.requests) == 1

    def test_the_last_turn_takes_no_tool_call_and_must_answer_in_json(self):
        model = ScriptedModel([message(calls=[("find_files", '{"contains": "x"}')]), message(calls=[("find_files", '{"contains": "y"}')]), message('{"done": true}')])
        assert chat_json_with_tools(model, "s", "u", TOOLS, lambda n, a: "r", max_turns=3) == {"done": True}
        last = model.requests[-1]
        assert last["tool_choice"] == "none" and last["response_format"] == {"type": "json_object"}
        assert "tool_choice" not in model.requests[0] and "tool_choice" not in model.requests[1]

    def test_a_model_that_still_calls_tools_on_the_last_turn_gives_no_answer(self):
        model = ScriptedModel([message(calls=[("find_files", "{}")]), message(calls=[("find_files", "{}")])])
        with pytest.raises(ValueError, match="no answer"):
            chat_json_with_tools(model, "s", "u", TOOLS, lambda n, a: "r", max_turns=2)

    @pytest.mark.parametrize("arguments", ["not json", "[1, 2]", "", "null"])
    def test_arguments_that_are_not_an_object_become_an_empty_one(self, arguments):
        model = ScriptedModel([message(calls=[("find_files", arguments)]), message("{}")])
        seen = []
        chat_json_with_tools(model, "s", "u", TOOLS, lambda name, args: seen.append(args) or "r")
        assert seen == [{}]

    def test_several_calls_in_one_turn_are_all_answered(self):
        model = ScriptedModel([message(calls=[("read_file", '{"path": "a"}'), ("read_file", '{"path": "b"}')]), message("{}")])
        chat_json_with_tools(model, "s", "u", TOOLS, lambda name, args: args["path"].upper())
        tools = [m for m in model.requests[1]["messages"] if m["role"] == "tool"]
        assert [(m["tool_call_id"], m["content"]) for m in tools] == [("c1", "A"), ("c2", "B")]
