from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance import settings
from finance.branding import banner
from finance.paths import DataDirError, get_data_paths, validate_data_dir
from finance.services import budget as budget_service
from finance.services.compare import build_compare_dataset
from finance.services.data_repo import DataRepoError, git_commit, git_pull, git_push, git_status
from finance.services.init_data import initialize_data_dir
from finance.services.investments import build_investment_journal, get_history, list_investments, set_valuation
from finance.services.journal import build_bank_journal
from finance.services.migrate import migrate_v1
from finance.services.reports import run_cashflow, run_hledger, run_investments, run_named_report
from finance.services.review import review_unknowns
from finance.services.rules import apply_rules, list_rules
from finance.services.statement_import import format_import_result, import_statement
from finance.services.sync import sync_bank
from finance.services.verify import verify_accounts


def cmd_doctor(_: argparse.Namespace) -> int:
    try:
        paths = get_data_paths()
    except DataDirError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Config dir:   {settings.config_dir()}")
    print(f"Data dir:     {paths.root}  [{settings.source_of('data_dir')}]")
    errors = validate_data_dir(paths)
    if errors:
        print("Data directory validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Data directory looks valid.")
    print(f"Banks config:   {paths.banks_config}")
    print(f"Rules config:   {paths.rules_config}")
    print(f"Aliases config: {paths.aliases_config}")
    print(f"Accounts config:{paths.accounts_config}")
    print(f"Main journal:   {paths.main_journal}")
    print(f"Manual journal: {paths.manual_journal}")
    print(f"Sync state:     {paths.sync_state}")

    from finance.services.security import check_encryption_coverage

    warnings = check_encryption_coverage(paths.root)
    if warnings:
        print("\nSecurity warnings:")
        for warning in warnings:
            print(f"  ⚠ {warning}")
        print("  Fix: add the paths to .gitattributes (filter=git-crypt) or gitignore raw statements.")
    return 0


def cmd_init_data(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"ERROR: target is not empty: {target}")
        print("Use --force to initialize inside a non-empty directory.")
        return 1
    initialize_data_dir(target)
    settings.set_value("data_dir", str(target))
    print(f"Initialized V2 data dir: {target}")
    print(f"Saved data dir to {settings.config_file()} — no need to export FIN_DATA_DIR.")
    print("Next step (optional): cd <your-data-repo> && git-crypt init")
    return 0


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("finance-v2")
    except Exception:
        return "0.1.0"


def cmd_config_show(_: argparse.Namespace) -> int:
    cfg = settings.config_file()
    env = settings.env_file()
    print(f"Config dir:  {settings.config_dir()}")
    print(f"Config file: {cfg}  {'(exists)' if cfg.exists() else '(not created yet)'}")
    print(f"Env file:    {env}  {'(exists)' if env.exists() else '(none)'}")
    print()
    for key, info in settings.resolved().items():
        value = info["value"]
        shown = value if value not in (None, "") else "(unset)"
        print(f"  {key:14} = {str(shown):<42} [{info['source']}]")
    return 0


def cmd_config_get(args: argparse.Namespace) -> int:
    value = settings.get(args.key)
    print("" if value is None else value)
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    key = settings.normalize_key(args.key)
    value = args.value
    if key == "data_dir":
        value = str(Path(value).expanduser().resolve())
    try:
        path = settings.set_value(key, value)
    except KeyError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Set {key} = {value}")
    print(f"Wrote {path}")
    return 0


def cmd_config_unset(args: argparse.Namespace) -> int:
    try:
        settings.set_value(args.key, None)
    except KeyError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Unset {settings.normalize_key(args.key)}")
    return 0


def cmd_config_path(_: argparse.Namespace) -> int:
    print(settings.config_file())
    return 0


def cmd_config_edit(_: argparse.Namespace) -> int:
    import os
    import subprocess

    editor = os.getenv("VISUAL") or os.getenv("EDITOR") or "vi"
    path = settings.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("")
    return subprocess.call([*editor.split(), str(path)])


def cmd_categories_list(_: argparse.Namespace) -> int:
    from finance.classify.taxonomy import load_taxonomy

    try:
        taxonomy = load_taxonomy(get_data_paths().categories_config)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not taxonomy.categories:
        print("No categories.yaml yet. Run `fin categories seed` to create one from your data.")
        return 0
    for category in taxonomy.sorted():
        print(category)
    print(f"\n{len(taxonomy.categories)} categories")
    return 0


def cmd_categories_seed(_: argparse.Namespace) -> int:
    from finance.classify.taxonomy import categories_in_use, load_taxonomy, write_taxonomy
    from finance.services.transactions import load_all_transactions

    try:
        paths = get_data_paths()
        existing = load_taxonomy(paths.categories_config).categories
        used = categories_in_use(load_all_transactions())
        merged = existing | used
        write_taxonomy(paths.categories_config, merged)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Wrote {paths.categories_config}")
    print(f"{len(merged)} categories ({len(merged) - len(existing)} new from your data, {len(existing)} already listed)")
    return 0


def cmd_categories_check(_: argparse.Namespace) -> int:
    from finance.classify.taxonomy import load_taxonomy, unlisted_categories
    from finance.services.transactions import load_all_transactions

    try:
        taxonomy = load_taxonomy(get_data_paths().categories_config)
        if not taxonomy.enforced:
            print("No categories.yaml yet. Run `fin categories seed` first.")
            return 0
        unlisted = unlisted_categories(load_all_transactions(), taxonomy)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not unlisted:
        print("OK — every category in use is listed in the taxonomy.")
        return 0
    print(f"{len(unlisted)} category(ies) used but not in categories.yaml (typo or new?):")
    for category in sorted(unlisted):
        print(f"  {category}")
    return 1


def cmd_categories_rename(args: argparse.Namespace) -> int:
    from finance.services.categories import rename_category

    try:
        result = rename_category(args.old, args.new)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Renamed {result['old']} -> {result['new']}")
    print(f"  transactions updated: {result['transactions']}")
    print(f"  files updated: {', '.join(result['files']) or '(none)'}")
    return 0


def cmd_merchants_list(args: argparse.Namespace) -> int:
    from finance.classify.history import build_history
    from finance.services.transactions import load_all_transactions

    try:
        model = build_history(load_all_transactions())
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    merchants = model.merchants()
    if args.conflicted:
        merchants = [m for m in merchants if m.conflicted]
    if args.min_samples:
        merchants = [m for m in merchants if m.samples >= args.min_samples]
    if args.sort == "conf":
        merchants.sort(key=lambda s: (s.confidence, -s.samples))   # least confident first, to review
    elif args.sort == "name":
        merchants.sort(key=lambda s: s.key)
    if not merchants:
        print("No merchants match.")
        return 0
    rows = merchants[: args.limit] if args.limit else merchants
    print(f"{'merchant key':34}{'top category':32}{'conf':>6}{'n':>5}{'cats':>6}")
    print("-" * 83)
    for stats in rows:
        print(
            f"{stats.key[:33]:34}{stats.top_category[:31]:32}"
            f"{stats.confidence * 100:>5.0f}%{stats.samples:>5}{len(stats.category_counts):>6}"
        )
    print(f"\n{len(merchants)} merchants  ·  verify one with `fin merchants show <key>`")
    return 0


def cmd_merchants_show(args: argparse.Namespace) -> int:
    import difflib

    from finance.classify.history import build_history, matching_records
    from finance.services.transactions import load_all_transactions

    try:
        transactions = load_all_transactions()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    model = build_history(transactions)
    stats = model.by_key.get(args.key)
    if stats is None:
        print(f"No learned merchant with key '{args.key}'.")
        near = difflib.get_close_matches(args.key, list(model.by_key), n=5, cutoff=0.5)
        if near:
            print("Close keys: " + ", ".join(near))
        return 1

    print(f"Merchant: {stats.display_name}    key='{stats.key}'    samples={stats.samples}")
    print("Category breakdown:")
    for category, count, share in stats.breakdown():
        print(f"  {share * 100:>5.0f}%  {count:>4}  {category}")

    matches = matching_records(transactions, args.key)
    shown = sorted(matches, key=lambda r: r.date)[: args.examples]
    print(f"\nExample transactions ({len(shown)} of {len(matches)}):")
    for record in shown:
        print(f"  {record.date}  {record.amount:>11} {record.currency}  {record.category:<26}  {record.description[:48]}")
    return 0


def _prompt_category(taxonomy) -> str | None:
    import difflib

    value = input("    category: ").strip()
    if not value:
        return None
    if taxonomy.enforced and not taxonomy.is_valid(value):
        near = difflib.get_close_matches(value, taxonomy.sorted(), n=3, cutoff=0.5)
        if near:
            print(f"    not in taxonomy — close matches: {', '.join(near)}")
        if input(f"    use '{value}' anyway? [y/N] ").strip().lower() != "y":
            return None
    return value


def _prompt_split(record, candidates):
    from decimal import Decimal

    from finance.classify.allocation import Allocation, AllocationError, magnitude, validate_allocations

    total = magnitude(record.amount)
    print(f"    split {total} {record.currency} — enter 'category amount' per line; a category alone takes the remainder; blank cancels.")
    if candidates:
        print("    candidates: " + ", ".join(f"{n}) {c.category}" for n, c in enumerate(candidates, 1)))
    allocations: list = []
    remaining = total
    while remaining > 0:
        line = input(f"    remaining {remaining}: ").strip()
        if not line:
            print("    cancelled")
            return None
        head, _, tail = line.rpartition(" ")
        token, amount_text = (head, tail) if head else (tail, "")
        if token.isdigit() and candidates and 1 <= int(token) <= len(candidates):
            category = candidates[int(token) - 1].category
        else:
            category = token
        if amount_text:
            try:
                amount = Decimal(amount_text)
            except Exception:
                print("    bad amount")
                continue
        else:
            amount = remaining
        if amount <= 0 or amount > remaining:
            print(f"    amount must be > 0 and <= {remaining}")
            continue
        allocations.append(Allocation(category, f"{amount:.2f}"))
        remaining -= amount
    try:
        validate_allocations(allocations, record.amount)
    except AllocationError as exc:
        print(f"    {exc}")
        return None
    return allocations


def cmd_categorize(args: argparse.Namespace) -> int:
    import sys

    from finance.classify.normalize import merchant_key
    from finance.classify.taxonomy import load_taxonomy
    from finance.services.categorize import apply_category, apply_splits, auto_apply, build_plan, rebuild_journal
    from finance.services.rules import create_rule

    try:
        if not args.dry_run:
            summary = auto_apply(args.bank)
            print(f"Auto-categorized {summary['auto_applied']} confident transaction(s); {summary['remaining']} to review.")
        plan = build_plan(args.bank)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.dry_run:
        auto = sum(1 for _, c in plan if c.auto)
        print(f"[dry-run] {auto} would auto-apply, {len(plan) - auto} would need review:")
        rows = plan[: args.limit] if args.limit else plan
        for record, c in rows:
            tag = "AUTO" if c.auto else "ask "
            print(
                f"  {tag}  {record.date} {record.amount:>10} {record.currency}  "
                f"{(c.recommended or '-'):<26} [{c.source} {c.confidence * 100:.0f}%]  {record.description[:38]}"
            )
        return 0

    if args.auto:
        return 0

    if not plan:
        print("Nothing to review.")
        return 0
    if not sys.stdin.isatty():
        print(f"{len(plan)} transaction(s) need review — run in a terminal to categorize interactively.")
        return 0

    taxonomy = load_taxonomy(get_data_paths().categories_config)
    reviewed = 0
    for index, (record, c) in enumerate(plan, 1):
        if args.ai and not c.recommended:
            from finance.classify.llm import LLMError, suggest_category

            try:
                ai_category = suggest_category(record.description, record.amount, record.currency, taxonomy.sorted())
                if ai_category:
                    c.recommended, c.source, c.confidence = ai_category, "llm", 0.0
            except LLMError as exc:
                print(f"    (AI unavailable: {exc})")
                args.ai = False   # stop retrying every row once it's clearly not set up
        print()
        print(f"[{index}/{len(plan)}]  {record.date}  {record.amount:>11} {record.currency}   merchant={c.merchant or '?'}")
        print(f"    {record.description[:72]}")
        if c.candidates:
            print("    " + "  ".join(f"{n}) {cand.category} {cand.share * 100:.0f}%" for n, cand in enumerate(c.candidates, 1)))
        print(f"    recommended: {c.recommended or '(none)'}   [{c.source} {c.confidence * 100:.0f}%]")
        action = input("    [Enter=accept  #=pick  c=category  s=split  k=skip  q=quit] > ").strip()

        if action.lower() == "q":
            break
        if action.lower() == "k":
            continue

        chosen = None
        if action == "":
            chosen = c.recommended
            if not chosen:
                print("    no recommendation — use c or s")
                continue
        elif action.isdigit() and 1 <= int(action) <= len(c.candidates):
            chosen = c.candidates[int(action) - 1].category
        elif action.lower() == "c":
            chosen = _prompt_category(taxonomy)
            if not chosen:
                continue
        elif action.lower() == "s":
            allocations = _prompt_split(record, c.candidates)
            if not allocations:
                continue
            apply_splits(args.bank, record, allocations, merchant=c.merchant)
            reviewed += 1
            continue
        else:
            print("    unrecognized")
            continue

        source = "llm" if (action == "" and c.source == "llm") else "manual"
        apply_category(args.bank, record.id, chosen, source=source, merchant=c.merchant)
        reviewed += 1

        # offer to pin a rule — but only for merchants that aren't historically ambiguous
        key = merchant_key(record.description)
        if key and len(c.candidates) <= 1:
            if input(f"    ↳ always categorize '{key}' as {chosen}? [y/N] ").strip().lower() == "y":
                try:
                    create_rule(chosen, merchant=key)
                    print("    rule saved")
                except Exception as exc:
                    print(f"    could not save rule: {exc}")

    rebuild_journal(args.bank)
    remaining = len(build_plan(args.bank))
    print(f"\nReviewed {reviewed}. {remaining} still uncategorized.")
    return 0


def cmd_analyze_recurring(args: argparse.Namespace) -> int:
    from finance.services.analysis import recurring

    try:
        items = recurring(args.bank, min_occurrences=args.min)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if args.subscriptions:
        items = [r for r in items if r.amount_stable and r.active]
    if not items:
        print("No recurring merchants found.")
        return 0
    print(f"{'merchant':30}{'cadence':12}{'typical':>11}{'n':>4}{'last':>12}  flags")
    print("-" * 82)
    for r in items:
        flags = []
        if not r.active:
            flags.append("lapsed")
        if r.amount_stable:
            flags.append("stable")
        print(f"{r.merchant[:29]:30}{r.cadence:12}{r.typical_amount:>11,.2f}{r.occurrences:>4}{r.last:>12}  {' '.join(flags)}")
    print(f"\n{len(items)} recurring merchant(s)")
    return 0


def cmd_analyze_cashflow(args: argparse.Namespace) -> int:
    from finance.services.analysis import cashflow

    try:
        rows = cashflow(args.bank, months=args.months)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not rows:
        print("No data.")
        return 0
    print(f"{'month':10}{'income':>13}{'spend':>13}{'net':>13}{'saved':>8}")
    print("-" * 57)
    for row in rows:
        rate = "-" if row.savings_rate is None else f"{row.savings_rate * 100:.0f}%"
        print(f"{row.month:10}{row.income:>13,.2f}{row.spend:>13,.2f}{row.net:>+13,.2f}{rate:>8}")
    return 0


def cmd_analyze_trends(args: argparse.Namespace) -> int:
    from finance.services.analysis import trends

    try:
        rows, columns = trends(args.bank, months=args.months, depth=args.depth)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not rows:
        print("No expense data.")
        return 0
    shown = rows[: args.top] if args.top else rows
    latest = columns[-1]
    print(f"Category spend — {latest} vs trailing average of prior {len(columns) - 1} month(s)\n")
    print(f"{'category':34}{'this month':>13}{'prev avg':>13}{'change':>13}")
    print("-" * 73)
    for t in shown:
        pct = "" if t.change_pct is None else f" ({t.change_pct * 100:+.0f}%)"
        print(f"{t.category[:33]:34}{t.latest:>13,.2f}{t.previous_avg:>13,.2f}{t.change:>+13,.2f}{pct}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    try:
        result = sync_bank(
            args.bank,
            account=args.account,
            begin=args.begin,
            end=args.end,
            days_back=args.days,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(
        f"Synced {result['bank']}[{result['account']}]: fetched={result['fetched']} "
        f"inserted={result['inserted']} updated={result['updated']}"
    )
    print(f"Date range: {result['start_date']} -> {result['end_date']}")
    if result["years"]:
        print(f"Touched years: {', '.join(map(str, result['years']))}")
    return 0


def cmd_journal_build(args: argparse.Namespace) -> int:
    try:
        result = build_bank_journal(args.bank)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Built journal for {result['bank']}: {result['transactions']} transactions")
    print(f"Output: {result['output']}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    try:
        result = import_statement(
            args.file,
            bank=args.bank,
            account=args.account,
            dry_run=args.dry_run,
            copy_raw=not args.no_copy_raw,
            ai_fallback=args.ai_fallback,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(format_import_result(result))
    return 0


def cmd_migrate_v1(args: argparse.Namespace) -> int:
    try:
        result = migrate_v1(
            Path(args.source).expanduser().resolve(),
            overwrite_manual=not args.no_overwrite_manual,
            overwrite_rules=not args.no_overwrite_rules,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Migrated V1 from: {result['source']}")
    print(f"Transactions parsed: {result['records']}")
    print(f"Inserted: {result['inserted']}  Updated: {result['updated']}")
    if result["years"]:
        print(f"Years: {', '.join(map(str, result['years']))}")
    print(f"Manual journal: {result['manual_journal']}")
    print(f"Generated journal: {result['generated_journal']}")
    print(f"Rules migrated: {result['rules_migrated']}")
    print(f"Rules config: {result['rules_config']}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    try:
        rows = review_unknowns(args.bank, args.category)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not rows:
        print("No unknown transactions found.")
        return 0
    for row in rows:
        alias = f" | alias={row.alias}" if getattr(row, 'alias', None) else ""
        print(f"{row.date} | {row.amount:>10} {row.currency} | {row.id} | {row.description}{alias}")
    print(f"Total unknowns: {len(rows)}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("ERROR: API deps missing. Install with: pip install -e '.[api]'")
        return 1
    import json
    import os
    import secrets

    token = os.environ.get("FIN_API_TOKEN") or secrets.token_urlsafe(24)
    os.environ["FIN_API_TOKEN"] = token
    runtime = settings.config_dir() / "runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(json.dumps({"url": f"http://{args.host}:{args.port}", "token": token}))
    print(f"Serving fin API at http://{args.host}:{args.port}   (address+token in {runtime})")
    uvicorn.run("finance.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(url: str, timeout: float = 8.0) -> bool:
    import time
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url + "/health", timeout=0.5)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def cmd_tui(_: argparse.Namespace) -> int:
    import json
    import os
    import secrets
    import shutil
    import subprocess
    import sys
    import urllib.request

    binary = shutil.which("fin-tui") or os.path.expanduser("~/.local/bin/fin-tui")
    if not os.path.exists(binary):
        print("ERROR: fin-tui not found. Build it with `make tui` (or `make install`).")
        return 1

    # reuse a healthy running API, else spawn an ephemeral one
    runtime = settings.config_dir() / "runtime.json"
    url = token = None
    proc = None
    if runtime.exists():
        try:
            rt = json.loads(runtime.read_text())
            urllib.request.urlopen(rt["url"] + "/health", timeout=1)
            url, token = rt["url"], rt["token"]
        except Exception:
            pass
    if url is None:
        token = secrets.token_urlsafe(24)
        url = f"http://127.0.0.1:{_free_port()}"
        env = {**os.environ, "FIN_API_TOKEN": token}
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "finance.api.app:app",
             "--host", "127.0.0.1", "--port", url.rsplit(":", 1)[1]],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not _wait_healthy(url):
            proc.terminate()
            print("ERROR: could not start the API")
            return 1

    try:
        subprocess.run([binary], env={**os.environ, "FIN_API_URL": url, "FIN_API_TOKEN": token or ""})
    finally:
        if proc:
            proc.terminate()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    import json
    import os
    import secrets
    import subprocess
    import sys
    import urllib.request
    import webbrowser

    from finance.api.app import _web_dist

    if _web_dist() is None:
        print("ERROR: web bundle not built. Run `make web` (or `make install`).")
        return 1

    # reuse a healthy running API (fin serve), else spawn an ephemeral one
    runtime = settings.config_dir() / "runtime.json"
    url = token = None
    proc = None
    if runtime.exists():
        try:
            rt = json.loads(runtime.read_text())
            urllib.request.urlopen(rt["url"] + "/health", timeout=1)
            url, token = rt["url"], rt["token"]
        except Exception:
            pass
    if url is None:
        token = secrets.token_urlsafe(24)
        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        env = {**os.environ, "FIN_API_TOKEN": token}
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "finance.api.app:app",
             "--host", "127.0.0.1", "--port", str(port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not _wait_healthy(url):
            proc.terminate()
            print("ERROR: could not start the API")
            return 1

    print(f"fin web → {url}")
    if not args.no_open:
        webbrowser.open(url)
    if proc is None:
        print("Using the running `fin serve` API (already serving; leave it running).")
        return 0
    print("Serving the web app. Press Ctrl+C to stop.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


def cmd_banks_list(_: argparse.Namespace) -> int:
    from finance.banks import list_banks, load_bank

    names = list_banks()
    if not names:
        print("No banks configured yet.")
        return 0
    print(f"{'bank':16}{'source':8}{'name':24}accounts")
    print("-" * 70)
    for name in names:
        b = load_bank(name)
        print(f"{b.bank:16}{b.source:8}{b.name:24}{', '.join(b.account_names())}")
    return 0


def cmd_banks_migrate(args: argparse.Namespace) -> int:
    """Write config/banks/<bank>.yaml for every legacy bank that lacks one."""
    import yaml

    from finance.banks import load_bank
    from finance.config import load_app_config

    config = load_app_config()
    banks_dir = config.paths.banks_dir
    banks_dir.mkdir(parents=True, exist_ok=True)
    legacy = config.banks.get("banks", {})
    if not legacy:
        print("No legacy banks.yaml entries to migrate.")
        return 0

    wrote = 0
    for name in sorted(legacy):
        target = banks_dir / f"{name}.yaml"
        if target.exists() and not args.force:
            print(f"skip {name} (exists)")
            continue
        doc = load_bank(name).to_dict()  # synthesized from legacy + profile
        target.write_text(yaml.safe_dump(doc, sort_keys=False))
        print(f"wrote {target}")
        wrote += 1
    print(f"\nMigrated {wrote} bank(s). Review the files and set each ingest.source (api|csv|pdf).")
    return 0


def cmd_verify(_: argparse.Namespace) -> int:
    try:
        results = verify_accounts()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not results:
        print("No accounts carry a statement balance yet — nothing to verify.")
        return 0

    print(f"{'account':40}{'as of':12}{'statement':>14}{'ledger':>14}{'diff':>12}  status")
    print("-" * 100)
    drift = False
    for row in results:
        ledger = "-" if row["ledger_balance"] is None else f"{row['ledger_balance']:,.2f}"
        diff = "-" if row["difference"] is None else f"{row['difference']:+,.2f}"
        if row["ledger_balance"] is None:
            status = "no ledger data"
        elif row["ok"]:
            status = "OK"
        else:
            status = "DRIFT  <<"
            drift = True
        print(
            f"{row['ledger_account']:40}{row['as_of']:12}"
            f"{row['statement_balance']:>14,.2f}{ledger:>14}{diff:>12}  {status}"
        )
    if drift:
        print("\n`<<` marks an account whose ledger balance disagrees with the bank statement.")
    return 1 if drift else 0


def cmd_rules_list(_: argparse.Namespace) -> int:
    try:
        rules = list_rules()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    for rule in rules:
        print(f"{rule['priority']:>4}  {rule['name']}  ->  {rule['category']}")
    print(f"Total rules: {len(rules)}")
    return 0


def cmd_rules_add(args: argparse.Namespace) -> int:
    from finance.services.rules import create_rule

    try:
        name = create_rule(
            args.category,
            merchant=args.merchant,
            description_regex=args.description_regex,
            account=args.account,
            institution=args.institution,
            direction=args.direction,
            amount_lt=args.amount_lt,
            amount_gt=args.amount_gt,
            currency=args.currency,
            name=args.name,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Added rule '{name}' -> {args.category}")
    return 0


def cmd_rules_apply(args: argparse.Namespace) -> int:
    try:
        result = apply_rules(args.bank, include_manual=args.include_manual)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Applied rules to {result['transactions']} transactions; updated {result['updated']}")
    return 0


def cmd_hledger(args: argparse.Namespace) -> int:
    return run_hledger(args.args)


def cmd_cashflow(args: argparse.Namespace) -> int:
    return run_cashflow(args.args)


def cmd_investments_hledger(args: argparse.Namespace) -> int:
    return run_investments(args.args)


def cmd_reports(args: argparse.Namespace) -> int:
    try:
        return run_named_report(args.name)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        ds = build_compare_dataset(
            args.bank,
            account=args.account,
            begin=args.begin,
            end=args.end,
            days=args.days,
            date_mode=args.date_mode,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    api_keys = {r.key for r in ds.api_rows}
    journal_keys = {r.key for r in ds.journal_rows}
    only_api = [r for r in ds.api_rows if r.key not in journal_keys]
    only_journal = [r for r in ds.journal_rows if r.key not in api_keys]

    print(f"Compare {ds.bank}[{ds.account}]  {ds.start_date} -> {ds.end_date}  date_mode={ds.date_mode}")
    print(
        f"  api rows={len(ds.api_rows)}  journal rows={len(ds.journal_rows)}  "
        f"matched={len(ds.api_rows) - len(only_api)}"
    )
    print(
        f"  balances: api_current={ds.api_current_balance} api_available={ds.api_available_balance} "
        f"journal_end={ds.journal_balance} ({ds.journal_balance_label})"
    )

    def _dump(title: str, rows: list) -> None:
        print(f"\n{title} ({len(rows)}):")
        for row in sorted(rows, key=lambda r: (r.date, r.amount)):
            print(f"  {row.date}  {row.amount:>12} {row.currency}  {row.label}")

    if only_api:
        _dump("Only in bank API (missing locally)", only_api)
    if only_journal:
        _dump("Only in local journal (not on API)", only_journal)
    if not only_api and not only_journal:
        print("\nAll rows matched.")
    return 0


def cmd_investment_set(args: argparse.Namespace) -> int:
    from datetime import date as _date
    date = args.date or _date.today().strftime("%Y-%m-%d")
    try:
        result = set_valuation(
            args.name,
            args.value,
            date=date,
            currency=args.currency,
            notes=args.notes,
            account_override=args.account,
            is_baseline=args.baseline,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    kind = "Baseline" if args.baseline else "Recorded"
    print(f"{kind} {result['name']} ({result['account']}): {result['value']} {args.currency} on {result['date']}")
    print(f"Journal: {result['journal_output']}")
    return 0


def cmd_investment_list(_: argparse.Namespace) -> int:
    try:
        rows = list_investments()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not rows:
        print("No investments recorded.")
        return 0
    for r in rows:
        print(f"{r['name']:<24} {r['account']:<40} {float(r['value']):>12.2f} {r['currency']}  ({r['date']})")
    return 0


def cmd_investment_history(args: argparse.Namespace) -> int:
    try:
        rows = get_history(args.name)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    if not rows:
        print(f"No valuations found for {args.name}.")
        return 0
    for r in rows:
        delta = float(r['delta'])
        sign = "+" if delta >= 0 else ""
        note = f"  {r['notes']}" if r['notes'] else ""
        print(f"{r['date']}  {float(r['value']):>12.2f} {r['currency']}  ({sign}{delta:.2f}){note}")
    return 0


def cmd_investment_build(_: argparse.Namespace) -> int:
    try:
        result = build_investment_journal()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Built investments journal: {result['output']}")
    if result["accounts"]:
        print(f"Accounts: {', '.join(result['accounts'])}")
    return 0


def _budget_year(args: argparse.Namespace) -> int:
    return args.year or date.today().year + 1


def cmd_budget_show(args: argparse.Namespace) -> int:
    try:
        budget = budget_service.load_budget(_budget_year(args))
    except budget_service.BudgetError as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.accounts:
        print(f"{budget.title} — per-account goals\n")
        print(f"{'account':38}{'monthly':>10}{'months':>8}{'annual':>12}")
        for line in sorted(budget.lines, key=lambda ln: -abs(ln.annual)):
            print(f"{line.account:38}{line.monthly:>10,.2f}{line.months:>8}{line.annual:>12,.2f}")
        return 0

    print(f"{budget.title}\n")
    print(f"{'':38}{'per year':>12}{'per month':>12}")
    print("-" * 62)
    for group in budget.expense_groups:
        print(f"{group.label:38}{group.annual:>12,.0f}{group.monthly:>12,.0f}")
    print("-" * 62)
    print(f"{'Total expenses':38}{budget.expense_total:>12,.0f}"
          f"{budget.expense_total / 12:>12,.0f}")
    print()
    for group in budget.income_groups:
        print(f"{group.label:38}{group.annual:>12,.0f}")
    print("-" * 62)
    print(f"{'Total income':38}{budget.income_total:>12,.0f}")
    print(f"{'Surplus to savings':38}{budget.surplus:>12,.0f}")
    if budget.paid_by_others:
        print()
        print(f"{'Paid directly by others':38}{budget.others_total:>12,.0f}")
        print(f"{'Total cost of the year':38}{budget.total_cost:>12,.0f}")
    return 0


def cmd_budget_compare(args: argparse.Namespace) -> int:
    year = _budget_year(args)
    try:
        budget = budget_service.load_budget(year)
    except budget_service.BudgetError as exc:
        print(f"ERROR: {exc}")
        return 1

    months = max(1, args.months)
    begin, end, months = budget_service.month_window(months)
    rows = budget_service.compare(budget, begin, end, months)

    label = "this month" if months == 1 else f"last {months} months"
    print(f"Actual spending vs the {year} budget — {label} ({begin} to {end})\n")
    print(f"{'':36}{'actual':>10}{'budget':>10}{'diff':>10}{'used':>8}")
    print("-" * 74)
    for row in sorted(rows, key=lambda r: -r.variance):
        pct = f"{row.pct}%" if row.pct is not None else "-"
        flag = "  <<" if row.pct is not None and row.pct > 110 else ""
        print(f"{row.group.label:36}{row.actual:>10,.0f}{row.goal:>10,.0f}"
              f"{row.variance:>+10,.0f}{pct:>8}{flag}")
    print("-" * 74)
    actual = sum((r.actual for r in rows), Decimal(0))
    goal = sum((r.goal for r in rows), Decimal(0))
    used = int(actual / goal * 100) if goal else 0
    print(f"{'TOTAL':36}{actual:>10,.0f}{goal:>10,.0f}{actual - goal:>+10,.0f}{used:>7}%")

    extra = budget_service.unbudgeted(budget, begin, end)
    if extra:
        total_extra = sum(extra.values(), Decimal(0))
        print()
        print(f"{'Not in the budget (funded from savings)':36}{total_extra:>10,.0f}")
        for account, amount in sorted(extra.items(), key=lambda kv: -kv[1]):
            print(f"  {account:34}{amount:>10,.0f}")
        print(f"{'ALL SPENDING':36}{actual + total_extra:>10,.0f}")

    print(f"\nBudget rates are the {year} monthly goals; digs costs are counted at their")
    print("occupied-month rate. `<<` marks a line running more than 10% over.")
    return 0


def cmd_budget_performance(args: argparse.Namespace) -> int:
    print(budget_service.performance(_budget_year(args), depth=args.depth))
    return 0


def cmd_data_status(_: argparse.Namespace) -> int:
    try:
        return git_status()
    except DataRepoError as exc:
        print(f"ERROR: {exc}")
        return 1


def cmd_data_pull(_: argparse.Namespace) -> int:
    try:
        return git_pull()
    except DataRepoError as exc:
        print(f"ERROR: {exc}")
        return 1


def cmd_data_push(_: argparse.Namespace) -> int:
    try:
        return git_push()
    except DataRepoError as exc:
        print(f"ERROR: {exc}")
        return 1


def cmd_data_commit(args: argparse.Namespace) -> int:
    from datetime import datetime
    message = args.message or datetime.now().strftime("data update %Y-%m-%d %H:%M")
    try:
        return git_commit(message, add_all=not args.no_add)
    except DataRepoError as exc:
        print(f"ERROR: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fin",
        description=banner(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"fin {_version()}")
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="Validate the data directory and core files")
    doctor.set_defaults(func=cmd_doctor)

    config_p = sub.add_parser("config", help="View or change app settings (~/.config/fin)")
    config_sub = config_p.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show", help="Show config dir and resolved settings").set_defaults(func=cmd_config_show)
    config_sub.add_parser("path", help="Print the config file path").set_defaults(func=cmd_config_path)
    config_sub.add_parser("edit", help="Open the config file in $EDITOR").set_defaults(func=cmd_config_edit)
    c_get = config_sub.add_parser("get", help="Print one setting's value")
    c_get.add_argument("key")
    c_get.set_defaults(func=cmd_config_get)
    c_set = config_sub.add_parser("set", help="Set a setting, eg `fin config set data-dir <path>`")
    c_set.add_argument("key")
    c_set.add_argument("value")
    c_set.set_defaults(func=cmd_config_set)
    c_unset = config_sub.add_parser("unset", help="Remove a setting")
    c_unset.add_argument("key")
    c_unset.set_defaults(func=cmd_config_unset)

    categories = sub.add_parser("categories", help="Manage the category taxonomy (config/categories.yaml)")
    categories_sub = categories.add_subparsers(dest="categories_command", required=True)
    categories_sub.add_parser("list", help="List taxonomy categories").set_defaults(func=cmd_categories_list)
    categories_sub.add_parser(
        "seed", help="Create/update the taxonomy from categories already in your data"
    ).set_defaults(func=cmd_categories_seed)
    categories_sub.add_parser(
        "check", help="Report categories used in transactions but not in the taxonomy"
    ).set_defaults(func=cmd_categories_check)
    c_rename = categories_sub.add_parser(
        "rename", help="Rename/merge a category across transactions, taxonomy, journals and config"
    )
    c_rename.add_argument("old", help="Existing category, eg expenses:lifestyle:drinks")
    c_rename.add_argument("new", help="New category, eg expenses:lifestyle:bars")
    c_rename.set_defaults(func=cmd_categories_rename)

    merchants = sub.add_parser("merchants", help="Inspect merchants learned from categorized history")
    merchants_sub = merchants.add_subparsers(dest="merchants_command", required=True)
    m_list = merchants_sub.add_parser("list", help="List learned merchants with their usual category")
    m_list.add_argument("--limit", type=int, help="Show only the top N")
    m_list.add_argument(
        "--sort", choices=["samples", "conf", "name"], default="samples",
        help="Sort order (conf = least confident first, for review)",
    )
    m_list.add_argument("--conflicted", action="store_true", help="Only merchants seen in more than one category")
    m_list.add_argument("--min-samples", type=int, help="Only merchants with at least N samples")
    m_list.set_defaults(func=cmd_merchants_list)
    m_show = merchants_sub.add_parser("show", help="Show a merchant's category breakdown + example transactions")
    m_show.add_argument("key", help="Merchant key (from `fin merchants list`)")
    m_show.add_argument("--examples", type=int, default=12, help="How many example transactions to show")
    m_show.set_defaults(func=cmd_merchants_show)

    banks = sub.add_parser("banks", help="Per-bank ingestion config (config/banks/<bank>.yaml)")
    banks_sub = banks.add_subparsers(dest="banks_command", required=True)
    banks_sub.add_parser("list", help="List configured banks and their ingest source").set_defaults(
        func=cmd_banks_list)
    b_migrate = banks_sub.add_parser(
        "migrate", help="Write per-bank config files from the legacy banks.yaml")
    b_migrate.add_argument("--force", action="store_true", help="Overwrite existing per-bank files")
    b_migrate.set_defaults(func=cmd_banks_migrate)

    init_data = sub.add_parser("init-data", help="Initialize a new V2 data directory")
    init_data.add_argument("path", help="Target path for the separate finance data repo")
    init_data.add_argument("--force", action="store_true", help="Allow initialization in a non-empty directory")
    init_data.set_defaults(func=cmd_init_data)

    sync = sub.add_parser("sync", help="Fetch one bank account into canonical JSONL storage")
    sync.add_argument("bank", help="Bank/provider name, eg investec")
    sync.add_argument("--account", choices=["checking", "savings"], default="checking", help="Investec account to sync")
    sync.add_argument("--days", type=int, default=7, help="Lookback window in days when --begin is not supplied")
    sync.add_argument("--begin", help="Begin date YYYY-MM-DD")
    sync.add_argument("--end", help="End date YYYY-MM-DD")
    sync.set_defaults(func=cmd_sync)

    journal = sub.add_parser("journal-build", help="Generate an hledger journal from canonical transactions")
    journal.add_argument("bank", help="Bank/provider name, eg investec")
    journal.set_defaults(func=cmd_journal_build)

    imp = sub.add_parser("import", help="Import a bank statement (CSV/PDF) into canonical JSONL storage")
    imp.add_argument("bank", help="Bank/provider name, eg investec, tyme, fnb")
    imp.add_argument("file", help="Statement file (CSV or PDF)")
    imp.add_argument("--account", default="checking", help="Account the statement is from (default: checking)")
    imp.add_argument("--dry-run", action="store_true", help="Parse, verify the balance chain and preview without writing")
    imp.add_argument("--no-copy-raw", action="store_true", help="Do not copy the raw file into FIN_DATA_DIR/imports")
    imp.add_argument(
        "--ai-fallback",
        action="store_true",
        help="If PDF parsing fails, send the statement text to OpenAI to extract transactions "
        "(needs OPENAI_API_KEY; sends data to an external service; the result is still balance-chain validated)",
    )
    imp.set_defaults(func=cmd_import)

    migrate = sub.add_parser("migrate-v1", help="Import existing V1 journal data into V2 canonical storage")
    migrate.add_argument("source", help="Path to the V1 project root")
    migrate.add_argument("--no-overwrite-manual", action="store_true", help="Do not replace V2 manual.journal with migrated v1 manual/opening/investment content")
    migrate.add_argument("--no-overwrite-rules", action="store_true", help="Do not replace V2 rules.yaml with migrated v1 rules")
    migrate.set_defaults(func=cmd_migrate_v1)

    review = sub.add_parser("review", help="List unknown transactions from canonical JSONL storage")
    review.add_argument("bank", help="Bank/provider name, eg investec")
    review.add_argument("--category", choices=["expenses", "income", "both"], default="both")
    review.set_defaults(func=cmd_review)

    categorize = sub.add_parser(
        "categorize", help="Auto-apply confident categories, then review the rest with recommendations"
    )
    categorize.add_argument("bank", help="Bank/provider name, eg investec")
    categorize.add_argument("--auto", action="store_true", help="Only auto-apply confident matches; no prompts")
    categorize.add_argument(
        "--ai", action="store_true",
        help="For unknown merchants, ask OpenAI to propose a category from your taxonomy (needs OPENAI_API_KEY)",
    )
    categorize.add_argument("--dry-run", action="store_true", help="Show what would happen; change nothing")
    categorize.add_argument("--limit", type=int, help="With --dry-run, cap the rows shown")
    categorize.set_defaults(func=cmd_categorize)

    rules = sub.add_parser("rules-list", help="List active categorization rules")
    rules.set_defaults(func=cmd_rules_list)

    rules_add = sub.add_parser("rules-add", help="Add a categorization rule")
    rules_add.add_argument("--category", required=True, help="Category to assign")
    rules_add.add_argument("--merchant", help="Match this merchant key (see `fin merchants list`)")
    rules_add.add_argument("--description-regex", help="Match this regex against the raw description")
    rules_add.add_argument("--account", help="Match this source account, eg checking")
    rules_add.add_argument("--institution", help="Match this institution, eg investec")
    rules_add.add_argument("--direction", choices=["in", "out"], help="Match money in or money out")
    rules_add.add_argument("--amount-lt", help="Match amount less than")
    rules_add.add_argument("--amount-gt", help="Match amount greater than")
    rules_add.add_argument("--currency", help="Match currency, eg ZAR")
    rules_add.add_argument("--name", help="Rule name (auto-generated if omitted)")
    rules_add.set_defaults(func=cmd_rules_add)

    rules_apply = sub.add_parser("rules-apply", help="Apply rules to canonical transactions")
    rules_apply.add_argument("bank", help="Bank/provider name, eg investec")
    rules_apply.add_argument("--include-manual", action="store_true", help="Also re-apply rules to manually categorized transactions")
    rules_apply.set_defaults(func=cmd_rules_apply)

    hledger = sub.add_parser("hledger", help="Run hledger with no filters (all accounts)")
    hledger.add_argument("args", nargs=argparse.REMAINDER)
    hledger.set_defaults(func=cmd_hledger)

    cashflow = sub.add_parser("cashflow", help="Run hledger scoped to cash accounts (excludes investments and unrealised gains)")
    cashflow.add_argument("args", nargs=argparse.REMAINDER)
    cashflow.set_defaults(func=cmd_cashflow)

    investments_hledger = sub.add_parser("investments", help="Run hledger scoped to investment accounts and unrealised gains")
    investments_hledger.add_argument("args", nargs=argparse.REMAINDER)
    investments_hledger.set_defaults(func=cmd_investments_hledger)

    reports = sub.add_parser("reports", help="Run a named report against the V2 main journal")
    reports.add_argument("name", choices=["bs", "is", "expenses", "unknowns"])
    reports.set_defaults(func=cmd_reports)

    compare = sub.add_parser("compare", help="Compare live API transactions against local canonical/journal transactions")
    compare.add_argument("bank", help="Bank/provider name, eg investec")
    compare.add_argument("--account", choices=["checking", "savings"], default="checking", help="Investec account to compare")
    compare.add_argument("--days", type=int, default=30, help="Lookback window in days when --begin is not supplied")
    compare.add_argument("--begin", help="Begin date YYYY-MM-DD")
    compare.add_argument("--end", help="End date YYYY-MM-DD")
    compare.add_argument("--date-mode", choices=["posting", "action"], help="Date semantics for API-side comparison; defaults to posting for checking, action for savings")
    compare.set_defaults(func=cmd_compare)

    verify = sub.add_parser("verify", help="Reconcile each account's latest statement balance against the ledger")
    verify.set_defaults(func=cmd_verify)

    serve = sub.add_parser("serve", help="Run the local API (for the TUI and web frontends)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev)")
    serve.set_defaults(func=cmd_serve)

    tui = sub.add_parser("tui", help="Launch the terminal UI (auto-starts the API)")
    tui.set_defaults(func=cmd_tui)

    web = sub.add_parser("web", help="Launch the web dashboard (auto-starts the API)")
    web.add_argument("--no-open", action="store_true", help="Don't open the browser")
    web.set_defaults(func=cmd_web)

    analyze = sub.add_parser("analyze", help="Analyze spending: recurring, cashflow, trends")
    analyze_sub = analyze.add_subparsers(dest="analyze_command", required=True)

    a_rec = analyze_sub.add_parser("recurring", help="Detect recurring merchants / subscriptions")
    a_rec.add_argument("--bank", help="Limit to one bank (default: all)")
    a_rec.add_argument("--min", type=int, default=3, help="Minimum occurrences to consider (default: 3)")
    a_rec.add_argument("--subscriptions", action="store_true", help="Only stable-amount, still-active ones")
    a_rec.set_defaults(func=cmd_analyze_recurring)

    a_cf = analyze_sub.add_parser("cashflow", help="Monthly income, spend, net and savings rate")
    a_cf.add_argument("--bank", help="Limit to one bank (default: all)")
    a_cf.add_argument("--months", type=int, help="Show only the last N months")
    a_cf.set_defaults(func=cmd_analyze_cashflow)

    a_tr = analyze_sub.add_parser("trends", help="Category spend: this month vs trailing average")
    a_tr.add_argument("--bank", help="Limit to one bank (default: all)")
    a_tr.add_argument("--months", type=int, default=6, help="Window in months (default: 6)")
    a_tr.add_argument("--depth", type=int, default=2, help="Roll categories to this colon-depth (default: 2)")
    a_tr.add_argument("--top", type=int, help="Show only the top N movers")
    a_tr.set_defaults(func=cmd_analyze_trends)

    inv_set = sub.add_parser("investment-set", help="Record a new investment valuation")
    inv_set.add_argument("name", help="Short investment name, eg easyequities")
    inv_set.add_argument("value", help="Current market value")
    inv_set.add_argument("--date", help="Valuation date YYYY-MM-DD (default: today)")
    inv_set.add_argument("--currency", default="ZAR")
    inv_set.add_argument("--notes", help="Optional notes")
    inv_set.add_argument("--account", help="Override ledger account (default: assets:investments:<name>)")
    inv_set.add_argument("--baseline", action="store_true", help="Mark as baseline (no journal entry — use when manual.journal already records the opening value)")
    inv_set.set_defaults(func=cmd_investment_set)

    inv_list = sub.add_parser("investment-list", help="Show latest value for all investments")
    inv_list.set_defaults(func=cmd_investment_list)

    inv_history = sub.add_parser("investment-history", help="Show all valuations for an investment")
    inv_history.add_argument("name", help="Short investment name")
    inv_history.set_defaults(func=cmd_investment_history)

    inv_build = sub.add_parser("investment-build", help="Regenerate investments.journal without adding a valuation")
    inv_build.set_defaults(func=cmd_investment_build)

    budget = sub.add_parser("budget", help="2027-style budget goals from the budget journal")
    budget_sub = budget.add_subparsers(dest="budget_command", required=True)

    b_show = budget_sub.add_parser("show", help="Print the budget, grouped by category")
    b_show.add_argument("--year", type=int, help="Budget year (default: next year)")
    b_show.add_argument("--accounts", action="store_true", help="List raw per-account goals instead")
    b_show.set_defaults(func=cmd_budget_show)

    b_cmp = budget_sub.add_parser("compare", help="Actual spending vs the budget's monthly rates")
    b_cmp.add_argument("--year", type=int, help="Budget year to measure against (default: next year)")
    b_cmp.add_argument("--months", type=int, default=1, help="Trailing window in months (default: 1)")
    b_cmp.set_defaults(func=cmd_budget_compare)

    b_perf = budget_sub.add_parser("performance", help="Actual vs budget, by month (hledger --budget)")
    b_perf.add_argument("--year", type=int, help="Budget year (default: next year)")
    b_perf.add_argument("--depth", type=int, help="Roll accounts up to this depth")
    b_perf.set_defaults(func=cmd_budget_performance)

    data_status = sub.add_parser("data-status", help="Run git status in the FIN_DATA_DIR repo")
    data_status.set_defaults(func=cmd_data_status)

    data_pull = sub.add_parser("data-pull", help="Run git pull --rebase in the FIN_DATA_DIR repo")
    data_pull.set_defaults(func=cmd_data_pull)

    data_push = sub.add_parser("data-push", help="Run git push in the FIN_DATA_DIR repo")
    data_push.set_defaults(func=cmd_data_push)

    data_commit = sub.add_parser("data-commit", help="Run git add/commit in the FIN_DATA_DIR repo")
    data_commit.add_argument("-m", "--message", default=None, help="Commit message (default: auto datetime)")
    data_commit.add_argument("--no-add", action="store_true", help="Do not run 'git add .' before commit")
    data_commit.set_defaults(func=cmd_data_commit)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        raise SystemExit(0)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
