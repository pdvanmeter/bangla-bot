from __future__ import annotations

import json
import math
import os
from collections import Counter
from typing import Any

from progress_manager import SRS_LEVEL_LABELS, is_item_due, today_str

VOCAB_DIR = os.path.join("curriculum", "vocabulary")
GRAMMAR_FILE = os.path.join("curriculum", "grammar.json")

POS_FILES: list[tuple[str, str]] = [
    ("noun", "nouns.json"),
    ("verb", "verbs.json"),
    ("adjective", "adjectives.json"),
    ("adverb", "adverbs.json"),
    ("pronoun", "pronouns.json"),
    ("postposition", "postpositions.json"),
    ("conjunction", "conjunctions.json"),
    ("interjection", "interjections.json"),
    ("number", "numbers.json"),
]

POS_LABELS: dict[str, str] = {
    "noun": "Noun",
    "verb": "Verb",
    "adjective": "Adjective",
    "adverb": "Adverb",
    "pronoun": "Pronoun",
    "postposition": "Postposition",
    "conjunction": "Conjunction",
    "interjection": "Interjection",
    "number": "Number",
}

_POS_ORDER: dict[str, int] = {pos: idx for idx, (pos, _) in enumerate(POS_FILES)}

_VOCAB_CACHE: tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], list[dict[str, Any]]] | None = None
_GRAMMAR_CACHE: tuple[list[dict[str, Any]], dict[str, dict[str, Any]]] | None = None


def load_vocabulary(
    vocab_dir: str = VOCAB_DIR,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """
    Loads all per-POS JSON files in `vocab_dir`.
    Returns `(vocab_by_pos, vocab_by_id, all_vocab_sorted_by_freq)`.
    """
    global _VOCAB_CACHE
    use_cache = os.path.abspath(vocab_dir) == os.path.abspath(VOCAB_DIR)
    if use_cache and _VOCAB_CACHE is not None:
        return _VOCAB_CACHE

    vocab_by_pos: dict[str, list[dict[str, Any]]] = {}
    vocab_by_id: dict[str, dict[str, Any]] = {}
    all_items: list[dict[str, Any]] = []

    for pos_name, filename in POS_FILES:
        file_path = os.path.join(vocab_dir, filename)
        if not os.path.exists(file_path):
            vocab_by_pos[pos_name] = []
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        normalized: list[dict[str, Any]] = []
        for item in items:
            entry = dict(item)
            entry.setdefault("pos", pos_name)
            normalized.append(entry)
            vocab_by_id[entry["id"]] = entry
            all_items.append(entry)
        vocab_by_pos[pos_name] = normalized

    all_vocab_sorted = sorted(
        all_items,
        key=lambda x: (-int(x.get("frequency", 0)), x["id"]),
    )
    result = (vocab_by_pos, vocab_by_id, all_vocab_sorted)
    if use_cache:
        _VOCAB_CACHE = result
    return result


def load_grammar(
    grammar_file: str = GRAMMAR_FILE,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """
    Loads `grammar.json` and flattens level groups into `(grammar_list, grammar_by_id)`.
    """
    global _GRAMMAR_CACHE
    use_cache = os.path.abspath(grammar_file) == os.path.abspath(GRAMMAR_FILE)
    if use_cache and _GRAMMAR_CACHE is not None:
        return _GRAMMAR_CACHE

    if not os.path.exists(grammar_file):
        return [], {}

    with open(grammar_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    grammar_list: list[dict[str, Any]] = []
    grammar_by_id: dict[str, dict[str, Any]] = {}
    counter = 1

    for level_name, entries in raw.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            item = dict(entry)
            if not item.get("id"):
                item["id"] = f"gram_{counter:04d}"
            item["curriculum_level"] = level_name
            grammar_list.append(item)
            grammar_by_id[item["id"]] = item
            counter += 1

    result = (grammar_list, grammar_by_id)
    if use_cache:
        _GRAMMAR_CACHE = result
    return result


def select_new_words(
    progress: dict[str, Any],
    count: int = 5,
    vocab_by_pos: dict[str, list[dict[str, Any]]] | None = None,
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Selects `count` unseen vocabulary words ordered by corpus frequency while
    balancing across Parts of Speech.

    When `count >= 4`, anchors at least 1 verb, 1 nominal (noun/pronoun), and
    1 modifier (adjective/adverb/number) when available, then fills remaining
    slots via penalized log-frequency priority with a soft per-POS cap.
    """
    if count <= 0:
        return []

    if vocab_by_pos is None:
        vocab_by_pos, _, _ = load_vocabulary()

    learned_ids = set(progress.get("vocabulary", {}).keys())
    if exclude_ids:
        learned_ids |= exclude_ids

    queues: dict[str, list[dict[str, Any]]] = {}
    for pos_name, _ in POS_FILES:
        queues[pos_name] = [
            item for item in vocab_by_pos.get(pos_name, []) if item["id"] not in learned_ids
        ]

    max_per_pos = max(1, math.ceil(count * 0.4))
    picked: list[dict[str, Any]] = []
    picked_per_pos: Counter[str] = Counter()

    def pop_best_from_group(
        pos_group: tuple[str, ...], enforce_cap: bool = True
    ) -> dict[str, Any] | None:
        best_pos: str | None = None
        best_key: tuple[float, int, int] | None = None

        for pos_name in pos_group:
            q = queues.get(pos_name)
            if not q:
                continue
            if enforce_cap and picked_per_pos[pos_name] >= max_per_pos:
                continue
            head = q[0]
            freq = max(1, int(head.get("frequency", 1)))
            score = math.log10(freq + 10) - 1.25 * picked_per_pos[pos_name]
            key = (score, freq, -_POS_ORDER.get(pos_name, 99))
            if best_key is None or key > best_key:
                best_key = key
                best_pos = pos_name

        if best_pos is None:
            return None

        chosen = dict(queues[best_pos].pop(0))
        picked.append(chosen)
        picked_per_pos[best_pos] += 1
        return chosen

    if count >= 4:
        pop_best_from_group(("verb",), enforce_cap=True)
        pop_best_from_group(("noun", "pronoun"), enforce_cap=True)
        pop_best_from_group(("adjective", "adverb", "number"), enforce_cap=True)

    all_pos = tuple(pos for pos, _ in POS_FILES)
    while len(picked) < count:
        nxt = pop_best_from_group(all_pos, enforce_cap=True)
        if nxt is None:
            nxt = pop_best_from_group(all_pos, enforce_cap=False)
        if nxt is None:
            break

    return picked


def _enrich_review_record(
    item: dict[str, Any],
    rec: dict[str, Any],
    current_day: str,
) -> dict[str, Any]:
    lvl = max(1, min(5, int(rec.get("srs_level", 1))))
    return {
        **item,
        "srs_level": lvl,
        "srs_label": SRS_LEVEL_LABELS.get(lvl, f"Level {lvl}"),
        "first_encountered": rec.get("first_encountered", ""),
        "last_practiced": rec.get("last_practiced", ""),
        "next_review_due": rec.get("next_review_due", ""),
        "encounters": int(rec.get("encounters", 1)),
        "last_outcome": rec.get("last_outcome", ""),
        "is_due": is_item_due(rec, current_day),
    }


def select_review_words(
    progress: dict[str, Any],
    count: int = 5,
    vocab_by_id: dict[str, dict[str, Any]] | None = None,
    exclude_ids: set[str] | None = None,
    today: str | None = None,
) -> list[dict[str, Any]]:
    """
    Selects up to `count` learned words for review.
    Strictly due items come first (lowest SRS level, oldest due/practiced date),
    backfilled by non-due learned words (lowest SRS level, least recently practiced).
    """
    if count <= 0:
        return []

    if vocab_by_id is None:
        _, vocab_by_id, _ = load_vocabulary()

    current_day = today or today_str()
    excluded = exclude_ids or set()
    vocab_records = progress.get("vocabulary", {})

    due: list[dict[str, Any]] = []
    backfill: list[dict[str, Any]] = []

    for item_id, rec in vocab_records.items():
        if item_id in excluded or item_id not in vocab_by_id:
            continue
        enriched = _enrich_review_record(vocab_by_id[item_id], rec, current_day)
        if enriched["is_due"]:
            due.append(enriched)
        else:
            backfill.append(enriched)

    due.sort(
        key=lambda x: (
            x["srs_level"],
            x["next_review_due"],
            x["last_practiced"],
            x["id"],
        )
    )
    backfill.sort(
        key=lambda x: (
            x["srs_level"],
            x["last_practiced"],
            x["next_review_due"],
            x["id"],
        )
    )
    return (due + backfill)[:count]


def select_session_grammar(
    progress: dict[str, Any],
    count: int = 2,
    allow_new: bool = True,
    grammar_list: list[dict[str, Any]] | None = None,
    today: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Selects `(new_grammar, review_grammar)` up to `count` items total.
    """
    if count <= 0:
        return [], []

    if grammar_list is None:
        grammar_list, _ = load_grammar()

    current_day = today or today_str()
    grammar_records = progress.get("grammar", {})

    due_reviews: list[dict[str, Any]] = []
    backfill_reviews: list[dict[str, Any]] = []
    unseen: list[dict[str, Any]] = []

    for item in grammar_list:
        gid = item["id"]
        rec = grammar_records.get(gid)
        if rec is None:
            unseen.append(dict(item))
        else:
            enriched = _enrich_review_record(item, rec, current_day)
            if enriched["is_due"]:
                due_reviews.append(enriched)
            else:
                backfill_reviews.append(enriched)

    due_reviews.sort(
        key=lambda x: (
            x["srs_level"],
            x["next_review_due"],
            x["last_practiced"],
            x["id"],
        )
    )
    backfill_reviews.sort(
        key=lambda x: (
            x["srs_level"],
            x["last_practiced"],
            x["next_review_due"],
            x["id"],
        )
    )

    if not allow_new:
        return [], (due_reviews + backfill_reviews)[:count]

    chosen_new: list[dict[str, Any]] = []
    chosen_review: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    if due_reviews and unseen and count >= 2:
        review_quota = min(len(due_reviews), count // 2)
        for item in due_reviews[:review_quota]:
            chosen_review.append(item)
            used_ids.add(item["id"])
        for item in unseen:
            if len(chosen_new) + len(chosen_review) >= count:
                break
            chosen_new.append(item)
            used_ids.add(item["id"])
    else:
        for item in unseen:
            if len(chosen_new) >= count:
                break
            chosen_new.append(item)
            used_ids.add(item["id"])

    for item in due_reviews + backfill_reviews:
        if len(chosen_new) + len(chosen_review) >= count:
            break
        if item["id"] not in used_ids:
            chosen_review.append(item)
            used_ids.add(item["id"])

    return chosen_new, chosen_review


def get_known_supporting_vocab(
    progress: dict[str, Any],
    vocab_by_id: dict[str, dict[str, Any]] | None = None,
    limit: int = 75,
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Returns up to `limit` already-learned words (excluding `exclude_ids`)
    sorted by highest SRS level and highest corpus frequency so the tutor
    can build practice sentences using familiar words.
    """
    if vocab_by_id is None:
        _, vocab_by_id, _ = load_vocabulary()

    excluded = exclude_ids or set()
    vocab_records = progress.get("vocabulary", {})
    candidates: list[dict[str, Any]] = []

    for item_id, rec in vocab_records.items():
        if item_id in excluded or item_id not in vocab_by_id:
            continue
        lvl = max(1, min(5, int(rec.get("srs_level", 1))))
        item = dict(vocab_by_id[item_id])
        item["srs_level"] = lvl
        candidates.append(item)

    candidates.sort(
        key=lambda x: (-x["srs_level"], -int(x.get("frequency", 0)), x["id"])
    )
    return candidates[:limit]


def query_vocabulary(
    progress: dict[str, Any],
    search: str = "",
    pos_filter: str = "all",
    status_filter: str = "all",
    loanword_filter: str = "all",
    sort_by: str = "frequency",
    offset: int = 0,
    limit: int = 50,
    today: str | None = None,
    all_vocab: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Queries the full vocabulary with SRS enrichment, filtering, sorting, and pagination.
    Returns `(page_items, total_matched)`.
    """
    if all_vocab is None:
        _, _, all_vocab = load_vocabulary()

    current_day = today or today_str()
    vocab_records = progress.get("vocabulary", {})
    q = search.strip().lower()

    matched: list[dict[str, Any]] = []
    for base in all_vocab:
        if pos_filter != "all" and base.get("pos") != pos_filter:
            continue

        is_loan = bool(base.get("is_loanword", False))
        if loanword_filter == "loanword" and not is_loan:
            continue
        if loanword_filter == "native" and is_loan:
            continue

        rec = vocab_records.get(base["id"])
        if rec is None:
            srs_level = 0
            srs_label = SRS_LEVEL_LABELS[0]
            first_enc = ""
            last_prac = ""
            next_due = ""
            encounters = 0
            due_now = False
        else:
            srs_level = max(1, min(5, int(rec.get("srs_level", 1))))
            srs_label = SRS_LEVEL_LABELS.get(srs_level, f"Level {srs_level}")
            first_enc = rec.get("first_encountered", "")
            last_prac = rec.get("last_practiced", "")
            next_due = rec.get("next_review_due", "")
            encounters = int(rec.get("encounters", 1))
            due_now = is_item_due(rec, current_day)

        if status_filter == "encountered" and srs_level == 0:
            continue
        if status_filter == "unseen" and srs_level != 0:
            continue
        if status_filter == "due" and not due_now:
            continue
        if status_filter.startswith("level_"):
            try:
                target_lvl = int(status_filter.split("_", 1)[1])
            except ValueError:
                target_lvl = -1
            if srs_level != target_lvl:
                continue

        if q:
            haystack = " ".join(
                [
                    str(base.get("id", "")),
                    str(base.get("bengali", "")),
                    str(base.get("transliteration", "")),
                    str(base.get("english", "")),
                    str(base.get("bengali_numeral", "")),
                ]
            ).lower()
            if q not in haystack:
                continue

        matched.append(
            {
                **base,
                "srs_level": srs_level,
                "srs_label": srs_label,
                "first_encountered": first_enc,
                "last_practiced": last_prac,
                "next_review_due": next_due,
                "encounters": encounters,
                "is_due": due_now,
            }
        )

    if sort_by == "srs_level":
        matched.sort(
            key=lambda x: (
                x["srs_level"] == 0,
                -x["srs_level"],
                -int(x.get("frequency", 0)),
                x["id"],
            )
        )
    elif sort_by == "first_encountered":
        with_date = [m for m in matched if m["first_encountered"]]
        without_date = [m for m in matched if not m["first_encountered"]]
        with_date.sort(
            key=lambda x: (x["first_encountered"], int(x.get("frequency", 0))),
            reverse=True,
        )
        matched = with_date + without_date
    elif sort_by == "last_practiced":
        with_date = [m for m in matched if m["last_practiced"]]
        without_date = [m for m in matched if not m["last_practiced"]]
        with_date.sort(
            key=lambda x: (x["last_practiced"], int(x.get("frequency", 0))),
            reverse=True,
        )
        matched = with_date + without_date
    else:
        matched.sort(key=lambda x: (-int(x.get("frequency", 0)), x["id"]))

    total = len(matched)
    if limit <= 0:
        return matched[offset:], total
    return matched[offset : offset + limit], total
