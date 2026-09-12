"""Budget goals: read them from the journal, roll them up, export them.

The source of truth is ``journal/budget-<year>.journal`` in the data repo, a
set of hledger periodic transaction rules. Those rules are what ``hledger
balance --budget`` measures actual spending against, so the numbers the
exports show and the numbers the ledger checks can never drift apart.

``config/budget-groups.yaml`` says only how the per-account goals are grouped
for presentation, plus the handful of figures that never pass through these
accounts (rent paid straight to the landlord, fees covered by the bursary).
"""

from __future__ import annotations

import html
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import yaml

from finance.config import load_app_config
from finance.services import hledger

# "~ monthly from 2027-02 to 2027-12  * Digs running costs"
_RULE = re.compile(
    r"^~\s*(?P<interval>\S+)"
    r"(?:\s+from\s+(?P<start>\d{4}-\d{2}(?:-\d{2})?))?"
    r"(?:\s+to\s+(?P<end>\d{4}-\d{2}(?:-\d{2})?))?"
    r"\s*(?:\*|;|$)"
)
# "    expenses:groceries      1433 ZAR   ; trailing comment"
_POSTING = re.compile(
    r"^\s+(?P<account>[A-Za-z][\w:-]*(?:\s[\w:-]+)*?)"
    r"\s{2,}(?P<sign>-?)(?P<amount>[\d,]+(?:\.\d+)?)\s*(?P<commodity>[A-Za-z]{3})?\s*(?:;.*)?$"
)

BALANCING_ACCOUNTS = {"equity:budget"}


class BudgetError(Exception):
    pass


# Two seasons, from the 2027 academic calendar. Short mid-semester recesses
# count as term (he stays in the digs); January, July and December are the
# months spent at home.
TERM_MONTHS = (2, 3, 4, 5, 6, 8, 9, 10, 11)   # 9 months in the digs
HOLIDAY_MONTHS = (1, 7, 12)                   # 3 months at home


@dataclass
class BudgetLine:
    """One account's goal, month by month.

    A line can be set by several periodic rules — a term rate for Feb-Nov and a
    different one for December and January — so the goal is held per month of
    the year rather than as a single figure.
    """

    account: str
    by_month: dict[int, Decimal] = field(default_factory=dict)

    def add(self, months: set[int], amount: Decimal) -> None:
        for month in months:
            self.by_month[month] = self.by_month.get(month, Decimal(0)) + amount

    @property
    def annual(self) -> Decimal:
        return sum(self.by_month.values(), Decimal(0))

    @property
    def months(self) -> int:
        """How many months of the year this line is actually funded in."""
        return sum(1 for v in self.by_month.values() if v)

    def _mean(self, months: tuple[int, ...]) -> Decimal:
        vals = [self.by_month.get(m, Decimal(0)) for m in months]
        return sum(vals, Decimal(0)) / len(vals) if vals else Decimal(0)

    @property
    def term_rate(self) -> Decimal:
        return self._mean(TERM_MONTHS)

    @property
    def holiday_rate(self) -> Decimal:
        return self._mean(HOLIDAY_MONTHS)

    @property
    def monthly(self) -> Decimal:
        """Even spread across the year, for annual-view reporting."""
        return self.annual / 12


SECTION_LABELS = {
    "monthly": "PAID EVERY MONTH",
    "term": "PAID ONLY DURING TERM \u2014 nothing in January, July or December",
}


@dataclass
class Group:
    label: str
    note: str
    annual: Decimal
    section: str = "monthly"
    essential: bool | None = None
    funder: str = ""
    rate: Decimal = Decimal(0)
    term_rate: Decimal = Decimal(0)
    holiday_rate: Decimal = Decimal(0)
    by_month: dict[int, Decimal] = field(default_factory=dict)
    accounts: list[str] = field(default_factory=list)   # journal lines with a goal
    patterns: list[str] = field(default_factory=list)   # what the config claims

    @property
    def monthly(self) -> Decimal:
        """Annual spread evenly over twelve months."""
        return (self.annual / 12).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    def rate_for(self, month: int) -> Decimal:
        return self.by_month.get(month, Decimal(0))


@dataclass
class Budget:
    year: int
    lines: list[BudgetLine]
    title: str = ""
    expense_groups: list[Group] = field(default_factory=list)
    income_groups: list[Group] = field(default_factory=list)
    paid_by_others: list[dict] = field(default_factory=list)
    funders: list[dict] = field(default_factory=list)

    def essentials(self) -> list[Group]:
        return [g for g in self.expense_groups if g.essential]

    def non_essentials(self) -> list[Group]:
        return [g for g in self.expense_groups if g.essential is False]

    def others_by_funder(self, funder: str) -> list[dict]:
        return [e for e in self.paid_by_others if e.get("funder") == funder]

    def income_by_funder(self, funder: str) -> list[Group]:
        return [g for g in self.income_groups if g.funder == funder]

    def expense_sections(self) -> list[tuple[str, str, list[Group]]]:
        """(key, heading, groups) in a fixed order, skipping empty sections."""
        out = []
        for key, heading in SECTION_LABELS.items():
            members = [g for g in self.expense_groups if g.section == key]
            if members:
                out.append((key, heading, members))
        return out

    @property
    def expense_total(self) -> Decimal:
        return sum((g.annual for g in self.expense_groups), Decimal(0))

    @property
    def income_total(self) -> Decimal:
        return sum((g.annual for g in self.income_groups), Decimal(0))

    @property
    def surplus(self) -> Decimal:
        return self.income_total - self.expense_total

    @property
    def others_total(self) -> Decimal:
        return sum((Decimal(str(x["amount"])) for x in self.paid_by_others), Decimal(0))

    @property
    def funders_total(self) -> Decimal:
        return sum((Decimal(str(x["amount"])) for x in self.funders), Decimal(0))

    @property
    def total_cost(self) -> Decimal:
        return self.expense_total + self.others_total


def _months_covered(start: str, end: str, year: int) -> set[int]:
    """Which months of `year` a rule's [start, end) range covers."""
    def ym(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
        if not value:
            return fallback
        parts = value.split("-")
        return int(parts[0]), int(parts[1])

    sy, sm = ym(start, (year, 1))
    ey, em = ym(end, (year + 1, 1))
    first = max(sy * 12 + sm, year * 12 + 1)
    last = min(ey * 12 + em, (year + 1) * 12 + 1)  # exclusive
    return {((n - 1) % 12) + 1 for n in range(first, last)}


def parse_budget_journal(path: Path, year: int) -> list[BudgetLine]:
    """Read periodic transaction rules into per-account goals."""
    if not path.exists():
        raise BudgetError(f"No budget journal at {path}")

    lines: dict[str, BudgetLine] = {}
    months: set[int] = set()
    in_rule = False

    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith(";"):
            if not stripped:
                in_rule = False
            continue

        if raw.startswith("~"):
            match = _RULE.match(stripped)
            if not match:
                raise BudgetError(f"Cannot parse periodic rule: {stripped!r}")
            if match.group("interval") != "monthly":
                raise BudgetError(
                    f"Only monthly budget rules are supported, got {match.group('interval')!r}"
                )
            months = _months_covered(match.group("start") or "", match.group("end") or "", year)
            in_rule = True
            continue

        if not in_rule or raw == stripped:  # a posting must be indented
            continue

        match = _POSTING.match(raw)
        if not match:
            continue
        account = match.group("account").strip()
        if account in BALANCING_ACCOUNTS:
            continue
        amount = Decimal(match.group("amount").replace(",", ""))
        if match.group("sign") == "-":
            amount = -amount
        lines.setdefault(account, BudgetLine(account=account)).add(months, amount)

    if not lines:
        raise BudgetError(f"No budget goals found in {path}")
    return list(lines.values())


def _match(account: str, patterns: list[str]) -> bool:
    return any(account == p or account.startswith(p + ":") for p in patterns)


def _build_groups(
    specs: list[dict], lines: list[BudgetLine], sign: int, sort: bool = False
) -> tuple[list[Group], set[str]]:
    groups: list[Group] = []
    claimed: set[str] = set()
    for spec in specs or []:
        patterns = spec.get("accounts", [])
        matched = [ln for ln in lines if _match(ln.account, patterns)]
        claimed.update(ln.account for ln in matched)
        groups.append(
            Group(
                label=spec["label"],
                note=spec.get("note", "") or "",
                section=spec.get("section", "monthly"),
                essential=spec.get("essential"),
                funder=spec.get("funder", "") or "",
                annual=sum((ln.annual for ln in matched), Decimal(0)) * sign,
                rate=sum((ln.monthly for ln in matched), Decimal(0)) * sign,
                term_rate=sum((ln.term_rate for ln in matched), Decimal(0)) * sign,
                holiday_rate=sum((ln.holiday_rate for ln in matched), Decimal(0)) * sign,
                by_month={
                    m: sum((ln.by_month.get(m, Decimal(0)) for ln in matched), Decimal(0)) * sign
                    for m in range(1, 13)
                },
                accounts=[ln.account for ln in matched],
                patterns=list(patterns),
            )
        )
    if sort:
        groups.sort(key=lambda g: -g.annual)
    return groups, claimed


def load_budget(year: int) -> Budget:
    """Read the journal goals and the grouping config into one object."""
    paths = load_app_config().paths
    lines = parse_budget_journal(paths.budget_journal(year), year)

    config: dict = {}
    if paths.budget_groups_config.exists():
        config = yaml.safe_load(paths.budget_groups_config.read_text()) or {}
    spec = config.get(year) or config.get(str(year)) or {}

    expense_lines = [ln for ln in lines if ln.account.startswith("expenses")]
    income_lines = [ln for ln in lines if ln.account.startswith("income")]

    expense_groups, claimed_exp = _build_groups(
        spec.get("expense_groups", []), expense_lines, 1, sort=True
    )
    income_groups, claimed_inc = _build_groups(spec.get("income_groups", []), income_lines, -1)

    # A goal that no group claims would silently vanish from the exports.
    orphans = sorted(
        {ln.account for ln in expense_lines if ln.annual} - claimed_exp
        | {ln.account for ln in income_lines if ln.annual} - claimed_inc
    )
    if orphans:
        raise BudgetError(
            "These budget accounts are not covered by any group in "
            f"{paths.budget_groups_config.name}: {', '.join(orphans)}"
        )

    return Budget(
        year=year,
        lines=lines,
        title=spec.get("title") or f"{year} Budget",
        expense_groups=expense_groups,
        income_groups=income_groups,
        paid_by_others=spec.get("paid_by_others", []) or [],
        funders=spec.get("funders", []) or [],
    )


@dataclass
class GroupActual:
    """One budget group measured against what was actually spent."""

    group: Group
    actual: Decimal
    goal: Decimal

    @property
    def variance(self) -> Decimal:
        return self.actual - self.goal

    @property
    def pct(self) -> int | None:
        if not self.goal:
            return None
        return int((self.actual / self.goal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def actual_by_account(begin: str, end: str) -> dict[str, Decimal]:
    """Flat per-account actual spend for a date window, at cost."""
    rows = hledger.read_csv(
        ["balance", "^expenses", "--flat", "--no-total", "--cost", "-b", begin, "-e", end]
    )
    out: dict[str, Decimal] = {}
    for row in rows:
        account = (row.get("account") or "").strip()
        raw = (row.get("balance") or "").strip()
        if not account or not raw:
            continue
        total = Decimal(0)
        for part in raw.split(","):
            cleaned = re.sub(r"[^\d.\-]", "", part)
            if cleaned not in ("", "-", "."):
                total += Decimal(cleaned)
        out[account] = total
    return out


def month_window(
    months: int = 1, today: date | None = None
) -> tuple[str, str, list[int]]:
    """The last `months` calendar months as [begin, end), plus their months-of-year."""
    today = today or date.today()
    end_y, end_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    total = today.year * 12 + today.month - (months - 1)
    begin_y, begin_m = divmod(total - 1, 12)
    covered = [((n - 1) % 12) + 1 for n in range(total, total + months)]
    return f"{begin_y}-{begin_m + 1:02d}-01", f"{end_y}-{end_m:02d}-01", covered


def compare(
    budget: Budget, begin: str, end: str, months: list[int] | int
) -> list[GroupActual]:
    """Actual spend against the budget goals for the specific months in the window.

    `months` is the list of months-of-year the window covers, so a December is
    measured against the December goal rather than an annual average.
    """
    covered = list(range(1, months + 1)) if isinstance(months, int) else months
    actuals = actual_by_account(begin, end)
    results: list[GroupActual] = []
    for group in budget.expense_groups:
        spent = sum(
            (amount for account, amount in actuals.items() if _match(account, group.patterns)),
            Decimal(0),
        )
        goal = sum((group.rate_for(m) for m in covered), Decimal(0))
        results.append(GroupActual(group=group, actual=spent, goal=goal))
    return results


def unbudgeted(budget: Budget, begin: str, end: str) -> dict[str, Decimal]:
    """Real spending that no budget group claims.

    Travel, device replacements and side projects are deliberately funded from
    savings rather than the monthly budget, so they carry no goal. They are
    still money out the door, and a comparison that quietly dropped them would
    read better than the truth.
    """
    actuals = actual_by_account(begin, end)
    claimed = {
        account
        for group in budget.expense_groups
        for account in actuals
        if _match(account, group.patterns)
    }
    return {a: v for a, v in actuals.items() if v and a not in claimed}


def performance(year: int, depth: int | None = None, monthly: bool = True) -> str:
    """hledger's actual-vs-goal report for the budget year."""
    argv = ["balance", "--budget", "^expenses", "^income"]
    if monthly:
        argv.append("-M")
    if depth:
        argv += ["--depth", str(depth)]
    argv += ["-b", f"{year}-01-01", "-e", f"{year + 1}-01-01"]
    _code, output = hledger.run_text(argv)
    return output


# --------------------------------------------------------------------------
# exports
# --------------------------------------------------------------------------

def _round(value: Decimal) -> Decimal:
    """Whole rands, half up. Monthly goals carry cents; budgets do not."""
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _fmt(value: Decimal) -> str:
    return f"{_round(value):,.0f}"


def export_xlsx(budget: Budget, path: Path) -> Path:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.worksheet.properties import PageSetupProperties
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise BudgetError("openpyxl is required for xlsx export (pip install openpyxl)") from exc

    ink, accent, green = "1A1D23", "274472", "1B6E4A"
    head_fill = PatternFill("solid", fgColor=accent)
    sec_fill = PatternFill("solid", fgColor="EEF2F8")
    tot_fill = PatternFill("solid", fgColor="F2F4F7")
    thin = Side(style="thin", color="DCE0E6")
    med = Side(style="medium", color=ink)
    ncol = 5

    ref: dict[str, int] = {}
    wb = Workbook()
    ws = wb.active or wb.create_sheet()
    ws.title = f"{budget.year} Budget"
    row = 1

    def title(text: str, size: int) -> None:
        nonlocal row
        ws.cell(row=row, column=1, value=text).font = Font(bold=True, size=size, color=ink)
        row += 1

    def header() -> None:
        nonlocal row
        for i, label in enumerate(
            ["Item", "Term month", "Holiday month", "Per year", "Notes"], 1
        ):
            cell = ws.cell(row=row, column=i, value=label)
            cell.fill = head_fill
            cell.font = Font(bold=True, color="FFFFFF", size=10)
            cell.alignment = Alignment(
                horizontal="left" if i in (1, 5) else "right", vertical="center"
            )
        ws.row_dimensions[row].height = 22
        row += 1

    def section(text: str) -> None:
        nonlocal row
        ws.cell(row=row, column=1, value=text).font = Font(bold=True, size=10, color=accent)
        for i in range(1, ncol + 1):
            ws.cell(row=row, column=i).fill = sec_fill
            ws.cell(row=row, column=i).border = Border(bottom=thin)
        row += 1

    def item(
        label: str,
        annual: Decimal,
        note: str = "",
        term: Decimal | None = None,
        holiday: Decimal | None = None,
    ) -> int:
        nonlocal row
        ws.cell(row=row, column=1, value=label).font = Font(size=10)
        for col, val in ((2, term), (3, holiday)):
            if val is not None:
                ws.cell(row=row, column=col, value=int(_round(val))).number_format = "#,##0"
        cell = ws.cell(row=row, column=4, value=int(_round(annual)))
        cell.number_format = "#,##0"
        ws.cell(row=row, column=5, value=note).font = Font(size=9, color="6B7280")
        for i in range(1, ncol + 1):
            ws.cell(row=row, column=i).border = Border(bottom=thin)
        ref[label] = row
        row += 1
        return row - 1

    def total(
        label: str,
        first: int,
        last: int,
        note: str = "",
        big: bool = False,
        cols: tuple[str, ...] = ("D",),
    ) -> int:
        nonlocal row
        size = 11 if big else 10
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=size)
        for col in cols:
            cell = ws.cell(row=row, column=ord(col) - 64, value=f"=SUM({col}{first}:{col}{last})")
            cell.number_format = "#,##0"
            cell.font = Font(bold=True, size=size)
        ws.cell(row=row, column=5, value=note).font = Font(size=9, color="6B7280")
        for i in range(1, ncol + 1):
            ws.cell(row=row, column=i).fill = tot_fill
            ws.cell(row=row, column=i).border = Border(top=med, bottom=thin)
        row += 1
        return row - 1

    title(budget.title, 16)
    row += 1
    header()

    sub_rows: list[int] = []
    for _key, heading, members in budget.expense_sections():
        section(heading)
        first = row
        for group in members:
            item(group.label, group.annual, group.note, group.term_rate, group.holiday_rate)
        sub_rows.append(total("Subtotal", first, row - 1, cols=("B", "C", "D")))
        row += 1
    ws.cell(row=row, column=1, value="TOTAL EXPENSES").font = Font(bold=True, size=12)
    for col in ("B", "C", "D"):
        expr = "+".join(f"{col}{n}" for n in sub_rows)
        cell = ws.cell(row=row, column=ord(col) - 64, value=f"={expr}")
        cell.number_format = "#,##0"
        cell.font = Font(bold=True, size=12)
    for i in range(1, ncol + 1):
        ws.cell(row=row, column=i).fill = tot_fill
        ws.cell(row=row, column=i).border = Border(top=med, bottom=med)
    exp_row = row
    row += 1
    row += 1

    section("MY INCOME")
    first = row
    for group in budget.income_groups:
        item(group.label, group.annual, group.note)
    inc_row = total("Total income", first, row - 1)
    row += 1

    section("SUMMARY")
    for label, formula in (("Income", f"=D{inc_row}"), ("Expenses", f"=D{exp_row}")):
        ws.cell(row=row, column=1, value=label).font = Font(size=10)
        ws.cell(row=row, column=4, value=formula).number_format = "#,##0"
        for i in range(1, ncol + 1):
            ws.cell(row=row, column=i).border = Border(bottom=thin)
        row += 1
    ws.cell(row=row, column=1, value="Surplus to savings").font = Font(bold=True, size=11)
    cell = ws.cell(row=row, column=4, value=f"=D{inc_row}-D{exp_row}")
    cell.number_format = "#,##0"
    cell.font = Font(bold=True, size=11, color=green)
    for i in range(1, ncol + 1):
        ws.cell(row=row, column=i).fill = tot_fill
        ws.cell(row=row, column=i).border = Border(top=med, bottom=thin)
    row += 2

    if budget.paid_by_others:
        section("PAID DIRECTLY BY OTHERS")
        first = row
        for entry in budget.paid_by_others:
            item(entry["label"], Decimal(str(entry["amount"])), entry.get("note", "") or "")
        sub_row = total("Subtotal", first, row - 1)
        ws.cell(row=row, column=1, value="TOTAL COST OF MY YEAR").font = Font(bold=True, size=11)
        cell = ws.cell(row=row, column=4, value=f"=D{exp_row}+D{sub_row}")
        cell.number_format = "#,##0"
        cell.font = Font(bold=True, size=11)
        for i in range(1, ncol + 1):
            ws.cell(row=row, column=i).fill = tot_fill
            ws.cell(row=row, column=i).border = Border(top=med, bottom=med)
        cost_row = row
        row += 2
    else:
        cost_row = exp_row

    if budget.funders:
        section("WHO FUNDS IT")
        first = row
        for entry in budget.funders:
            item(entry["label"], Decimal(str(entry["amount"])), entry.get("note", "") or "")
        fund_row = total("Total funding", first, row - 1)
        ws.cell(row=row, column=1, value="Funding less cost").font = Font(size=10, italic=True)
        cell = ws.cell(row=row, column=4, value=f"=D{fund_row}-D{cost_row}")
        cell.number_format = "#,##0"
        cell.font = Font(size=10, italic=True)
        ws.cell(row=row, column=5, value="Equals the surplus above").font = Font(
            size=9, color="6B7280"
        )
        row += 1

    for col, width in zip("ABCDE", [36, 12, 11, 12, 50]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A4"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1

    ref["__expenses__"] = exp_row
    ref["__income__"] = inc_row
    _funding_sheet(wb, budget, ref, ws.title)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path



def _funding_sheet(wb, budget: Budget, ref: dict[str, int], budget_sheet: str) -> None:
    """A second sheet proposing how the cost is split, every figure a live
    reference back to the budget sheet so the two can never disagree."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.properties import PageSetupProperties

    ink, accent, green = "1A1D23", "274472", "1B6E4A"
    head_fill = PatternFill("solid", fgColor=accent)
    sec_fill = PatternFill("solid", fgColor="EEF2F8")
    tot_fill = PatternFill("solid", fgColor="F2F4F7")
    thin = Side(style="thin", color="DCE0E6")
    med = Side(style="medium", color=ink)
    ws = wb.create_sheet("Funding")
    q = f"'{budget_sheet}'!D"          # the budget sheet's annual column
    row = 1

    def title(text, size, bold=True, colour=ink):
        nonlocal row
        ws.cell(row=row, column=1, value=text).font = Font(bold=bold, size=size, color=colour)
        row += 1

    def header():
        nonlocal row
        for i, label in enumerate(["Item", "Annual", "Notes"], 1):
            c = ws.cell(row=row, column=i, value=label)
            c.fill = head_fill
            c.font = Font(bold=True, color="FFFFFF", size=10)
            c.alignment = Alignment(horizontal="left" if i in (1, 3) else "right",
                                    vertical="center")
        ws.row_dimensions[row].height = 22
        row += 1

    def section(text):
        nonlocal row
        ws.cell(row=row, column=1, value=text).font = Font(bold=True, size=10, color=accent)
        for i in range(1, 4):
            ws.cell(row=row, column=i).fill = sec_fill
            ws.cell(row=row, column=i).border = Border(bottom=thin)
        row += 1

    def line(label, formula, note=""):
        nonlocal row
        ws.cell(row=row, column=1, value=label).font = Font(size=10)
        ws.cell(row=row, column=2, value=formula).number_format = "#,##0"
        ws.cell(row=row, column=3, value=note).font = Font(size=9, color="6B7280")
        for i in range(1, 4):
            ws.cell(row=row, column=i).border = Border(bottom=thin)
        row += 1
        return row - 1

    def total(label, formula, note="", big=False, green_val=False):
        nonlocal row
        size = 12 if big else 10
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=size)
        c = ws.cell(row=row, column=2, value=formula)
        c.number_format = "#,##0"
        c.font = Font(bold=True, size=size, color=green if green_val else ink)
        ws.cell(row=row, column=3, value=note).font = Font(size=9, color="6B7280")
        for i in range(1, 4):
            ws.cell(row=row, column=i).fill = tot_fill
            ws.cell(row=row, column=i).border = Border(top=med, bottom=med if big else thin)
        row += 1
        return row - 1

    def r(label):                       # a live reference to the budget sheet
        return f"={q}{ref[label]}"

    title(f"{budget.year} Funding Proposal", 16)
    title("How the cost of my year could be split. Every figure below is pulled "
          "from the budget sheet.", 9, False, "6B7280")
    row += 1
    header()

    others = budget.paid_by_others
    mom_direct = [e for e in others if e.get("funder") == "mom"]
    dad_direct = [e for e in others if e.get("funder") == "dad"]
    bursary_direct = [e for e in others if e.get("funder") == "bursary"]

    section("WHAT MY YEAR COSTS")
    cost_rows = [line("My living costs", f"={q}{ref['__expenses__']}", "total from the budget sheet")]
    for e in others:
        cost_rows.append(line(e["label"], r(e["label"])))
    cost_row = total("TOTAL COST OF MY YEAR",
                     "=" + "+".join(f"B{x}" for x in cost_rows), big=True)
    row += 1

    section("ESSENTIALS \u2014 split evenly between Mom and Dad")
    ess_rows = []
    for g in budget.essentials():
        ess_rows.append(line(g.label, r(g.label)))
    for e in mom_direct + dad_direct:
        ess_rows.append(line(e["label"], r(e["label"])))
    ess_row = total("Total essentials", f"=SUM(B{ess_rows[0]}:B{ess_rows[-1]})")
    each_row = total("Each parent", f"=B{ess_row}/2", "half of the essentials")
    row += 1

    section("NON-ESSENTIALS \u2014 I fund these myself")
    non_rows = [line(g.label, r(g.label)) for g in budget.non_essentials()]
    non_row = total("Total non-essentials", f"=SUM(B{non_rows[0]}:B{non_rows[-1]})")
    row += 1

    section("WHAT I BRING TO THE TABLE")
    cash_rows = [line(g.label, r(g.label)) for g in budget.income_by_funder("me")]
    fee_rows = [line(e["label"], r(e["label"]),
                     "paid straight to the university \u2014 never reaches my account")
                for e in bursary_direct]
    bring_rows = cash_rows + fee_rows
    bring_row = total("Total I bring", "=" + "+".join(f"B{x}" for x in bring_rows))
    row += 1

    section("THE PROPOSED SPLIT")
    burs = "+".join(f"B{ref[e['label']]}" for e in bursary_direct) if bursary_direct else "0"
    me_row = line("Me", f"=B{non_row}+{'+'.join(f'B{x}' for x in bring_rows[len(budget.income_by_funder('me')):])}",
                  "my non-essentials + the bursary fees")
    mom_row = line("Mom", f"=B{each_row}")
    dad_row = line("Dad", f"=B{each_row}")
    split_row = total("Total funded", f"=B{me_row}+B{mom_row}+B{dad_row}",
                      "must equal the total cost above")
    row += 1

    # Derive the saving from cash that actually moves. The bursary's fees appear
    # on both sides above and cancel, which makes "brings less contributes" a
    # correct but confusing way to show it.
    section("WHAT I ACTUALLY SAVE \u2014 cash in and out")
    cash_in = [
        line(g.label, f"=B{n}")
        for g, n in zip(budget.income_by_funder("me"), cash_rows)
    ]
    cash_in.append(
        line("Allowance from Mom and Dad for my essentials",
             f"=SUM(B{ess_rows[0]}:B{ess_rows[len(budget.essentials()) - 1]})",
             "the essential living lines above")
    )
    in_row = total("Cash I receive", "=" + "+".join(f"B{x}" for x in cash_in))
    out_row = line("My living costs", f"=-{q}{ref['__expenses__']}")
    sav_row = total("My saving", f"=B{in_row}+B{out_row}",
                    "cash in, less what I spend", big=True, green_val=True)
    row += 1

    section("FOR COMPARISON \u2014 the current arrangement")
    cur_sav = line("My saving today", f"={q}{ref['__income__']}-{q}{ref['__expenses__']}",
                   "income less my living costs")
    cur_me = line("Me \u2014 today", f"=B{bring_row}-B{cur_sav}", "saving is not contributing")
    # these must reference the BUDGET sheet (q), not column B of this one
    mom_parts = [f"{q}{ref[g.label]}" for g in budget.income_by_funder("mom")]
    mom_parts += [f"{q}{ref[e['label']]}" for e in mom_direct]
    cur_mom = line("Mom \u2014 today", "=" + "+".join(mom_parts),
                   "allowance plus what she pays directly")
    dad_parts = [f"{q}{ref[e['label']]}" for e in dad_direct]
    cur_dad = line("Dad \u2014 today", "=" + "+".join(dad_parts))
    total("Total \u2014 today", f"=B{cur_me}+B{cur_mom}+B{cur_dad}")

    for col, width in zip("ABC", [40, 14, 46]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A5"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1

_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root {{
    --paper:#fff; --ground:#F7F8FA; --ink:#1A1D23; --soft:#404754;
    --muted:#6B7280; --faint:#98A0AC; --rule:#DCE0E6; --hard:#B9C0CA;
    --accent:#274472; --accent-lt:#EEF2F8; --pos:#1B6E4A;
    --serif:"Newsreader",Georgia,serif;
    --sans:"Public Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:0 1.5rem 5rem; background:var(--ground); color:var(--ink);
         font-family:var(--sans); font-size:1rem; line-height:1.6; -webkit-font-smoothing:antialiased; }}
  .sheet {{ max-width:860px; margin:0 auto; background:var(--paper); padding:3rem 3.25rem 3.5rem;
            border:1px solid var(--rule); }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:1.5rem; margin-bottom:2.25rem; }}
  .kicker {{ font-family:var(--mono); font-size:.74rem; letter-spacing:.11em; text-transform:uppercase;
             color:var(--accent); margin:0 0 .9rem; }}
  h1 {{ font-family:var(--serif); font-size:2.3rem; font-weight:500; line-height:1.12;
        letter-spacing:-.015em; margin:0 0 .7rem; text-wrap:balance; }}
  .lede {{ font-family:var(--serif); font-size:1.1rem; line-height:1.55; color:var(--soft);
           margin:0; max-width:56ch; }}
  h2 {{ font-family:var(--serif); font-size:1.4rem; font-weight:500; letter-spacing:-.01em;
        margin:2.75rem 0 .3rem; padding-bottom:.45rem; border-bottom:1px solid var(--hard); }}
  p {{ margin:0 0 1rem; max-width:64ch; }}
  .num {{ font-family:var(--mono); font-variant-numeric:tabular-nums; font-weight:500; }}
  .tw {{ overflow-x:auto; margin:1.25rem 0 .6rem; }}
  table {{ width:100%; border-collapse:collapse; font-size:.925rem; min-width:420px; }}
  caption {{ text-align:left; font-family:var(--mono); font-size:.72rem; letter-spacing:.07em;
             text-transform:uppercase; color:var(--muted); padding-bottom:.5rem; }}
  th {{ font-family:var(--mono); font-size:.72rem; font-weight:500; letter-spacing:.05em;
        text-transform:uppercase; color:var(--muted); text-align:right; padding:.4rem .65rem;
        border-bottom:1px solid var(--ink); white-space:nowrap; vertical-align:bottom; }}
  th:first-child {{ text-align:left; }}
  td {{ padding:.44rem .65rem; border-bottom:1px solid var(--rule); text-align:right;
        font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap; }}
  td:first-child {{ text-align:left; font-family:var(--sans); white-space:normal; min-width:14rem; }}
  td .sub {{ display:block; font-size:.78rem; color:var(--muted); line-height:1.35; }}
  .thsub {{ display:block; font-weight:400; text-transform:none; letter-spacing:0; color:var(--faint); }}
  td.zero {{ color:var(--faint); }}
  tr.sechead td {{ font-family:var(--mono); font-size:.7rem; letter-spacing:.06em;
    text-transform:uppercase; color:var(--accent); background:var(--accent-lt);
    padding-top:.7rem; padding-bottom:.4rem; border-bottom:1px solid var(--hard); }}
  tr.secsub td {{ font-weight:600; border-top:1px solid var(--hard); }}
  tfoot td {{ border-bottom:none; border-top:2px solid var(--ink); font-weight:600; padding-top:.55rem; }}
  tfoot tr.mo td {{ border-top:1px solid var(--rule); font-weight:400; color:var(--muted); font-size:.85rem; }}
  tr.rule-top td {{ border-top:1px solid var(--hard); }}
  .pos {{ color:var(--pos); }}
  .box {{ background:var(--accent-lt); border-left:3px solid var(--accent); padding:1.15rem 1.35rem;
          margin:1.5rem 0; max-width:64ch; }}
  .box p:last-child {{ margin-bottom:0; }}
  .box .lbl {{ font-family:var(--mono); font-size:.72rem; letter-spacing:.09em; text-transform:uppercase;
               color:var(--accent); margin:0 0 .45rem; }}
  .bar {{ display:flex; height:2.4rem; border:1px solid var(--hard); overflow:hidden; margin:1.3rem 0 .8rem; }}
  .bar div {{ display:flex; align-items:center; justify-content:center; font-family:var(--mono);
              font-size:.68rem; font-weight:500; color:#fff; white-space:nowrap; overflow:hidden; }}
  .key {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:.5rem 1.5rem;
          font-size:.9rem; margin-bottom:1.5rem; }}
  .key div {{ display:flex; align-items:baseline; gap:.5rem; }}
  .key i {{ flex:0 0 auto; width:.68rem; height:.68rem; }}
  .key .v {{ font-family:var(--mono); font-variant-numeric:tabular-nums; font-weight:500; margin-left:auto; }}
  footer {{ margin-top:2.75rem; padding-top:1.1rem; border-top:1px solid var(--rule);
            font-family:var(--mono); font-size:.72rem; color:var(--faint); line-height:1.6; }}
  @media (max-width:640px) {{
    body {{ padding:0 .75rem 3rem; }} .sheet {{ padding:2rem 1.25rem 2.5rem; }} h1 {{ font-size:1.85rem; }}
  }}
  @media print {{
    body {{ background:#fff; padding:0; font-size:10.5pt; }}
    .sheet {{ border:none; max-width:none; padding:0; }}
    h2 {{ break-after:avoid; }} table, .box, .bar {{ break-inside:avoid; }}
  }}
</style>
</head>
<body>
<div class="sheet">
  <header>
    <p class="kicker">{kicker}</p>
    <h1>{title}</h1>
    <p class="lede">What next year costs, where the money comes from, and what I expect to have
      left over. Built from my actual bank records, not estimates.</p>
  </header>

  <h2>The short version</h2>
  <div class="tw"><table>
    <caption>{year} at a glance</caption>
    <tbody>
      <tr><td>My living expenses (everything I pay for myself)</td><td>{expense_total}</td></tr>
      <tr><td>My income (earnings, bursary, allowance)</td><td>{income_total}</td></tr>
      <tr class="rule-top"><td>Expected surplus, going into savings</td><td class="pos">{surplus}</td></tr>
    </tbody>
    <tfoot><tr class="mo"><td>Per month &mdash; term / holiday</td><td>{term_month} / {holiday_month}</td></tr></tfoot>
  </table></div>
  {cost_note}{season_note}

  <h2>What I spend</h2>
  <div class="tw"><table>
    <caption>Living expenses, {year} plan</caption>
    <thead><tr><th scope="col">Category</th>
      <th scope="col">Term<br><span class="thsub">9 months</span></th>
      <th scope="col">Holiday<br><span class="thsub">Jan / Jul / Dec</span></th>
      <th scope="col">Per year</th></tr></thead>
    <tbody>
{expense_rows}    </tbody>
    <tfoot><tr><td>Total</td><td>{term_month}</td><td>{holiday_month}</td><td>{expense_total}</td></tr></tfoot>
  </table></div>

  <h2>Where the money comes from</h2>
  <div class="tw"><table>
    <caption>{year} income</caption>
    <thead><tr><th scope="col">Source</th><th scope="col">Per year</th></tr></thead>
    <tbody>
{income_rows}    </tbody>
    <tfoot><tr><td>Total</td><td>{income_total}</td></tr></tfoot>
  </table></div>
{others_section}{funders_section}
  <footer>{footer}</footer>
</div>
</body>
</html>
"""

_FUND_COLOURS = ["#40474F", "#9C5410", "#274472", "#1B6E4A", "#6B7280"]


def render_html(budget: Budget, kicker: str = "", footer: str = "") -> str:
    def section_rows(sections: list[tuple[str, str, list[Group]]]) -> str:
        out = []
        for _key, heading, members in sections:
            out.append(
                f'      <tr class="sechead"><td colspan="4">{html.escape(heading)}</td></tr>\n'
            )
            out.append(rows(members, True))
            t = sum((_round(g.term_rate) for g in members), Decimal(0))
            h = sum((_round(g.holiday_rate) for g in members), Decimal(0))
            a = sum((_round(g.annual) for g in members), Decimal(0))
            zh = ' class="zero"' if not h else ""
            out.append(
                f'      <tr class="secsub"><td>Subtotal</td><td>{_fmt(t)}</td>'
                f'<td{zh}>{_fmt(h)}</td><td>{_fmt(a)}</td></tr>\n'
            )
        return "".join(out)

    def rows(groups: list[Group], seasonal: bool) -> str:
        out = []
        for g in groups:
            sub = f'<span class="sub">{html.escape(g.note)}</span>' if g.note else ""
            if seasonal:
                zh = ' class="zero"' if not g.holiday_rate else ""
                cells = (
                    f"<td>{_fmt(g.term_rate)}</td>"
                    f"<td{zh}>{_fmt(g.holiday_rate)}</td>"
                    f"<td>{_fmt(g.annual)}</td>"
                )
            else:
                cells = f"<td>{_fmt(g.annual)}</td>"
            out.append(
                f"      <tr>\n        <td>{html.escape(g.label)}{sub}</td>\n        {cells}\n      </tr>\n"
            )
        return "".join(out)

    cost_note = ""
    others_section = ""
    if budget.paid_by_others:
        cost_note = (
            f"  <p>Rent, university fees and car costs sit outside that "
            f'R<span class="num">{_fmt(budget.expense_total)}</span> because they are paid '
            f"directly by other people and never pass through my account. Adding them in, the "
            f'full cost of my year is <span class="num">R{_fmt(budget.total_cost)}</span>.</p>\n'
        )
        body = "".join(
            f'      <tr><td>{html.escape(e["label"])}'
            + (f'<span class="sub">{html.escape(e["note"])}</span>' if e.get("note") else "")
            + f'</td><td>{_fmt(Decimal(str(e["amount"])))}</td></tr>\n'
            for e in budget.paid_by_others
        )
        others_section = f"""
  <h2>The full cost of my year</h2>
  <div class="tw"><table>
    <caption>Total cost, {budget.year}</caption>
    <tbody>
      <tr><td>My living expenses (above)</td><td>{_fmt(budget.expense_total)}</td></tr>
{body}    </tbody>
    <tfoot><tr><td>Total cost of the year</td><td>{_fmt(budget.total_cost)}</td></tr></tfoot>
  </table></div>
"""

    funders_section = ""
    if budget.funders:
        bars, keys = [], []
        for i, entry in enumerate(budget.funders):
            colour = _FUND_COLOURS[i % len(_FUND_COLOURS)]
            amount = Decimal(str(entry["amount"]))
            label = html.escape(entry["label"])
            bars.append(f'<div style="flex:{int(amount)} 0 0;background:{colour}">{label}</div>')
            note = f" — {html.escape(entry['note'])}" if entry.get("note") else ""
            keys.append(
                f'<div><i style="background:{colour}"></i><span>{label}{note}</span>'
                f'<span class="v">{_fmt(amount)}</span></div>'
            )
        alt = "; ".join(
            f"{html.escape(e['label'])} R{_fmt(Decimal(str(e['amount'])))}" for e in budget.funders
        )
        funders_section = f"""
  <h2>Who funds it</h2>
  <div class="bar" role="img" aria-label="Funding split: {alt}.">{''.join(bars)}</div>
  <div class="key">{''.join(keys)}</div>
  <div class="box">
    <p class="lbl">Worth saying plainly</p>
    <p>Total funding comes to <span class="num">R{_fmt(budget.funders_total)}</span> against
      <span class="num">R{_fmt(budget.total_cost)}</span> of cost, leaving about
      <span class="num">R{_fmt(budget.funders_total - budget.total_cost)}</span>. That surplus goes
      into savings rather than into living, which I would rather say up front than have discovered.</p>
  </div>
"""

    # Sum the ROUNDED per-line figures, so the printed column adds up to the
    # printed total exactly as the spreadsheet's live SUM() does.
    term_month = sum((_round(g.term_rate) for g in budget.expense_groups), Decimal(0))
    holiday_month = sum((_round(g.holiday_rate) for g in budget.expense_groups), Decimal(0))
    term_only = [g for g in budget.expense_groups if g.section == "term"]
    term_only_month = sum((_round(g.term_rate) for g in term_only), Decimal(0))
    term_only_year = sum((_round(g.annual) for g in term_only), Decimal(0))
    term_only = [g for g in budget.expense_groups if g.section == "term"]
    term_only_month = sum((_round(g.term_rate) for g in term_only), Decimal(0))
    term_only_year = sum((_round(g.annual) for g in term_only), Decimal(0))
    season_note = (
        f'  <p>The year splits in two, from the university calendar. I am in the digs for '
        f'<strong>nine months</strong> (February to June and August to November) and at home '
        f'for <strong>three</strong> &mdash; January, July and December. Counted in days it is '
        f'283 in the digs and 82 at home. The short mid-semester recesses count as term, '
        f'since I stay in Stellenbosch.</p>\n'
        f'  <p><strong>The electricity and the cleaner are not paid in January, July or '
        f'December.</strong> The flat is empty, so there is no prepaid electricity to buy and '
        f'Andiswe does not come. The same goes for laundry, the gym, printing and household '
        f'bits. Those term-only costs are <span class="num">R{_fmt(term_only_month)}</span> a '
        f'month, <span class="num">R{_fmt(term_only_year)}</span> for the year, and they are '
        f'listed separately below so it is clear they are paid nine times, not twelve.</p>\n'
        f'  <p>A term month costs <span class="num">R{_fmt(term_month)}</span> and a holiday '
        f'month <span class="num">R{_fmt(holiday_month)}</span>. The holiday month is the '
        f'<em>more</em> expensive of the two, even though all of those digs costs stop &mdash; '
        f'because I socialise more when I am home and Christmas presents land. That is the '
        f'honest answer to why the budget is not simply nine twelfths of a year.</p>\n'
    )
    return _HTML.format(
        term_month=_fmt(term_month),
        holiday_month=_fmt(holiday_month),
        season_note=season_note,
        title=html.escape(budget.title),
        year=budget.year,
        kicker=html.escape(kicker or f"Prepared {date.today():%d %B %Y}"),
        expense_total=_fmt(budget.expense_total),
        income_total=_fmt(budget.income_total),
        surplus=_fmt(budget.surplus),
        expense_month=_fmt((budget.expense_total / 12).quantize(Decimal("1"))),
        expense_rows=section_rows(budget.expense_sections()),
        income_rows=rows(budget.income_groups, False),
        cost_note=cost_note,
        others_section=others_section,
        funders_section=funders_section,
        footer=html.escape(
            footer
            or "Generated from journal/budget-{}.journal in the finance data repo. "
            "All amounts in Rand.".format(budget.year)
        ),
    )


def export_html(budget: Budget, path: Path, **kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(budget, **kwargs))
    return path


_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "chromium",
    "google-chrome",
]


def export_pdf(html_path: Path, pdf_path: Path) -> Path:
    """Render an exported HTML page to PDF using headless Chrome."""
    from shutil import which

    binary = next(
        (p for p in _CHROME_PATHS if Path(p).exists() or which(p)),
        None,
    )
    if not binary:
        raise BudgetError("No Chrome/Chromium found for PDF export; the HTML export still works")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            binary, "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
    )
    if not pdf_path.exists():
        raise BudgetError(f"PDF export failed: {result.stderr.strip()[:300]}")
    return pdf_path
