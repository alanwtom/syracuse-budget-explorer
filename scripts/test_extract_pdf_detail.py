"""Layout rules for the adopted-budget PDF parser.

These exercise the structural logic rather than one file's page numbers, because
that logic is what has to survive a new fiscal year's document. Each test builds
the line dictionaries the PDF reader produces, so a layout rule can be checked
without a PDF.
"""
import unittest

from extract_pdf_detail import (
    SEPARATOR,
    detect_page_range,
    TOTAL_LINE,
    build_sections,
    merge_wrapped_labels,
    reconcile,
    resolve_columns,
    to_number,
)


def line(label, indent, figures=(), page=1, code=None):
    """Build a reader-shaped line. Figures are (text, right-edge) pairs."""
    return {
        "page": page,
        "code": code,
        "label": label,
        "indent": indent,
        "figures": [
            {"text": t, "right": x, "unreadable": any("ç" <= c <= "ô" for c in t)}
            for t, x in figures
        ],
    }


class FigureParsing(unittest.TestCase):
    def test_parenthesised_figures_are_negative(self):
        self.assertEqual(to_number("(3,340,750)"), -3340750)

    def test_plain_figures_keep_their_value(self):
        self.assertEqual(to_number("350,640,243"), 350640243)

    def test_figures_in_the_broken_font_are_refused_not_guessed(self):
        self.assertIsNone(to_number("1ï,ðîï,967"))

    def test_column_rules_are_not_figures(self):
        for rule in ("=", "==", "_", "—"):
            self.assertTrue(SEPARATOR.match(rule), rule)


class TotalRecognition(unittest.TestCase):
    def test_total_is_recognised_after_separators_are_stripped(self):
        """Revenue totals print as "TOTAL X: = = =" and must still match."""
        self.assertTrue(TOTAL_LINE.match("TOTAL WATER FUND REVENUE"))

    def test_department_total_is_recognised(self):
        self.assertTrue(TOTAL_LINE.match("Total Executive"))

    def test_an_ordinary_row_is_not_a_total(self):
        self.assertIsNone(TOTAL_LINE.match("Sale of Water"))


class WrappedLabels(unittest.TestCase):
    def test_a_wrapped_label_joins_the_row_carrying_the_figures(self):
        merged = merge_wrapped_labels([
            line("Office of Constituent Assistance Resource", 180),
            line("Employees", 180, [("313,368", 444)]),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["label"], "Office of Constituent Assistance Resource Employees")

    def test_a_left_margin_header_is_not_treated_as_a_wrap(self):
        merged = merge_wrapped_labels([
            line("Executive", 53),
            line("Office of the Mayor", 180, [("971,657", 444)]),
        ])
        self.assertEqual([m["label"] for m in merged], ["Executive", "Office of the Mayor"])


class Hierarchy(unittest.TestCase):
    def department(self):
        return [
            line("Executive", 53),
            line("Office of the Mayor", 180, [("100", 444)]),
            line("Bureau of Research", 180, [("50", 444)]),
            line("Total Executive", 180, [("150", 444)]),
        ]

    def report_for(self, lines):
        return reconcile(build_sections(resolve_columns(lines)))

    def test_department_total_sums_only_its_own_rows(self):
        report = self.report_for(self.department())
        self.assertEqual(report[0]["columns"][0]["status"], "exact")

    def test_fund_total_sums_subtotals_without_double_counting_leaves(self):
        """The leaves are already inside the department total; counting both doubles."""
        lines = self.department() + [line("TOTAL DEPARTMENTAL", 53, [("150", 444)])]
        report = self.report_for(lines)
        fund = report[-1]
        self.assertEqual(fund["level"], "fund")
        self.assertEqual(fund["columns"][0]["summed"], 150)
        self.assertEqual(fund["columns"][0]["status"], "exact")

    def test_rows_from_a_department_without_a_total_still_reach_the_fund_total(self):
        lines = self.department() + [
            line("Common Council", 53),
            line("Common Council", 180, [("25", 444)]),
            line("TOTAL DEPARTMENTAL", 53, [("175", 444)]),
        ]
        self.assertEqual(self.report_for(lines)[-1]["columns"][0]["status"], "exact")

    def test_an_untotalled_department_does_not_pollute_the_next_department(self):
        lines = [
            line("Common Council", 53),
            line("Common Council", 180, [("25", 444)]),
        ] + self.department()
        report = self.report_for(lines)
        executive = next(s for s in report if s["name"] == "Executive")
        self.assertEqual(executive["columns"][0]["summed"], 150)

    def test_rows_do_not_carry_across_a_new_statement(self):
        lines = [
            line("Stray Row", 180, [("999", 444)]),
            line("EXPENDITURE SUMMARY - ADOPTED BUDGET", 282),
        ] + self.department()
        report = self.report_for(lines)
        self.assertEqual(report[0]["columns"][0]["summed"], 150)


class DamageReporting(unittest.TestCase):
    def test_an_unreadable_figure_makes_a_sum_incomplete_not_mismatched(self):
        """Damage in the document must not be reported as a parsing failure."""
        lines = [
            line("Executive", 53),
            line("Office of the Mayor", 180, [("100", 444)]),
            line("Bureau of Research", 180, [("íìð", 444)]),
            line("Total Executive", 180, [("150", 444)]),
        ]
        column = reconcile(build_sections(resolve_columns(lines)))[0]["columns"][0]
        self.assertTrue(column["status"].startswith("incomplete"))
        self.assertEqual(column["summed"], 100)

    def test_a_genuine_disagreement_is_reported_as_a_mismatch(self):
        lines = [
            line("Executive", 53),
            line("Office of the Mayor", 180, [("100", 444)]),
            line("Total Executive", 180, [("103", 444)]),
        ]
        column = reconcile(build_sections(resolve_columns(lines)))[0]["columns"][0]
        self.assertEqual(column["status"], "mismatch")
        self.assertEqual(column["difference"], -3)


class ColumnAlignment(unittest.TestCase):
    def test_columns_are_measured_per_page(self):
        """Two pages may set their tables at different x positions."""
        lines = [
            line("Executive", 53, page=1),
            line("Office of the Mayor", 180, [("100", 444), ("200", 550)], page=1),
            line("Total Executive", 180, [("100", 444), ("200", 550)], page=1),
            line("TOTAL DEPARTMENTAL", 53, [("100", 444), ("200", 550)], page=1),
            # Page 2 sets its columns 250pt to the right of page 1's.
            line("Water", 53, page=2),
            line("Sale of Water", 180, [("300", 700), ("400", 800)], page=2),
            line("TOTAL WATER FUND", 53, [("300", 700), ("400", 800)], page=2),
        ]
        report = reconcile(build_sections(resolve_columns(lines)))
        for section in report:
            for column in section["columns"]:
                self.assertEqual(column["status"], "exact", (section["name"], column))


class FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class FakePdf:
    """Stands in for a PDF whose pages carry the given headings."""
    def __init__(self, heading_pages, total=120):
        self.pages = [
            FakePage("REVENUE SUMMARY - ADOPTED BUDGET" if n + 1 in heading_pages else "narrative")
            for n in range(total)
        ]


class PageDetection(unittest.TestCase):
    def test_the_contents_page_mention_is_not_mistaken_for_the_tables(self):
        first, last = detect_page_range(FakePdf([9] + list(range(50, 76))))
        self.assertEqual(first, 50)

    def test_blocks_split_by_unreadable_pages_are_joined(self):
        """One year sets the pages between two blocks in an unreadable font."""
        first, last = detect_page_range(FakePdf([9] + list(range(38, 50)) + list(range(64, 76))))
        self.assertEqual(first, 38)
        self.assertGreaterEqual(last, 75)

    def test_a_distant_block_is_not_absorbed(self):
        first, last = detect_page_range(FakePdf(list(range(25, 40)) + [100, 101], total=120))
        self.assertEqual(first, 25)
        self.assertLess(last, 100)

    def test_a_pdf_with_no_headings_reports_nothing_rather_than_guessing(self):
        self.assertIsNone(detect_page_range(FakePdf([])))


if __name__ == "__main__":
    unittest.main()
