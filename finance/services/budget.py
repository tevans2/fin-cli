"""Budget goals: read them from the journal, roll them up, compare to actuals.

The source of truth is ``journal/budget-<year>.journal`` in the data repo, a
set of hledger periodic transaction rules. Those rules are what ``hledger
balance --budget`` measures actual spending against, so the numbers the
exports show and the numbers the ledger checks can never drift apart.

``config/budget-groups.yaml`` says only how the per-account goals are grouped
for presentation, plus the handful of figures that never pass through these
accounts (rent paid straight to the landlord, fees covered by the bursary).
"""

from __future__ import annotations

import re
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
