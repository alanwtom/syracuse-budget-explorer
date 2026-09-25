"""Layout rules for the adopted-budget PDF parser.

These exercise the structural logic rather than one file's page numbers, because
that logic is what has to survive a new fiscal year's document. Each test builds
the line dictionaries the PDF reader produces, so a layout rule can be checked
without a PDF.
"""
import unittest

from extract_pdf_detail import (
    FACTOR,
    NUMERIC,
    PERCENT,
    STATEMENT_START,
    column_centres,
    FUND_HEADER,
    PAGE_HEADING,
    join_split_figures,
    SEPARATOR,
    join_wrapped_labels,
    shift_figures_to_waiting_labels,
    attach_split_totals,
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
            {"text": t, "right": x, "unreadable": any("ç" <= c <= "ô" for c in t),
             "factor": float(t) if FACTOR.match(t) else None}
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

    def test_a_bare_subtotal_closes_a_block(self):
        """Counting a subtotal as an ordinary row double-counts everything above it."""
        self.assertTrue(TOTAL_LINE.match("Subtotal"))
        self.assertTrue(TOTAL_LINE.match("Sub-Total"))

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
        """As printed: the fund total closes the heading it names, above both departments."""
        lines = [line("Departmental Operating Expenditures", 53)] + self.department() + [
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


class Subtotals(unittest.TestCase):
    def test_a_subtotal_is_not_added_on_top_of_the_rows_it_summarises(self):
        lines = [
            line("Water Fund", 53),
            line("Water Plant", 195, [("100", 444)]),
            line("Water Quality", 195, [("50", 444)]),
            line("Subtotal", 195, [("150", 444)]),
            line("TOTAL WATER FUND BUDGET", 53, [("150", 444)]),
        ]
        report = reconcile(build_sections(resolve_columns(lines)))
        fund = report[-1]
        self.assertEqual(fund["columns"][0]["summed"], 150, "leaves were counted twice")
        self.assertEqual(fund["columns"][0]["status"], "exact")


class LabelOnlyLines(unittest.TestCase):
    """A label with no figures is either a wrapped tail or a row awaiting figures."""

    def test_a_block_heading_never_takes_figures(self):
        """It stands further left than the rows it heads."""
        shifted = shift_figures_to_waiting_labels([
            line("Cash Capital Appropriations & Debt Service", 180),
            line("Serial Bond Principal & Interest", 203),
            line("Transfer - Cash Capital", 203, [("5,826,623", 723)]),
        ])
        heading = shifted[0]
        self.assertEqual(heading["label"], "Cash Capital Appropriations & Debt Service")
        self.assertEqual(heading["figures"], [])

    def test_a_row_label_takes_the_figures_beneath_it(self):
        shifted = shift_figures_to_waiting_labels([
            line("Serial Bond Principal & Interest", 203),
            line("Transfer - Cash Capital", 203, [("5,826,623", 723)]),
            line("Subtotal", 195, [("1,145,000", 723)]),
        ])
        by_label = {l["label"]: [f["text"] for f in l["figures"]] for l in shifted}
        self.assertEqual(by_label["Serial Bond Principal & Interest"], ["5,826,623"])
        self.assertEqual(by_label["Transfer - Cash Capital"], ["1,145,000"],
                         "the shift must carry on through the block's subtotal indent")

    def test_the_wrapped_reading_joins_the_label_instead(self):
        joined = join_wrapped_labels([
            line("Office of Constituent Assistance Resource", 180),
            line("Employees", 180, [("313,368", 444)]),
        ])
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0]["label"], "Office of Constituent Assistance Resource Employees")

    def test_the_reading_that_makes_more_totals_add_up_is_chosen(self):
        """Geometry cannot separate the two readings, so the arithmetic does."""
        rows = [
            line("Serial Bond Principal & Interest", 203),
            line("Transfer - Cash Capital", 203, [("5,826,623", 723)]),
            line("Subtotal", 203, [("1,145,000", 723)]),
            line("TOTAL WATER FUND BUDGET", 53, [("6,971,623", 723)]),
        ]
        chosen = merge_wrapped_labels(rows)
        labels = [l["label"] for l in chosen]
        self.assertIn("Serial Bond Principal & Interest", labels)
        self.assertNotIn("Serial Bond Principal & Interest Transfer - Cash Capital", labels)


class ExpensePageLayout(unittest.TestCase):
    """Rules found on the Municipal Sidewalk and Sewer expense pages."""

    def test_the_fiscal_year_heading_is_not_a_row(self):
        """"June 30, 2027" read as a row adds 2,027 to the first column."""
        self.assertTrue(PAGE_HEADING.search("Fiscal Year Ending June 30, 2027"))

    def test_a_sub_heading_ends_the_block_above_it(self):
        """Without the boundary the operating line is counted again below it."""
        lines = [
            line("SEWER FUND", 53),
            line("Sewer Departmental Operating Expenditures", 180, [("4,814,513", 723)]),
            line("Special Objects of Expense", 180),
            line("Medical Insurance", 195, [("1,449,763", 723)]),
            line("Social Security", 195, [("189,325", 723)]),
            line("Subtotal", 195, [("1,639,088", 723)]),
            line("TOTAL SEWER FUND BUDGET", 53, [("6,453,601", 723)]),
        ]
        report = reconcile(build_sections(resolve_columns(lines)))
        for section in report:
            self.assertEqual(section["columns"][0]["status"], "exact", section["name"])

    def test_a_heading_is_not_joined_to_the_row_beneath_it(self):
        joined = join_wrapped_labels([
            line("Special Objects of Expense", 180),
            line("Employee Retirement System", 195, [("34,728", 723)]),
        ])
        self.assertEqual([l["label"] for l in joined],
                         ["Special Objects of Expense", "Employee Retirement System"])

    def test_figures_on_a_total_line_go_to_the_row_waiting_above_it(self):
        repaired = attach_split_totals([
            line("Serial Bond Principal & Interest", 195),
            line("TOTAL MUNICIPAL SIDEWALK FUND BUDGET", 53,
                 [("0", 444), ("1,041,319", 550), ("1,496,406", 638), ("1,467,424", 723)]),
            line("", 0, [("1,033,508", 444), ("2,285,237", 550), ("2,686,392", 638), ("2,719,688", 723)]),
        ])
        bond = next(l for l in repaired if l["label"].startswith("Serial Bond"))
        total = next(l for l in repaired if l["label"].startswith("TOTAL"))
        self.assertEqual(bond["figures"][-1]["text"], "1,467,424")
        self.assertEqual(total["figures"][-1]["text"], "2,719,688")
        self.assertFalse(any(l["label"] == "Subtotal" for l in repaired),
                         "the waiting row owns the figures; no subtotal is invented")


class SplitTotals(unittest.TestCase):
    """A fund total whose figures print on the line beneath its label."""

    def test_the_total_takes_the_figures_printed_below_it(self):
        repaired = attach_split_totals([
            line("TOTAL WATER FUND BUDGET", 53,
                 [("1,278,267", 444), ("7,283,929", 550), ("6,947,757", 638), ("6,971,623", 723)]),
            line("", 0,
                 [("21,387,648", 444), ("31,031,846", 550), ("28,577,762", 638), ("33,175,883", 723)]),
        ])
        total = next(l for l in repaired if l["label"].startswith("TOTAL"))
        self.assertEqual(total["figures"][-1]["text"], "33,175,883")

    def test_the_displaced_figures_survive_as_a_closing_subtotal(self):
        """Dropping them would leave the block with nothing to check against."""
        repaired = attach_split_totals([
            line("TOTAL WATER FUND BUDGET", 53,
                 [("1,278,267", 444), ("7,283,929", 550), ("6,947,757", 638), ("6,971,623", 723)]),
            line("", 0,
                 [("21,387,648", 444), ("31,031,846", 550), ("28,577,762", 638), ("33,175,883", 723)]),
        ])
        self.assertEqual(len(repaired), 2)
        displaced = repaired[0]
        self.assertEqual(displaced["figures"][-1]["text"], "6,971,623")
        self.assertTrue(TOTAL_LINE.match(displaced["label"]))
        self.assertGreater(displaced["indent"], 100, "must close its block, not the fund")

    def test_a_page_number_beneath_a_total_is_not_mistaken_for_its_figures(self):
        rows = [
            line("TOTAL SEWER FUND BUDGET", 53, [("1", 444), ("2", 550), ("3", 638), ("4", 723)]),
            line("", 0, [("58", 742)]),
        ]
        repaired = attach_split_totals(rows)
        total = next(l for l in repaired if l["label"].startswith("TOTAL"))
        self.assertEqual([f["text"] for f in total["figures"]], ["1", "2", "3", "4"])

    def test_a_department_total_is_left_alone(self):
        repaired = attach_split_totals([
            line("Total Executive", 180, [("100", 444), ("200", 550)]),
            line("", 0, [("900", 444), ("800", 550)]),
        ])
        total = repaired[0]
        self.assertEqual(total["figures"][0]["text"], "100")


class NamedBlocks(unittest.TestCase):
    """On the revenue pages every heading and total sits at the same indent."""

    def revenue(self):
        return [
            line("GENERAL FUND", 53),
            line("Departmental Income", 53),
            line("Finance", 53),
            line("Fees Abstract", 53, [("100", 723)]),
            line("Total Finance", 53, [("100", 723)]),
            line("City Clerk", 53),
            line("Licenses City Clerk", 53, [("60", 723)]),
            line("Total City Clerk", 53, [("60", 723)]),
            line("TOTAL DEPARTMENTAL INCOME", 53, [("160", 723)]),
            line("Sale of Property", 53),
            line("Sale of Surplus", 53, [("40", 723)]),
            line("TOTAL SALE OF PROPERTY", 53, [("40", 723)]),
            line("TOTAL GENERAL FUND REVENUE", 53, [("200", 723)]),
        ]

    def test_a_category_total_sums_the_department_totals_it_names(self):
        report = reconcile(build_sections(resolve_columns(self.revenue())))
        income = next(s for s in report if s["name"] == "DEPARTMENTAL INCOME")
        self.assertEqual(income["columns"][0]["summed"], 160)
        self.assertEqual(income["columns"][0]["status"], "exact")

    def test_a_fund_total_closes_the_heading_it_begins_with(self):
        report = reconcile(build_sections(resolve_columns(self.revenue())))
        fund = next(s for s in report if s["name"] == "GENERAL FUND REVENUE")
        self.assertEqual(fund["columns"][0]["summed"], 200, "categories counted once each")
        self.assertEqual(fund["columns"][0]["status"], "exact")

    def test_a_heading_and_its_total_need_not_be_worded_alike(self):
        """"Appropriations &" closes at "APPROPRIATION AND"."""
        lines = [
            line("Capital Appropriations & Debt Service", 53),
            line("Transfer to Capital Projects Fund", 53),
            line("Cash Capital", 180, [("30", 723)]),
            line("Transfer to Debt Service Fund", 53),
            line("Serial Bond", 180, [("70", 723)]),
            line("TOTAL CAPITAL APPROPRIATION AND DEBT SERVICE", 53, [("100", 723)]),
        ]
        report = reconcile(build_sections(resolve_columns(lines)))
        self.assertEqual(report[-1]["columns"][0]["status"], "exact")


def word(text, x0, x1, top=100):
    return {"text": text, "x0": x0, "x1": x1, "top": top}


class SplitFigures(unittest.TestCase):
    """The tax cap worksheet sets some figures in two touching pieces."""

    def test_a_leading_digit_touching_its_figure_is_rejoined(self):
        joined = join_split_figures([word("1", 500, 505), word("36,270,267", 505, 545)])
        self.assertEqual([w["text"] for w in joined], ["136,270,267"])

    def test_an_opening_parenthesis_touching_its_figure_is_rejoined(self):
        joined = join_split_figures([word("(", 500, 503), word("5,755,000)", 503, 540)])
        self.assertEqual(to_number(joined[0]["text"]), -5755000)

    def test_figures_in_separate_columns_stay_apart(self):
        joined = join_split_figures([word("0", 440, 445), word("2,625,846", 500, 545)])
        self.assertEqual([w["text"] for w in joined], ["0", "2,625,846"])

    def test_a_growth_factor_is_not_an_amount(self):
        self.assertIsNone(to_number("1.0066"))


class Worksheets(unittest.TestCase):
    """Totals on the tax schedules that are formulas rather than plain sums."""

    def report(self, lines):
        return reconcile(build_sections(resolve_columns(lines)))

    def test_a_subtotal_scaled_by_a_growth_factor(self):
        rows = [
            line("Prior Year Levy", 179, [("100,000", 723)]),
            line("Subtotal", 172, [("100,000", 723)]),
            line("Tax Base Growth Factor", 166, [("1.0066", 723)]),
            line("Subtotal", 172, [("100,660", 723)]),
        ]
        column = self.report(rows)[1]["columns"][0]
        self.assertEqual(column["status"], "exact")
        self.assertEqual(column["method"], "growth factor applied to the line above")

    def test_a_running_subtotal(self):
        rows = [
            line("Prior Year Levy", 179, [("100,000", 723)]),
            line("Subtotal", 172, [("100,000", 723)]),
            line("Additions", 166),
            line("PILOTS", 179, [("5,000", 723)]),
            line("Subtotal", 172, [("105,000", 723)]),
        ]
        self.assertEqual(self.report(rows)[1]["columns"][0]["method"], "running total")

    def test_a_subtraction_printed_as_a_negative(self):
        rows = [
            line("PILOTS Receivable for the Coming Year", 179, [("5,755,000", 723)]),
            line("Subtotal", 172, [("(5,755,000)", 723)]),
        ]
        self.assertEqual(self.report(rows)[0]["columns"][0]["method"], "subtracted")

    def test_rows_in_one_column_with_their_total_carried_into_the_next(self):
        rows = [
            line("Tax Levy", 224),
            line("City", 233, [("61,913,554", 509)]),
            line("School District", 233, [("68,445,723", 509)]),
            line("Tax Levy", 322, [("130,359,277", 606)]),
        ]
        column = [c for c in self.report(rows)[0]["columns"] if c["printed"] is not None][0]
        self.assertEqual(column["method"], "carried into the total column")

    def test_a_total_can_close_several_blocks_it_names(self):
        rows = [
            line("Net Debt Exclusions", 224),
            line("City Gen Fund", 233, [("26,495,345", 509)]),
            line("Net Capital Exclusions", 224),
            line("City Gen Fund", 233, [("333,000", 509)]),
            line("Total Exclusions", 322, [("26,828,345", 606)]),
        ]
        report = self.report(rows)
        self.assertEqual(report[0]["rowCount"], 2)
        self.assertEqual([c for c in report[0]["columns"] if c["printed"] is not None][0]["status"], "exact")

    def test_a_wrong_figure_still_fails_every_identity(self):
        """The rules explain a worksheet total; they must not excuse a wrong one."""
        rows = [
            line("Prior Year Levy", 179, [("100,000", 723)]),
            line("Subtotal", 172, [("100,000", 723)]),
            line("Tax Base Growth Factor", 166, [("1.0066", 723)]),
            line("Subtotal", 172, [("100,999", 723)]),
        ]
        self.assertEqual(self.report(rows)[1]["columns"][0]["status"], "mismatch")


class FundHeadings(unittest.TestCase):
    def test_funds_and_special_assessment_districts_are_funds(self):
        for heading in ("GENERAL FUND", "WATER FUND", "DOWNTOWN SPECIAL ASSESSMENT",
                        "CROUSE-MARSHALL SPECIAL ASSESSMENT"):
            self.assertTrue(FUND_HEADER.search(heading), heading)

    def test_the_assessment_department_is_not_a_fund(self):
        """Read as a fund, it filed 51 General Fund lines under a fund that does not exist."""
        self.assertIsNone(FUND_HEADER.search("Assessment"))


class PriorYearLayouts(unittest.TestCase):
    """Layouts found in the 2022-23 to 2025-26 budget books."""

    def report(self, lines):
        return reconcile(build_sections(resolve_columns(lines)))

    def test_a_percentage_is_not_part_of_a_label(self):
        """"TOTAL DEPARTMENTAL: 4.6%" must still close "Departmental Operating Expenditures"."""
        self.assertTrue(PERCENT.match("4.6%"))
        self.assertTrue(PERCENT.match("(2.5%)"))
        self.assertIsNone(to_number("4.6%"))

    def test_a_figure_may_carry_a_dollar_sign(self):
        self.assertTrue(NUMERIC.match("$5,296,329,457"))
        self.assertEqual(to_number("$5,296,329,457"), 5296329457)

    def test_the_tax_schedules_start_statements_of_their_own(self):
        for title in ("PROPERTY TAX CAP CALCULATION", "COMPUTATION OF CONSTITUTIONAL TAX LIMIT"):
            self.assertTrue(STATEMENT_START.search(title), title)

    def test_a_department_total_on_the_page_after_its_rows(self):
        """"Total Public Works" printed on the next page still closes its divisions."""
        rows = [
            line("EXPENDITURE SUMMARY - ADOPTED BUDGET", 280, page=67),
            line("Public Works", 24, page=67),
            line("DPW Main Office", 148, [("100", 723)], page=67),
            line("DPW Street Repair", 148, [("50", 723)], page=67),
            line("EXPENDITURE SUMMARY - ADOPTED BUDGET", 280, page=68),
            line("Total Public Works", 148, [("150", 723)], page=68),
        ]
        total = next(s for s in self.report(rows) if s["name"] == "Public Works")
        self.assertEqual(total["rowCount"], 2)
        self.assertEqual(total["columns"][0]["status"], "exact")

    def test_a_heading_that_adds_a_first_word(self):
        """"Cash Capital Appropriations & Debt Service" closes at "TOTAL CAPITAL APPROPRIATION ..."."""
        rows = [
            line("Cash Capital Appropriations & Debt Service", 24),
            line("Transfer to Capital Projects Fund", 24),
            line("Cash Capital Appropriations", 117, [("12,209,300", 723)]),
            line("Transfer to Debt Service Fund", 24),
            line("Serial Bond Principal & Interest", 117, [("19,515,920", 723)]),
            line("TOTAL CAPITAL APPROPRIATION AND DEBT SERVICE", 24, [("31,725,220", 723)]),
        ]
        self.assertEqual(self.report(rows)[-1]["columns"][0]["status"], "exact")

    def test_an_unlabelled_total_is_counted_once(self):
        """The 2023-24 Federal Aid block prints its total with no label."""
        rows = [
            line("GENERAL FUND", 53),
            line("Federal Aid", 53),
            line("Federal American Relief Plan", 53, [("16,736,551", 638), ("4,000,000", 723)]),
            line("", 0, [("16,736,551", 638), ("4,000,000", 723)]),
            line("Sale of Property", 53),
            line("Sale of Surplus", 53, [("100", 638), ("200", 723)]),
            line("TOTAL SALE OF PROPERTY", 53, [("100", 638), ("200", 723)]),
            line("TOTAL GENERAL FUND REVENUE", 53, [("16,736,651", 638), ("4,000,200", 723)]),
        ]
        fund = next(s for s in self.report(rows) if s["name"] == "GENERAL FUND REVENUE")
        for column in fund["columns"]:
            self.assertEqual(column["status"], "exact", column)

    def test_a_subtotal_under_the_wrong_label_is_still_a_subtotal(self):
        """Where a block's labels print a line out of step, its subtotal carries a neighbour's."""
        rows = [
            line("MUNICIPAL SIDEWALK FUND", 76),
            line("Cash Capital Appropriations & Debt Service", 211),
            line("Serial Bond Principal", 211, [("184,000", 550), ("779,317", 638)]),
            line("Serial Bonds Interest", 211, [("113,120", 550), ("262,002", 638)]),
            line("Serial Bond Principal & Interest", 226, [("297,120", 550), ("1,041,319", 638)]),
            line("TOTAL MUNICIPAL SIDEWALK FUND BUDGET", 76, [("297,120", 550), ("1,041,319", 638)]),
        ]
        fund = self.report(rows)[-1]
        self.assertEqual([c["status"] for c in fund["columns"] if c["printed"] is not None], ["exact", "exact"])

    def test_a_difference_column_printed_without_signs(self):
        """2024-25 prints a cut of $4,324 as "4,324"; it is checked row by row."""
        rows = [
            line("Executive", 24),
            line("Office of the Mayor", 160, [("720,994", 444), ("967,374", 550), ("246,380", 638)]),
            line("Gun Violence Prevention", 160, [("270,000", 444), ("265,676", 550), ("4,324", 638)]),
            line("Total Executive", 160, [("990,994", 444), ("1,233,050", 550), ("242,056", 638)]),
        ]
        column = self.report(rows)[0]["columns"][2]
        self.assertEqual(column["status"], "exact")
        self.assertIn("each row's difference", column["method"])

    def test_a_wrong_difference_is_not_excused(self):
        rows = [
            line("Executive", 24),
            line("Office of the Mayor", 160, [("720,994", 444), ("967,374", 550), ("246,380", 638)]),
            line("Gun Violence Prevention", 160, [("270,000", 444), ("265,676", 550), ("9,999", 638)]),
            line("Total Executive", 160, [("990,994", 444), ("1,233,050", 550), ("242,056", 638)]),
        ]
        self.assertEqual(self.report(rows)[0]["columns"][2]["status"], "mismatch")

    def test_a_line_taken_away_without_a_printed_sign(self):
        """"Plus Available Carryover" reduces the subtractions it sits among."""
        rows = [
            line("PILOTS Receivable for the Coming Year", 206, [("4,814,904", 550), ("6,040,150", 723)]),
            line("Plus Available Carryover from the Prior Year", 206, [("1,329,273", 550), ("939,980", 723)]),
            line("Subtotal", 199, [("3,485,631", 550), ("5,100,170", 723)]),
        ]
        columns = [c for c in self.report(rows)[0]["columns"] if c["printed"] is not None]
        self.assertEqual([c["status"] for c in columns], ["exact", "exact"])
        self.assertEqual(columns[0]["method"], "lines added and taken away")

    def test_signs_must_agree_across_columns(self):
        """One choice of signs has to reproduce every column, not a different one each."""
        rows = [
            line("PILOTS Receivable for the Coming Year", 206, [("4,814,904", 550), ("6,040,150", 723)]),
            line("Plus Available Carryover from the Prior Year", 206, [("1,329,273", 550), ("939,980", 723)]),
            line("Subtotal", 199, [("3,485,631", 550), ("6,980,130", 723)]),
        ]
        columns = [c for c in self.report(rows)[0]["columns"] if c["printed"] is not None]
        self.assertIn("mismatch", [c["status"] for c in columns])

    def test_a_stray_number_in_a_label_is_not_a_column(self):
        """"Legal Costs 207A" must not shift a full page of figures one column over."""
        rows = [line(f"Row {n}", 117, [("1,000", 444), ("2,000", 550), ("1,000", 638)]) for n in range(10)]
        rows.append(line("Legal Costs", 117, [("207", 300), ("70,000", 444), ("70,000", 550), ("0", 638)]))
        self.assertEqual(len(column_centres(rows)), 3)


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
