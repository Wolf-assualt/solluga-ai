"""
bot/session.py — Per-user in-memory conversation state.

Stores the current OrderDraft between the "order message" and
"confirm / cancel" button press.
"""

from __future__ import annotations

from typing import Optional

from core.order import OrderDraft

# { user_id (int) -> OrderDraft }
_sessions: dict[int, OrderDraft] = {}


def set_draft(user_id: int, draft: OrderDraft) -> None:
    _sessions[user_id] = draft


def get_draft(user_id: int) -> Optional[OrderDraft]:
    return _sessions.get(user_id)


def clear_draft(user_id: int) -> None:
    _sessions.pop(user_id, None)
