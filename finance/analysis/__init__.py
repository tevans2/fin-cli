"""Structured analysis over the canonical transaction store.

hledger gives balances and registers; this package computes the things it can't:
recurring/subscription detection, category trends, and cash-flow/savings-rate —
as pure functions returning typed results that any frontend (or a quick table)
can consume. Everything reads the canonical JSONL, expanding splits so each
category posting is counted once.
"""
