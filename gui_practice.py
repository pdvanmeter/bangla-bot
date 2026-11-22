import os
import threading
import time
from google import genai
import flet as ft

from tutor_core import (
    AVAILABLE_MODELS,
    PRIMARY_MODEL,
    build_generate_config,
    extract_audio_segments,
    load_system_instructions,
    play_audio_segments,
    prefetch_audio_segments,
    register_progress_callback,
    strip_audio_tags,
)


class MessageBubble(ft.Column):
    def __init__(self, text: str, is_user: bool, audio_segments: list[str] | None = None):
        super().__init__()
        self.text = text
        self.is_user = is_user
        self.audio_segments = audio_segments or []

        self.text_display = ft.Text(
            "",
            color=ft.Colors.WHITE,
            selectable=True,
            width=460,
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


def main(page: ft.Page):
    page.title = "Bangla Bot - Kolkata Dialect Tutor"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.window.width = 650
    page.window.height = 820

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        page.add(
            ft.Text(
                "Error: GOOGLE_API_KEY not found in environment variables.\n"
                "Please set GOOGLE_API_KEY or run via launch_windows.ps1 / launch.sh.",
                color=ft.Colors.RED_400,
                size=16,
            )
        )
        page.update()
        return

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        page.add(
            ft.Text(
                f"Failed to initialize Gemini Client: {str(e)}",
                color=ft.Colors.RED_400,
            )
        )
        page.update()
        return

    try:
        system_instructions = load_system_instructions()
    except Exception as e:
        page.add(
            ft.Text(
                f"Failed to load curriculum or GEMINI.md: {str(e)}",
                color=ft.Colors.RED_400,
            )
        )
        page.update()
        return

    current_model_name = [PRIMARY_MODEL]
    chat_session = [
        client.chats.create(
            model=current_model_name[0],
            config=build_generate_config(current_model_name[0], system_instructions),
        )
    ]

    def show_toast(message: str):
        try:
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(message),
                    duration=2000,
                )
            )
        except Exception:
            pass

    def on_progress_recorded(category: str, item_key: str, is_correct: bool, score: float):
        status_txt = "Correct!" if is_correct else "Needs practice"
        show_toast(f"Progress updated: {item_key} ({status_txt}, mastery: {score:.2f})")

    register_progress_callback(on_progress_recorded)

    def switch_model(new_model: str, is_fallback: bool = False):
        if new_model == current_model_name[0]:
            return
        try:
            history = chat_session[0].get_history()
        except Exception:
            history = None
        current_model_name[0] = new_model
        cfg = build_generate_config(new_model, system_instructions)
        chat_session[0] = (
            client.chats.create(model=new_model, config=cfg, history=history)
            if history is not None
            else client.chats.create(model=new_model, config=cfg)
        )
        model_dropdown.value = new_model
        status_label.value = f"{'Fallback' if is_fallback else 'Active'}: {new_model}"
        status_label.color = ft.Colors.ORANGE_300 if is_fallback else ft.Colors.GREY_400
        page.update()

    def on_model_dropdown_change(e):
        selected = model_dropdown.value
        if selected and selected != current_model_name[0]:
            switch_model(selected, is_fallback=False)
            show_toast(f"Switched model to {selected}")

    model_dropdown = ft.Dropdown(
        value=current_model_name[0],
        options=[ft. dropdown.Option(m) for m in AVAILABLE_MODELS],
        width=200,
        text_size=13,
        content_padding=8,
        on_select=on_model_dropdown_change,
        tooltip="Select Gemini Flash model",
    )

    autoplay_switch = ft.Switch(
        label="Auto-play audio",
        value=True,
        tooltip="Automatically play Bengali pronunciation when new audio arrives",
    )

    status_label = ft.Text(
        f"Active: {current_model_name[0]}",
        size=12,
        italic=True,
        color=ft.Colors.GREY_400,
    )

    welcome_header = ft.Column(
        [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Bangla Bot", size=28, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "Kolkata dialect (Cholitobhasha) tutor",
                                size=14,
                                color=ft.Colors.GREY_300,
                            ),
                        ],
                        expand=True,
                    ),
                    model_dropdown,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row(
                [autoplay_switch, status_label],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Divider(),
        ],
        spacing=6,
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

    def send_message(e):
        if not user_input.value or not user_input.value.strip():
            return

        msg_text = user_input.value.strip()
        user_input.value = ""
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

    def send_with_handling(message_text: str, thinking_msg: MessageBubble | None = None):
        tried_models = {current_model_name[0]}
        while True:
            try:
                t0 = time.perf_counter()
                resp = chat_session[0].send_message(message=message_text)
                dt = time.perf_counter() - t0
                status_label.value = f"Active: {current_model_name[0]} ({dt:.1f}s)"
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

            # Pre-fetch TTS audio immediately
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

            if audio_segments and autoplay_switch.value:
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

    user_input = ft.TextField(
        hint_text="Type your response here...",
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

    page.add(
        welcome_header,
        ft.Container(
            content=chat_history,
            expand=True,
        ),
        ft.Row(controls=[user_input, send_button]),
    )

    thinking_msg = MessageBubble("Starting session...", is_user=False)
    chat_history.controls.append(thinking_msg)
    page.update()
    threading.Thread(
        target=process_response,
        args=(
            "The user has opened the app. Greet them briefly and ask if they are ready to start practicing.",
            thinking_msg,
        ),
        daemon=True,
    ).start()


if __name__ == "__main__":
    ft.run(main)
