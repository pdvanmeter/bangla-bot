from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from curriculum_manager import (
    GRAMMAR_FILE,
    VOCAB_DIR,
    get_known_supporting_vocab,
    load_grammar,
    load_vocabulary,
    select_new_words,
    select_review_words,
    select_session_grammar,
)
from progress_manager import PROGRESS_FILE, apply_session_scores, ensure_progress_file

BASE_PROMPT_FILE = os.path.join("prompts", "tutor_base.md")


@dataclass
class SessionPlan:
    mode: str  # "learn" | "review" | "conversation" | "custom"
    submode: str  # "full" | "conversation_only"
    new_words: list[dict[str, Any]] = field(default_factory=list)
    review_words: list[dict[str, Any]] = field(default_factory=list)
    new_grammar: list[dict[str, Any]] = field(default_factory=list)
    review_grammar: list[dict[str, Any]] = field(default_factory=list)
    supporting_vocab: list[dict[str, Any]] = field(default_factory=list)

    @property
    def all_vocab_ids(self) -> set[str]:
        return {w["id"] for w in self.new_words} | {w["id"] for w in self.review_words}

    @property
    def all_grammar_ids(self) -> set[str]:
        return {g["id"] for g in self.new_grammar} | {g["id"] for g in self.review_grammar}

    @property
    def all_item_ids(self) -> set[str]:
        return self.all_vocab_ids | self.all_grammar_ids

    @property
    def new_item_ids(self) -> set[str]:
        return {w["id"] for w in self.new_words} | {g["id"] for g in self.new_grammar}

    @property
    def total_items(self) -> int:
        return len(self.all_item_ids)

    def summary_label(self) -> str:
        word_parts: list[str] = []
        if self.new_words:
            word_parts.append(f"{len(self.new_words)} new")
        if self.review_words:
            word_parts.append(f"{len(self.review_words)} review")
        word_str = ", ".join(word_parts) if word_parts else "0 words"
        gram_count = len(self.new_grammar) + len(self.review_grammar)
        mode_title = self.mode.capitalize()
        if self.mode == "custom" and self.submode == "conversation_only":
            mode_title = "Custom (Conversation)"
        return f"{mode_title}: {word_str} | {gram_count} grammar"


def create_learn_session(
    new_word_count: int = 5,
    review_word_count: int = 5,
    grammar_count: int = 2,
    progress_path: str = PROGRESS_FILE,
    vocab_dir: str = VOCAB_DIR,
    grammar_file: str = GRAMMAR_FILE,
) -> SessionPlan:
    progress = ensure_progress_file(progress_path)
    vocab_by_pos, vocab_by_id, _ = load_vocabulary(vocab_dir)
    grammar_list, _ = load_grammar(grammar_file)

    new_words = select_new_words(
        progress, count=max(0, new_word_count), vocab_by_pos=vocab_by_pos
    )
    new_vocab_ids = {w["id"] for w in new_words}
    review_words = select_review_words(
        progress,
        count=max(0, review_word_count),
        vocab_by_id=vocab_by_id,
        exclude_ids=new_vocab_ids,
    )
    new_grammar, review_grammar = select_session_grammar(
        progress,
        count=max(0, grammar_count),
        allow_new=True,
        grammar_list=grammar_list,
    )
    target_vocab_ids = new_vocab_ids | {w["id"] for w in review_words}
    supporting_vocab = get_known_supporting_vocab(
        progress, vocab_by_id=vocab_by_id, limit=75, exclude_ids=target_vocab_ids
    )

    plan = SessionPlan(
        mode="learn",
        submode="full",
        new_words=new_words,
        review_words=review_words,
        new_grammar=new_grammar,
        review_grammar=review_grammar,
        supporting_vocab=supporting_vocab,
    )
    if plan.total_items == 0:
        raise ValueError("No vocabulary or grammar items available for a Learning session.")
    return plan


def create_review_session(
    review_word_count: int = 10,
    grammar_count: int = 2,
    progress_path: str = PROGRESS_FILE,
    vocab_dir: str = VOCAB_DIR,
    grammar_file: str = GRAMMAR_FILE,
) -> SessionPlan:
    progress = ensure_progress_file(progress_path)
    _, vocab_by_id, _ = load_vocabulary(vocab_dir)
    grammar_list, _ = load_grammar(grammar_file)

    review_words = select_review_words(
        progress, count=max(0, review_word_count), vocab_by_id=vocab_by_id
    )
    new_grammar, review_grammar = select_session_grammar(
        progress,
        count=max(0, grammar_count),
        allow_new=False,
        grammar_list=grammar_list,
    )
    supporting_vocab = get_known_supporting_vocab(
        progress,
        vocab_by_id=vocab_by_id,
        limit=75,
        exclude_ids={w["id"] for w in review_words},
    )

    plan = SessionPlan(
        mode="review",
        submode="full",
        new_words=[],
        review_words=review_words,
        new_grammar=new_grammar,
        review_grammar=review_grammar,
        supporting_vocab=supporting_vocab,
    )
    if plan.total_items == 0:
        raise ValueError(
            "No learned words or grammar concepts available to review yet. Start a Learning session first!"
        )
    return plan


def create_conversation_session(
    review_word_count: int = 10,
    grammar_count: int = 2,
    progress_path: str = PROGRESS_FILE,
    vocab_dir: str = VOCAB_DIR,
    grammar_file: str = GRAMMAR_FILE,
) -> SessionPlan:
    plan = create_review_session(
        review_word_count=review_word_count,
        grammar_count=grammar_count,
        progress_path=progress_path,
        vocab_dir=vocab_dir,
        grammar_file=grammar_file,
    )
    plan.mode = "conversation"
    plan.submode = "conversation_only"
    return plan


def create_custom_session(
    vocab_ids: list[str],
    grammar_ids: list[str] | None = None,
    submode: str = "full",
    progress_path: str = PROGRESS_FILE,
    vocab_dir: str = VOCAB_DIR,
    grammar_file: str = GRAMMAR_FILE,
) -> SessionPlan:
    if submode not in ("full", "conversation_only"):
        raise ValueError(f"Unsupported custom session submode: {submode}")

    progress = ensure_progress_file(progress_path)
    _, vocab_by_id, _ = load_vocabulary(vocab_dir)
    _, grammar_by_id = load_grammar(grammar_file)

    learned_vocab = progress.get("vocabulary", {})
    learned_grammar = progress.get("grammar", {})

    new_words: list[dict[str, Any]] = []
    review_words: list[dict[str, Any]] = []
    seen_vid: set[str] = set()

    for vid in vocab_ids:
        if vid in seen_vid or vid not in vocab_by_id:
            continue
        seen_vid.add(vid)
        item = dict(vocab_by_id[vid])
        rec = learned_vocab.get(vid)
        if rec is None:
            new_words.append(item)
        else:
            item["srs_level"] = int(rec.get("srs_level", 1))
            item["last_practiced"] = rec.get("last_practiced", "")
            review_words.append(item)

    new_grammar: list[dict[str, Any]] = []
    review_grammar: list[dict[str, Any]] = []
    seen_gid: set[str] = set()

    for gid in grammar_ids or []:
        if gid in seen_gid or gid not in grammar_by_id:
            continue
        seen_gid.add(gid)
        g_item = dict(grammar_by_id[gid])
        rec = learned_grammar.get(gid)
        if rec is None:
            new_grammar.append(g_item)
        else:
            g_item["srs_level"] = int(rec.get("srs_level", 1))
            g_item["last_practiced"] = rec.get("last_practiced", "")
            review_grammar.append(g_item)

    supporting_vocab = get_known_supporting_vocab(
        progress, vocab_by_id=vocab_by_id, limit=75, exclude_ids=seen_vid
    )

    plan = SessionPlan(
        mode="custom",
        submode=submode,
        new_words=new_words,
        review_words=review_words,
        new_grammar=new_grammar,
        review_grammar=review_grammar,
        supporting_vocab=supporting_vocab,
    )
    if plan.total_items == 0:
        raise ValueError(
            "Please select at least one valid vocabulary word or grammar concept for a Custom session."
        )
    return plan


def _format_vocab_for_prompt(items: list[dict[str, Any]], include_srs: bool) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for w in items:
        entry: dict[str, Any] = {
            "id": w["id"],
            "bengali": w["bengali"],
            "transliteration": w["transliteration"],
            "english": w["english"],
            "pos": w["pos"],
            "is_loanword": bool(w.get("is_loanword", False)),
        }
        if w.get("pos") == "number":
            entry["bengali_numeral"] = w.get("bengali_numeral", "")
            entry["numeric_value"] = w.get("numeric_value", "")
            if w.get("notes"):
                entry["notes"] = w["notes"]
        if include_srs and "srs_level" in w:
            entry["srs_level"] = w["srs_level"]
        formatted.append(entry)
    return formatted


def _format_grammar_for_prompt(items: list[dict[str, Any]], include_srs: bool) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for g in items:
        entry: dict[str, Any] = {
            "id": g["id"],
            "concept": g.get("concept", ""),
            "description": g.get("description", ""),
        }
        for extra_key in ("rules", "levels", "examples"):
            if extra_key in g:
                entry[extra_key] = g[extra_key]
        if include_srs and "srs_level" in g:
            entry["srs_level"] = g["srs_level"]
        formatted.append(entry)
    return formatted


def build_session_system_instructions(
    plan: SessionPlan,
    base_prompt_path: str = BASE_PROMPT_FILE,
) -> str:
    """
    Loads the base tutor prompt and appends mode-specific session structure,
    target items, supporting known vocabulary, and scoring requirements.
    """
    with open(base_prompt_path, "r", encoding="utf-8") as f:
        base_prompt = f.read().strip()

    has_new = bool(plan.new_words or plan.new_grammar)

    if plan.submode == "conversation_only":
        quick_ref_note = (
            "Briefly show a compact quick-reference list of ONLY the New items above your opening Bangla line. "
            if has_new
            else "Do NOT introduce or list the review items beforehand — jump straight into conversation. "
        )
        workflow_block = (
            "### Session Workflow: Conversation Practice Only\n"
            "1. **Skip Intro & Translation Drills**: " + quick_ref_note + "\n"
            "2. **Interactive Bangla Practice Conversation**: Start immediately with a natural, welcoming Bengali greeting/question (`<audio>...</audio>` + transliteration) that begins weaving in the session's target words and grammar concepts. Keep the conversation flowing across multiple turns until EVERY target word and grammar concept in the session has been actively used or tested. Provide brief, helpful feedback in English on the learner's Bangla replies (without spoiling missing target words—give hints first), and then continue the Bangla dialogue.\n"
            "3. **Conclude & Score**: Once all target items are covered (or the learner asks to finish), present a clear English scorecard summarizing their recall on every item and call `submit_session_scores` with ALL required `item_id`s."
        )
    elif has_new:
        workflow_block = (
            "### Session Workflow: Full Learning Session\n"
            "1. **Phase 1 — Introduction (Initial Message ONLY)**:\n"
            "   - Present ONLY the **New Vocabulary** and **New Grammar Concepts** clearly (Bengali script in `<audio>...</audio>`, transliteration, English meaning, POS). Highlight any `is_loanword: true` items as English loanwords, and show both `bengali_numeral` and `bengali` word for any numbers.\n"
            "   - **CRITICAL RULE**: Do NOT list, mention, or pre-explain the **Review Vocabulary** or **Review Grammar** in Phase 1.\n"
            "   - End Phase 1 by inviting the learner to reply when they are ready for the translation exercises (or optionally answer a simple warm-up).\n"
            "2. **Phase 2 — Bidirectional Translation Questions (One Question at a Time)**:\n"
            "   - Ask **one translation question per turn**, alternating between English -> Bangla and Bangla -> English.\n"
            "   - Ensure your questions systematically test ALL **New Vocabulary**, **Review Vocabulary**, **New Grammar**, and **Review Grammar** (combine multiple targets naturally per sentence so the drill stays brisk and engaging, ~6–10 questions total).\n"
            "   - On an incorrect answer, explain what part needs adjustment and give a hint **without stating the direct answer**, letting the learner retry.\n"
            "3. **Phase 3 — Bangla Practice Conversation**:\n"
            "   - After translation questions have covered the items, smoothly transition into a short, natural Bangla conversation (3–5 exchanges) that prompts the learner to use all session words and grammar constructions in context.\n"
            "   - Give constructive feedback in English while keeping the Bangla conversation moving until everything is covered.\n"
            "4. **Phase 4 — Session Conclusion & `submit_session_scores`**:\n"
            "   - Present a concise scorecard covering every session item and invoke `submit_session_scores` with ALL required `item_id`s."
        )
    else:
        workflow_block = (
            "### Session Workflow: Full Review Session\n"
            "1. **Skip Phase 1 (No Introduction)**: Do NOT pre-list or explain the review words or grammar beforehand. Begin immediately in your first message with Question 1 of Phase 2.\n"
            "2. **Phase 2 — Bidirectional Translation Questions (One Question at a Time)**:\n"
            "   - Ask **one translation question per turn**, alternating between English -> Bangla and Bangla -> English, covering ALL **Review Vocabulary** and **Review Grammar** items.\n"
            "   - On an incorrect answer, give targeted hints **without stating the direct answer**, letting the learner retry.\n"
            "3. **Phase 3 — Bangla Practice Conversation**:\n"
            "   - Once all items have been drilled in translation, transition into a natural Bangla conversation (3–5 exchanges) practicing all session words and grammar. Give English coaching as needed while keeping the conversation going until everything is covered.\n"
            "4. **Phase 4 — Session Conclusion & `submit_session_scores`**:\n"
            "   - Present a concise scorecard for every item and invoke `submit_session_scores` with ALL required `item_id`s."
        )

    supporting_lines = [
        f"- {w['bengali']} ({w['transliteration']}: {w['english']} [{w['pos']}])"
        for w in plan.supporting_vocab
    ]
    supporting_text = (
        "\n".join(supporting_lines)
        if supporting_lines
        else "(None yet — keep sentences very simple and stick closely to the session vocabulary and basic pronouns/verbs.)"
    )

    required_ids = sorted(plan.all_item_ids)

    briefing = (
        f"\n\n# Current Session Briefing\n"
        f"**Session Mode:** `{plan.mode}` (`{plan.submode}`)\n"
        f"**Summary:** {plan.summary_label()}\n\n"
        f"{workflow_block}\n\n"
        f"## New Vocabulary (Introduce in Phase 1)\n```json\n"
        f"{json.dumps(_format_vocab_for_prompt(plan.new_words, include_srs=False), ensure_ascii=False, indent=2)}\n```\n\n"
        f"## Review Vocabulary (Withhold from Intro — Test in Drills/Conversation)\n```json\n"
        f"{json.dumps(_format_vocab_for_prompt(plan.review_words, include_srs=True), ensure_ascii=False, indent=2)}\n```\n\n"
        f"## New Grammar Concepts (Introduce in Phase 1)\n```json\n"
        f"{json.dumps(_format_grammar_for_prompt(plan.new_grammar, include_srs=False), ensure_ascii=False, indent=2)}\n```\n\n"
        f"## Review Grammar Concepts (Withhold from Intro — Test in Drills/Conversation)\n```json\n"
        f"{json.dumps(_format_grammar_for_prompt(plan.review_grammar, include_srs=True), ensure_ascii=False, indent=2)}\n```\n\n"
        f"## Previously Learned Supporting Vocabulary (Safe to use when forming sentences)\n"
        f"{supporting_text}\n\n"
        f"## Required Session Item IDs (MUST ALL be passed to `submit_session_scores` at the end)\n"
        f"`{json.dumps(required_ids)}`\n"
    )
    return base_prompt + briefing


def build_kickoff_message(plan: SessionPlan) -> str:
    """Returns the initial prompt sent to start the tutor session."""
    if plan.submode == "conversation_only":
        return (
            "The learner has started a Conversation session. Follow the Session Briefing: "
            "open directly with your welcoming Bengali conversation starter covering the target items."
        )
    if plan.new_words or plan.new_grammar:
        return (
            "The learner has started a new session. Follow Phase 1 of the Session Briefing: "
            "introduce ONLY the New Vocabulary and New Grammar concepts clearly (do NOT reveal the "
            "Review items), and ask when the learner is ready to begin the translation drills."
        )
    return (
        "The learner has started a Review session. Skip introductions and immediately present "
        "Question 1 of Phase 2 (Bidirectional Translation Questions) using the Review items."
    )


class ItemScoreInput(BaseModel):
    item_id: str = Field(
        description="Exact ID from Required Session Item IDs, e.g., 'noun_0001' or 'gram_0001'."
    )
    outcome: Literal["promote", "stay", "demote"] = Field(
        description=(
            "'promote' = recalled easily/accurately; "
            "'stay' = recalled with effort or after hints; "
            "'demote' = could not recall or answer had to be revealed."
        )
    )
    note: str = Field(
        default="",
        description="Brief 1-line note on learner performance for this item.",
    )


def make_session_score_tool(
    plan: SessionPlan,
    progress_path: str = PROGRESS_FILE,
    on_scores_saved: Callable[[dict[str, Any]], None] | None = None,
):
    """
    Creates a session-scoped `submit_session_scores` callable tool bound to `plan`.
    Validates that all required session IDs are present before persisting via `progress_manager`.
    """
    pending_scores: dict[str, dict[str, Any]] = {}
    state = {"finalized": False}
    required_ids = set(plan.all_item_ids)

    def submit_session_scores(scores: list[ItemScoreInput]) -> str:
        """
        Records end-of-session SRS outcomes ('promote', 'stay', or 'demote') for every
        vocabulary word and grammar concept covered in the current session.
        """
        if state["finalized"]:
            return "Session scores have already been saved for this session."

        invalid_ids: list[str] = []
        for entry in scores:
            if isinstance(entry, dict):
                item_id = str(entry.get("item_id", "")).strip()
                outcome = str(entry.get("outcome", "stay")).strip().lower()
                note = str(entry.get("note", "")).strip()
            else:
                item_id = str(entry.item_id).strip()
                outcome = str(entry.outcome).strip().lower()
                note = str(entry.note).strip()

            if item_id not in required_ids:
                if item_id:
                    invalid_ids.append(item_id)
                continue

            pending_scores[item_id] = {
                "item_id": item_id,
                "outcome": outcome,
                "note": note,
            }

        missing = sorted(required_ids - set(pending_scores.keys()))
        if missing:
            parts = [
                f"Recorded {len(pending_scores)}/{len(required_ids)} valid items, "
                f"but missing scores for: {json.dumps(missing)}."
            ]
            if invalid_ids:
                parts.append(f"Ignored unrecognized item_ids: {json.dumps(invalid_ids)}.")
            parts.append(
                "Please call `submit_session_scores` again with the missing item_ids so progress can be saved."
            )
            return " ".join(parts)

        result = apply_session_scores(
            scores=list(pending_scores.values()),
            new_item_ids=plan.new_item_ids,
            valid_vocab_ids=plan.all_vocab_ids,
            valid_grammar_ids=plan.all_grammar_ids,
            mode=plan.mode,
            file_path=progress_path,
        )
        state["finalized"] = True

        if on_scores_saved is not None:
            on_scores_saved(result)

        lines = [
            f"Saved SRS updates for {len(result['updated'])} items ({plan.mode} session):"
        ]
        for u in result["updated"]:
            tag = "NEW -> Level 1" if u["was_new"] else f"L{u['old_level']} -> L{u['new_level']} ({u['outcome']})"
            lines.append(f"- {u['item_id']}: {tag}, next due {u['next_review_due']}")
        return "\n".join(lines)

    return submit_session_scores
