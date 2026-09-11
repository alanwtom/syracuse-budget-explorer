import copy
import json
import unittest
from pathlib import Path
from validate_budget import validate


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
