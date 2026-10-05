import io

import pytest
from openpyxl import Workbook

from app.services.alert_inventory import MAX_BYTES, parse_inventory, summarize_inventory


def names(result):
    return [a["name"] for a in result["alerts"]]


def xlsx(rows, extra_sheet_first=False):
    book = Workbook()
    sheet = book.active
    if extra_sheet_first:
        sheet.title = "Cover"
        sheet = book.create_sheet("Alerts")
    else:
        sheet.title = "Alerts"
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


class TestSpreadsheet:
    def test_name_and_category_columns_are_found_by_their_headers(self):
        data = xlsx([["Owner", "Alert Name", "Service"], ["NetOps", "VPN tunnel down", "VPN"], ["SRE", "Pod restarts", "AKS"]])
        result = parse_inventory("alerts.xlsx", data)
        assert result["name_column"] == "Alert Name" and result["category_column"] == "Service"
        assert result["alerts"] == [{"name": "VPN tunnel down", "category": "VPN"}, {"name": "Pod restarts", "category": "AKS"}]
        assert result["sheet"] == "Alerts"

    def test_the_first_sheet_with_data_is_used(self):
        result = parse_inventory("alerts.xlsx", xlsx([["Name"], ["A1"]], extra_sheet_first=True))
        assert names(result) == ["A1"] and result["sheet"] == "Alerts"  # the empty "Cover" sheet is skipped

    def test_an_empty_spreadsheet_is_reported(self):
        with pytest.raises(ValueError, match="empty"):
            parse_inventory("alerts.xlsx", xlsx([]))

    def test_a_file_that_is_not_a_spreadsheet_fails_cleanly(self):
        with pytest.raises(Exception):
            parse_inventory("alerts.xlsx", b"this is not a zip")

    def test_old_xls_is_refused_with_a_way_forward(self):
        with pytest.raises(ValueError, match="Save the file as .xlsx or .csv"):
            parse_inventory("alerts.xls", b"x")


class TestDelimited:
    def test_comma_semicolon_and_tab(self):
        for sep in (",", ";", "\t"):
            text = f"Alert{sep}Category\nVPN down{sep}Network\nPod restarts{sep}AKS\n"
            result = parse_inventory("a.csv", text.encode())
            assert names(result) == ["VPN down", "Pod restarts"], sep
            assert result["category_column"] == "Category"

    def test_quoted_commas_stay_in_one_cell(self):
        result = parse_inventory("a.csv", b'Name,Team\n"CPU high, node pool A",SRE\n')
        assert names(result) == ["CPU high, node pool A"]

    def test_the_first_column_is_used_when_no_header_looks_like_a_name(self):
        result = parse_inventory("a.csv", b"Thing,Other\nalpha,1\nbeta,2\n")
        assert result["name_column"] == "Thing" and names(result) == ["alpha", "beta"]

    def test_duplicates_blank_names_and_spacing_are_cleaned_and_counted(self):
        result = parse_inventory("a.csv", b"Alert\nVPN   down\nvpn down\n\n ,\nOther\n")
        assert names(result) == ["VPN down", "Other"] and result["duplicates"] == 1

    def test_the_columns_can_be_chosen(self):
        data = b"Alert,Title,Service,Team\nA,Real name,S,T\n"
        chosen = parse_inventory("a.csv", data, name_column="Title", category_column="Team")
        assert names(chosen) == ["Real name"] and chosen["category_column"] == "Team"
        assert parse_inventory("a.csv", data, category_column="")["category_column"] is None
        assert parse_inventory("a.csv", data, name_column="Nope")["name_column"] == "Alert"

    def test_utf8_bom_utf16_and_windows_1252_are_read(self):
        assert names(parse_inventory("a.csv", "﻿Alert\nCafé down\n".encode("utf-8"))) == ["Café down"]
        assert names(parse_inventory("a.csv", "Alert\nCafé down\n".encode("utf-16"))) == ["Café down"]
        assert names(parse_inventory("a.csv", "Alert\nCafé down\n".encode("cp1252"))) == ["Café down"]

    def test_a_header_only_file_has_no_alerts(self):
        with pytest.raises(ValueError, match="at least one alert"):
            parse_inventory("a.csv", b"Alert\n")


class TestMarkdownAndText:
    def test_a_markdown_table_is_read_like_a_spreadsheet(self):
        text = "# Inventory\n\n| Alert Name | Service |\n| --- | --- |\n| VPN down | VPN |\n| Pod restarts | AKS |\n"
        result = parse_inventory("inventory.md", text.encode())
        assert names(result) == ["VPN down", "Pod restarts"] and result["category_column"] == "Service"

    def test_bullets_and_plain_lines_are_one_alert_each(self):
        result = parse_inventory("alerts.txt", b"- VPN down\n* Pod restarts\n1. Disk full\n2) Login errors\nPlain line\n")
        assert names(result) == ["VPN down", "Pod restarts", "Disk full", "Login errors", "Plain line"]
        assert result["category_column"] is None


class TestLimitsAndTypes:
    def test_unknown_types_are_refused(self):
        with pytest.raises(ValueError, match="Upload a .xlsx"):
            parse_inventory("alerts.pdf", b"x")
        with pytest.raises(ValueError, match="Upload a .xlsx"):
            parse_inventory("alerts", b"x")

    def test_a_huge_file_is_refused(self):
        with pytest.raises(ValueError, match="larger than"):
            parse_inventory("a.csv", b"x" * (MAX_BYTES + 1))

    def test_too_many_rows_are_refused(self, monkeypatch):
        import app.services.alert_inventory as module

        monkeypatch.setattr(module, "MAX_ROWS", 3)
        with pytest.raises(ValueError, match="more than 3 rows"):
            parse_inventory("a.csv", b"Alert\na\nb\nc\nd\n")


class TestSummary:
    def test_counts_categories_and_a_sample(self):
        data = b"Alert,Service\n" + b"".join(f"a{n},{'VPN' if n < 3 else 'AKS'}\n".encode() for n in range(5))
        summary = summarize_inventory(parse_inventory("inv.csv", data))
        assert summary["count"] == 5 and summary["filename"] == "inv.csv"
        assert summary["categories"] == [{"name": "VPN", "count": 3}, {"name": "AKS", "count": 2}]  # biggest first
        assert summary["sample"] == ["a0", "a1", "a2", "a3", "a4"]
        assert "alerts" not in summary

    def test_no_inventory_means_no_summary(self):
        assert summarize_inventory(None) is None
