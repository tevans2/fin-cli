"""Opt-in LLM fallback: propose a category for an unknown merchant.

Only used when the deterministic layers (rules, history) have no recommendation
and the user passed ``--ai``. The model must choose from the existing taxonomy —
its answer is validated against that list, so it can't invent categories — and
the user still confirms. Confirming it (and saving a rule) makes the choice
deterministic from then on, so the model is a one-time cost per merchant.

Privacy: this sends the transaction description to OpenAI. It needs
OPENAI_API_KEY and the openai package (the ``[ai]`` extra).
"""

from __future__ import annotations

import json
import os


class LLMError(RuntimeError):
    pass


def validate_choice(category, categories: list[str]) -> str | None:
    """Accept the model's category only if it's exactly one of ours."""
    return category if category and category in set(categories) else None


def _build_prompt(description: str, amount: str, currency: str, categories: list[str]) -> str:
    catalogue = "\n".join(f"- {c}" for c in categories)
    return (
        f"Valid categories:\n{catalogue}\n\n"
        f'Transaction: "{description}"  amount {amount} {currency}\n\n'
        'Return JSON {"category": "<exactly one category from the list, or null if none fit>"}.'
    )


def suggest_category(
    description: str,
    amount: str,
    currency: str,
    categories: list[str],
    *,
    model: str | None = None,
) -> str | None:
    if not categories:
        raise LLMError("AI suggestions need a taxonomy — run `fin categories seed` first")

    from finance import settings
    from finance.config import ensure_env_loaded

    ensure_env_loaded()
    if not os.getenv("OPENAI_API_KEY"):
        raise LLMError("AI suggestions need OPENAI_API_KEY (set it in ~/.config/fin/.env or the environment)")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LLMError("AI suggestions need the openai package: pip install -e '.[ai]'") from exc

    client = OpenAI()
    response = client.chat.completions.create(
        model=model or settings.get("openai_model"),
        response_format={"type": "json_object"},
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You categorize bank transactions. Choose exactly one category from the "
                "provided list, or null if none fit. Return only JSON.",
            },
            {"role": "user", "content": _build_prompt(description, amount, currency, categories)},
        ],
    )
    try:
        data = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as exc:
        raise LLMError(f"AI returned invalid JSON: {exc}") from exc
    return validate_choice(data.get("category"), categories)
