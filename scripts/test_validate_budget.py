import copy
import json
import unittest
from pathlib import Path
from validate_budget import stale_findings, validate


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(__file__).resolve().parents[1] / 'data/budget.json').read_text(encoding='utf-8'))

    def status(self, label):
        return next(c['status'] for c in validate(self.data) if c['label'] == label)

    def test_checked_in_data_and_unresolved_residuals(self):
        checks = validate(self.data)
        self.assertFalse(any(c['status'] == 'check' for c in checks))
        self.assertTrue(any(c['status'] == 'review' for c in checks))

    def test_pdf_totals_agree_with_exported_formal_totals(self):
        self.assertEqual(self.status('Formal totals match the adopted PDF'), 'pass')

    def test_transcription_error_is_caught_against_the_pdf(self):
        """A wrong formal total must fail, or the check proves nothing."""
        self.data['funds'][0]['formal']['fy27Adopted'] += 1000
        self.assertEqual(self.status('Formal totals match the adopted PDF'), 'check')

    def test_pdf_confirmed_rows_are_reported(self):
        self.assertEqual(self.status('Account rows confirmed by the adopted PDF'), 'pass')

    def test_a_row_conflicting_with_the_pdf_fails_the_check(self):
        """A disagreement between the two sources must not pass quietly."""
        self.data['pdfConfirmation'] = {'confirmed': 99, 'conflicting': 1, 'available': 100}
        self.assertEqual(self.status('Account rows confirmed by the adopted PDF'), 'check')

    def test_budget_book_differences_reach_the_site_data(self):
        """Residents are told where the book's own totals do not add up."""
        differences = self.data.get('bookDifferences')
        self.assertIsInstance(differences, list)
        for item in differences:
            self.assertEqual(set(item), {'page', 'fund', 'section', 'difference'})
            self.assertNotEqual(item['difference'], 0)

    def test_budget_book_mistakes_shown_to_residents_match_the_parser(self):
        self.assertEqual(self.status('Budget book mistakes shown to residents still match the parser'), 'pass')

    def test_a_finding_the_parser_no_longer_reports_is_stale(self):
        """A sentence about a mistake must not outlive the evidence for it."""
        spec = {'books': [{'book': '2030-31', 'report': 'r.json'}],
                'findings': [{'book': '2030-31', 'pages': [71], 'amounts': [47594], 'text': '...'}]}
        report = {'sections': [{'page': 71, 'columns': [{'status': 'exact', 'difference': 0}]}]}
        self.assertTrue(stale_findings(spec, lambda path: report))

    def test_a_finding_still_reported_is_not_stale(self):
        spec = {'books': [{'book': '2030-31', 'report': 'r.json'}],
                'findings': [{'book': '2030-31', 'pages': [71], 'amounts': [47594], 'text': '...'}]}
        report = {'sections': [{'page': 71, 'columns': [{'status': 'mismatch', 'difference': 47594}]}]}
        self.assertEqual(stale_findings(spec, lambda path: report), [])

    def test_the_site_carries_each_books_mistakes(self):
        books = self.data.get('bookFindings')
        self.assertEqual([b['book'] for b in books], ['2026-27', '2025-26', '2024-25', '2023-24', '2022-23'])
        self.assertTrue(all(f['text'] and f['pages'] for b in books for f in b['findings']))

    def test_duplicate_id(self):
        self.data['rows'].append(copy.deepcopy(self.data['rows'][0]))
        self.assertEqual(self.status('Unique record IDs'), 'check')

    def test_corrupt_change(self):
        self.data['rows'][0]['change']['amount'] += 100
        self.assertEqual(self.status('Record change arithmetic'), 'check')

    def test_corrupt_formal_total(self):
        self.data['funds'][0]['formal']['fy27Adopted'] += 1
        self.assertEqual(self.status('Formal City fund reconciliation'), 'check')

    def test_missing_amendment_record(self):
        self.data['appliedAmendments'][0]['rowId'] = 'missing'
        self.assertEqual(self.status('Amendment record coverage'), 'check')


if __name__ == '__main__':
    unittest.main()
