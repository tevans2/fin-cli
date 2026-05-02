from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, Static

from decimal import Decimal, InvalidOperation

from finance.config import load_app_config
from finance.models.transaction import TransactionRecord, TransactionSplit
from finance.services.journal import build_bank_journal
from finance.services.review import create_alias
from finance.services.suggestions import suggest_category_for_record
from finance.services.transactions import (
    filter_unknown_transactions,
    load_bank_transactions,
    update_transaction_category,
    update_transaction_splits,
)
from finance.storage.accounts_store import AccountsStore


UNKNOWN_CATEGORIES = {"expenses:unknown", "income:unknown"}


def _score(query: str, candidate: str) -> float:
    if not query:
        return 1.0
    q = query.lower()
    c = candidate.lower()
    if q in c:
        return 2.0 + (len(q) / max(len(c), 1))
    return SequenceMatcher(None, q, c).ratio()


def gather_accounts(bank: str) -> list[str]:
    config = load_app_config()
    declared = AccountsStore(config.paths.accounts_config).load()
    if declared:
        return declared

    records = load_bank_transactions(bank)
    accounts: set[str] = set()
    for record in records:
        accounts.add(record.ledger_account)
        if record.category not in UNKNOWN_CATEGORIES:
            accounts.add(record.category)
    return sorted(accounts)


@dataclass
class CategorizeResult:
    updated: int = 0
    skipped: int = 0
    aliases_created: int = 0


class AliasScreen(ModalScreen[str | None]):
    def __init__(self, initial: str = ""):
        super().__init__()
        self.initial = initial

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Create alias", id="alias_title"),
            Input(value=self.initial, placeholder="Alias label", id="alias_input"),
            Static("Enter = save, Esc = cancel", id="alias_help"),
            id="alias_modal",
        )

    def on_mount(self) -> None:
        self.query_one("#alias_input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def key_escape(self) -> None:
        self.dismiss(None)


class SplitScreen(ModalScreen[list[TransactionSplit] | None]):
    BINDINGS = [
        Binding("ctrl+s", "finish", "Save split", priority=True),
        Binding("ctrl+d", "delete_last", "Delete last", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+j", "cursor_down", "Down", priority=True),
        Binding("ctrl+k", "cursor_up", "Up", priority=True),
    ]

    def __init__(self, record: TransactionRecord, accounts: list[str]):
        super().__init__()
        self.record = record
        self.accounts = accounts
        self.splits: list[TransactionSplit] = []
        self.total = abs(Decimal(str(record.amount)))
        self.remaining = self.total

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._remaining_text(), id="split_remaining"),
            Static("", id="split_list"),
            Input(placeholder="Account (type to filter)", id="split_account_input"),
            OptionList(id="split_account_options"),
            Input(placeholder="Amount", id="split_amount_input"),
            Static("Tab=switch fields  Ctrl-j/k=navigate  Enter=add split  Ctrl-d=delete last  Esc=cancel  (saves automatically when fully allocated)", id="split_help"),
            id="split_modal",
        )

    def on_mount(self) -> None:
        self.query_one("#split_account_input", Input).focus()
        self._refresh_options()

    def _remaining_text(self) -> str:
        return f"Total: {self.total}  Remaining: {self.remaining}"

    def _refresh_options(self) -> None:
        query = self.query_one("#split_account_input", Input).value.strip()
        ranked = sorted(self.accounts, key=lambda c: _score(query, c), reverse=True)
        filtered = [c for c in ranked if _score(query, c) > 0.25][:50]
        option_list = self.query_one("#split_account_options", OptionList)
        option_list.clear_options()
        for opt in filtered:
            option_list.add_option(opt)
        if filtered:
            option_list.highlighted = 0

    def _refresh_split_list(self) -> None:
        self.query_one("#split_remaining", Static).update(self._remaining_text())
        lines = [f"  {s.account}  {s.amount}" + (f"  ({s.notes})" if s.notes else "") for s in self.splits]
        self.query_one("#split_list", Static).update("\n".join(lines) if lines else "[dim]No splits yet[/dim]")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "split_account_input":
            self._refresh_options()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "split_account_input":
            self.query_one("#split_amount_input", Input).focus()
        elif event.input.id == "split_amount_input":
            self._add_split()

    def _add_split(self) -> None:
        option_list = self.query_one("#split_account_options", OptionList)
        account_input = self.query_one("#split_account_input", Input)
        if option_list.highlighted is not None and option_list.options:
            account = str(option_list.get_option_at_index(option_list.highlighted).prompt)
        else:
            account = account_input.value.strip()
        if not account:
            return
        amount_str = self.query_one("#split_amount_input", Input).value.strip()
        try:
            amount = Decimal(amount_str)
        except InvalidOperation:
            return
        if amount <= 0 or amount > self.remaining:
            return
        self.splits.append(TransactionSplit(account=account, amount=str(amount)))
        self.remaining -= amount
        if self.remaining == 0:
            self.dismiss(self.splits)
            return
        account_input.value = ""
        self.query_one("#split_amount_input", Input).value = ""
        self._refresh_options()
        self._refresh_split_list()
        account_input.focus()

    def action_finish(self) -> None:
        if self.remaining == 0 and self.splits:
            self.dismiss(self.splits)

    def action_delete_last(self) -> None:
        if self.splits:
            removed = self.splits.pop()
            self.remaining += Decimal(removed.amount)
            self._refresh_split_list()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_cursor_down(self) -> None:
        option_list = self.query_one("#split_account_options", OptionList)
        if option_list.highlighted is None:
            option_list.highlighted = 0
        else:
            option_list.highlighted = min(option_list.highlighted + 1, len(option_list.options) - 1)

    def action_cursor_up(self) -> None:
        option_list = self.query_one("#split_account_options", OptionList)
        if option_list.highlighted is None:
            option_list.highlighted = 0
        else:
            option_list.highlighted = max(option_list.highlighted - 1, 0)


class CategorizeTui(App[CategorizeResult]):
    CSS = """
    #details { width: 1fr; padding: 1 2; }
    #picker { width: 1fr; padding: 1 2; }
    #account_input, #account_options { margin-top: 1; }
    #mode_bar { height: 2; padding: 0 1; }
    #action_bar { height: 2; padding: 0 1; }
    #alias_modal {
        width: 60;
        height: 8;
        border: round $accent;
        padding: 1 2;
        background: $panel;
    }
    #split_modal {
        width: 80;
        height: 24;
        border: round $accent;
        padding: 1 2;
        background: $panel;
    }
    #split_list { height: 6; overflow-y: auto; margin-bottom: 1; }
    #split_account_options { height: 6; }
    """

    BINDINGS = [
        Binding("escape", "toggle_actions", "Actions"),
        Binding("enter", "apply_selection", "Apply", show=False),
        Binding("c", "category_mode", "Category", show=False),
        Binding("a", "alias_mode", "Alias", show=False),
        Binding("s", "skip", "Skip", show=False),
        Binding("q", "quit_review", "Quit", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("ctrl+j", "cursor_down", "Down", show=False),
        Binding("ctrl+k", "cursor_up", "Up", show=False),
    ]

    def __init__(self, bank: str, category: str = "both"):
        super().__init__()
        self.bank = bank
        self.records = filter_unknown_transactions(bank, category)
        self.accounts = gather_accounts(bank)
        self.index = 0
        self.result = CategorizeResult()
        self.action_mode = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Mode: category picker", id="mode_bar")
        yield Static("Picker keys: Enter=apply  Ctrl-j/Ctrl-k or j/k=move  Esc=actions", id="action_bar")
        with Horizontal():
            yield Static(id="details")
            with Vertical(id="picker"):
                yield Static("Account picker", id="picker_title")
                yield Input(placeholder="Type to filter accounts", id="account_input")
                yield OptionList(id="account_options")
        yield Footer()

    def on_mount(self) -> None:
        if not self.records:
            self.exit(self.result)
            return
        self._refresh_record_view()
        self._set_picker_mode()

    def _current(self) -> TransactionRecord:
        return self.records[self.index]

    def _current_suggestion(self) -> str | None:
        suggestion = suggest_category_for_record(self.bank, self._current())
        if suggestion and suggestion not in UNKNOWN_CATEGORIES:
            return suggestion
        current = self._current().category
        if current not in UNKNOWN_CATEGORIES:
            return current
        return None

    def _filtered_accounts(self, query: str) -> list[str]:
        ranked = sorted(self.accounts, key=lambda candidate: _score(query, candidate), reverse=True)
        return [candidate for candidate in ranked if _score(query, candidate) > 0.25][:50]

    def _refresh_options(self, prefill: str | None = None) -> None:
        input_widget = self.query_one("#account_input", Input)
        if prefill is not None:
            input_widget.value = prefill
        query = input_widget.value.strip()
        options = self._filtered_accounts(query)
        option_list = self.query_one("#account_options", OptionList)
        option_list.clear_options()
        for option in options:
            option_list.add_option(option)
        if options:
            option_list.highlighted = 0

    def _refresh_record_view(self) -> None:
        record = self._current()
        details = self.query_one("#details", Static)
        primary_label = record.alias or record.description
        secondary_label = record.description if record.alias else None
        details_lines = [
            f"[dim][{self.index + 1}/{len(self.records)}][/dim]",
            f"[b]Date:[/b]        [b]{record.date}[/b]",
            "",
            f"[b]Transaction:[/b]",
            f"[bold]{primary_label}[/bold]",
        ]
        if record.alias:
            details_lines.extend([
                f"[b]Original:[/b]",
                f"{secondary_label}",
            ])
        details_lines.extend([
            "",
            f"[b]Amount:[/b]      {record.amount} {record.currency}",
            f"[b]Source:[/b]      {record.ledger_account}",
            f"[b]Txn ID:[/b]      {record.id}",
            f"[b]Current:[/b]     {record.category}",
            f"[b]Suggested:[/b]   {self._current_suggestion() or '-'}",
            f"[b]Source kind:[/b] {record.category_source}",
        ])
        details.update("\n".join(details_lines))
        self._refresh_options(prefill=self._current_suggestion() or "")

    def _set_picker_mode(self) -> None:
        self.action_mode = False
        self.query_one("#mode_bar", Static).update("Mode: category picker")
        self.query_one("#action_bar", Static).update("Picker keys: Enter=apply  Ctrl-j/Ctrl-k or j/k=move  Esc=actions")
        input_widget = self.query_one("#account_input", Input)
        input_widget.disabled = False
        input_widget.focus()

    def _set_action_mode(self) -> None:
        self.action_mode = True
        self.query_one("#mode_bar", Static).update("Mode: actions")
        self.query_one("#action_bar", Static).update("Actions: c=back to picker  a=alias  x=split  s=skip  q=quit")
        input_widget = self.query_one("#account_input", Input)
        input_widget.disabled = True
        self.query_one("#account_options", OptionList).focus()

    def _advance(self) -> None:
        if self.index >= len(self.records) - 1:
            build_bank_journal(self.bank)
            self.exit(self.result)
            return
        self.index += 1
        self._refresh_record_view()
        self._set_picker_mode()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "account_input":
            self._refresh_options()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "account_input" and not self.action_mode:
            self.action_apply_selection()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.action_toggle_actions()
            event.prevent_default()
            event.stop()
            return

        if self.action_mode:
            if event.key == "a":
                self.action_alias_mode()
                event.prevent_default()
                event.stop()
                return
            if event.key == "x":
                self.action_split_mode()
                event.prevent_default()
                event.stop()
                return
            if event.key == "c":
                self.action_category_mode()
                event.prevent_default()
                event.stop()
                return
            if event.key == "s":
                self.action_skip()
                event.prevent_default()
                event.stop()
                return
            if event.key == "q":
                self.action_quit_review()
                event.prevent_default()
                event.stop()
                return

        if event.key in {"ctrl+j", "j"} and not self.action_mode:
            self.action_cursor_down()
            event.prevent_default()
            event.stop()
        elif event.key in {"ctrl+k", "k"} and not self.action_mode:
            self.action_cursor_up()
            event.prevent_default()
            event.stop()

    def action_toggle_actions(self) -> None:
        if self.action_mode:
            self._set_picker_mode()
        else:
            self._set_action_mode()

    def action_category_mode(self) -> None:
        self._set_picker_mode()

    def action_alias_mode(self) -> None:
        if not self.action_mode:
            return

        record = self._current()

        def _handle_alias(alias: str | None) -> None:
            if alias:
                create_alias(self.bank, record.id, record.description, alias)
                self.result.aliases_created += 1
                record.alias = alias
                self._refresh_record_view()

        self.push_screen(AliasScreen(record.alias or ""), _handle_alias)

    def action_split_mode(self) -> None:
        if not self.action_mode:
            return
        record = self._current()

        def _handle_splits(splits: list[TransactionSplit] | None) -> None:
            if splits:
                update_transaction_splits(self.bank, record.id, splits)
                self.result.updated += 1
                self._advance()

        self.push_screen(SplitScreen(record, self.accounts), _handle_splits)

    def action_skip(self) -> None:
        if not self.action_mode:
            return
        self.result.skipped += 1
        self._advance()

    def action_quit_review(self) -> None:
        build_bank_journal(self.bank)
        self.exit(self.result)

    def action_cursor_down(self) -> None:
        option_list = self.query_one("#account_options", OptionList)
        if option_list.highlighted is None:
            option_list.highlighted = 0
        else:
            option_list.highlighted = min(option_list.highlighted + 1, len(option_list.options) - 1)

    def action_cursor_up(self) -> None:
        option_list = self.query_one("#account_options", OptionList)
        if option_list.highlighted is None:
            option_list.highlighted = 0
        else:
            option_list.highlighted = max(option_list.highlighted - 1, 0)

    def action_apply_selection(self) -> None:
        if self.action_mode:
            return
        option_list = self.query_one("#account_options", OptionList)
        prompt = self.query_one("#account_input", Input)
        value = prompt.value.strip()
        if option_list.highlighted is not None and option_list.options:
            value = str(option_list.get_option_at_index(option_list.highlighted).prompt)
        if not value:
            return
        if value in UNKNOWN_CATEGORIES:
            return
        if update_transaction_category(self.bank, self._current().id, value, source="manual"):
            self.result.updated += 1
        self._advance()


def run_categorize_tui(bank: str, category: str = "both") -> dict:
    app = CategorizeTui(bank, category)
    result = app.run() or CategorizeResult()
    remaining = len(filter_unknown_transactions(bank, category))
    return {
        "updated": result.updated,
        "skipped": result.skipped,
        "aliases_created": result.aliases_created,
        "remaining": remaining,
    }
