"""FastAPI app wrapping the core services. See docs/api-spec.md.

- Localhost only, bearer-token gated when FIN_API_TOKEN is set (unset = open, dev).
- A single in-process lock serializes writes (no TUI/web race).
- A cached Classifier makes classification instant, reloaded lazily after writes.
"""

from __future__ import annotations

import os
import threading

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from finance.classify.allocation import Allocation, AllocationError
from finance.classify.cache import Classifier
from finance.classify.engine import Classification
from finance.models.transaction import TransactionRecord

_write_lock = threading.Lock()


# ── request bodies ────────────────────────────────────────────────────────────
class ApplyBody(BaseModel):
    bank: str
    id: str
    category: str | None = None
    splits: list[dict] | None = None
    merchant: str | None = None


class AutoBody(BaseModel):
    bank: str | None = None


class ConfirmBody(BaseModel):
    bank: str
    ids: list[str]


class RejectBody(BaseModel):
    bank: str
    id: str


class RestoreBody(BaseModel):
    bank: str
    record: dict


class CategoryAddBody(BaseModel):
    category: str


class RenameBody(BaseModel):
    old: str
    new: str


class RuleBody(BaseModel):
    category: str
    merchant: str | None = None
    description_regex: str | None = None
    account: str | None = None
    direction: str | None = None
    amount_lt: str | None = None
    amount_gt: str | None = None
    name: str | None = None


class ImportBody(BaseModel):
    path: str
    bank: str
    account: str = "checking"
    ai_fallback: bool = False
    dry_run: bool = False


# ── serialization ─────────────────────────────────────────────────────────────
def _classification_dict(c: Classification) -> dict:
    return {
        "merchant": c.merchant,
        "recommended": c.recommended,
        "confidence": c.confidence,
        "source": c.source,
        "auto": c.auto,
        "candidates": [{"category": x.category, "share": x.share, "count": x.count} for x in c.candidates],
    }


def _plan_item(record: TransactionRecord, c: Classification) -> dict:
    return {"record": record.to_dict(), "classification": _classification_dict(c)}


def create_app() -> FastAPI:
    app = FastAPI(title="fin API")
    app.state.classifier = None
    app.state.dirty = True

    def classifier() -> Classifier:
        if app.state.classifier is None or app.state.dirty:
            app.state.classifier = Classifier()
            app.state.dirty = False
        return app.state.classifier

    def mark_dirty() -> None:
        app.state.dirty = True

    def all_banks() -> list[str]:
        from finance.config import load_app_config

        txn_dir = load_app_config().paths.transactions_dir
        if not txn_dir.exists():
            return []
        return sorted(d.name for d in txn_dir.iterdir() if d.is_dir() and not d.name.startswith("."))

    def auth(authorization: str | None = Header(default=None)) -> None:
        token = os.getenv("FIN_API_TOKEN")
        if not token:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid or missing token")

    guard = [Depends(auth)]

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/status", dependencies=guard)
    def status() -> dict:
        from collections import Counter

        from finance.services.transactions import load_all_transactions

        records = load_all_transactions()
        uncategorized = Counter()
        needs_review = Counter()
        for r in records:
            if r.category in ("expenses:unknown", "income:unknown"):
                uncategorized[r.institution] += 1
            elif not r.reviewed:
                needs_review[r.institution] += 1
        return {
            "uncategorized": sum(uncategorized.values()),
            "needs_review": sum(needs_review.values()),
            "banks": {b: {"uncategorized": uncategorized.get(b, 0), "needs_review": needs_review.get(b, 0)}
                      for b in {r.institution for r in records}},
        }

    # ── classification (priority) ─────────────────────────────────────────────
    @app.get("/categorize/plan", dependencies=guard)
    def plan(bank: str | None = None, scope: str = "uncat") -> list[dict]:
        from finance.services.categorize import build_plan

        c = classifier()
        items: list[dict] = []
        for b in ([bank] if bank else all_banks()):
            items += [_plan_item(r, cl) for r, cl in build_plan(b, scope=scope, history=c.history, rules=c.rules)]
        items.sort(key=lambda i: (i["record"]["date"], i["record"]["id"]), reverse=True)
        return items

    @app.post("/categorize/auto", dependencies=guard)
    def auto(body: AutoBody | None = None) -> dict:
        from finance.services.categorize import auto_apply

        with _write_lock:
            c = classifier()
            banks = [body.bank] if body and body.bank else all_banks()
            results = [auto_apply(b, history=c.history, rules=c.rules) for b in banks]
            mark_dirty()
        return {
            "auto_applied": sum(r["auto_applied"] for r in results),
            "needs_review": sum(r["needs_review"] for r in results),
        }

    @app.post("/categorize/apply", dependencies=guard)
    def apply(body: ApplyBody) -> dict:
        from finance.services.categorize import apply_category, apply_splits, rebuild_journal, snapshot
        from finance.services.transactions import load_bank_transactions

        with _write_lock:
            before = snapshot(body.bank, body.id)
            if body.splits:
                record = next((r for r in load_bank_transactions(body.bank) if r.id == body.id), None)
                if record is None:
                    raise HTTPException(404, "transaction not found")
                allocations = [Allocation(s["account"], s["amount"], s.get("notes")) for s in body.splits]
                try:
                    ok = apply_splits(body.bank, record, allocations, merchant=body.merchant)
                except AllocationError as exc:
                    raise HTTPException(400, str(exc)) from exc
            elif body.category:
                ok = apply_category(body.bank, body.id, body.category, merchant=body.merchant)
            else:
                raise HTTPException(400, "provide category or splits")

            rebuild_journal(body.bank)
            after = snapshot(body.bank, body.id)
            mark_dirty()
        return {"ok": ok, "before": before, "after": after}

    @app.post("/categorize/confirm", dependencies=guard)
    def confirm_route(body: ConfirmBody) -> dict:
        from finance.services.categorize import confirm, snapshot

        with _write_lock:
            before = [snapshot(body.bank, i) for i in body.ids]
            n = confirm(body.bank, body.ids)
            after = [snapshot(body.bank, i) for i in body.ids]
            mark_dirty()
        return {"confirmed": n, "before": before, "after": after}

    @app.post("/categorize/reject", dependencies=guard)
    def reject_route(body: RejectBody) -> dict:
        from finance.services.categorize import reject, snapshot

        with _write_lock:
            before = snapshot(body.bank, body.id)
            ok = reject(body.bank, body.id)
            after = snapshot(body.bank, body.id)
            mark_dirty()
        return {"ok": ok, "before": before, "after": after}

    @app.post("/categorize/restore", dependencies=guard)
    def restore_route(body: RestoreBody) -> dict:
        from finance.services.categorize import restore_record

        with _write_lock:
            try:
                ok = restore_record(body.bank, body.record)
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(400, str(exc)) from exc
            mark_dirty()
        return {"ok": ok}

    # ── transactions, merchants, taxonomy ─────────────────────────────────────
    @app.get("/transactions", dependencies=guard)
    def transactions(
        scope: str = "all", bank: str | None = None, merchant: str | None = None,
        category: str | None = None, since: str | None = None, until: str | None = None,
        q: str | None = None, limit: int = 200,
    ) -> list[dict]:
        from finance.classify.normalize import merchant_key
        from finance.services.transactions import load_all_transactions, load_bank_transactions

        records = load_bank_transactions(bank) if bank else load_all_transactions()
        unknown = ("expenses:unknown", "income:unknown")
        if scope == "uncat":
            records = [r for r in records if r.category in unknown]
        elif scope == "review":
            records = [r for r in records if not r.reviewed and r.category not in unknown]
        if merchant:
            records = [r for r in records if merchant_key(r.description) == merchant]
        if category:
            records = [r for r in records if r.category == category]
        if since:
            records = [r for r in records if r.date >= since]
        if until:
            records = [r for r in records if r.date <= until]
        if q:
            ql = q.lower()
            records = [r for r in records if ql in r.description.lower()]
        records.sort(key=lambda r: (r.date, r.id), reverse=True)
        return [r.to_dict() for r in records[:limit]]

    @app.get("/merchants", dependencies=guard)
    def merchants() -> list[dict]:
        c = classifier()
        return [
            {"key": s.key, "merchant": s.display_name, "top_category": s.top_category,
             "confidence": s.confidence, "samples": s.samples, "conflicted": s.conflicted}
            for s in c.history.merchants()
        ]

    @app.get("/merchants/{key}", dependencies=guard)
    def merchant_detail(key: str) -> dict:
        from finance.classify.history import matching_records
        from finance.services.transactions import load_all_transactions

        c = classifier()
        stats = c.history.by_key.get(key)
        if stats is None:
            raise HTTPException(404, "unknown merchant")
        examples = sorted(matching_records(load_all_transactions(), key), key=lambda r: r.date, reverse=True)[:20]
        return {
            "key": key,
            "merchant": stats.display_name,
            "samples": stats.samples,
            "breakdown": [{"category": cat, "count": n, "share": share} for cat, n, share in stats.breakdown()],
            "examples": [r.to_dict() for r in examples],
        }

    @app.get("/taxonomy", dependencies=guard)
    def taxonomy() -> dict:
        return {"categories": classifier().taxonomy.sorted()}

    # ── categories & rules ────────────────────────────────────────────────────
    @app.post("/categories", dependencies=guard)
    def add_category(body: CategoryAddBody) -> dict:
        from finance.classify.taxonomy import load_taxonomy, write_taxonomy
        from finance.config import load_app_config

        with _write_lock:
            path = load_app_config().paths.categories_config
            cats = load_taxonomy(path).categories | {body.category}
            write_taxonomy(path, cats)
            mark_dirty()
        return {"ok": True, "count": len(cats)}

    @app.post("/categories/rename", dependencies=guard)
    def rename_category_route(body: RenameBody) -> dict:
        from finance.services.categories import rename_category

        with _write_lock:
            result = rename_category(body.old, body.new)
            mark_dirty()
        return result

    @app.post("/rules", dependencies=guard)
    def add_rule(body: RuleBody) -> dict:
        from finance.services.rules import create_rule

        with _write_lock:
            try:
                name = create_rule(
                    body.category, merchant=body.merchant, description_regex=body.description_regex,
                    account=body.account, direction=body.direction, amount_lt=body.amount_lt,
                    amount_gt=body.amount_gt, name=body.name,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            mark_dirty()
        return {"name": name}

    # ── ops ───────────────────────────────────────────────────────────────────
    @app.get("/verify", dependencies=guard)
    def verify() -> list[dict]:
        from finance.services.verify import verify_accounts

        return [
            {**row, "statement_balance": str(row["statement_balance"]),
             "ledger_balance": None if row["ledger_balance"] is None else str(row["ledger_balance"]),
             "difference": None if row["difference"] is None else str(row["difference"])}
            for row in verify_accounts()
        ]

    @app.post("/import", dependencies=guard)
    def import_statement_route(body: ImportBody) -> dict:
        from finance.services.statement_import import import_statement

        with _write_lock:
            try:
                result = import_statement(
                    body.path, bank=body.bank, account=body.account,
                    dry_run=body.dry_run, ai_fallback=body.ai_fallback,
                )
            except Exception as exc:
                raise HTTPException(400, str(exc)) from exc
            mark_dirty()
        summary = result.pop("summary")
        result["summary"] = {
            "rows": summary.rows, "date_range": summary.date_range,
            "opening_balance": summary.opening_balance, "closing_balance": summary.closing_balance,
            "balance_chain_verified": summary.balance_chain_verified,
        }
        return result

    @app.get("/analysis/cashflow", dependencies=guard)
    def cashflow(bank: str | None = None, months: int | None = None) -> list[dict]:
        from finance.services.analysis import cashflow as cf

        return [
            {"month": r.month, "income": str(r.income), "spend": str(r.spend),
             "net": str(r.net), "savings_rate": r.savings_rate}
            for r in cf(bank, months=months)
        ]

    @app.get("/analysis/recurring", dependencies=guard)
    def recurring(bank: str | None = None, min_occurrences: int = 3) -> list[dict]:
        from finance.services.analysis import recurring as rec

        return [
            {"merchant": r.merchant, "cadence": r.cadence, "interval_days": r.interval_days,
             "typical_amount": str(r.typical_amount), "amount_stable": r.amount_stable,
             "occurrences": r.occurrences, "last": r.last, "active": r.active}
            for r in rec(bank, min_occurrences=min_occurrences)
        ]

    @app.get("/analysis/trends", dependencies=guard)
    def trends(bank: str | None = None, months: int = 6, depth: int = 2) -> dict:
        from finance.services.analysis import trends as tr

        rows, columns = tr(bank, months=months, depth=depth)
        return {
            "columns": columns,
            "trends": [
                {"category": t.category, "latest": str(t.latest), "previous_avg": str(t.previous_avg),
                 "change": str(t.change), "change_pct": t.change_pct}
                for t in rows
            ],
        }

    return app


app = create_app()
