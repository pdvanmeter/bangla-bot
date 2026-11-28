import os
import tempfile
import unittest

from curriculum_manager import (
    load_grammar,
    load_vocabulary,
    query_vocabulary,
    select_new_words,
    select_review_words,
    select_session_grammar,
)
from progress_manager import (
    SRS_INTERVAL_DAYS,
    add_days,
    apply_session_scores,
    compute_progress_summary,
    ensure_progress_file,
    reset_progress_data,
)
from session_builder import (
    build_kickoff_message,
    build_session_system_instructions,
    create_conversation_session,
    create_custom_session,
    create_learn_session,
    create_review_session,
    make_session_score_tool,
)
from tutor_core import PRIMARY_MODEL, build_generate_config


class TestCurriculumAndSRS(unittest.TestCase):
    def test_curriculum_loads_all_pos_and_grammar(self):
        self.assertFalse(os.path.exists(os.path.join("curriculum", "vocabulary.json")))
        vocab_by_pos, vocab_by_id, all_vocab = load_vocabulary()
        expected_counts = {
            "noun": 3070,
            "adjective": 1035,
            "adverb": 295,
            "verb": 265,
            "interjection": 137,
            "pronoun": 86,
            "postposition": 57,
            "conjunction": 55,
            "number": 39,
        }
        for pos_name, exp_cnt in expected_counts.items():
            self.assertEqual(len(vocab_by_pos[pos_name]), exp_cnt, f"Mismatch for {pos_name}")
        self.assertEqual(len(all_vocab), 5039)
        self.assertEqual(len(vocab_by_id), 5039)

        grammar_list, grammar_by_id = load_grammar()
        self.assertEqual(len(grammar_list), 5)
        for i in range(1, 6):
            self.assertIn(f"gram_000{i}", grammar_by_id)

    def test_select_new_words_pos_balance(self):
        vocab_by_pos, _, _ = load_vocabulary()
        progress = {"schema_version": 2, "vocabulary": {}, "grammar": {}, "session_history": []}

        # Simulate 5 consecutive 5-word sessions
        seen_ids: set[str] = set()
        for session_idx in range(5):
            picked = select_new_words(progress, count=5, vocab_by_pos=vocab_by_pos)
            self.assertEqual(len(picked), 5)
            pos_counts: dict[str, int] = {}
            for w in picked:
                self.assertNotIn(w["id"], seen_ids)
                seen_ids.add(w["id"])
                pos_counts[w["pos"]] = pos_counts.get(w["pos"], 0) + 1
                progress["vocabulary"][w["id"]] = {"srs_level": 1}

            self.assertIn("verb", pos_counts, f"Session {session_idx} missing a verb")
            self.assertTrue(
                "noun" in pos_counts or "pronoun" in pos_counts,
                f"Session {session_idx} missing nominal",
            )
            self.assertTrue(
                any(p in pos_counts for p in ("adjective", "adverb", "number")),
                f"Session {session_idx} missing modifier",
            )
            for p, cnt in pos_counts.items():
                self.assertLessEqual(cnt, 2, f"Session {session_idx} over-picked {p}: {cnt}")

    def test_select_review_words_due_before_backfill(self):
        _, vocab_by_id, _ = load_vocabulary()
        today = "2026-11-27"
        progress = {
            "schema_version": 2,
            "vocabulary": {
                # Not due yet (future), low level
                "noun_0001": {
                    "srs_level": 1,
                    "first_encountered": "2026-11-26",
                    "last_practiced": "2026-11-26",
                    "next_review_due": "2026-11-29",
                    "encounters": 1,
                },
                # Strictly due, level 2
                "verb_0001": {
                    "srs_level": 2,
                    "first_encountered": "2026-11-20",
                    "last_practiced": "2026-11-24",
                    "next_review_due": "2026-11-27",
                    "encounters": 2,
                },
                # Strictly due, level 1 (should come first!)
                "pron_0001": {
                    "srs_level": 1,
                    "first_encountered": "2026-11-25",
                    "last_practiced": "2026-11-25",
                    "next_review_due": "2026-11-26",
                    "encounters": 1,
                },
                # Not due yet, level 3
                "adj_0001": {
                    "srs_level": 3,
                    "first_encountered": "2026-11-18",
                    "last_practiced": "2026-11-25",
                    "next_review_due": "2026-12-02",
                    "encounters": 3,
                },
            },
            "grammar": {},
        }

        selected = select_review_words(progress, count=4, vocab_by_id=vocab_by_id, today=today)
        self.assertEqual(
            [w["id"] for w in selected],
            ["pron_0001", "verb_0001", "noun_0001", "adj_0001"],
        )
        self.assertTrue(selected[0]["is_due"])
        self.assertTrue(selected[1]["is_due"])
        self.assertFalse(selected[2]["is_due"])

    def test_srs_transitions_and_new_item_level_1_lock(self):
        _, vocab_by_id, _ = load_vocabulary()
        _, grammar_by_id = load_grammar()
        valid_v = set(vocab_by_id.keys())
        valid_g = set(grammar_by_id.keys())

        with tempfile.TemporaryDirectory() as tmpdir:
            pfile = os.path.join(tmpdir, "progress.json")
            day1 = "2026-11-01"

            # New items should lock at Level 1 even if outcome == "promote"
            res1 = apply_session_scores(
                scores=[
                    {"item_id": "noun_0001", "outcome": "promote", "note": "easy"},
                    {"item_id": "verb_0001", "outcome": "demote", "note": "missed"},
                    {"item_id": "gram_0001", "outcome": "promote", "note": "great"},
                ],
                new_item_ids={"noun_0001", "verb_0001", "gram_0001"},
                valid_vocab_ids=valid_v,
                valid_grammar_ids=valid_g,
                mode="learn",
                today=day1,
                file_path=pfile,
            )
            data = res1["progress"]
            self.assertEqual(data["vocabulary"]["noun_0001"]["srs_level"], 1)
            self.assertEqual(
                data["vocabulary"]["noun_0001"]["next_review_due"],
                add_days(day1, SRS_INTERVAL_DAYS[1]),
            )
            self.assertEqual(data["vocabulary"]["verb_0001"]["srs_level"], 1)
            self.assertEqual(data["grammar"]["gram_0001"]["srs_level"], 1)

            # Day 2 review: promote, stay, demote floor at 1
            day2 = "2026-11-02"
            res2 = apply_session_scores(
                scores=[
                    {"item_id": "noun_0001", "outcome": "promote"},
                    {"item_id": "verb_0001", "outcome": "demote"},
                    {"item_id": "gram_0001", "outcome": "stay"},
                ],
                new_item_ids=set(),
                valid_vocab_ids=valid_v,
                valid_grammar_ids=valid_g,
                mode="review",
                today=day2,
                file_path=pfile,
            )
            d2 = res2["progress"]
            self.assertEqual(d2["vocabulary"]["noun_0001"]["srs_level"], 2)
            self.assertEqual(d2["vocabulary"]["noun_0001"]["first_encountered"], day1)
            self.assertEqual(d2["vocabulary"]["noun_0001"]["encounters"], 2)
            self.assertEqual(
                d2["vocabulary"]["noun_0001"]["next_review_due"],
                add_days(day2, SRS_INTERVAL_DAYS[2]),
            )
            self.assertEqual(d2["vocabulary"]["verb_0001"]["srs_level"], 1)
            self.assertEqual(d2["grammar"]["gram_0001"]["srs_level"], 1)

            # Promote noun_0001 up to max level 5 and verify cap
            for step in range(4):
                apply_session_scores(
                    scores=[{"item_id": "noun_0001", "outcome": "promote"}],
                    new_item_ids=set(),
                    valid_vocab_ids=valid_v,
                    valid_grammar_ids=valid_g,
                    mode="review",
                    today=day2,
                    file_path=pfile,
                )
            final_data = ensure_progress_file(pfile)
            self.assertEqual(final_data["vocabulary"]["noun_0001"]["srs_level"], 5)
            # Demote from 5 -> 4
            apply_session_scores(
                scores=[{"item_id": "noun_0001", "outcome": "demote"}],
                new_item_ids=set(),
                valid_vocab_ids=valid_v,
                valid_grammar_ids=valid_g,
                mode="review",
                today=day2,
                file_path=pfile,
            )
            final_data = ensure_progress_file(pfile)
            self.assertEqual(final_data["vocabulary"]["noun_0001"]["srs_level"], 4)

    def test_session_builder_prompts_and_score_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pfile = os.path.join(tmpdir, "progress.json")
            reset_progress_data(pfile)

            # Review session fails cleanly when nothing is learned yet
            with self.assertRaises(ValueError):
                create_review_session(progress_path=pfile)

            # Learn session selects 5 new, 0 review (none learned), 2 grammar
            plan = create_learn_session(
                new_word_count=5, review_word_count=5, grammar_count=2, progress_path=pfile
            )
            self.assertEqual(len(plan.new_words), 5)
            self.assertEqual(len(plan.review_words), 0)
            self.assertEqual(len(plan.new_grammar), 2)
            prompt_text = build_session_system_instructions(plan)
            self.assertIn("Current Session Briefing", prompt_text)
            self.assertIn("Full Learning Session", prompt_text)
            self.assertTrue(build_kickoff_message(plan))

            saved_results: list[dict] = []
            tool = make_session_score_tool(
                plan, progress_path=pfile, on_scores_saved=saved_results.append
            )
            cfg = build_generate_config(PRIMARY_MODEL, prompt_text, tools=[tool])
            self.assertEqual(len(cfg.tools), 1)

            # Partial submission does not finalize
            all_ids = sorted(plan.all_item_ids)
            msg_partial = tool(
                [{"item_id": all_ids[0], "outcome": "promote", "note": "good"}]
            )
            self.assertIn("missing scores", msg_partial)
            self.assertEqual(len(saved_results), 0)

            # Submit remaining IDs
            msg_complete = tool(
                [{"item_id": iid, "outcome": "promote", "note": ""} for iid in all_ids[1:]]
            )
            self.assertIn("Saved SRS updates", msg_complete)
            self.assertEqual(len(saved_results), 1)

            # Now review and conversation sessions work
            rev_plan = create_review_session(
                review_word_count=5, grammar_count=2, progress_path=pfile
            )
            self.assertEqual(len(rev_plan.review_words), 5)
            self.assertEqual(len(rev_plan.new_words), 0)
            self.assertIn("Full Review Session", build_session_system_instructions(rev_plan))

            conv_plan = create_conversation_session(
                review_word_count=5, grammar_count=2, progress_path=pfile
            )
            self.assertEqual(conv_plan.submode, "conversation_only")
            self.assertIn("Conversation Practice Only", build_session_system_instructions(conv_plan))

            # Custom session mixing 1 learned and 1 unseen word
            _, _, all_vocab = load_vocabulary()
            learned_vid = sorted(plan.all_vocab_ids)[0]
            unseen_vid = next(w["id"] for w in all_vocab if w["id"] not in plan.all_vocab_ids)
            custom_plan = create_custom_session(
                vocab_ids=[learned_vid, unseen_vid],
                grammar_ids=["gram_0005"],
                submode="full",
                progress_path=pfile,
            )
            self.assertEqual(len(custom_plan.review_words), 1)
            self.assertEqual(len(custom_plan.new_words), 1)
            self.assertEqual(len(custom_plan.new_grammar), 1)

    def test_query_vocabulary_filters_and_sorting(self):
        _, _, all_vocab = load_vocabulary()
        progress = {
            "schema_version": 2,
            "vocabulary": {
                "noun_0001": {
                    "srs_level": 2,
                    "first_encountered": "2026-11-20",
                    "last_practiced": "2026-11-25",
                    "next_review_due": "2026-11-26",
                    "encounters": 2,
                },
                "verb_0001": {
                    "srs_level": 4,
                    "first_encountered": "2026-11-15",
                    "last_practiced": "2026-11-27",
                    "next_review_due": "2026-12-11",
                    "encounters": 4,
                },
            },
            "grammar": {},
        }

        enc_items, enc_total = query_vocabulary(
            progress, status_filter="encountered", today="2026-11-27", all_vocab=all_vocab
        )
        self.assertEqual(enc_total, 2)
        self.assertEqual(len(enc_items), 2)

        due_items, due_total = query_vocabulary(
            progress, status_filter="due", today="2026-11-27", all_vocab=all_vocab
        )
        self.assertEqual(due_total, 1)
        self.assertEqual(due_items[0]["id"], "noun_0001")

        num_items, num_total = query_vocabulary(
            progress, pos_filter="number", search="baro", all_vocab=all_vocab
        )
        self.assertEqual(num_total, 1)
        self.assertEqual(num_items[0]["bengali"], "বারো")

        loan_items, loan_total = query_vocabulary(
            progress, loanword_filter="loanword", limit=10, all_vocab=all_vocab
        )
        self.assertGreater(loan_total, 0)
        self.assertTrue(all(it["is_loanword"] for it in loan_items))

        sorted_srs, _ = query_vocabulary(
            progress, sort_by="srs_level", limit=5, all_vocab=all_vocab
        )
        self.assertEqual([it["id"] for it in sorted_srs[:2]], ["verb_0001", "noun_0001"])

        summary = compute_progress_summary(progress, len(all_vocab), 5, today="2026-11-27")
        self.assertEqual(summary["learned_vocab"], 2)
        self.assertEqual(summary["due_vocab"], 1)

    def test_module_imports(self):
        import gui_practice
        import practice
        import reset_progress
        import summary

        self.assertTrue(callable(gui_practice.main))
        self.assertTrue(callable(practice.main))
        self.assertTrue(callable(summary.generate_summary))
        self.assertTrue(callable(reset_progress.reset_progress))

        bubble = gui_practice.MessageBubble(
            "<audio>আমি বাড়ি যাচ্ছি।</audio> (ami bari jacchi.)",
            is_user=False,
            audio_segments=["আমি বাড়ি যাচ্ছি।"],
        )
        self.assertEqual(bubble.text_display.value, "আমি বাড়ি যাচ্ছি। (ami bari jacchi.)")
        self.assertTrue(bubble.play_button.visible)
        badge = gui_practice._make_badge("L1", gui_practice.SRS_LEVEL_COLORS[1])
        self.assertIsNotNone(badge)

    def test_gui_views_layout_constraints(self):
        import flet as ft
        import gui_practice

        class DummyPage:
            title = ""
            theme_mode = None
            padding = 0
            scroll = None
            controls = []

            class window:
                width = 0
                height = 0

            def add(self, *args):
                self.controls.extend(args)

            def update(self):
                pass

            def show_dialog(self, dialog):
                pass

            def run_task(self, *args, **kwargs):
                pass

        def walk_controls(controls):
            ordered_texts = []
            buttons = {}

            def visit(ctrl, parent):
                if isinstance(ctrl, ft.Control) is False:
                    return

                # 1. Validate expand=True parent rules
                if getattr(ctrl, "expand", False) and parent is not None:
                    self.assertNotIsInstance(
                        parent,
                        (ft.Container, ft.Card, ft.ListView),
                        f"expand=True control {type(ctrl).__name__} placed directly inside {type(parent).__name__}",
                    )
                    if isinstance(parent, (ft.Row, ft.Column)):
                        self.assertFalse(
                            getattr(parent, "wrap", False),
                            f"expand=True control {type(ctrl).__name__} placed inside wrapped {type(parent).__name__}",
                        )

                # 2. Validate Row does not use STRETCH without finite height
                if isinstance(ctrl, ft.Row):
                    if ctrl.vertical_alignment == ft.CrossAxisAlignment.STRETCH:
                        self.assertIsNotNone(
                            ctrl.height,
                            "Row with CrossAxisAlignment.STRETCH must have finite height",
                        )

                # 3. Validate every Column in the tree uses tight=True
                if isinstance(ctrl, ft.Column):
                    self.assertTrue(
                        ctrl.tight,
                        f"Column {ctrl} must set tight=True inside layout tree",
                    )

                if isinstance(ctrl, ft.Text) and isinstance(ctrl.value, str):
                    ordered_texts.append(ctrl.value)

                if isinstance(ctrl, (ft.FilledButton, ft.OutlinedButton, ft.TextButton)):
                    label = ctrl.content if isinstance(ctrl.content, str) else getattr(ctrl.content, "value", "")
                    if label:
                        buttons[label] = ctrl
                        ordered_texts.append(label)

                if hasattr(ctrl, "controls") and isinstance(ctrl.controls, list):
                    for child in ctrl.controls:
                        visit(child, ctrl)
                if hasattr(ctrl, "content") and isinstance(ctrl.content, ft.Control):
                    visit(ctrl.content, ctrl)

            for top in controls:
                visit(top, None)
            return ordered_texts, buttons

        page = DummyPage()
        gui_practice.main(page)

        # Dashboard view assertions
        dash_texts, dash_buttons = walk_controls(page.controls)
        for expected_btn in (
            "Start Learning Session",
            "Start Review Session",
            "Start Conversation",
            "Open Vocabulary List",
            "Custom Session",
        ):
            self.assertIn(expected_btn, dash_buttons)

        self.assertLess(
            dash_texts.index("Start Learning Session"),
            dash_texts.index("Progress Summary"),
            "Learning Session card should appear before Progress Summary",
        )

        # Navigate to Vocabulary Browser and validate layout
        dash_buttons["Open Vocabulary List"].on_click(None)
        _, browser_buttons = walk_controls(page.controls)
        self.assertIn("Back to Dashboard", browser_buttons)

        # Navigate back to Dashboard, then to Custom Session Picker and validate layout
        browser_buttons["Back to Dashboard"].on_click(None)
        _, dash_buttons_2 = walk_controls(page.controls)
        dash_buttons_2["Custom Session"].on_click(None)
        _, picker_buttons = walk_controls(page.controls)
        self.assertIn("Back to Dashboard", picker_buttons)
        self.assertIn("Start Custom Session", picker_buttons)

        # Return to Dashboard cleanly
        picker_buttons["Back to Dashboard"].on_click(None)
        _, dash_buttons_3 = walk_controls(page.controls)
        self.assertIn("Start Learning Session", dash_buttons_3)


if __name__ == "__main__":
    unittest.main()
