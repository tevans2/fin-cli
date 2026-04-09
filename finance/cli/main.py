from __future__ import annotations

import argparse
import sys
from pathlib import Path

from finance.paths import DataDirError, get_data_paths, validate_data_dir
from finance.services.data_repo import DataRepoError, git_commit, git_pull, git_push, git_status
from finance.services.import_statement import import_tyme_csv
from finance.services.init_data import initialize_data_dir
from finance.services.journal import build_bank_journal
from finance.services.migrate import migrate_v1
from finance.services.reports import run_hledger, run_named_report
from finance.services.review import categorize_unknowns_interactively, review_unknowns
from finance.services.rules import apply_rules, list_rules
from finance.services.sync import sync_bank


def cmd_doctor(_: argparse.Namespace) -> int:
    try:
        paths = get_data_paths()
    except DataDirError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"FIN_DATA_DIR: {paths.root}")
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
    return 0


def cmd_init_data(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"ERROR: target is not empty: {target}")
        print("Use --force to initialize inside a non-empty directory.")
        return 1
    initialize_data_dir(target)
    print(f"Initialized V2 data dir: {target}")
    print("Next steps:")
    print(f"  export FIN_DATA_DIR={target}")
    print("  cd <your-data-repo> && git-crypt init")
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
    if args.bank != "tyme":
        print("ERROR: only tyme CSV import is supported right now")
        return 1
    try:
        result = import_tyme_csv(
            args.file,
            account=args.account,
            delimiter=args.delimiter,
            dry_run=args.dry_run,
            copy_raw=not args.no_copy_raw,
            date_column=args.date_column,
            description_column=args.description_column,
            amount_column=args.amount_column,
            debit_column=args.debit_column,
            credit_column=args.credit_column,
            balance_column=args.balance_column,
            reference_column=args.reference_column,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(
        f"Imported {result['bank']}[{result['account']}]: rows={result['rows']} inserted={result['inserted']} "
        f"updated={result['updated']} unchanged={result['unchanged']} dry_run={result['dry_run']}"
    )
    if result["date_range"]:
        print(f"Date range: {result['date_range']['start']} -> {result['date_range']['end']}")
    print(f"Detected mapping: {result['mapping']}")
    if result["years"]:
        print(f"Touched years: {', '.join(map(str, result['years']))}")
    if result["raw_copy"]:
        print(f"Raw CSV copy: {result['raw_copy']}")
    if result["journal_output"]:
        print(f"Journal output: {result['journal_output']}")
    if result["preview"]:
        print("Preview:")
        for row in result["preview"]:
            print(f"  {row['date']} | {row['amount']:>10} | {row['description']} | {row['id']}")
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


def cmd_categorize(args: argparse.Namespace) -> int:
    try:
        if args.cli:
            result = categorize_unknowns_interactively(args.bank, args.category)
        else:
            from finance.tui.categorize import run_categorize_tui
            result = run_categorize_tui(args.bank, args.category)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Updated: {result['updated']}  Skipped: {result['skipped']}  Aliases created: {result['aliases_created']}  Remaining unknowns: {result['remaining']}")
    return 0


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


def cmd_reports(args: argparse.Namespace) -> int:
    try:
        return run_named_report(args.name)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        from finance.tui.compare import run_compare_tui
        result = run_compare_tui(
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
    print(
        f"Compared {result['bank']}[{result['account']}]: api={result['api_count']} journal={result['journal_count']} "
        f"date_mode={result['date_mode']} range={result['start_date']}->{result['end_date']} offset={result['offset']}"
    )
    print(
        f"Balances: api_current={result['api_current_balance']} api_available={result['api_available_balance']} "
        f"journal_end={result['journal_balance']}"
    )
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
    try:
        return git_commit(args.message, add_all=not args.no_add)
    except DataRepoError as exc:
        print(f"ERROR: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fin", description="Finance V2 CLI")
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="Validate FIN_DATA_DIR and core files")
    doctor.set_defaults(func=cmd_doctor)

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

    imp = sub.add_parser("import", help="Import statement data into canonical JSONL storage")
    imp.add_argument("bank", choices=["tyme"], help="Statement import source")
    imp.add_argument("file", help="CSV statement file")
    imp.add_argument("--account", choices=["checking", "savings"], default="checking")
    imp.add_argument("--delimiter", default=",", help="CSV delimiter")
    imp.add_argument("--dry-run", action="store_true", help="Parse and preview without writing data")
    imp.add_argument("--no-copy-raw", action="store_true", help="Do not copy the raw CSV into FIN_DATA_DIR/imports")
    imp.add_argument("--date-column", help="Explicit CSV date column name")
    imp.add_argument("--description-column", help="Explicit CSV description column name")
    imp.add_argument("--amount-column", help="Explicit CSV signed amount column name")
    imp.add_argument("--debit-column", help="Explicit CSV debit column name")
    imp.add_argument("--credit-column", help="Explicit CSV credit column name")
    imp.add_argument("--balance-column", help="Explicit CSV balance column name")
    imp.add_argument("--reference-column", help="Explicit CSV reference/id column name")
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

    categorize = sub.add_parser("categorize", help="Interactively categorize unknown canonical transactions")
    categorize.add_argument("bank", help="Bank/provider name, eg investec")
    categorize.add_argument("--category", choices=["expenses", "income", "both"], default="both")
    categorize.add_argument("--cli", action="store_true", help="Use the line-by-line CLI review flow instead of the TUI")
    categorize.add_argument("--tui", action="store_true", help="Use the TUI review flow (default)")
    categorize.set_defaults(func=cmd_categorize)

    rules = sub.add_parser("rules-list", help="List active categorization rules")
    rules.set_defaults(func=cmd_rules_list)

    rules_apply = sub.add_parser("rules-apply", help="Apply rules to canonical transactions")
    rules_apply.add_argument("bank", help="Bank/provider name, eg investec")
    rules_apply.add_argument("--include-manual", action="store_true", help="Also re-apply rules to manually categorized transactions")
    rules_apply.set_defaults(func=cmd_rules_apply)

    hledger = sub.add_parser("hledger", help="Run hledger against the V2 main journal")
    hledger.add_argument("args", nargs=argparse.REMAINDER)
    hledger.set_defaults(func=cmd_hledger)

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

    data_status = sub.add_parser("data-status", help="Run git status in the FIN_DATA_DIR repo")
    data_status.set_defaults(func=cmd_data_status)

    data_pull = sub.add_parser("data-pull", help="Run git pull --rebase in the FIN_DATA_DIR repo")
    data_pull.set_defaults(func=cmd_data_pull)

    data_push = sub.add_parser("data-push", help="Run git push in the FIN_DATA_DIR repo")
    data_push.set_defaults(func=cmd_data_push)

    data_commit = sub.add_parser("data-commit", help="Run git add/commit in the FIN_DATA_DIR repo")
    data_commit.add_argument("-m", "--message", required=True, help="Commit message")
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
