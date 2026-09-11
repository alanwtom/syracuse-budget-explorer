'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  ChevronRight,
  ExternalLink,
  Landmark,
  Search,
  Sparkles,
  WalletCards,
  X,
} from 'lucide-react';

import budgetJson from '@/data/budget.json';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

type BudgetKey =
  | 'fy21Actual'
  | 'fy22Actual'
  | 'fy23Actual'
  | 'fy24Actual'
  | 'fy25Actual'
  | 'fy26Budget'
  | 'fy26Estimate'
  | 'fy27Proposed'
  | 'fy27Adjusted'
  | 'fy27Adopted';

type Row = {
  id: string;
  fundId: string;
  fundName: string;
  section: 'revenue' | 'expense';
  level: 'account' | 'line';
  category: string | null;
  department: string | null;
  division: string | null;
  code: string | null;
  name: string;
  values: Partial<Record<BudgetKey, number>>;
  change: { amount: number; pct: number | null };
  source: string;
  sourceSheet: string;
  sourceRow: number | null;
  adoptedMethod: string;
  note?: string;
  amendments?: string[];
};

type FormalItem = {
  name: string;
  fy26Budget: number;
  fy27Adopted: number;
  change: number;
  pct: number | null;
};

type Fund = {
  id: string;
  name: string;
  kind: string;
  formal: FormalItem;
};

type BarItem = {
  label: string;
  amount: number;
  pct: number;
  scope: string;
};

type Amendment = {
  id: string;
  section: 'revenue' | 'expense';
  label: string;
  detail: string;
  amount: number;
  code: string;
};

type BudgetData = {
  meta: {
    title: string;
    fiscalPeriod: string;
    fiscalDates: string;
    lastUpdated: string;
    scope: string;
    sourceNote: string;
    workbookCaveat: string;
  };
  years: { key: BudgetKey; label: string }[];
  summary: {
    city: FormalItem;
    generalFund: FormalItem;
    schoolDistrict: FormalItem;
    otherCityFunds: FormalItem;
    combinedNet: FormalItem;
    interfund: number;
    revenueSources: BarItem[];
    spendingSources: BarItem[];
    narrative: { label: string; body: string; kind: string }[];
  };
  funds: Fund[];
  rows: Row[];
  amendments: Amendment[];
  validation: { label: string; status: string; detail: string }[];
  sources: Record<string, { label: string; url: string }>;
  openData: {
    catalogUrl: string;
    note: string;
    layers: { label: string; url: string }[];
  };
};

type ModelContextTool = {
  name: string;
  title?: string;
  description: string;
  inputSchema: Record<string, unknown>;
  execute: (input: unknown) => unknown;
  annotations?: { readOnlyHint?: boolean; untrustedContentHint?: boolean };
};

type ModelContext = {
  registerTool: (
    tool: ModelContextTool,
    options?: { signal?: AbortSignal },
  ) => void | Promise<void>;
};

declare global {
  interface Document {
    modelContext?: ModelContext;
  }
}

const data = budgetJson as BudgetData;
const currency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const navItems = [
  { value: 'overview', label: 'Overview', icon: Landmark },
  { value: 'in', label: 'Money in', icon: WalletCards },
  { value: 'out', label: 'Money out', icon: BarChart3 },
  { value: 'changes', label: 'What changed', icon: Sparkles },
  { value: 'explore', label: 'Explore lines', icon: Search },
] as const;

function fmtMoney(value: number | undefined | null) {
  return value === undefined || value === null ? '—' : currency.format(value);
}

function fmtCompact(value: number) {
  if (Math.abs(value) >= 1_000_000_000) {
    return `$${(value / 1_000_000_000).toFixed(1)}B`;
  }
  return `$${(value / 1_000_000).toFixed(1)}M`;
}

function fmtDelta(value: number) {
  return `${value >= 0 ? '+' : '−'}${fmtMoney(Math.abs(value))}`;
}

function fmtPct(value: number | null) {
  if (value === null) return 'New';
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(1)}%`;
}

function rowBasis(row: Row) {
  if (row.adoptedMethod === 'adopted_pdf_amendment_only') return 'FY27 amendment only';
  return row.values.fy27Adjusted !== undefined ? 'FY27 adjusted proposal' : 'FY27 workbook proposal';
}

function writeQuery(values: Record<string, string | null>) {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(values)) {
    if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  }
  window.history.replaceState(null, '', url);
}

function sectionLabel(value: string) {
  return value === 'revenue' ? 'Money in' : 'Money out';
}

// `pass`, `review` and `check` are three distinct confidence states and must not
// be collapsed. A `check` is a failing invariant in the exported data; a `review`
// is an unresolved difference between sources that is reported, not resolved.
const checkStates = {
  pass: { label: 'Pass', className: 'text-[#2f6b4f]' },
  review: { label: 'Unresolved difference', className: 'text-[#8a5a1b]' },
  check: { label: 'Failed check', className: 'text-[#a33126]' },
} as const;

function checkState(status: string) {
  if (status in checkStates) return checkStates[status as keyof typeof checkStates];
  // An unrecognised status is reported verbatim rather than assumed to be benign.
  return { label: status, className: 'text-[#a33126]' };
}

function isLargeChange(row: Row) {
  const old = row.values.fy26Budget ?? 0;
  const amountLarge = Math.abs(row.change.amount) >= 250000;
  const percentLarge = old >= 25000 && row.change.pct !== null && Math.abs(row.change.pct) >= 20;
  return amountLarge || percentLarge;
}

function ChangeMark({ amount }: { amount: number }) {
  const positive = amount >= 0;
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={positive ? 'change-positive' : 'change-negative'}>
      <Icon aria-hidden="true" className="size-4" />
      {fmtDelta(amount)}
    </span>
  );
}

function ExternalSource({
  source,
  children,
}: {
  source: { label: string; url: string };
  children?: React.ReactNode;
}) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-sm font-medium text-[#1e5870] underline decoration-[#9fc5c7] underline-offset-4 hover:text-[#0f2b3d]"
    >
      {children ?? source.label}
      <ExternalLink aria-hidden="true" className="size-3.5" />
    </a>
  );
}

function Panel({
  eyebrow,
  title,
  description,
  children,
  className = '',
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="mb-6">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2 className="section-title">{title}</h2>
        {description && <p className="section-description">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function ProgressList({ items }: { items: BarItem[] }) {
  const max = Math.max(...items.map((item) => item.amount), 1);
  return (
    <ul className="space-y-5">
      {items.map((item) => (
        <li key={item.label}>
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <span className="text-sm font-medium text-[#203442]">{item.label}</span>
            <span className="tabular-nums text-sm text-[#52656d]">{fmtCompact(item.amount)}</span>
          </div>
          <div className="budget-track" aria-label={`${item.label}: ${fmtMoney(item.amount)}, ${item.pct}%`}>
            <div className="budget-bar" style={{ width: `${Math.max(3, (item.amount / max) * 100)}%` }} />
          </div>
          <p className="mt-1.5 text-xs text-[#52656d]">{item.pct.toFixed(2)}% of the combined net budget</p>
        </li>
      ))}
    </ul>
  );
}

function MetricCard({
  label,
  value,
  note,
  accent = false,
}: {
  label: string;
  value: string;
  note: string;
  accent?: boolean;
}) {
  return (
    <div className={`metric-card ${accent ? 'metric-card-accent' : ''}`}>
      <p className="eyebrow">{label}</p>
      <p className="metric-value">{value}</p>
      <p className="metric-note">{note}</p>
    </div>
  );
}

function SourceStrip() {
  return (
    <section className="source-strip">
      <div>
        <p className="eyebrow">Follow the record</p>
        <h2 className="mt-2 text-lg font-semibold text-[#173140]">Follow the sources and assumptions.</h2>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-[#5b6d74]">
          Formal adopted totals come from the City budget book. Account history and proposals come from the City Auditor workbook; mapped amendments produce calculated adjustments. Older public layers are available for cross-checks.
        </p>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-3">
        <ExternalSource source={data.sources.adoptedPdf}>Adopted PDF</ExternalSource>
        <ExternalSource source={data.sources.workbook}>Auditor workbook</ExternalSource>
        <ExternalSource source={data.sources.openData}>Open Data</ExternalSource>
      </div>
    </section>
  );
}

function Overview() {
  const city = data.summary.city;
  const maxFund = Math.max(...data.funds.map((fund) => fund.formal.fy27Adopted));
  return (
    <div className="stagger space-y-6">
      <div className="grid gap-6 lg:grid-cols-[1.25fr_.75fr]">
        <Panel
          eyebrow="One city, six funds"
          title="Where the City budget sits"
          description="Fund shares use the gross City total. The headline subtracts inter-fund transfers to avoid double counting. The school district is separate."
        >
          <div className="space-y-5">
            {data.funds.map((fund) => {
              const percent = (fund.formal.fy27Adopted / data.funds.reduce((sum, item) => sum + item.formal.fy27Adopted, 0)) * 100;
              return (
                <div key={fund.id}>
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-[#203442]">{fund.name}</span>
                    <span className="tabular-nums text-sm font-semibold text-[#173140]">{fmtCompact(fund.formal.fy27Adopted)}</span>
                  </div>
                  <div className="budget-track">
                    <div
                      className="budget-bar"
                      style={{ width: `${Math.max(2, (fund.formal.fy27Adopted / maxFund) * 100)}%` }}
                    />
                  </div>
                  <div className="mt-1.5 flex justify-between text-xs text-[#52656d]">
                    <span>{percent.toFixed(1)}% of City funds before inter-fund adjustment</span>
                    <span className={fund.formal.change >= 0 ? 'change-positive' : 'change-negative'}>
                      {fmtPct(fund.formal.pct)} from FY26
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel eyebrow="The short version" title="Three things to know">
          <div className="space-y-4">
            {data.summary.narrative.map((item, index) => (
              <div key={item.label} className="story-card">
                <span className="story-number">0{index + 1}</span>
                <div>
                  <h3 className="text-sm font-semibold text-[#173140]">{item.label}</h3>
                  <p className="mt-1 text-sm leading-6 text-[#5b6d74]">{item.body}</p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Net City funds" value={fmtCompact(city.fy27Adopted)} note={`${fmtPct(city.pct)} from FY26 adopted`} accent />
        <MetricCard label="General Fund" value={fmtCompact(data.summary.generalFund.fy27Adopted)} note="The main operating fund" />
        <MetricCard label="School district" value={fmtCompact(data.summary.schoolDistrict.fy27Adopted)} note="Shown separately in the combined view" />
        <MetricCard label="Inter-fund adjustment" value={fmtMoney(data.summary.interfund)} note="Removed from the City total" />
      </div>
    </div>
  );
}

function MoneyIn() {
  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_.85fr]">
      <Panel
        eyebrow="Where money comes from"
        title="State aid is the largest source"
        description="This follows the formal combined City and school district summary in the adopted budget."
      >
        <ProgressList items={data.summary.revenueSources} />
      </Panel>
      <div className="stagger space-y-6">
        <Panel eyebrow="Read this first" title="Two budgets meet here">
          <p className="text-sm leading-7 text-[#52656d]">
            The combined view is useful for the full public picture. It includes the Syracuse City School District, which is not a City fund. Use Explore lines when you want City account detail.
          </p>
          <div className="mt-5 rounded-2xl bg-[#eef5f2] p-4">
            <p className="eyebrow text-[#32736f]">Combined net budget</p>
            <p className="mt-1 text-3xl font-semibold tracking-[-0.04em] text-[#173140]">{fmtCompact(data.summary.combinedNet.fy27Adopted)}</p>
            <p className="mt-1 text-sm text-[#5b6d74]">{fmtPct(data.summary.combinedNet.pct)} from FY26</p>
          </div>
        </Panel>
        <Panel eyebrow="A key change" title="Temporary AIM aid rises">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[3px] border border-[#d9e0da] text-[#5b6d74]">
              <ArrowUpRight aria-hidden="true" className="size-5" />
            </div>
            <p className="text-sm leading-7 text-[#52656d]">
              The adopted plan raises Temporary AIM state aid from <strong className="font-semibold text-[#173140]">$15.0M</strong> in the workbook proposal to <strong className="font-semibold text-[#173140]">$35.0M</strong>.
            </p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function MoneyOut({ onExplore }: { onExplore: () => void }) {
  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_.85fr]">
      <Panel
        eyebrow="Where money goes"
        title="School and people lead the plan"
        description="The adopted summary groups the full City and school district plan into large service areas."
      >
        <ProgressList items={data.summary.spendingSources} />
      </Panel>
      <div className="stagger space-y-6">
        <Panel eyebrow="City view" title="The General Fund in context">
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-[#e6e8e1] pb-4">
              <span className="text-sm text-[#5b6d74]">General Fund</span>
              <span className="font-semibold tabular-nums text-[#173140]">{fmtCompact(data.summary.generalFund.fy27Adopted)}</span>
            </div>
            <div className="flex items-center justify-between border-b border-[#e6e8e1] pb-4">
              <span className="text-sm text-[#5b6d74]">Employee benefits</span>
              <span className="font-semibold tabular-nums text-[#173140]">{fmtCompact(data.summary.spendingSources.find((item) => item.label === 'Employee benefits')?.amount ?? 0)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-[#5b6d74]">Police + Fire</span>
              <span className="font-semibold tabular-nums text-[#173140]">{fmtCompact(data.summary.spendingSources.filter((item) => ['Police', 'Fire'].includes(item.label)).reduce((sum, item) => sum + item.amount, 0))}</span>
            </div>
          </div>
          <Button className="mt-6 bg-[#173140] text-white hover:bg-[#234b5e]" onClick={onExplore}>
            Explore department lines
            <ChevronRight aria-hidden="true" />
          </Button>
        </Panel>
        <Panel eyebrow="Plain language" title="The largest named use">
          <p className="text-sm leading-7 text-[#52656d]">
            Employee benefits are the largest named City operating group in the adopted combined summary. Personnel costs sit across departments, so the explorer keeps the department and account trail visible.
          </p>
        </Panel>
      </div>
    </div>
  );
}

function ChangeCard({ row, onOpen }: { row: Row; onOpen: (row: Row) => void }) {
  return (
    <button type="button" className="change-card text-left" onClick={() => onOpen(row)}>
      <div className="flex min-w-0 items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-[#173140]">{row.name}</p>
          <p className="mt-1 truncate text-xs text-[#52656d]">
            {row.fundName} · {row.department ?? row.category ?? sectionLabel(row.section)}
          </p>
        </div>
        <ChangeMark amount={row.change.amount} />
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 text-xs text-[#52656d]">
        <span>{rowBasis(row)}</span>
        <span className="inline-flex items-center gap-1">{fmtPct(row.change.pct)} vs FY26 adopted<ChevronRight aria-hidden="true" className="change-arrow size-3.5" /></span>
      </div>
    </button>
  );
}

function Changes({ onOpen }: { onOpen: (row: Row) => void }) {
  const [filter, setFilter] = useState<'all' | 'revenue' | 'expense'>('all');
  const notableRows = useMemo(() => {
    return data.rows
      .filter((row) => isLargeChange(row) && (filter === 'all' || row.section === filter))
      .sort((a, b) => Math.abs(b.change.amount) - Math.abs(a.change.amount))
      .slice(0, 12);
  }, [filter]);

  return (
    <div className="stagger space-y-6">
      <Panel
        eyebrow="What changed"
        title="Large changes rise to the top"
        description="Compared with FY26 adopted: workbook proposals, adjusted where amendments are mapped. These are not verified adopted account totals. Flagged at $250,000 or at 20% on a prior budget of at least $25,000."
      >
        <div className="mb-6 flex flex-wrap gap-2" aria-label="Change type">
          {(['all', 'revenue', 'expense'] as const).map((item) => (
            <Button
              key={item}
              size="sm"
              variant={filter === item ? 'default' : 'outline'}
              className={`rounded-[3px] font-normal transition-colors duration-150 ${filter === item ? 'bg-[#173140] text-white hover:bg-[#234b5e]' : 'border-[#dfe3dc] text-[#5b6d74] hover:bg-[#f3f5f1]'}`}
              aria-pressed={filter === item}
              onClick={() => setFilter(item)}
            >
              {item === 'all' ? 'All changes' : item === 'revenue' ? 'Money in' : 'Money out'}
            </Button>
          ))}
        </div>
        {notableRows.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {notableRows.map((row) => <ChangeCard key={row.id} row={row} onOpen={onOpen} />)}
          </div>
        ) : (
          <p className="rounded-xl bg-[#f4f5f1] p-5 text-sm text-[#5b6d74]">No large changes match this filter.</p>
        )}
      </Panel>

      <Panel
        eyebrow="Why the final plan differs"
        title="The adopted amendments"
        description="These entries are taken from the adopted PDF's final amendment list. Positive amounts add money. Negative amounts reduce the proposal."
      >
        <div className="divide-y divide-[#e6e8e1]">
          {data.amendments.map((amendment) => (
            <div key={amendment.id} className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
              <div>
                <p className="text-sm font-semibold text-[#173140]">{amendment.label}</p>
                <p className="mt-1 text-xs leading-5 text-[#52656d]">{amendment.detail}</p>
              </div>
              <span className="shrink-0 text-sm font-semibold tabular-nums">
                <span className={amendment.amount >= 0 ? 'change-positive' : 'change-negative'}>{fmtDelta(amendment.amount)}</span>
              </span>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Explore({ onOpen }: { onOpen: (row: Row) => void }) {
  const [fundId, setFundId] = useState('general-fund');
  const [section, setSection] = useState<'revenue' | 'expense'>('expense');
  const [department, setDepartment] = useState('all');
  const [query, setQuery] = useState('');
  const [visibleCount, setVisibleCount] = useState(40);
  const [restored, setRestored] = useState(false);
  const [copied, setCopied] = useState(false);
  // URL state is restored after hydration so server and client first renders agree.
  /* oxlint-disable react/react-compiler */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const linkedRow = data.rows.find((item) => item.id === params.get('row'));
    const fund = linkedRow?.fundId ?? params.get('fund');
    if (data.funds.some((item) => item.id === fund)) setFundId(fund!);
    const view = linkedRow?.section ?? params.get('view');
    if (view === 'revenue' || view === 'expense') setSection(view);
    const dept = params.get('department');
    if (dept && data.rows.some((item) => item.department === dept)) setDepartment(dept);
    setQuery(params.get('q') ?? '');
    setRestored(true);
  }, []);
  /* oxlint-enable react/react-compiler */
  useEffect(() => {
    if (restored) writeQuery({ fund: fundId, view: section, department: department === 'all' ? null : department, q: query || null });
  }, [fundId, section, department, query, restored]);
  async function copyView() {
    try { await navigator.clipboard.writeText(window.location.href); setCopied(true); }
    catch { setCopied(false); }
  }

  const departments = useMemo(() => {
    const values = data.rows
      .filter((row) => row.fundId === fundId && row.section === section && row.department)
      .map((row) => row.department as string);
    return Array.from(new Set(values)).sort();
  }, [fundId, section]);

  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return data.rows
      .filter((row) => row.fundId === fundId && row.section === section)
      .filter((row) => department === 'all' || row.department === department)
      .filter((row) => {
        if (!needle) return true;
        return [row.name, row.code, row.category, row.department, row.division]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(needle);
      })
      .sort((a, b) => Math.abs(b.change.amount) - Math.abs(a.change.amount));
  }, [department, fundId, query, section]);

  const selectedFund = data.funds.find((fund) => fund.id === fundId) ?? data.funds[0];

  function changeFund(value: string) {
    setVisibleCount(40);
    setFundId(value);
    setDepartment('all');
  }

  function changeSection(value: string) {
    setVisibleCount(40);
    setSection(value as 'revenue' | 'expense');
    setDepartment('all');
  }

  return (
    <div id="explore-lines" className="stagger space-y-6">
      <Panel
        eyebrow="Department to account"
        title="Follow one line through time"
        description="Choose a fund and open a line for its history and source. FY27 detail is the workbook proposal, adjusted where a final amendment is mapped. Formal adopted totals are shown separately in Overview."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <div className="field-label">
            <span>Fund</span>
            <Select value={fundId} onValueChange={(value) => changeFund(value ?? 'general-fund')}>
              <SelectTrigger aria-label="Fund" className="mt-2 w-full bg-white"><SelectValue>{selectedFund.name}</SelectValue></SelectTrigger>
              <SelectContent>
                {data.funds.map((fund) => <SelectItem key={fund.id} value={fund.id}>{fund.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="field-label">
            <span>View</span>
            <Select value={section} onValueChange={(value) => changeSection(value ?? 'expense')}>
              <SelectTrigger aria-label="View" className="mt-2 w-full bg-white"><SelectValue>{sectionLabel(section)}</SelectValue></SelectTrigger>
              <SelectContent>
                <SelectItem value="expense">Money out</SelectItem>
                <SelectItem value="revenue">Money in</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="field-label">
            <span>Department</span>
            <Select value={department} onValueChange={(value) => { setVisibleCount(40); setDepartment(value ?? 'all'); }}>
              <SelectTrigger aria-label="Department" className="mt-2 w-full bg-white"><SelectValue>{department === 'all' ? 'All departments' : department}</SelectValue></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All departments</SelectItem>
                {departments.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="relative mt-4 max-w-xl">
          <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#52656d]" />
          <Input aria-label="Search account, code, department or division" value={query} onChange={(event) => { setVisibleCount(40); setCopied(false); setQuery(event.target.value); }} placeholder="Search account, code, department…" className="h-10 bg-white pl-9" />
          {query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#52656d] hover:text-[#173140]"><X aria-hidden="true" className="size-4" /></button>}
        </div>
      </Panel>

      <section className="panel overflow-hidden p-0">
        <div className="flex flex-col gap-2 border-b border-[#e6e8e1] px-5 py-5 sm:flex-row sm:items-end sm:justify-between sm:px-6">
          <div>
            <p className="eyebrow">{selectedFund.name} · {sectionLabel(section)}</p>
            <h2 className="mt-1 text-lg font-semibold text-[#173140]">{filteredRows.length} lines to inspect</h2>
          </div>
          <p className="text-xs text-[#52656d]">Sorted by absolute change from FY26 adopted; FY27 basis shown per line</p>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-5 sm:pl-6">Line item</TableHead>
              <TableHead>Department</TableHead>
              <TableHead className="text-right">FY27 detail</TableHead>
              <TableHead className="pr-5 text-right sm:pr-6">Change</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredRows.slice(0, visibleCount).map((row) => (
              <TableRow key={row.id}>
                <TableCell className="min-w-[250px] pl-5 sm:pl-6">
                  <button type="button" className="group text-left" onClick={() => onOpen(row)}>
                    <span className="block font-medium text-[#173140] group-hover:text-[#1e5870]">{row.name}</span>
                    <span className="mt-1 block text-xs text-[#52656d]">{row.code ? `Account ${row.code}` : 'Adopted line'} · {row.category ?? sectionLabel(row.section)}</span>
                  </button>
                </TableCell>
                <TableCell className="min-w-[150px] max-w-[220px] whitespace-normal text-[#5b6d74]">{row.department ?? '—'}{row.division && <span className="mt-1 block text-xs">{row.division}</span>}</TableCell>
                <TableCell className="text-right font-medium tabular-nums text-[#173140]">{fmtMoney(row.values.fy27Adjusted ?? row.values.fy27Proposed)}<span className="mt-1 block text-xs font-normal text-[#52656d]">{rowBasis(row)}</span></TableCell>
                <TableCell className="pr-5 text-right tabular-nums sm:pr-6"><ChangeMark amount={row.change.amount} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e6e8e1] p-5">
          <output className="text-sm text-[#52656d]">Showing {Math.min(visibleCount, filteredRows.length)} of {filteredRows.length} matching lines.</output>
          {visibleCount < filteredRows.length && <Button variant="outline" onClick={() => setVisibleCount((count) => count + 40)}>Show 40 more</Button>}
          <Button variant="outline" onClick={copyView}>{copied ? 'Link copied' : 'Copy view link'}</Button>
        </div>
        {!filteredRows.length && <p className="px-5 py-8 text-sm text-[#5b6d74] sm:px-6">No lines match this search.</p>}
      </section>
    </div>
  );
}

function RowSheet({ row, onClose }: { row: Row | null; onClose: () => void }) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  return (
    <Sheet open={Boolean(row)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent side="right" initialFocus={titleRef} className="data-[side=right]:w-full data-[side=right]:sm:max-w-xl overflow-y-auto overflow-x-hidden border-l border-[#dfe5df] bg-[#fbfcf8]">
        {row && (
          <>
            <SheetHeader className="border-b border-[#e6e8e1] px-6 pb-5 pt-7">
              <p className="eyebrow">{row.fundName} · {sectionLabel(row.section)}</p>
              <SheetTitle ref={titleRef} tabIndex={-1} className="mt-2 pr-6 text-2xl font-semibold tracking-[-0.03em] text-[#173140]">{row.name}</SheetTitle>
              <SheetDescription className="mt-2 leading-6">{[row.department, row.division, row.code ? `Account ${row.code}` : null].filter(Boolean).join(' · ') || 'Adopted budget line'}</SheetDescription>
            </SheetHeader>
            <div className="space-y-6 px-6 py-6">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="detail-stat">
                  <p className="eyebrow">{rowBasis(row)}</p>
                  <p className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-[#173140]">{fmtMoney(row.values.fy27Adjusted ?? row.values.fy27Proposed)}</p>
                </div>
                <div className="detail-stat">
                  <p className="eyebrow">Change</p>
                  <p className="mt-1 text-2xl font-semibold tracking-[-0.03em]"><ChangeMark amount={row.change.amount} /></p>
                </div>
              </div>

              <div>
                <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
                  <h3 className="text-sm font-semibold text-[#173140]">History</h3>
                  <span className="text-xs text-[#52656d]">Actuals, budgets and proposal — different bases</span>
                </div>
                <div className="divide-y divide-[#e6e8e1] rounded-2xl border border-[#e6e8e1] bg-white">
                  {data.years.filter((year) => year.key !== 'fy27Adjusted' || row.values.fy27Adjusted !== undefined).map((year) => (
                    <div key={year.key} className="flex items-center justify-between px-4 py-3 text-sm">
                      <span className={year.key === 'fy27Adopted' ? 'font-semibold text-[#173140]' : 'text-[#5b6d74]'}>{year.key === 'fy27Adjusted' ? rowBasis(row) : year.label}</span>
                      <span className={year.key === 'fy27Adopted' ? 'font-semibold tabular-nums text-[#173140]' : 'tabular-nums text-[#52656d]'}>{fmtMoney(row.values[year.key])}</span>
                    </div>
                  ))}
                </div>
              </div>

              {row.amendments?.length ? (
                <div className="rounded-2xl border border-[#ead79d] bg-[#fff9e7] p-4">
                  <p className="eyebrow text-[#725619]">Final amendment applied</p>
                  <p className="mt-1 text-sm leading-6 text-[#6e5b2d]">A published amendment has been applied to the workbook proposal. This calculated figure is not a separately verified adopted account total.</p>
                </div>
              ) : null}
              {row.note ? <p className="rounded-2xl bg-[#eef5f2] p-4 text-sm leading-6 text-[#52656d]">{row.note}</p> : null}

              <div className="border-t border-[#e6e8e1] pt-5">
                <p className="eyebrow">Source trail</p>
                <div className="mt-3 space-y-2">
                  <ExternalSource source={data.sources.adoptedPdf}>Adopted PDF</ExternalSource>
                  <br />
                  <ExternalSource source={data.sources.workbook}>Auditor workbook</ExternalSource>
                  <p className="pt-1 text-xs leading-5 text-[#52656d]">{row.sourceSheet}{row.sourceRow ? `, row ${row.sourceRow}` : ''} · {row.adoptedMethod.replaceAll('_', ' ')}</p>
                </div>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default function Home() {
  const [activeTab, setActiveTab] = useState('overview');
  const [selectedRow, setSelectedRow] = useState<Row | null>(null);

  useEffect(() => {
    const context = typeof document === 'undefined' ? undefined : document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tool: ModelContextTool = {
      name: 'show_budget_line',
      title: 'Show budget line',
      description: 'Open one budget line in the visible Syracuse Budget Explorer detail panel. Use a rowId from the normalized budget data.',
      inputSchema: {
        type: 'object',
        properties: { rowId: { type: 'string' } },
        required: ['rowId'],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true, untrustedContentHint: false },
      execute: (input: unknown) => {
        if (!input || typeof input !== 'object' || !('rowId' in input) || typeof input.rowId !== 'string') {
          throw new Error('rowId must be a string.');
        }
        const row = data.rows.find((item) => item.id === input.rowId);
        if (!row) throw new Error('That budget line was not found.');
        setActiveTab('explore');
        setSelectedRow(row);
        return {
          status: 'opened',
          rowId: row.id,
          name: row.name,
          fund: row.fundName,
          section: row.section,
          fy27Detail: row.values.fy27Adjusted ?? row.values.fy27Proposed ?? null,
          basis: rowBasis(row),
          change: row.change.amount,
        };
      },
    };
    try {
      void Promise.resolve(context.registerTool(tool, { signal: lifecycle.signal })).catch(() => undefined);
    } catch {
      return () => lifecycle.abort();
    }
    return () => lifecycle.abort();
  }, []);

  // URL state is restored after hydration so server and client first renders agree.
  /* oxlint-disable react/react-compiler */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get('tab');
    if (navItems.some((item) => item.value === requested)) setActiveTab(requested!);
    const row = data.rows.find((item) => item.id === params.get('row'));
    if (row) { setSelectedRow(row); setActiveTab('explore'); }
  }, []);
  /* oxlint-enable react/react-compiler */
  function openRow(row: Row) { setSelectedRow(row); writeQuery({ row: row.id }); }
  function selectTab(value: string) { setActiveTab(value); writeQuery({ tab: value }); }

  return (
    <main className="min-h-screen bg-[#f4f5f1] text-[#173140]">
      <header className="site-header">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 px-5 py-5 sm:px-8 lg:flex-row lg:items-center lg:justify-between lg:px-10">
          <div className="flex items-center gap-3">
            <div className="brand-mark" aria-hidden="true">S</div>
            <div>
              <p className="text-[15px] font-semibold tracking-[-0.01em] text-white">Syracuse Budget Explorer</p>
              <p className="mt-0.5 text-xs text-[#b6c7c9]">Independent project by Alan Tom · Not a City website</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[#c2d2d1]">
            <span className="inline-flex items-center gap-2">FY2026–27 adopted</span>
            <span className="hidden h-4 w-px bg-[#5a737c] sm:block" />
            <span>Updated {data.meta.lastUpdated}</span>
          </div>
        </div>
        <div className="border-t border-[#2c5361] bg-[#122f3e]">
          <div className="mx-auto flex max-w-7xl flex-col gap-2 px-5 py-3 text-xs sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10">
            <p className="text-[#c2d2d1]">{data.meta.fiscalDates} · adopted City funds plus combined context</p>
            <ExternalSource source={data.sources.budgetPage}>City budget page</ExternalSource>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10 lg:py-12">
        <section className="grid gap-6 lg:grid-cols-[1.3fr_.7fr] lg:items-end">
          <div>
            <p className="eyebrow text-[#32736f]">Public money, made legible</p>
            <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-[1.04] tracking-[-0.038em] text-[#173140] sm:text-5xl">Understand the Syracuse budget.</h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[#52656d] sm:text-lg">See where money comes from, where it goes, and what changed in the adopted FY2026–27 plan. Start with the summary. Drill down to a department or account when you want the detail.</p>
            <div className="mt-4 flex flex-wrap gap-3"><a className="rounded-[4px] bg-[#173140] px-4 py-2 text-sm text-white transition-colors duration-150 hover:bg-[#22475a]" href="#budget-views" onClick={() => selectTab('explore')}>Explore a budget line</a><a className="py-2 text-sm underline" href="#about-project">About this project</a></div><div className="mt-4 flex flex-wrap gap-2">
              <Badge variant="outline" className="rounded-[3px] border-[#cfdcd6] bg-transparent font-normal text-[#4c6b66]">Official sources · Independent interpretation</Badge>
              <Badge variant="outline" className="rounded-[3px] border-[#dfe3dc] bg-transparent font-normal text-[#6b7c83]">6 City funds</Badge>
              <Badge variant="outline" className="rounded-[3px] border-[#dfe3dc] bg-transparent font-normal text-[#6b7c83]">FY21–FY27 history</Badge>
            </div>
          </div>
          <div className="hero-total">
            <div className="flex items-center justify-between gap-4">
              <p className="eyebrow text-[#dbe8e1]">Net City funds</p>
              <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-[#9fb3ad]">Adopted</span>
            </div>
            <p className="mt-5 text-5xl font-semibold tracking-[-0.06em] text-white">{fmtCompact(data.summary.city.fy27Adopted)}</p>
            <div className="mt-3 flex items-center gap-2 text-sm text-[#dbe8e1]"><ChangeMark amount={data.summary.city.change} /> from FY26 adopted</div>
            <p className="mt-6 border-t border-[#44636a] pt-4 text-sm leading-6 text-[#b6c7c9]">This total includes the General, Water, Sewer, Sidewalk, Downtown, and Crouse-Marshall funds, less inter-fund appropriations.</p>
          </div>
        </section>

        <section id="budget-views" className="mt-8 scroll-mt-4">
          <Tabs value={activeTab} onValueChange={(value) => selectTab(value ?? 'overview')}>
            <div className="mb-6 overflow-x-auto pb-1">
              <TabsList variant="line" className="w-full justify-start gap-2 border-b border-[#dfe5df] rounded-none p-0">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  return <TabsTrigger key={item.value} value={item.value} className="h-11 flex-none gap-2 px-3 text-[#5b6d74] data-active:text-[#173140]"><Icon aria-hidden="true" className="size-4" />{item.label}</TabsTrigger>;
                })}
              </TabsList>
            </div>
            <TabsContent value="overview"><Overview /></TabsContent>
            <TabsContent value="in"><MoneyIn /></TabsContent>
            <TabsContent value="out"><MoneyOut onExplore={() => selectTab('explore')} /></TabsContent>
            <TabsContent value="changes"><Changes onOpen={openRow} /></TabsContent>
            <TabsContent value="explore"><Explore onOpen={openRow} /></TabsContent>
          </Tabs>
        </section>

        <div className="mt-8"><SourceStrip /></div>
        <section id="about-project" className="panel mt-6 scroll-mt-4">
          <h2 className="section-title">About this project</h2>
          <p className="section-description">An independent civic-data project by Alan Tom, built with AI assistance to make public budget records easier to explore. Not affiliated with or endorsed by the City of Syracuse.</p>
          <p className="mt-4 text-sm leading-6 text-[#52656d]">The work connects a workbook parser, a traceable data model and an interactive interface. The key decision: keep formal adopted totals separate from workbook account proposals and calculated amendment adjustments. Account detail has not been fully reconciled to the budget book.</p>
          <a className="mt-4 inline-block text-sm underline" href="/project-notes.html" target="_blank" rel="noreferrer">Read the project notes and source findings</a>
          <details className="mt-5 border-t border-[#dfe5df] pt-4">
            <summary className="cursor-pointer text-sm font-semibold">Data checks and unresolved differences</summary>
            <p className="mt-3 text-sm text-[#52656d]">Checks verify the exported data, not the authenticity or completeness of the source documents. A <strong>failed check</strong> means the exported data breaks an invariant it must satisfy. An <strong>unresolved difference</strong> means two sources disagree, or measure different things; these stay visible rather than being forced to match.</p>
            <ul className="mt-4 space-y-4">{data.validation.map((item) => { const state = checkState(item.status); return <li key={item.label} className="text-sm"><strong><span className={state.className}>{state.label}</span> · {item.label}</strong><p className="mt-1 leading-6 text-[#52656d]">{item.detail}</p></li>; })}</ul>
          </details>
        </section>

        <footer className="mt-8 border-t border-[#dfe5df] pt-6 pb-4">
          <div className="flex flex-col gap-4 text-xs leading-5 text-[#52656d] md:flex-row md:items-start md:justify-between">
            <div className="max-w-2xl">
              <p className="font-semibold text-[#52656d]">Data note</p>
              <p className="mt-1">{data.meta.sourceNote} {data.meta.workbookCaveat}</p>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              <ExternalSource source={data.sources.auditorPage}>Auditor notes</ExternalSource>
              <ExternalSource source={data.sources.openData}>Open Data Portal</ExternalSource>
              <ExternalSource source={data.sources.budgetPage}>Budget page</ExternalSource>
            </div>
          </div>
        </footer>
      </div>
      <RowSheet row={selectedRow} onClose={() => { setSelectedRow(null); writeQuery({ row: null }); }} />
    </main>
  );
}
