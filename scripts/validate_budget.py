"""Validate exported records without assuming workbook lines equal formal totals."""
import json
import math
import sys
from pathlib import Path


def validate(data):
    rows = data['rows']
    checks = []
    def check(label, ok, detail):
        checks.append({'label': label, 'status': 'pass' if ok else 'check', 'detail': detail})
    check('Unique record IDs', len({r['id'] for r in rows}) == len(rows), f'{len(rows)} exported records checked.')
    finite = all(isinstance(v, (int, float)) and math.isfinite(v) for r in rows for v in r['values'].values())
    check('Finite account values', finite, 'Every supplied historical amount must be a finite number.')
    mismatches = []
    for r in rows:
        v = r['values']
        expected = round(v.get('fy27Adjusted', v.get('fy27Proposed', 0)) - v.get('fy26Budget', 0), 2)
        if abs(expected - r['change']['amount']) > .01:
            mismatches.append(r['id'])
    check('Record change arithmetic', not mismatches, f'{len(mismatches)} mismatches against the displayed FY27 basis and FY26 budget.')
    s = data['summary']
    net = sum(f['formal']['fy27Adopted'] for f in data['funds']) + s['interfund']
    check('Formal City fund reconciliation', abs(net - s['city']['fy27Adopted']) < .01,
          f'Exported fund totals plus inter-fund adjustment: ${net:,.0f}; formal net: ${s["city"]["fy27Adopted"]:,.0f}. This checks transcribed totals, not source authenticity.')
    check('Combined City and school total', abs(s['city']['fy27Adopted'] + s['schoolDistrict']['fy27Adopted'] - s['combinedNet']['fy27Adopted']) < .01, 'City net plus school district must equal the combined net total.')
    applied = data.get('appliedAmendments', [])
    by_id = {r['id']: r for r in rows}
    check('Amendment record coverage', len(applied) == len(data['amendments']) and all(a['rowId'] in by_id for a in applied), 'Every listed amendment must map to an exported record.')
    # Surface residuals, never silently certify mixed-grain workbook rows.
    for fund in data['funds']:
        for section in ('revenue', 'expense'):
            group = [r for r in rows if r['fundId'] == fund['id'] and r['section'] == section]
            total = sum(r['values'].get('fy27Adjusted', r['values'].get('fy27Proposed', 0)) for r in group)
            residual = round(total - fund['formal']['fy27Adopted'], 2)
            explanation = 'Detail uses workbook proposals and mapped amendments; it is not certified adopted account data.'
            if fund['id'] == 'general-fund' and section == 'expense':
                explanation += ' The original $3 residual traces to General Fund!N499: Public Works is stated as $41,121,923 while its exported detail sums to $41,121,926. Values are retained, not forced to match.'
            if fund['id'] == 'crouse-marshall':
                explanation += ' The $181,863 formal assessment excludes $18,000 of other program revenue. The workbook operating revenue and expense totals are both $199,863 (sheet rows 2, 9 and 35). These totals have different scopes.'
            if fund['id'] == 'downtown-assessment':
                explanation += ' Scope and source discrepancies both apply: adopted PDF page 61 gives assessment $1,390,714 plus allowance $21,178 = $1,411,892; workbook K56 instead has $1,309,714, K58 $21,178, and K55 states $1,441,892. PDF page 227 also shows broader program spending $2,609,019 versus workbook detail $2,609,020. Do not treat workbook district detail as the adopted levy.'
            checks.append({'label': f'{fund["name"]} {section}: detail versus formal',
                'status': 'pass' if abs(residual) < .01 else 'review',
                'detail': f'Detail ${total:,.2f}; formal ${fund["formal"]["fy27Adopted"]:,.2f}; difference ${residual:,.2f}. {explanation}'})
    return checks


if __name__ == '__main__':
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'data/budget.json'
    checks = validate(json.loads(path.read_text(encoding='utf-8')))
    print(json.dumps(checks, indent=2))
    sys.exit(1 if any(c['status'] == 'check' for c in checks) else 0)
