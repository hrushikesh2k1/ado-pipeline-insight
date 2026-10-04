"""IRP generation: exactly the three sections of the organisation's example and a 3-column Remediation table (STEPS, ACTIONS, ADDITIONAL INFO).

The fixtures are synthetic but shaped like the real example: a blank table header row with the real column names in the first body row,
very long table cells (the whole table is far longer than the old 5,000-character cap) and ten more sections after Remediation Steps."""
from types import SimpleNamespace

import pytest

from app.services import irp_format as fmt
from app.services.irp_service import IrpService

HEADER = "| **STEPS** | **ACTIONS** | **ADDITIONAL INFO** |"


def long_example(rows: int = 14) -> str:
    cases = "\n".join(f"| **Case {i}** : Failure mode {i} | " + "1. Check the thing carefully. " * 30 + f"SENTINEL_ROW_{i} | note {i} |" for i in range(1, rows + 1))
    return f"""# VPN \\- Tunnel disconnected

# Alert Details

| **Alert** | VPN - Tunnel disconnected |
| --- | --- |
| **Description** | *This alert is designed to trigger when/if the tunnel drops.* |
| **Severity** | Critical |
| **Source** | Log |
| **Root Cause** | - **Case 1 : ** Deleted - **Case 2 : ** PSK mismatch |
| **Product** | Common |

# Prerequisites

# Remediation Steps

|  |  |  |
| --- | --- | --- |
| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |
| **Check **the status | 1. Review the **Query Result**. | Ref : |
{cases}
| Health Check | Repeat the check. | |

## Testing Scenarios

| **Scenario** | **Steps** |
| --- | --- |
| **Deleting** | 1. Via the Portal |

## Overview

*text*

## RCA & Mitigation

| **Scenario** | **Application Impact** | **Alert Latency (min)** | **Related alerts** | **Response Plan** |
| --- | --- | --- | --- | --- |
| a | b | 4 mins | c | d |

## Lessons learned

- one
"""


def headings(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith("#")]


def table_rows(markdown: str) -> list[list[str]]:
    start = markdown.index("# Remediation Steps")
    return [fmt.split_table_row(line) for line in markdown[start:].splitlines() if line.startswith("|")]


class TestWhatTheModelIsGiven:
    def test_the_skeleton_is_the_start_of_the_example_through_its_remediation_section(self):
        skeleton, cut = fmt.extract_skeleton(long_example())
        assert not cut and "# Alert Details" in skeleton and "# Remediation Steps" in skeleton
        assert "Testing Scenarios" not in skeleton and "RCA & Mitigation" not in skeleton and "Lessons learned" not in skeleton

    def test_a_table_far_longer_than_the_old_5000_character_cap_arrives_whole(self):
        skeleton, _ = fmt.extract_skeleton(long_example())
        assert len(skeleton) > 8000 and "SENTINEL_ROW_14" in skeleton and "| Health Check |" in skeleton

    def test_an_example_without_a_remediation_section_is_sent_whole(self):
        text = "# Title\n\nsome text\n\n## Other\n\nmore"
        assert fmt.extract_skeleton(text) == (text, False)

    def test_headings_inside_code_fences_are_not_section_boundaries(self):
        text = "# Remediation Steps\n\n```\n## not a heading\n```\n\n| a | b |\n\n## Next"
        assert "not a heading" in fmt.extract_skeleton(text)[0] and "## Next" not in fmt.extract_skeleton(text)[0]

    def test_a_very_long_example_is_cut_at_the_limit_and_says_so(self):
        text, cut = fmt.extract_skeleton("# Remediation Steps\n\n" + "x" * 500, limit=100)
        assert len(text) == 100 and cut

    @pytest.mark.parametrize("heading,expected", [
        ("Alert Details", fmt.SECTION_ALERT), ("Alert Overview", fmt.SECTION_ALERT), ("**Alert Details:**", fmt.SECTION_ALERT),
        ("Prerequisites", fmt.SECTION_PREREQUISITES), ("Prerequisite", fmt.SECTION_PREREQUISITES),
        ("Remediation Steps", fmt.SECTION_REMEDIATION), ("Remediation Steps:", fmt.SECTION_REMEDIATION),
        ("Remediation Overview", None), ("Overview", None), ("Alert Properties", None), ("Testing Scenarios", None),
    ])
    def test_which_headings_are_the_three_sections(self, heading, expected):
        assert fmt.section_key(heading) == expected

    def test_the_prompt_states_the_exact_sections_and_columns(self):
        prompt = fmt.IRP_SYSTEM_PROMPT
        assert HEADER in prompt and "EXACTLY 3 columns" in prompt and "Never add a 4th column" in prompt
        assert all(f'"{name}"' in prompt for name in fmt.SECTIONS) and "about 10 rows" in prompt and "no hard limit" in prompt

    def test_the_user_message_carries_the_whole_skeleton_and_labels_the_template_as_guidelines(self):
        data = {"alert_name": "A", "severity": "Sev-1", "cvrd": "", "target_resource": "r", "trigger_condition": "t", "owning_team": "o",
                "environment": "Production", "alert_output_columns": "", "alert_details": "", "arm_template_context": "", "additional_notes": ""}
        skeleton, _ = fmt.extract_skeleton(long_example())
        message = fmt.build_user_prompt(data, skeleton, "TEMPLATE BODY " * 10)
        assert "SENTINEL_ROW_14" in message and "<irp_example>" in message and "</irp_example>" in message
        assert "WRITING GUIDELINES" in message and "follow the RULES and the example" in message and "TEMPLATE BODY" in message
        assert "Severity: Sev-1" in message
        bare = fmt.build_user_prompt(data, "", "")
        assert "irp_example" not in bare and "irp_template" not in bare


class TestEnforcingTheSkeleton:
    def test_extra_sections_are_removed_and_the_title_is_the_alert_name(self):
        out, problems = fmt.normalize_irp_markdown(long_example(), "My Alert")
        assert headings(out) == ["# My Alert", "# Alert Details", "# Prerequisites", "# Remediation Steps"] and problems == []
        assert "Testing Scenarios" not in out and "RCA & Mitigation" not in out and "Lessons learned" not in out

    def test_the_header_is_exactly_the_three_names_and_the_blank_header_row_of_the_example_is_not_copied(self):
        out, _ = fmt.normalize_irp_markdown(long_example(), "A")
        rows = table_rows(out)
        assert rows[0] == ["**STEPS**", "**ACTIONS**", "**ADDITIONAL INFO**"] and all(c.strip("-") == "" for c in rows[1])
        assert all(len(r) == 3 for r in rows) and len(rows) == 2 + 1 + 14 + 1  # header, divider, first row, 14 cases, health check
        assert not any(r[0].strip("* ") == "STEPS" for r in rows[2:])  # the old names row is gone from the body

    def test_a_fourth_expected_outcome_column_is_folded_into_additional_info(self):
        text = ("# Remediation Steps\n\n| **Steps** | **Actions** | **Expected Outcome** | **Additional Comments** |\n| --- | --- | --- | --- |\n"
                "| Check | Run `az x` | Status is Connected | See guide |\n")
        out, _ = fmt.normalize_irp_markdown(text, "A")
        rows = table_rows(out)
        assert rows[0] == ["**STEPS**", "**ACTIONS**", "**ADDITIONAL INFO**"] and len(rows[2]) == 3
        assert rows[2][0] == "Check" and rows[2][1] == "Run `az x`"
        assert rows[2][2] == "**Expected Outcome:** Status is Connected<br>**Additional Comments:** See guide"

    def test_the_old_column_names_are_renamed(self):
        text = "# Remediation Steps\n\n| **STEPS** | **ACTION** | **ADDITIONAL COMMENTS** |\n| --- | --- | --- |\n| a | b | c |\n"
        assert table_rows(fmt.normalize_irp_markdown(text, "A")[0])[0] == ["**STEPS**", "**ACTIONS**", "**ADDITIONAL INFO**"]

    def test_unescaped_pipes_in_a_query_are_folded_back_into_the_actions_cell(self):
        text = ("# Remediation Steps\n\n| **STEPS** | **ACTIONS** | **ADDITIONAL INFO** |\n| --- | --- | --- |\n"
                "| Check logs | AzureDiagnostics | where Level == 1 | project TimeGenerated | Expected: rows |\n")
        row = table_rows(fmt.normalize_irp_markdown(text, "A")[0])[2]
        assert len(row) == 3 and row[0] == "Check logs" and row[2] == "Expected: rows"
        assert row[1] == "AzureDiagnostics \\| where Level == 1 \\| project TimeGenerated"

    def test_pipes_in_backticks_pre_blocks_and_escaped_pipes_do_not_split_cells(self):
        assert len(fmt.split_table_row("| a | `x | y` | c |")) == 3
        assert len(fmt.split_table_row("| a | <pre><code>x | y</code></pre> | c |")) == 3
        assert fmt.split_table_row("| a | x \\| y | c |") == ["a", "x \\| y", "c"]

    def test_a_row_that_merely_mentions_steps_or_actions_is_not_mistaken_for_the_column_names(self):
        text = "# Remediation Steps\n\n| **STEPS** | **ACTIONS** | **ADDITIONAL INFO** |\n| --- | --- | --- |\n| Step 2: take action | Run it | |\n"
        assert table_rows(fmt.normalize_irp_markdown(text, "A")[0])[2][0] == "Step 2: take action"

    def test_a_code_fence_around_the_answer_and_chatter_before_it_are_dropped(self):
        wrapped = "```markdown\nSure, here is the IRP:\n\n# Alert Details\n\n| **Alert** | x |\n| --- | --- |\n```"
        out, _ = fmt.normalize_irp_markdown(wrapped, "A")
        assert "```" not in out and "Sure" not in out and headings(out)[1] == "# Alert Details"

    def test_the_authoring_checklist_and_everything_after_the_sections_is_dropped(self):
        text = long_example() + "\n# IRP Authoring Checklist (with Examples)\n\n* [ ] Use the latest template\n"
        out, _ = fmt.normalize_irp_markdown(text, "A")
        assert "Authoring" not in out and "latest template" not in out

    def test_alert_overview_is_accepted_and_written_as_alert_details(self):
        out, problems = fmt.normalize_irp_markdown("## Alert Overview\n\n| **Alert** | x |\n| --- | --- |\n\n## Remediation Steps\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n", "A")
        assert "# Alert Details" in out and "Alert Overview" not in out and problems == []

    def test_a_sub_heading_inside_prerequisites_becomes_a_bold_line_so_it_cannot_read_as_another_section(self):
        out, _ = fmt.normalize_irp_markdown("# Prerequisites\n\n### Access\n\n- Reader role\n\n# Remediation Steps\n", "A")
        assert "**Access**" in out and "### Access" not in out and "- Reader role" in out
        assert headings(out) == ["# A", "# Alert Details", "# Prerequisites", "# Remediation Steps"]

    def test_comment_lines_inside_a_code_block_in_prerequisites_are_not_touched(self):
        out, _ = fmt.normalize_irp_markdown("# Prerequisites\n\n```bash\n# sign in first\naz login\n```\n\n# Remediation Steps\n", "A")
        assert "# sign in first" in out and "**sign in first**" not in out


SECTIONS_BASE = """# Alert Details

| **Alert** | x |
| --- | --- |
| **Severity** | Sev-1 |

# Prerequisites

- Reader role

# Remediation Steps

| **STEPS** | **ACTIONS** | **ADDITIONAL INFO** |
| --- | --- | --- |
| Check status | Run `az x` | Connected |
"""


class TestNoOtherSections:
    """The IRP has the title and three sections. However the model writes an extra one, it does not get through."""

    @pytest.mark.parametrize("extra,words", [
        ("\n#### **Post-Incident Analysis (Optional):**\n\n- **Who/Why deleted:** check the activity log\n", ("Post-Incident", "Who/Why")),  # the template's own heading style
        ("\n### Testing Scenarios\n\n| **Scenario** | **Steps** |\n| --- | --- |\n| a | b |\n", ("Testing Scenarios", "| a | b |")),
        ("\n**Post-Incident Analysis:**\n\n- How to avoid this in future\n", ("Post-Incident", "How to avoid")),
        ("\nLessons learned:\n\n- one\n", ("Lessons learned",)),
        ("\n## Lessons learned\n\n- one\n", ("Lessons learned",)),
        ("\n# IRP Authoring Checklist (with Examples)\n\n* [ ] Use the latest template\n", ("Authoring", "latest template")),
        ("\n| **Scenario** | **Steps** |\n| --- | --- |\n| a | b |\n", ("| a | b |",)),  # a second table with no heading
        ("\nNote: if this fails, escalate to the network team.\n", ("escalate",)),  # a trailing note under the table
    ])
    def test_extra_sections_after_the_remediation_table_are_dropped(self, extra, words):
        out, problems = fmt.normalize_irp_markdown(SECTIONS_BASE + extra, "A")
        assert headings(out) == ["# A", "# Alert Details", "# Prerequisites", "# Remediation Steps"]
        assert not any(word in out for word in words) and problems == []
        assert table_rows(out)[2] == ["Check status", "Run `az x`", "Connected"]  # the real content is untouched

    def test_an_extra_section_between_the_three_is_dropped_too(self):
        text = SECTIONS_BASE.replace("# Prerequisites", "#### Alert Properties\n\n| **Severity:** | Critical |\n| --- | --- |\n\n# Prerequisites")
        out, _ = fmt.normalize_irp_markdown(text, "A")
        assert "Alert Properties" not in out and "Critical" not in out

    def test_alert_details_keeps_only_its_table(self):
        text = SECTIONS_BASE.replace("| **Severity** | Sev-1 |\n", "| **Severity** | Sev-1 |\n\nSee also the overview below.\n")
        out, _ = fmt.normalize_irp_markdown(text, "A")
        assert "See also" not in out and "| **Severity** | Sev-1 |" in out

    def test_an_extra_section_name_in_a_code_block_or_a_bullet_is_not_mistaken_for_a_section(self):
        text = SECTIONS_BASE.replace("- Reader role", "- Reader role\n- References: see the access package\n\n```\nLessons learned:\n```")
        out, _ = fmt.normalize_irp_markdown(text, "A")
        assert "- References: see the access package" in out and "Lessons learned:" in out

    def test_the_prompt_tells_the_model_not_to_write_the_templates_other_sections(self):
        assert "do not write it" in fmt.IRP_SYSTEM_PROMPT and "Nothing may follow" in fmt.IRP_SYSTEM_PROMPT

    @pytest.mark.parametrize("label,expected", [
        ("#### **Post-Incident Analysis (Optional):**", True), ("**Lessons learned**", True), ("References:", True), ("## Testing Scenarios", True),
        ("# IRP Authoring Checklist (with Examples)", True), ("RCA & Mitigation", True), ("Overview", True),
        ("# Alert Details", False), ("Alert Overview", False), ("Remediation Steps", False), ("Prerequisites:", False),
        ("- References: see the guide", False), ("Run the references check", False), ("1. Overview of the access", False),
    ])
    def test_which_lines_name_an_unwanted_section(self, label, expected):
        assert fmt.is_extra_section_label(label) is expected

    def test_missing_pieces_are_reported_not_hidden(self):
        out, problems = fmt.normalize_irp_markdown("# Alert Details\n\n| **Alert** | x |\n| --- | --- |\n", "A")
        assert headings(out) == ["# A", "# Alert Details", "# Prerequisites", "# Remediation Steps"]
        assert any("Remediation Steps" in p for p in problems)
        out, problems = fmt.normalize_irp_markdown("# Remediation Steps\n\nno table here\n", "A")
        assert any("no table" in p for p in problems)
        assert fmt.normalize_irp_markdown("   ", "A") == ("", ["The generator returned no text."])

    def test_normalising_twice_changes_nothing(self):
        once, _ = fmt.normalize_irp_markdown(long_example(), "A")
        assert fmt.normalize_irp_markdown(once, "A")[0] == once


class FakeCompletions:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


def service_with(completions):
    client = SimpleNamespace(deployment="d", client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    return IrpService(openai_client=client)


BAD_MODEL_REPLY = """# VPN Tunnel Disconnected

# Alert Details

| **Alert** | VPN Tunnel Disconnected |
| --- | --- |
| **Severity** | Sev-1 |

# Prerequisites

- Reader role

# Remediation Steps

| STEP | ACTION | EXPECTED OUTCOME | ADDITIONAL COMMENTS |
| --- | --- | --- | --- |
| Check status | `az network vpn-connection show` | Connected | none |

## Testing Scenarios

| **Scenario** | **Steps** |
| --- | --- |
| x | y |

## Lessons learned

- stuff
"""


class TestGenerateIrp:
    ARGS = {"alert_name": "VPN Tunnel Disconnected", "severity": "Sev-1"}

    def test_the_model_gets_the_whole_example_and_the_exact_rules(self):
        completions = FakeCompletions(BAD_MODEL_REPLY)
        service_with(completions).generate_irp(**self.ARGS, irp_example=long_example(), irp_template="TEMPLATE " * 50)
        call = completions.calls[0]
        assert call["messages"][0] == {"role": "system", "content": fmt.IRP_SYSTEM_PROMPT}
        user = call["messages"][1]["content"]
        assert "SENTINEL_ROW_14" in user and "Testing Scenarios" not in user  # the end of the long table is there, the unwanted sections are not
        assert "TEMPLATE TEMPLATE" in user

    def test_a_reply_with_four_columns_and_extra_sections_comes_back_in_the_agreed_shape(self):
        result = service_with(FakeCompletions(BAD_MODEL_REPLY)).generate_irp(**self.ARGS)
        md = result["markdown_content"]
        assert headings(md) == ["# VPN Tunnel Disconnected", "# Alert Details", "# Prerequisites", "# Remediation Steps"]
        rows = table_rows(md)
        assert rows[0] == ["**STEPS**", "**ACTIONS**", "**ADDITIONAL INFO**"] and all(len(r) == 3 for r in rows)
        assert "**Expected Outcome:** Connected" in md
        assert result["generated_by"] == "ai" and result["notice"] is None

    def test_a_failed_ai_call_uses_the_built_in_plan_and_says_so(self):
        result = service_with(FakeCompletions(error=TimeoutError("boom"))).generate_irp(**self.ARGS, irp_example="# Remediation Steps\n")
        assert result["generated_by"] == "built-in"
        assert "TimeoutError" in result["notice"] and "were not read" in result["notice"] and "boom" not in result["notice"]
        assert headings(result["markdown_content"])[1:] == ["# Alert Details", "# Prerequisites", "# Remediation Steps"]

    def test_an_empty_ai_reply_uses_the_built_in_plan_and_says_so(self):
        result = service_with(FakeCompletions("   ")).generate_irp(**self.ARGS)
        assert result["generated_by"] == "built-in" and "returned no text" in result["notice"]

    def test_without_azure_openai_the_built_in_plan_is_used_and_the_notice_says_how_to_fix_it(self):
        result = IrpService(settings=SimpleNamespace(azure_openai_endpoint="", azure_openai_deployment="")).generate_irp(**self.ARGS, irp_example="x", irp_template="y")
        assert result["generated_by"] == "built-in"
        assert "not configured" in result["notice"] and "AZURE_OPENAI_ENDPOINT" in result["notice"] and "were not read" in result["notice"]
        assert "VPN plan" in result["notice"]

    def test_no_uploads_means_no_not_read_remark(self):
        result = IrpService(settings=SimpleNamespace(azure_openai_endpoint="", azure_openai_deployment="")).generate_irp(**self.ARGS)
        assert "were not read" not in result["notice"]

    @pytest.mark.parametrize("alert,resource,expected_text", [
        ("High CPU on AKS pods", "aks-prod", "kubectl top pods"), ("App Service slow responses", "my app service", "az appservice plan"), ("VPN down", "vpn-gw", "az network vpn-connection"),
    ])
    def test_every_built_in_plan_has_the_three_sections_and_the_three_columns(self, alert, resource, expected_text):
        result = IrpService(settings=SimpleNamespace(azure_openai_endpoint="", azure_openai_deployment="")).generate_irp(alert_name=alert, target_resource=resource)
        md = result["markdown_content"]
        assert headings(md) == [f"# {alert}", "# Alert Details", "# Prerequisites", "# Remediation Steps"] and expected_text in md
        assert all(len(r) == 3 for r in table_rows(md)) and table_rows(md)[0] == ["**STEPS**", "**ACTIONS**", "**ADDITIONAL INFO**"]

    def test_an_example_over_the_limit_is_cut_and_the_notice_says_so(self, monkeypatch):
        monkeypatch.setattr("app.services.irp_service.MAX_EXAMPLE_CHARS", 200)
        completions = FakeCompletions(BAD_MODEL_REPLY)
        result = service_with(completions).generate_irp(**self.ARGS, irp_example="# Remediation Steps\n\n" + "x" * 1000)
        assert result["generated_by"] == "ai" and "only the first 200 were used" in result["notice"]

    def test_a_reply_without_a_table_is_returned_with_a_problem_notice(self):
        result = service_with(FakeCompletions("# Alert Details\n\n| **Alert** | x |\n| --- | --- |\n\n# Remediation Steps\n\nplain text\n")).generate_irp(**self.ARGS)
        assert result["generated_by"] == "ai" and "no table" in result["notice"]


def gfm_cells(line: str) -> list[str]:
    """How GitHub-flavoured Markdown and the Azure DevOps wiki cut a table row: at every unescaped pipe, even inside `code`."""
    import re

    return re.split(r"(?<!\\)\|", line.strip())[1:-1]


class TestPipesInsideCellsDoNotBecomeColumns:
    KQL_ROW = "| Case 1: tunnel dropped | Run in Log Analytics: `AzureDiagnostics | where Level == 1 | project TimeGenerated` | Check the rows |"

    def reply(self, row):
        return f"# Remediation Steps\n\n{fmt.REMEDIATION_HEADER}\n{fmt.REMEDIATION_DIVIDER}\n{row}\n"

    def test_a_raw_pipe_inside_a_code_span_is_escaped_so_the_wiki_keeps_three_columns(self):
        out, _ = fmt.normalize_irp_markdown(self.reply(self.KQL_ROW), "A")
        line = next(line for line in out.splitlines() if "tunnel dropped" in line)
        assert len(gfm_cells(line)) == 3
        assert "`AzureDiagnostics \\| where Level == 1 \\| project TimeGenerated`" in line

    def test_pipes_inside_pre_blocks_are_escaped_too(self):
        row = "| Check | <pre><code>Perf | where X == 1</code></pre> | ok |"
        out, _ = fmt.normalize_irp_markdown(self.reply(row), "A")
        assert len(gfm_cells(next(line for line in out.splitlines() if "Check" in line))) == 3

    def test_already_escaped_pipes_are_not_escaped_twice(self):
        row = "| Check | `a \\| b` | ok |"
        out, _ = fmt.normalize_irp_markdown(self.reply(row), "A")
        assert "`a \\| b`" in out and "\\\\|" not in out

    def test_every_table_row_of_a_generated_plan_has_exactly_three_cells_as_the_wiki_reads_it(self):
        out, _ = fmt.normalize_irp_markdown(long_example().replace("| Health Check |", "| Run `Perf | where X == 1` |"), "A")
        assert {len(gfm_cells(line)) for line in out[out.index("# Remediation Steps"):].splitlines() if line.startswith("|")} == {3}

    def test_the_builtin_plans_also_read_as_three_columns_in_the_wiki(self):
        for alert, resource in (("High CPU on AKS pods", "aks-prod"), ("App Service slow responses", "my app service"), ("VPN down", "vpn-gw")):
            md = IrpService(settings=SimpleNamespace(azure_openai_endpoint="", azure_openai_deployment="")).generate_irp(alert_name=alert, target_resource=resource)["markdown_content"]
            assert {len(gfm_cells(line)) for line in md[md.index("# Remediation Steps"):].splitlines() if line.startswith("|")} == {3}, alert
