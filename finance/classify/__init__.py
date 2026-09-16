"""Classification: derive a merchant and category allocation for a transaction.

The pipeline (built incrementally) resolves, from a transaction's signals
(date, amount, ref, account, institution, description):

  merchant  — a stable identity that links transactions even when their refs,
              dates or trailing noise differ (via a normalized "merchant key")
  category  — one or more allocations that partition the amount so every
              rand/cent lands in exactly one category (a single category is just
              one allocation covering the whole amount)

Layers, in priority order: explicit rules → learned history → optional LLM
fallback, each carrying a source and confidence.
"""
