"""A prebuilt classifier: history model + rules + taxonomy, reloaded on write.

Building the history model scans every transaction, so doing it per request is
slow. The API holds one Classifier, reuses it for every classify call, and calls
``reload()`` only after a mutation — making classification instant.
"""

from __future__ import annotations

from finance.classify.engine import Classification, classify
from finance.classify.history import HistoryModel, build_history
from finance.classify.taxonomy import Taxonomy, load_taxonomy
from finance.config import load_app_config
from finance.models.rules import Rule
from finance.models.transaction import TransactionRecord
from finance.services.transactions import load_all_transactions
from finance.storage.rules_store import RulesStore


class Classifier:
    history: HistoryModel
    rules: list[Rule]
    taxonomy: Taxonomy

    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        config = load_app_config()
        self.history = build_history(load_all_transactions())
        self.rules = RulesStore(config.paths.rules_config).load()
        self.taxonomy = load_taxonomy(config.paths.categories_config)

    def classify(self, record: TransactionRecord) -> Classification:
        return classify(record, history=self.history, rules=self.rules)
