import os
import threading
import time
import flet as ft
from google import genai

from curriculum_manager import (
    POS_FILES,
    POS_LABELS,
    load_grammar,
    load_vocabulary,
    query_vocabulary,
)
from progress_manager import (
    SRS_INTERVAL_DAYS,
    SRS_LEVEL_LABELS,
    compute_progress_summary,
    ensure_progress_file,
)
from session_builder import (
    SessionPlan,
    build_kickoff_message,
    build_session_system_instructions,
    create_conversation_session,
    create_custom_session,
    create_learn_session,
    create_review_session,
    make_session_score_tool,
)
from tutor_core import (
    AVAILABLE_MODELS,
    PRIMARY_MODEL,
    build_generate_config,
    extract_audio_segments,
    play_audio_segment,
    play_audio_segments,
    prefetch_audio_segments,
    strip_audio_tags,
)

SRS_LEVEL_COLORS = {
    0: ft.Colors.GREY_600,
    1: ft.Colors.ORANGE_400,
    2: ft.Colors.AMBER_400,
    3: ft.Colors.LIGHT_BLUE_400,
    4: ft.Colors.CYAN_400,
    5: ft.Colors.GREEN_400,
}


class MessageBubble(ft.Column):
    def __init__(self, text: str, is_user: bool, audio_segments: list[str] | None = None):
        super().__init__(tight=True)
        self.text = text
        self.is_user = is_user
        self.audio_segments = audio_segments or []

        self.text_display = ft.Text(
            "",
            color=ft.Colors.WHITE,
            selectable=True,
            width=660,
            no_wrap=False,
        )
        self.play_button = ft.IconButton(
            icon=ft.Icons.VOLUME_UP_ROUNDED,
            icon_color=ft.Colors.BLUE_300,
            icon_size=22,
            on_click=self.on_play_click,
            visible=bool(self.audio_segments),
            tooltip="Play Bengali pronunciation",
        )

        alignment = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START
        bg_color = ft.Colors.BLUE_700 if is_user else ft.Colors.GREY_800

        self.container = ft.Container(
            content=self.text_display,
            bgcolor=bg_color,
            padding=12,
            border_radius=ft.BorderRadius.all(12),
        )

        row_controls = (
            [self.container, self.play_button]
            if not is_user
            else [self.play_button, self.container]
        )

        self.controls = [
            ft.Row(
                controls=row_controls,
                alignment=alignment,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5,
            )
        ]
        self._update_content()

    def _update_content(self):
        self.text_display.value = strip_audio_tags(self.text)
        self.play_button.visible = bool(self.audio_segments)

    def update_message(self, text: str, audio_segments: list[str] | None = None):
        self.text = text
        self.audio_segments = audio_segments or []
        self._update_content()
        self.update()

    def on_play_click(self, e):
        if self.audio_segments:
            threading.Thread(
                target=play_audio_segments,
                args=(list(self.audio_segments),),
                daemon=True,
            ).start()


def _parse_int(value: str | None, default: int, minimum: int = 0, maximum: int = 50) -> int:
    try:
        parsed = int((value or "").strip())
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def _make_badge(text: str, bgcolor: str, text_color: str = ft.Colors.BLACK) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, weight=ft.FontWeight.BOLD, color=text_color),
        bgcolor=bgcolor,
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        border_radius=ft.BorderRadius.all(6),
    )


def main(page: ft.Page):
    page.title = "Bangla Bot - Kolkata Dialect Tutor"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 18
    page.scroll = None
    page.window.width = 980
    page.window.height = 860

    try:
        _, _, all_vocab = load_vocabulary()
        grammar_list, _ = load_grammar()
    except Exception as ex:
        page.add(
            ft.Text(
                f"Failed to load curriculum files: {ex}",
                color=ft.Colors.RED_400,
                size=15,
            )
        )
        page.update()
        return

    current_model_name = [PRIMARY_MODEL]
    autoplay_enabled = [True]

    def show_toast(message: str):
        try:
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(message),
                    duration=2500,
                )
            )
        except Exception:
            pass

    def set_view(*controls: ft.Control):
        page.controls = list(controls)
        page.update()

    def get_client() -> genai.Client | None:
        api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
        if not api_key:
            show_toast("GOOGLE_API_KEY is not set. Enter your key on the dashboard or set the env var.")
            return None
        try:
            return genai.Client(api_key=api_key)
        except Exception as ex:
            show_toast(f"Failed to initialize Gemini client: {ex}")
            return None

    # =====================================================================
    # View 1: Main Dashboard
    # =====================================================================
    def show_dashboard():
        progress = ensure_progress_file()
        summary = compute_progress_summary(progress, len(all_vocab), len(grammar_list))
        learned_total = summary["learned_vocab"] + summary["learned_grammar"]

        api_key_set = bool(os.environ.get("GOOGLE_API_KEY", "").strip())
        api_key_field = ft.TextField(
            label="GOOGLE_API_KEY",
            password=True,
            can_reveal_password=True,
            width=320,
            dense=True,
        )

        def save_api_key(e):
            val = (api_key_field.value or "").strip()
            if val:
                os.environ["GOOGLE_API_KEY"] = val
                show_toast("GOOGLE_API_KEY set for this session.")
                show_dashboard()

        api_banner = ft.Container(
            bgcolor=ft.Colors.ORANGE_900,
            padding=12,
            border_radius=ft.BorderRadius.all(10),
            content=ft.Row(
                [
                    ft.Text(
                        "GOOGLE_API_KEY is missing. Enter it to launch AI sessions:",
                        color=ft.Colors.WHITE,
                    ),
                    api_key_field,
                    ft.FilledButton("Set Key", on_click=save_api_key),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        def on_global_model_change(e):
            if model_dropdown.value:
                current_model_name[0] = model_dropdown.value
                show_toast(f"Default model set to {current_model_name[0]}")

        def on_autoplay_change(e):
            autoplay_enabled[0] = bool(autoplay_switch.value)

        model_dropdown = ft.Dropdown(
            value=current_model_name[0],
            options=[ft.dropdown.Option(key=m, text=m) for m in AVAILABLE_MODELS],
            width=190,
            text_size=13,
            content_padding=8,
            on_select=on_global_model_change,
            tooltip="Select Gemini Flash model",
        )
        autoplay_switch = ft.Switch(
            label="Auto-play audio",
            value=autoplay_enabled[0],
            on_change=on_autoplay_change,
        )

        def metric_tile(label: str, value: str, color: str) -> ft.Container:
            return ft.Container(
                expand=True,
                bgcolor=ft.Colors.GREY_900,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                border_radius=ft.BorderRadius.all(10),
                padding=12,
                content=ft.Column(
                    [
                        ft.Text(label, size=12, color=ft.Colors.GREY_400),
                        ft.Text(value, size=20, weight=ft.FontWeight.BOLD, color=color),
                    ],
                    spacing=4,
                    tight=True,
                ),
            )

        srs_rows: list[ft.Control] = []
        max_bar_denom = max(1, summary["learned_vocab"])
        for lvl in range(1, 6):
            cnt = summary["vocab_by_level"][lvl]
            interval = SRS_INTERVAL_DAYS[lvl]
            ratio = cnt / max_bar_denom if summary["learned_vocab"] > 0 else 0.0
            srs_rows.append(
                ft.Row(
                    [
                        ft.Text(
                            f"{SRS_LEVEL_LABELS[lvl]} ({interval}d)",
                            width=210,
                            size=12,
                            color=ft.Colors.GREY_200,
                        ),
                        ft.ProgressBar(
                            value=ratio,
                            bar_height=8,
                            color=SRS_LEVEL_COLORS[lvl],
                            bgcolor=ft.Colors.GREY_800,
                            expand=True,
                        ),
                        ft.Text(
                            f"{cnt:,}",
                            width=55,
                            text_align=ft.TextAlign.RIGHT,
                            size=12,
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10,
                )
            )

        progress_card = ft.Container(
            bgcolor=ft.Colors.GREY_900,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=ft.BorderRadius.all(12),
            padding=16,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Progress Summary", size=17, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                f"Unseen words remaining: {summary['unseen_vocab']:,} | Grammar due: {summary['due_grammar']}",
                                size=12,
                                color=ft.Colors.GREY_400,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            metric_tile(
                                "Vocabulary Learned",
                                f"{summary['learned_vocab']:,} / {summary['total_vocab']:,}",
                                ft.Colors.BLUE_300,
                            ),
                            metric_tile(
                                "Vocab Due Today",
                                f"{summary['due_vocab']:,}",
                                ft.Colors.AMBER_300 if summary["due_vocab"] > 0 else ft.Colors.GREEN_400,
                            ),
                            metric_tile(
                                "Grammar Learned",
                                f"{summary['learned_grammar']} / {summary['total_grammar']}",
                                ft.Colors.PURPLE_300,
                            ),
                            metric_tile(
                                "Sessions Completed",
                                f"{summary['sessions_completed']}",
                                ft.Colors.TEAL_300,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(height=8, color=ft.Colors.GREY_800),
                    ft.Text("5-Level SRS Vocabulary Distribution", size=13, weight=ft.FontWeight.W_600),
                    *srs_rows,
                ],
                spacing=10,
                tight=True,
            ),
        )

        # Session configuration inputs
        learn_new_tf = ft.TextField(label="New Words", value="5", width=95, dense=True)
        learn_rev_tf = ft.TextField(label="Review Words", value="5", width=105, dense=True)
        learn_gram_tf = ft.TextField(label="Grammar", value="2", width=85, dense=True)

        review_words_tf = ft.TextField(label="Review Words", value="10", width=110, dense=True)
        review_gram_tf = ft.TextField(label="Grammar", value="2", width=90, dense=True)

        conv_words_tf = ft.TextField(label="Target Words", value="10", width=110, dense=True)
        conv_gram_tf = ft.TextField(label="Grammar", value="2", width=90, dense=True)

        def launch_learn(e):
            if not get_client():
                return
            try:
                plan = create_learn_session(
                    new_word_count=_parse_int(learn_new_tf.value, 5, 0, 25),
                    review_word_count=_parse_int(learn_rev_tf.value, 5, 0, 30),
                    grammar_count=_parse_int(learn_gram_tf.value, 2, 0, 5),
                )
                start_chat_session(plan)
            except Exception as ex:
                show_toast(str(ex))

        def launch_review(e):
            if not get_client():
                return
            try:
                plan = create_review_session(
                    review_word_count=_parse_int(review_words_tf.value, 10, 1, 30),
                    grammar_count=_parse_int(review_gram_tf.value, 2, 0, 5),
                )
                start_chat_session(plan)
            except Exception as ex:
                show_toast(str(ex))

        def launch_conversation(e):
            if not get_client():
                return
            try:
                plan = create_conversation_session(
                    review_word_count=_parse_int(conv_words_tf.value, 10, 1, 30),
                    grammar_count=_parse_int(conv_gram_tf.value, 2, 0, 5),
                )
                start_chat_session(plan)
            except Exception as ex:
                show_toast(str(ex))

        def mode_card(
            title: str,
            subtitle: str,
            body_controls: list[ft.Control],
            highlight: bool = False,
            badge_text: str | None = None,
        ) -> ft.Container:
            header_items: list[ft.Control] = [
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD)
            ]
            if badge_text:
                header_items.append(
                    _make_badge(badge_text, ft.Colors.BLUE_600, ft.Colors.WHITE)
                )
            return ft.Container(
                expand=True,
                bgcolor=ft.Colors.GREY_900,
                border=(
                    ft.Border.all(2, ft.Colors.BLUE_500)
                    if highlight
                    else ft.Border.all(1, ft.Colors.GREY_800)
                ),
                border_radius=ft.BorderRadius.all(12),
                padding=14,
                content=ft.Column(
                    [
                        ft.Row(
                            header_items,
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(subtitle, size=12, color=ft.Colors.GREY_400),
                        *body_controls,
                    ],
                    spacing=10,
                    tight=True,
                ),
            )

        learn_card = mode_card(
            "Learning Session",
            "Introduces new POS-balanced words & grammar, drills them alongside review items, and ends with a Bangla conversation.",
            [
                ft.Row([learn_new_tf, learn_rev_tf, learn_gram_tf], spacing=8),
                ft.FilledButton(
                    "Start Learning Session",
                    icon=ft.Icons.SCHOOL_ROUNDED,
                    on_click=launch_learn,
                ),
            ],
            highlight=True,
            badge_text="Start Here",
        )

        review_note = (
            "Complete at least 1 Learning session to unlock Review mode."
            if learned_total == 0
            else "Drills due and weakest learned items via translation questions and conversation."
        )
        review_card = mode_card(
            "Review Session",
            review_note,
            [
                ft.Row([review_words_tf, review_gram_tf], spacing=8),
                ft.FilledButton(
                    "Start Review Session",
                    icon=ft.Icons.REFRESH_ROUNDED,
                    disabled=(learned_total == 0),
                    on_click=launch_review,
                ),
            ],
        )

        conv_note = (
            "Complete at least 1 Learning session to unlock Conversation mode."
            if learned_total == 0
            else "Jumps straight into a Bangla practice dialogue covering due & weakest learned items."
        )
        conv_card = mode_card(
            "Conversation Session",
            conv_note,
            [
                ft.Row([conv_words_tf, conv_gram_tf], spacing=8),
                ft.FilledButton(
                    "Start Conversation",
                    icon=ft.Icons.FORUM_ROUNDED,
                    disabled=(learned_total == 0),
                    on_click=launch_conversation,
                ),
            ],
        )

        tools_card = mode_card(
            "Vocabulary & Custom Practice",
            "Browse all 5,039 Kolkata words with SRS dates & filters, or hand-pick specific words and grammar for a custom session.",
            [
                ft.Row(
                    [
                        ft.OutlinedButton(
                            "Open Vocabulary List",
                            icon=ft.Icons.MENU_BOOK_ROUNDED,
                            on_click=lambda _: show_vocab_browser(),
                        ),
                        ft.OutlinedButton(
                            "Custom Session",
                            icon=ft.Icons.TUNE_ROUNDED,
                            on_click=lambda _: show_custom_picker(),
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
        )

        header_row = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("Bangla Bot", size=26, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Kolkata dialect (Cholitobhasha) SRS tutor",
                            size=13,
                            color=ft.Colors.GREY_300,
                        ),
                    ],
                    spacing=2,
                    tight=True,
                    expand=True,
                ),
                autoplay_switch,
                model_dropdown,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )

        body_controls: list[ft.Control] = []
        if not api_key_set:
            body_controls.append(api_banner)
        body_controls.extend(
            [
                ft.Text("Start a Lesson or Practice Session", size=16, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [learn_card, review_card],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Row(
                    [conv_card, tools_card],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                progress_card,
            ]
        )

        dashboard_body = ft.ListView(
            controls=body_controls,
            expand=True,
            spacing=12,
            padding=ft.Padding.only(top=4, bottom=12),
        )
        set_view(header_row, dashboard_body)

    # =====================================================================
    # View 2: Vocabulary Browser
    # =====================================================================
    def show_vocab_browser():
        progress = ensure_progress_file()
        state = {
            "search": "",
            "pos": "all",
            "status": "all",
            "loanword": "all",
            "sort": "frequency",
            "page": 0,
            "page_size": 50,
            "total": 0,
        }

        match_label = ft.Text("", size=13, color=ft.Colors.GREY_300)
        page_label = ft.Text("Page 1", size=13)
        list_view = ft.ListView(expand=True, spacing=6)

        def build_vocab_row(item: dict) -> ft.Container:
            lvl = item["srs_level"]
            bengali_txt = item["bengali"]
            if item.get("pos") == "number" and item.get("bengali_numeral"):
                bengali_display = f"{bengali_txt} ({item['bengali_numeral']})"
            else:
                bengali_display = bengali_txt

            badges: list[ft.Control] = [
                _make_badge(
                    POS_LABELS.get(item.get("pos", ""), item.get("pos", "")),
                    ft.Colors.BLUE_GREY_800,
                    ft.Colors.BLUE_200,
                )
            ]
            if item.get("is_loanword"):
                badges.append(_make_badge("Loanword", ft.Colors.INDIGO_800, ft.Colors.INDIGO_100))

            srs_text = "Unseen" if lvl == 0 else f"L{lvl}"
            srs_badge = _make_badge(
                srs_text,
                SRS_LEVEL_COLORS[lvl],
                ft.Colors.BLACK if lvl > 0 else ft.Colors.WHITE,
            )
            srs_controls: list[ft.Control] = [srs_badge]
            if item.get("is_due"):
                srs_controls.append(_make_badge("DUE", ft.Colors.RED_400, ft.Colors.BLACK))

            def on_play(e, word_bn=bengali_txt):
                threading.Thread(target=play_audio_segment, args=(word_bn,), daemon=True).start()

            return ft.Container(
                bgcolor=ft.Colors.GREY_900,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                border_radius=ft.BorderRadius.all(8),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                content=ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.VOLUME_UP_ROUNDED,
                            icon_color=ft.Colors.BLUE_300,
                            icon_size=20,
                            tooltip="Pronounce word",
                            on_click=on_play,
                        ),
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(bengali_display, size=15, weight=ft.FontWeight.BOLD),
                                        ft.Text(
                                            f"({item['transliteration']})",
                                            size=13,
                                            color=ft.Colors.BLUE_200,
                                        ),
                                        ft.Text(
                                            f"[{item['id']}]",
                                            size=11,
                                            color=ft.Colors.GREY_500,
                                        ),
                                    ],
                                    spacing=6,
                                    wrap=True,
                                ),
                                ft.Text(item["english"], size=13, color=ft.Colors.GREY_300),
                            ],
                            spacing=2,
                            tight=True,
                            expand=True,
                        ),
                        ft.Row(badges, spacing=4, width=155),
                        ft.Row(srs_controls, spacing=4, width=105),
                        ft.Column(
                            [
                                ft.Text(
                                    f"First: {item['first_encountered'] or '—'}",
                                    size=11,
                                    color=ft.Colors.GREY_300,
                                ),
                                ft.Text(
                                    f"Recent: {item['last_practiced'] or '—'}",
                                    size=11,
                                    color=ft.Colors.GREY_400,
                                ),
                            ],
                            spacing=2,
                            tight=True,
                            width=135,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
            )

        def refresh_list(reset_page: bool = False):
            if reset_page:
                state["page"] = 0
            offset = state["page"] * state["page_size"]
            items, total = query_vocabulary(
                progress=progress,
                search=state["search"],
                pos_filter=state["pos"],
                status_filter=state["status"],
                loanword_filter=state["loanword"],
                sort_by=state["sort"],
                offset=offset,
                limit=state["page_size"],
                all_vocab=all_vocab,
            )
            state["total"] = total
            total_pages = max(1, (total + state["page_size"] - 1) // state["page_size"])
            if state["page"] >= total_pages:
                state["page"] = max(0, total_pages - 1)
                items, total = query_vocabulary(
                    progress=progress,
                    search=state["search"],
                    pos_filter=state["pos"],
                    status_filter=state["status"],
                    loanword_filter=state["loanword"],
                    sort_by=state["sort"],
                    offset=state["page"] * state["page_size"],
                    limit=state["page_size"],
                    all_vocab=all_vocab,
                )

            match_label.value = f"{total:,} matching word(s)"
            page_label.value = f"Page {state['page'] + 1} of {total_pages}"
            prev_btn.disabled = state["page"] <= 0
            next_btn.disabled = (state["page"] + 1) >= total_pages

            if items:
                list_view.controls = [build_vocab_row(it) for it in items]
            else:
                list_view.controls = [
                    ft.Container(
                        padding=24,
                        content=ft.Text(
                            "No words match the active filters.",
                            color=ft.Colors.GREY_400,
                        ),
                    )
                ]
            page.update()

        def on_search_change(e):
            state["search"] = search_tf.value or ""
            refresh_list(reset_page=True)

        def on_pos_change(e):
            state["pos"] = pos_dd.value or "all"
            refresh_list(reset_page=True)

        def on_status_change(e):
            state["status"] = status_dd.value or "all"
            refresh_list(reset_page=True)

        def on_loan_change(e):
            state["loanword"] = loan_dd.value or "all"
            refresh_list(reset_page=True)

        def on_sort_change(e):
            state["sort"] = sort_dd.value or "frequency"
            refresh_list(reset_page=True)

        def on_prev(e):
            if state["page"] > 0:
                state["page"] -= 1
                refresh_list(reset_page=False)

        def on_next(e):
            total_pages = max(1, (state["total"] + state["page_size"] - 1) // state["page_size"])
            if state["page"] + 1 < total_pages:
                state["page"] += 1
                refresh_list(reset_page=False)

        search_tf = ft.TextField(
            hint_text="Search Bengali, transliteration, English, ID...",
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            width=260,
            dense=True,
            on_change=on_search_change,
            on_submit=on_search_change,
        )
        pos_dd = ft.Dropdown(
            label="POS",
            value="all",
            width=145,
            content_padding=8,
            options=[ft.dropdown.Option(key="all", text="All POS")]
            + [ft.dropdown.Option(key=p, text=POS_LABELS.get(p, p)) for p, _ in POS_FILES],
            on_select=on_pos_change,
        )
        status_dd = ft.Dropdown(
            label="SRS Category",
            value="all",
            width=170,
            content_padding=8,
            options=[
                ft.dropdown.Option(key="all", text="All Statuses"),
                ft.dropdown.Option(key="encountered", text="Encountered Only"),
                ft.dropdown.Option(key="unseen", text="Unseen Only"),
                ft.dropdown.Option(key="due", text="Due for Review"),
                ft.dropdown.Option(key="level_1", text="Level 1 (Learning)"),
                ft.dropdown.Option(key="level_2", text="Level 2 (Familiar)"),
                ft.dropdown.Option(key="level_3", text="Level 3 (Intermediate)"),
                ft.dropdown.Option(key="level_4", text="Level 4 (Strong)"),
                ft.dropdown.Option(key="level_5", text="Level 5 (Mastered)"),
            ],
            on_select=on_status_change,
        )
        loan_dd = ft.Dropdown(
            label="Origin",
            value="all",
            width=150,
            content_padding=8,
            options=[
                ft.dropdown.Option(key="all", text="All Origins"),
                ft.dropdown.Option(key="native", text="Native Bengali"),
                ft.dropdown.Option(key="loanword", text="English Loanwords"),
            ],
            on_select=on_loan_change,
        )
        sort_dd = ft.Dropdown(
            label="Sort By",
            value="frequency",
            width=165,
            content_padding=8,
            options=[
                ft.dropdown.Option(key="frequency", text="Frequency (High)"),
                ft.dropdown.Option(key="srs_level", text="SRS Level"),
                ft.dropdown.Option(key="first_encountered", text="First Encountered"),
                ft.dropdown.Option(key="last_practiced", text="Most Recent"),
            ],
            on_select=on_sort_change,
        )

        prev_btn = ft.OutlinedButton(
            "Prev",
            icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
            on_click=on_prev,
        )
        next_btn = ft.OutlinedButton(
            "Next",
            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
            on_click=on_next,
        )

        header_row = ft.Row(
            [
                ft.TextButton(
                    "Back to Dashboard",
                    icon=ft.Icons.ARROW_BACK_ROUNDED,
                    on_click=lambda _: show_dashboard(),
                ),
                ft.Text("Vocabulary Browser", size=20, weight=ft.FontWeight.BOLD),
                match_label,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        filter_row = ft.Row(
            [search_tf, pos_dd, status_dd, loan_dd, sort_dd],
            spacing=8,
            wrap=True,
        )
        pagination_row = ft.Row(
            [prev_btn, page_label, next_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
        )
        set_view(header_row, filter_row, list_view, pagination_row)
        refresh_list(reset_page=True)

    # =====================================================================
    # View 3: Custom Session Picker
    # =====================================================================
    def show_custom_picker():
        progress = ensure_progress_file()
        vocab_by_id = {w["id"]: w for w in all_vocab}
        selected_vocab_ids: list[str] = []
        selected_vocab_set: set[str] = set()
        selected_grammar_ids: set[str] = set()

        state = {
            "search": "",
            "pos": "all",
            "status": "all",
            "page": 0,
            "page_size": 50,
            "total": 0,
        }

        selected_chips_row = ft.Row(wrap=True, spacing=6)
        selection_count_text = ft.Text("Selected: 0 words, 0 grammar", size=13, color=ft.Colors.BLUE_200)
        page_label = ft.Text("Page 1", size=13)
        word_list_view = ft.ListView(expand=True, spacing=4)

        def refresh_selected_chips():
            chips: list[ft.Control] = []
            for vid in selected_vocab_ids[:18]:
                w = vocab_by_id.get(vid)
                if not w:
                    continue

                def on_remove(e, target_id=vid):
                    if target_id in selected_vocab_set:
                        selected_vocab_set.remove(target_id)
                        selected_vocab_ids.remove(target_id)
                        refresh_selected_chips()
                        refresh_picker_list(reset_page=False)

                chips.append(
                    ft.Chip(
                        label=ft.Text(f"{w['bengali']} ({w['transliteration']})", size=12),
                        on_delete=on_remove,
                    )
                )
            if len(selected_vocab_ids) > 18:
                chips.append(
                    ft.Text(
                        f"+{len(selected_vocab_ids) - 18} more selected",
                        size=12,
                        color=ft.Colors.GREY_400,
                    )
                )
            selected_chips_row.controls = chips
            selection_count_text.value = (
                f"Selected: {len(selected_vocab_ids)} word(s), {len(selected_grammar_ids)} grammar"
            )
            start_custom_btn.disabled = (len(selected_vocab_ids) + len(selected_grammar_ids)) == 0

        def build_picker_row(item: dict) -> ft.Container:
            vid = item["id"]
            lvl = item["srs_level"]

            def on_toggle(e, target_id=vid):
                if e.control.value:
                    if target_id not in selected_vocab_set:
                        selected_vocab_set.add(target_id)
                        selected_vocab_ids.append(target_id)
                else:
                    if target_id in selected_vocab_set:
                        selected_vocab_set.remove(target_id)
                        selected_vocab_ids.remove(target_id)
                refresh_selected_chips()
                page.update()

            srs_tag = "New" if lvl == 0 else f"L{lvl}"
            return ft.Container(
                bgcolor=ft.Colors.GREY_900,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                border_radius=ft.BorderRadius.all(8),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                content=ft.Row(
                    [
                        ft.Checkbox(
                            value=(vid in selected_vocab_set),
                            on_change=on_toggle,
                        ),
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(item["bengali"], size=15, weight=ft.FontWeight.BOLD),
                                        ft.Text(f"({item['transliteration']})", size=13, color=ft.Colors.BLUE_200),
                                        ft.Text(f"— {item['english']}", size=13, color=ft.Colors.GREY_300),
                                    ],
                                    spacing=6,
                                    wrap=True,
                                ),
                            ],
                            tight=True,
                            expand=True,
                        ),
                        _make_badge(
                            POS_LABELS.get(item.get("pos", ""), item.get("pos", "")),
                            ft.Colors.BLUE_GREY_800,
                            ft.Colors.BLUE_200,
                        ),
                        _make_badge(
                            srs_tag,
                            SRS_LEVEL_COLORS[lvl],
                            ft.Colors.BLACK if lvl > 0 else ft.Colors.WHITE,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
            )

        def refresh_picker_list(reset_page: bool = False):
            if reset_page:
                state["page"] = 0
            items, total = query_vocabulary(
                progress=progress,
                search=state["search"],
                pos_filter=state["pos"],
                status_filter=state["status"],
                offset=state["page"] * state["page_size"],
                limit=state["page_size"],
                all_vocab=all_vocab,
            )
            state["total"] = total
            total_pages = max(1, (total + state["page_size"] - 1) // state["page_size"])
            page_label.value = f"Page {state['page'] + 1} of {total_pages} ({total:,} words)"
            prev_btn.disabled = state["page"] <= 0
            next_btn.disabled = (state["page"] + 1) >= total_pages
            word_list_view.controls = [build_picker_row(it) for it in items]
            page.update()

        grammar_checkboxes: list[ft.Control] = []
        grammar_records = progress.get("grammar", {})
        for g in grammar_list:
            gid = g["id"]
            rec = grammar_records.get(gid)
            g_tag = "New" if rec is None else f"L{rec.get('srs_level', 1)}"

            def on_gram_toggle(e, target_gid=gid):
                if e.control.value:
                    selected_grammar_ids.add(target_gid)
                else:
                    selected_grammar_ids.discard(target_gid)
                refresh_selected_chips()
                page.update()

            grammar_checkboxes.append(
                ft.Checkbox(
                    label=f"{g['concept']} [{g_tag}]",
                    value=False,
                    on_change=on_gram_toggle,
                )
            )

        submode_dd = ft.Dropdown(
            label="Session Style",
            value="full",
            width=310,
            content_padding=8,
            options=[
                ft.dropdown.Option(key="full", text="Full (Intro unseen + Translations + Conversation)"),
                ft.dropdown.Option(key="conversation_only", text="Conversation Only"),
            ],
        )

        def clear_selection(e):
            selected_vocab_ids.clear()
            selected_vocab_set.clear()
            selected_grammar_ids.clear()
            for cb in grammar_checkboxes:
                cb.value = False
            refresh_selected_chips()
            refresh_picker_list(reset_page=False)

        def on_start_custom(e):
            if not get_client():
                return
            try:
                plan = create_custom_session(
                    vocab_ids=list(selected_vocab_ids),
                    grammar_ids=sorted(selected_grammar_ids),
                    submode=submode_dd.value or "full",
                )
                start_chat_session(plan)
            except Exception as ex:
                show_toast(str(ex))

        search_tf = ft.TextField(
            hint_text="Search words to add...",
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            width=260,
            dense=True,
            on_change=lambda e: (state.update({"search": search_tf.value or ""}), refresh_picker_list(True)),
        )
        pos_dd = ft.Dropdown(
            label="POS",
            value="all",
            width=150,
            content_padding=8,
            options=[ft.dropdown.Option(key="all", text="All POS")]
            + [ft.dropdown.Option(key=p, text=POS_LABELS.get(p, p)) for p, _ in POS_FILES],
            on_select=lambda e: (state.update({"pos": pos_dd.value or "all"}), refresh_picker_list(True)),
        )
        status_dd = ft.Dropdown(
            label="SRS Status",
            value="all",
            width=165,
            content_padding=8,
            options=[
                ft.dropdown.Option(key="all", text="All Statuses"),
                ft.dropdown.Option(key="unseen", text="New / Unseen"),
                ft.dropdown.Option(key="encountered", text="Learned"),
                ft.dropdown.Option(key="due", text="Due Now"),
            ],
            on_select=lambda e: (state.update({"status": status_dd.value or "all"}), refresh_picker_list(True)),
        )

        prev_btn = ft.OutlinedButton(
            "Prev",
            icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
            on_click=lambda e: (state.update({"page": max(0, state["page"] - 1)}), refresh_picker_list(False)),
        )
        next_btn = ft.OutlinedButton(
            "Next",
            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
            on_click=lambda e: (state.update({"page": state["page"] + 1}), refresh_picker_list(False)),
        )

        start_custom_btn = ft.FilledButton(
            "Start Custom Session",
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            disabled=True,
            on_click=on_start_custom,
        )

        header_row = ft.Row(
            [
                ft.TextButton(
                    "Back to Dashboard",
                    icon=ft.Icons.ARROW_BACK_ROUNDED,
                    on_click=lambda _: show_dashboard(),
                ),
                ft.Text("Custom Session Picker", size=20, weight=ft.FontWeight.BOLD),
                ft.Row([submode_dd, start_custom_btn], spacing=10),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        selection_box = ft.Container(
            bgcolor=ft.Colors.GREY_900,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=ft.BorderRadius.all(10),
            padding=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            selection_count_text,
                            ft.TextButton(
                                "Clear All",
                                icon=ft.Icons.CLEAR_ROUNDED,
                                on_click=clear_selection,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    selected_chips_row,
                    ft.Divider(height=4, color=ft.Colors.GREY_800),
                    ft.Text("Optional Grammar Concepts:", size=12, color=ft.Colors.GREY_400),
                    ft.Row(grammar_checkboxes, wrap=True, spacing=8),
                ],
                spacing=6,
                tight=True,
            ),
        )
        filter_row = ft.Row([search_tf, pos_dd, status_dd], spacing=8, wrap=True)
        pagination_row = ft.Row(
            [prev_btn, page_label, next_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=16,
        )
        set_view(header_row, selection_box, filter_row, word_list_view, pagination_row)
        refresh_selected_chips()
        refresh_picker_list(reset_page=True)

    # =====================================================================
    # View 4: Active Chat Session
    # =====================================================================
    def start_chat_session(plan: SessionPlan):
        client = get_client()
        if not client:
            return

        system_instructions = build_session_system_instructions(plan)
        session_finished = [False]

        completion_title = ft.Text(
            "Session scored and saved to progress.json!",
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.GREEN_200,
        )
        completion_details = ft.Text("", size=12, color=ft.Colors.GREY_200)
        completion_banner = ft.Container(
            visible=False,
            bgcolor=ft.Colors.GREEN_900,
            border=ft.Border.all(1, ft.Colors.GREEN_500),
            border_radius=ft.BorderRadius.all(10),
            padding=12,
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ft.Colors.GREEN_300),
                    ft.Column([completion_title, completion_details], spacing=2, tight=True, expand=True),
                    ft.FilledButton(
                        "Return to Dashboard",
                        on_click=lambda _: show_dashboard(),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
        )

        def on_scores_saved(result: dict):
            session_finished[0] = True
            updated = result.get("updated", [])
            promoted = sum(1 for u in updated if u["outcome"] == "promote")
            introduced = sum(1 for u in updated if u["was_new"])
            stayed = sum(1 for u in updated if u["outcome"] == "stay")
            demoted = sum(1 for u in updated if u["outcome"] == "demote")
            completion_details.value = (
                f"{len(updated)} items updated — New (Level 1): {introduced}, "
                f"Promoted: {promoted}, Stayed: {stayed}, Demoted: {demoted}."
            )
            completion_banner.visible = True
            finish_btn.disabled = True
            show_toast(f"Session progress saved ({len(updated)} items).")

        score_tool = make_session_score_tool(plan, on_scores_saved=on_scores_saved)

        active_model = [current_model_name[0]]
        chat_session = [
            client.chats.create(
                model=active_model[0],
                config=build_generate_config(
                    active_model[0], system_instructions, tools=[score_tool]
                ),
            )
        ]

        status_label = ft.Text(
            f"Active: {active_model[0]}",
            size=12,
            italic=True,
            color=ft.Colors.GREY_400,
        )

        def switch_model(new_model: str, is_fallback: bool = False):
            if new_model == active_model[0]:
                return
            try:
                history = chat_session[0].get_history()
            except Exception:
                history = None
            active_model[0] = new_model
            current_model_name[0] = new_model
            cfg = build_generate_config(new_model, system_instructions, tools=[score_tool])
            chat_session[0] = (
                client.chats.create(model=new_model, config=cfg, history=history)
                if history is not None
                else client.chats.create(model=new_model, config=cfg)
            )
            model_dropdown.value = new_model
            status_label.value = f"{'Fallback' if is_fallback else 'Active'}: {new_model}"
            status_label.color = ft.Colors.ORANGE_300 if is_fallback else ft.Colors.GREY_400
            page.update()

        model_dropdown = ft.Dropdown(
            value=active_model[0],
            options=[ft.dropdown.Option(key=m, text=m) for m in AVAILABLE_MODELS],
            width=180,
            text_size=13,
            content_padding=8,
            on_select=lambda e: (
                switch_model(model_dropdown.value, is_fallback=False)
                if model_dropdown.value and model_dropdown.value != active_model[0]
                else None
            ),
        )

        autoplay_switch = ft.Switch(
            label="Auto-play",
            value=autoplay_enabled[0],
            on_change=lambda e: autoplay_enabled.__setitem__(0, bool(autoplay_switch.value)),
        )

        chat_history = ft.ListView(
            expand=True,
            spacing=10,
            auto_scroll=True,
        )

        def scroll_to_bottom():
            try:
                page.run_task(chat_history.scroll_to, offset=-1, duration=250)
            except Exception:
                pass

        def send_with_handling(message_text: str, thinking_msg: MessageBubble | None = None):
            tried_models = {active_model[0]}
            while True:
                try:
                    t0 = time.perf_counter()
                    resp = chat_session[0].send_message(message=message_text)
                    dt = time.perf_counter() - t0
                    status_label.value = f"Active: {active_model[0]} ({dt:.1f}s)"
                    status_label.color = ft.Colors.GREY_400
                    return resp
                except Exception as e:
                    error_str = str(e)
                    recoverable = any(
                        code in error_str
                        for code in (
                            "404",
                            "NOT_FOUND",
                            "503",
                            "UNAVAILABLE",
                            "429",
                            "RESOURCE_EXHAUSTED",
                        )
                    )
                    if recoverable:
                        next_model = next(
                            (m for m in AVAILABLE_MODELS if m not in tried_models),
                            None,
                        )
                        if next_model:
                            tried_models.add(next_model)
                            if thinking_msg:
                                thinking_msg.update_message(
                                    f"Switching to fallback model ({next_model})..."
                                )
                            switch_model(next_model, is_fallback=True)
                            continue
                        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                            if thinking_msg:
                                thinking_msg.update_message(
                                    "Rate limit reached. Retrying in 5 seconds..."
                                )
                            time.sleep(5)
                            continue
                    raise e

        def process_response(text: str, thinking_msg: MessageBubble | None = None):
            try:
                response = send_with_handling(text, thinking_msg=thinking_msg)
                resp_text = response.text or ""
                audio_segments = extract_audio_segments(resp_text)

                if audio_segments:
                    prefetch_audio_segments(audio_segments)

                if thinking_msg:
                    thinking_msg.update_message(resp_text, audio_segments)
                else:
                    chat_history.controls.append(
                        MessageBubble(resp_text, is_user=False, audio_segments=audio_segments)
                    )

                user_input.disabled = False
                send_button.disabled = False
                page.update()
                scroll_to_bottom()

                if audio_segments and autoplay_enabled[0]:
                    threading.Thread(
                        target=play_audio_segments,
                        args=(list(audio_segments),),
                        daemon=True,
                    ).start()

            except Exception as ex:
                error_text = f"Error: {str(ex)}"
                if thinking_msg:
                    thinking_msg.update_message(error_text)
                else:
                    chat_history.controls.append(ft.Text(error_text, color=ft.Colors.RED_400))
                user_input.disabled = False
                send_button.disabled = False
                page.update()
                scroll_to_bottom()

        def dispatch_user_message(msg_text: str):
            user_input.disabled = True
            send_button.disabled = True
            chat_history.controls.append(MessageBubble(msg_text, is_user=True))
            thinking_msg = MessageBubble("Thinking...", is_user=False)
            chat_history.controls.append(thinking_msg)
            page.update()
            scroll_to_bottom()
            threading.Thread(
                target=process_response,
                args=(msg_text, thinking_msg),
                daemon=True,
            ).start()

        def send_message(e):
            if not user_input.value or not user_input.value.strip():
                return
            msg_text = user_input.value.strip()
            user_input.value = ""
            dispatch_user_message(msg_text)

        def on_finish_early_click(e):
            if session_finished[0] or user_input.disabled:
                return
            dispatch_user_message(
                "Please conclude the session now: present a concise summary scorecard for every "
                "session item and call `submit_session_scores` with all required item_ids to save my progress."
            )

        finish_btn = ft.OutlinedButton(
            "Finish & Score",
            icon=ft.Icons.FLAG_ROUNDED,
            on_click=on_finish_early_click,
        )

        user_input = ft.TextField(
            hint_text="Type your Bangla or English response here...",
            expand=True,
            on_submit=send_message,
            border_radius=20,
            autofocus=True,
        )
        send_button = ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            on_click=send_message,
            icon_color=ft.Colors.BLUE_400,
            tooltip="Send message",
        )

        top_bar_row = ft.Row(
            [
                ft.TextButton(
                    "Main Menu",
                    icon=ft.Icons.ARROW_BACK_ROUNDED,
                    on_click=lambda _: show_dashboard(),
                ),
                _make_badge(plan.summary_label(), ft.Colors.BLUE_900, ft.Colors.BLUE_100),
                ft.Row([finish_btn, autoplay_switch, model_dropdown], spacing=8),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        status_row = ft.Row([status_label], alignment=ft.MainAxisAlignment.END)
        divider = ft.Divider(height=4, color=ft.Colors.GREY_800)
        input_row = ft.Row(controls=[user_input, send_button])

        thinking_msg = MessageBubble("Starting session...", is_user=False)
        chat_history.controls.append(thinking_msg)
        user_input.disabled = True
        send_button.disabled = True
        set_view(top_bar_row, status_row, completion_banner, divider, chat_history, input_row)

        threading.Thread(
            target=process_response,
            args=(build_kickoff_message(plan), thinking_msg),
            daemon=True,
        ).start()

    show_dashboard()


if __name__ == "__main__":
    ft.run(main)
