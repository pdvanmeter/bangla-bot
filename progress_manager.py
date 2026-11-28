from __future__ import annotations

import datetime
import json
import os
from typing import Any

PROGRESS_FILE = "progress.json"
SCHEMA_VERSION = 2

SRS_INTERVAL_DAYS: dict[int, int] = {
    1: 1,
    2: 3,
    3: 7,
    4: 14,
    5: 30,
}

SRS_LEVEL_LABELS: dict[int, str] = {
    0: "Unseen",
    1: "Level 1 (Learning)",
    2: "Level 2 (Familiar)",
    3: "Level 3 (Intermediate)",
    4: "Level 4 (Strong)",
    5: "Level 5 (Mastered)",
}


def today_str() -> str:
    """Returns today's local date as YYYY-MM-DD."""
    return datetime.date.today().isoformat()


def add_days(date_str: str, days: int) -> str:
    """Adds `days` calendar days to an ISO YYYY-MM-DD date string."""
    base = datetime.date.fromisoformat(date_str)
    return (base + datetime.timedelta(days=days)).isoformat()


def default_progress_data() -> dict[str, Any]:
    """Returns a clean v2 SRS progress dictionary."""
    return {
        "schema_version": SCHEMA_VERSION,
        "vocabulary": {},
        "grammar": {},
        "session_history": [],
    }


def save_progress(data: dict[str, Any], file_path: str = PROGRESS_FILE) -> None:
    """Writes progress JSON atomically/cleanly to disk."""
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_progress_file(file_path: str = PROGRESS_FILE) -> dict[str, Any]:
    """
    Ensures `file_path` exists with schema_version == 2.
    Re-initializes cleanly if missing, corrupt, or from legacy v1 schema.
    """
    if not os.path.exists(file_path):
        data = default_progress_data()
        save_progress(data, file_path)
        return data

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = default_progress_data()
        save_progress(data, file_path)
        return data

    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        data = default_progress_data()
        save_progress(data, file_path)
        return data

    changed = False
    if not isinstance(data.get("vocabulary"), dict):
        data["vocabulary"] = {}
        changed = True
    if not isinstance(data.get("grammar"), dict):
        data["grammar"] = {}
        changed = True
    if not isinstance(data.get("session_history"), list):
        data["session_history"] = []
        changed = True

    if changed:
        save_progress(data, file_path)
    return data


def reset_progress_data(file_path: str = PROGRESS_FILE) -> dict[str, Any]:
    """Resets progress on disk to a clean v2 SRS schema and returns it."""
    data = default_progress_data()
    save_progress(data, file_path)
    return data


def is_item_due(record: dict[str, Any] | None, today: str | None = None) -> bool:
    """Returns True if an encountered SRS record is due for review on or before `today`."""
    if not record:
        return False
    current_day = today or today_str()
    due_date = record.get("next_review_due", "")
    if not due_date:
        return True
    return due_date <= current_day


def _extract_score_fields(score_entry: Any) -> tuple[str, str, str]:
    if isinstance(score_entry, dict):
        item_id = str(score_entry.get("item_id", "")).strip()
        outcome = str(score_entry.get("outcome", "stay")).strip().lower()
        note = str(score_entry.get("note", "")).strip()
    else:
        item_id = str(getattr(score_entry, "item_id", "")).strip()
        outcome = str(getattr(score_entry, "outcome", "stay")).strip().lower()
        note = str(getattr(score_entry, "note", "")).strip()
    if outcome not in ("promote", "stay", "demote"):
        outcome = "stay"
    return item_id, outcome, note


def apply_session_scores(
    scores: list[Any],
    new_item_ids: set[str],
    valid_vocab_ids: set[str],
    valid_grammar_ids: set[str],
    mode: str = "learn",
    today: str | None = None,
    file_path: str = PROGRESS_FILE,
) -> dict[str, Any]:
    """
    Applies end-of-session SRS transitions and persists `progress.json`.

    Newly introduced items (`item_id in new_item_ids` or previously unseen) are
    locked at Level 1 (`next_review_due = today + 1 day`) so they receive at
    least one spaced review before advancing.
    """
    data = ensure_progress_file(file_path)
    current_day = today or today_str()
    updated_items: list[dict[str, Any]] = []

    for entry in scores:
        item_id, outcome, note = _extract_score_fields(entry)
        if not item_id:
            continue

        if item_id in valid_vocab_ids:
            category = "vocabulary"
            target_dict = data["vocabulary"]
        elif item_id in valid_grammar_ids:
            category = "grammar"
            target_dict = data["grammar"]
        else:
            continue

        was_new = item_id in new_item_ids or item_id not in target_dict

        if was_new:
            old_level = 0
            new_level = 1
            next_due = add_days(current_day, SRS_INTERVAL_DAYS[1])
            target_dict[item_id] = {
                "srs_level": 1,
                "first_encountered": current_day,
                "last_practiced": current_day,
                "next_review_due": next_due,
                "encounters": 1,
                "last_outcome": "introduced",
            }
            recorded_outcome = "introduced"
        else:
            existing = target_dict[item_id]
            old_level = max(1, min(5, int(existing.get("srs_level", 1))))
            if outcome == "promote":
                new_level = min(5, old_level + 1)
            elif outcome == "demote":
                new_level = max(1, old_level - 1)
            else:
                new_level = old_level

            next_due = add_days(current_day, SRS_INTERVAL_DAYS[new_level])
            target_dict[item_id] = {
                "srs_level": new_level,
                "first_encountered": existing.get("first_encountered", current_day),
                "last_practiced": current_day,
                "next_review_due": next_due,
                "encounters": int(existing.get("encounters", 1)) + 1,
                "last_outcome": outcome,
            }
            recorded_outcome = outcome

        updated_items.append(
            {
                "item_id": item_id,
                "category": category,
                "old_level": old_level,
                "new_level": new_level,
                "outcome": recorded_outcome,
                "assessed_outcome": outcome,
                "was_new": was_new,
                "next_review_due": next_due,
                "note": note,
            }
        )

    history = data.setdefault("session_history", [])
    history.append(
        {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "mode": mode,
            "items_scored": len(updated_items),
        }
    )
    if len(history) > 100:
        data["session_history"] = history[-100:]

    save_progress(data, file_path)
    return {
        "updated": updated_items,
        "progress": data,
    }


def compute_progress_summary(
    progress: dict[str, Any],
    total_vocab: int,
    total_grammar: int,
    today: str | None = None,
) -> dict[str, Any]:
    """Computes dashboard/CLI summary metrics and 5-level SRS counts."""
    current_day = today or today_str()
    vocab_records = progress.get("vocabulary", {})
    grammar_records = progress.get("grammar", {})

    vocab_by_level = {lvl: 0 for lvl in range(1, 6)}
    due_vocab = 0
    for rec in vocab_records.values():
        lvl = max(1, min(5, int(rec.get("srs_level", 1))))
        vocab_by_level[lvl] += 1
        if is_item_due(rec, current_day):
            due_vocab += 1

    grammar_by_level = {lvl: 0 for lvl in range(1, 6)}
    due_grammar = 0
    for rec in grammar_records.values():
        lvl = max(1, min(5, int(rec.get("srs_level", 1))))
        grammar_by_level[lvl] += 1
        if is_item_due(rec, current_day):
            due_grammar += 1

    learned_vocab = len(vocab_records)
    learned_grammar = len(grammar_records)

    return {
        "total_vocab": total_vocab,
        "learned_vocab": learned_vocab,
        "unseen_vocab": max(0, total_vocab - learned_vocab),
        "due_vocab": due_vocab,
        "vocab_by_level": vocab_by_level,
        "total_grammar": total_grammar,
        "learned_grammar": learned_grammar,
        "unseen_grammar": max(0, total_grammar - learned_grammar),
        "due_grammar": due_grammar,
        "grammar_by_level": grammar_by_level,
        "sessions_completed": len(progress.get("session_history", [])),
    }
