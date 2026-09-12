"""FastAPI web UI for the finance app.

This layer is deliberately thin: every route delegates to `finance/services/*`,
exactly like the CLI does. It renders server-side with Jinja2 and uses HTMX for
partial swaps so the categorize flow feels as snappy as the TUI.
"""

from __future__ import annotations

import json
import shlex
from datetime import date
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from finance.models.transaction import TransactionSplit
from finance.services import budget as budget_service
from finance.services import hledger
from finance.services.categorize import (
    UNKNOWN_CATEGORIES,
    gather_accounts,
    list_banks,
    suggestion_for,
)
from finance.services.journal import build_bank_journal
from finance.services.reports import CASHFLOW_FILTERS, INVESTMENTS_FILTERS
from finance.services.review import create_alias
from finance.services.transactions import (
    filter_unknown_transactions,
    update_transaction_category,
    update_transaction_splits,
)
from finance.web import data

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="finance")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["money"] = lambda v: f"{v:,.2f}" if v is not None else "-"
templates.env.filters["money0"] = lambda v: f"{v:,.0f}" if v is not None else "-"

# key, label, hledger command, is_balance_family (supports --tree/-S).
# "transactions" is special: it renders the editable table, not hledger text.
REPORT_TYPES = [
    ("bs", "Balance sheet", "balancesheet", True),
    ("is", "Income statement", "incomestatement", True),
    ("balance", "Balance", "balance", True),
    ("register", "Register", "register", False),
    ("transactions", "Transactions (editable)", "", False),
]
_REPORT_BY_KEY = {k: (label, cmd, is_bal) for k, label, cmd, is_bal in REPORT_TYPES}


def _report_argv(p: dict) -> list[str]:
    """Assemble an hledger argv list from the panel's parameters."""
    _label, cmd, is_bal = _REPORT_BY_KEY.get(p["report"], _REPORT_BY_KEY["bs"])
    argv: list[str] = [cmd]
    if p.get("accounts", "").strip():
        argv += p["accounts"].split()
    if p.get("period") in ("W", "M", "Q", "Y"):
        argv.append(f"-{p['period']}")
    if p.get("begin"):
        argv += ["-b", p["begin"]]
    if p.get("end"):
        argv += ["-e", p["end"]]
    if p.get("depth"):
        argv += ["--depth", str(p["depth"])]
    if is_bal:
        argv.append("--tree" if p.get("layout", "tree") == "tree" else "--flat")
        if p.get("sort"):
            argv.append("-S")
    if p.get("value"):
        argv += ["-X", "ZAR", "--value=now"]
    if p.get("scope") == "cashflow":
        argv += CASHFLOW_FILTERS
    elif p.get("scope") == "investments":
        argv += INVESTMENTS_FILTERS
    return argv

# In-memory, per-process record of transactions skipped this session. Skip is
# intentionally transient (a skipped txn is still uncategorized on disk); this
# just keeps it out of the queue until the server restarts or skips are reset.
_skipped: dict[str, set[str]] = {}


def _skip_set(bank: str) -> set[str]:
    return _skipped.setdefault(bank, set())


def _queue(bank: str, category: str = "both"):
    skipped = _skip_set(bank)
    return [r for r in filter_unknown_transactions(bank, category) if r.id not in skipped]


def _render_card(request: Request, bank: str) -> HTMLResponse:
    queue = _queue(bank)
    total_unknown = len(filter_unknown_transactions(bank))
    done = total_unknown - len(queue)  # categorized + skipped this session
    record = queue[0] if queue else None
    ctx: dict = {
        "bank": bank,
        "remaining": len(queue),
        "position": done + 1 if record else done,
        "total": total_unknown,
    }
    if record is not None:
        ctx["record"] = record
        ctx["suggestion"] = suggestion_for(bank, record)
        return templates.TemplateResponse(request, "_card.html", ctx)
    return templates.TemplateResponse(request, "_done.html", ctx)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    banks = [
        {"name": bank, "unknown": len(filter_unknown_transactions(bank))}
        for bank in list_banks()
    ]
    return templates.TemplateResponse(
        request, "overview.html", {"banks": banks, "worth": data.net_worth()}
    )


@app.get("/transactions", response_class=HTMLResponse)
def transactions(
    request: Request,
    bank: str = "",
    account: str = "",
    category: str = "",
    month: str = "",
    q: str = "",
) -> HTMLResponse:
    view = data.transactions_view(bank=bank, account=account, category=category, month=month, query=q)
    return templates.TemplateResponse(request, "transactions.html", {"view": view})


@app.get("/investments", response_class=HTMLResponse)
def investments(request: Request) -> HTMLResponse:
    rows = data.investments()
    total = sum(r["value"] for r in rows if r["currency"] == "ZAR")
    return templates.TemplateResponse(
        request, "investments.html", {"rows": rows, "total_zar": total}
    )


@app.get("/reports", response_class=HTMLResponse)
def reports(
    request: Request,
    report: str = "bs",
    accounts: str = "",
    scope: str = "all",
    period: str = "",
    begin: str = "",
    end: str = "",
    depth: str = "",
    layout: str = "tree",
    sort: str = "",
    value: str = "",
) -> HTMLResponse:
    if report not in _REPORT_BY_KEY:
        report = "bs"
    params = {
        "report": report, "accounts": accounts, "scope": scope, "period": period,
        "begin": begin, "end": end, "depth": depth, "layout": layout,
        "sort": bool(sort), "value": bool(value),
    }
    ctx: dict = {
        "types": REPORT_TYPES,
        "params": params,
        "accounts_json": json.dumps(gather_accounts("")),
    }
    if report == "transactions":
        ctx["view"] = data.transactions_view(match=accounts, begin=begin, end=end)
    else:
        argv = _report_argv(params)
        _code, output = hledger.run_text(argv)
        ctx["output"] = output
        ctx["command"] = "hledger " + " ".join(shlex.quote(a) for a in argv)
    return templates.TemplateResponse(request, "reports.html", ctx)


@app.post("/reports/recategorize", response_class=HTMLResponse)
def reports_recategorize(
    request: Request,
    bank: str = Form(...),
    txn_id: str = Form(...),
    category: str = Form(...),
) -> HTMLResponse:
    category = category.strip()
    saved = False
    if category and category not in UNKNOWN_CATEGORIES:
        try:
            if update_transaction_category(bank, txn_id, category, source="manual"):
                build_bank_journal(bank)
                saved = True
        except (ValueError, OSError):
            saved = False
    return templates.TemplateResponse(
        request, "_report_txn_row.html", {"r": data.find_txn_row(txn_id), "saved": saved}
    )


@app.get("/budget", response_class=HTMLResponse)
def budget_page(
    request: Request,
    year: int | None = None,
    view: str = "groups",
    depth: str = "",
    months: int = 1,
) -> HTMLResponse:
    if view not in {"groups", "accounts", "performance", "compare"}:
        view = "groups"
    target = year or date.today().year + 1
    ctx: dict = {
        "view": view, "depth": depth, "months": months,
        "default_out": str(Path.cwd() / "other"),
    }
    try:
        budget = budget_service.load_budget(target)
    except budget_service.BudgetError as exc:
        # Still render the page so the year control is usable.
        ctx["error"] = str(exc)
        ctx["budget"] = budget_service.Budget(year=target, lines=[], title=f"{target} Budget")
        return templates.TemplateResponse(request, "budget.html", ctx)

    ctx["budget"] = budget
    ctx["lines"] = sorted(budget.lines, key=lambda ln: -abs(ln.annual))
    if view == "performance":
        ctx["performance"] = budget_service.performance(
            target, depth=int(depth) if depth.isdigit() else None
        )
    elif view == "compare":
        begin, end, window = budget_service.month_window(max(1, months))
        rows = budget_service.compare(budget, begin, end, window)
        rows.sort(key=lambda r: -r.variance)
        extra = budget_service.unbudgeted(budget, begin, end)
        ctx["compare"] = {
            "rows": rows,
            "begin": begin,
            "end": end,
            "months": window,
            "actual": sum((r.actual for r in rows), Decimal(0)),
            "goal": sum((r.goal for r in rows), Decimal(0)),
            "unbudgeted": sorted(extra.items(), key=lambda kv: -kv[1]),
            "unbudgeted_total": sum(extra.values(), Decimal(0)),
        }
    return templates.TemplateResponse(request, "budget.html", ctx)


@app.post("/budget/export", response_class=HTMLResponse)
def budget_export(
    year: int = Form(...),
    out: str = Form(""),
    pdf: str = Form(""),
) -> HTMLResponse:
    try:
        budget = budget_service.load_budget(year)
        out_dir = Path(out).expanduser() if out else Path.cwd() / "other"
        written = [budget_service.export_xlsx(budget, out_dir / f"{year}-budget.xlsx")]
        html_path = budget_service.export_html(budget, out_dir / f"{year}-budget.html")
        written.append(html_path)
        if pdf:
            written.append(budget_service.export_pdf(html_path, out_dir / f"{year}-budget.pdf"))
    except (budget_service.BudgetError, OSError) as exc:
        return HTMLResponse(f'<p class="error">{escape(str(exc))}</p>')
    items = "".join(f"<li><code>{escape(str(p))}</code></li>" for p in written)
    return HTMLResponse(f'<p class="ok">Exported:</p><ul class="filelist">{items}</ul>')


@app.get("/categorize/{bank}", response_class=HTMLResponse)
def categorize_page(request: Request, bank: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "categorize.html",
        {"bank": bank, "accounts": gather_accounts(bank)},
    )


@app.get("/categorize/{bank}/card", response_class=HTMLResponse)
def categorize_card(request: Request, bank: str) -> HTMLResponse:
    return _render_card(request, bank)


@app.post("/categorize/{bank}/apply", response_class=HTMLResponse)
def categorize_apply(
    request: Request,
    bank: str,
    txn_id: str = Form(...),
    category: str = Form(...),
) -> HTMLResponse:
    category = category.strip()
    if category and category not in UNKNOWN_CATEGORIES:
        if update_transaction_category(bank, txn_id, category, source="manual"):
            build_bank_journal(bank)
    return _render_card(request, bank)


@app.post("/categorize/{bank}/skip", response_class=HTMLResponse)
def categorize_skip(request: Request, bank: str, txn_id: str = Form(...)) -> HTMLResponse:
    _skip_set(bank).add(txn_id)
    return _render_card(request, bank)


@app.post("/categorize/{bank}/alias", response_class=HTMLResponse)
def categorize_alias(
    request: Request,
    bank: str,
    txn_id: str = Form(...),
    description: str = Form(...),
    alias: str = Form(...),
) -> HTMLResponse:
    alias = alias.strip()
    if alias:
        create_alias(bank, txn_id, description, alias)
    # Aliasing does not categorize — stay on the same transaction, refreshed.
    return _render_card(request, bank)


@app.post("/categorize/{bank}/split", response_class=HTMLResponse)
async def categorize_split(request: Request, bank: str) -> HTMLResponse:
    form = await request.form()
    txn_id = str(form.get("txn_id", ""))
    accounts = [str(a).strip() for a in form.getlist("split_account")]
    amounts = [str(a).strip() for a in form.getlist("split_amount")]

    splits: list[TransactionSplit] = []
    for account, amount in zip(accounts, amounts):
        if not account or not amount:
            continue
        try:
            value = Decimal(amount)
        except InvalidOperation:
            continue
        if value <= 0:
            continue
        splits.append(TransactionSplit(account=account, amount=f"{value:.2f}"))

    if splits and txn_id:
        try:
            if update_transaction_splits(bank, txn_id, splits):
                build_bank_journal(bank)
        except ValueError:
            # Split totals didn't match the transaction; leave it uncategorized.
            pass
    return _render_card(request, bank)
