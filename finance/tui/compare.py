from __future__ import annotations

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from finance.services.compare import CompareDataset, CompareRow, build_compare_dataset


@dataclass
class CompareResult:
    offset: int = 0


class CompareTui(App[CompareResult]):
    CSS = """
    #summary { height: 5; padding: 0 1; }
    #left, #right { width: 1fr; padding: 1 2; }
    #left_title, #right_title { height: 1; }
    """

    BINDINGS = [
        Binding("ctrl+j", "offset_down", "Offset +1"),
        Binding("ctrl+k", "offset_up", "Offset -1"),
        Binding("j", "offset_down", "Offset +1", show=False),
        Binding("k", "offset_up", "Offset -1", show=False),
        Binding("q", "quit_compare", "Quit"),
    ]

    def __init__(self, dataset: CompareDataset):
        super().__init__()
        self.dataset = dataset
        self.offset = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        with Horizontal():
            with Vertical(id="left"):
                yield Static("Investec API", id="left_title")
                yield Static(id="left_rows")
            with Vertical(id="right"):
                yield Static("Journal / Canonical", id="right_title")
                yield Static(id="right_rows")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _render_row(self, left: CompareRow | None, right: CompareRow | None) -> str:
        if left is None and right is None:
            return ""
        if left and right:
            match = left.key == right.key
            return "[green]MATCH[/green]" if match else "[red]DIFF[/red]"
        return "[yellow]MISSING[/yellow]"

    def _format_side(self, row: CompareRow | None) -> str:
        if row is None:
            return "[dim]-[/dim]"
        return f"{row.date}  {row.amount:>10}  {row.label}"

    def _refresh(self) -> None:
        api = self.dataset.api_rows
        journal = self.dataset.journal_rows
        left_lines: list[str] = []
        right_lines: list[str] = []
        compare_lines: list[str] = []

        max_rows = max(len(api), len(journal))
        visible = min(max_rows, 25)
        for i in range(visible):
            left = api[i] if i < len(api) else None
            j_index = i + self.offset
            right = journal[j_index] if 0 <= j_index < len(journal) else None
            left_lines.append(self._format_side(left))
            right_lines.append(self._format_side(right))
            compare_lines.append(self._render_row(left, right))

        api_balance = self.dataset.api_current_balance or "-"
        api_available = self.dataset.api_available_balance or "-"
        journal_balance = self.dataset.journal_balance or "-"
        self.query_one("#summary", Static).update(
            f"Bank: {self.dataset.bank}   Account: {self.dataset.account}   Date mode: {self.dataset.date_mode}   Range: {self.dataset.start_date} -> {self.dataset.end_date}   API: {len(api)}   Journal: {len(journal)}   Offset: {self.offset}\n"
            f"API balance now: {api_balance} {self.dataset.balance_currency}   Available: {api_available} {self.dataset.balance_currency}\n"
            f"Journal balance @ {self.dataset.end_date}: {journal_balance}   Account: {self.dataset.journal_balance_label}\n"
            "Use Ctrl-j / Ctrl-k (or j / k) to shift journal list for alignment."
        )
        self.query_one("#left_rows", Static).update("\n".join(left_lines))
        self.query_one("#right_rows", Static).update("\n".join(f"{status:<8} {line}" for status, line in zip(compare_lines, right_lines)))

    def action_offset_down(self) -> None:
        self.offset += 1
        self._refresh()

    def action_offset_up(self) -> None:
        self.offset -= 1
        self._refresh()

    def action_quit_compare(self) -> None:
        self.exit(CompareResult(offset=self.offset))


def run_compare_tui(
    bank: str,
    account: str = "checking",
    begin: str | None = None,
    end: str | None = None,
    days: int = 30,
    date_mode: str | None = None,
) -> dict:
    dataset = build_compare_dataset(bank, account=account, begin=begin, end=end, days=days, date_mode=date_mode)
    result = CompareTui(dataset).run() or CompareResult()
    return {
        "bank": bank,
        "account": dataset.account,
        "date_mode": dataset.date_mode,
        "api_count": len(dataset.api_rows),
        "journal_count": len(dataset.journal_rows),
        "api_current_balance": dataset.api_current_balance,
        "api_available_balance": dataset.api_available_balance,
        "journal_balance": dataset.journal_balance,
        "offset": result.offset,
        "start_date": dataset.start_date,
        "end_date": dataset.end_date,
    }
