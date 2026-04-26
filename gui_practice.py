import os
import re
import json
import time
import sys
import tempfile
import threading
from google import genai
from google.genai import types, errors
from gtts import gTTS
import flet as ft

# Configure Gemini API
api_key = os.environ.get("GOOGLE_API_KEY")

PROGRESS_FILE = "progress.json"
PRIMARY_MODEL = "gemini-3-flash-preview"
FALLBACK_MODEL = "gemini-2.5-flash"

# Global page reference for tools to trigger UI updates
_page_ref = [None]

def read_progress():
    """Reads the current learner's progress from progress.json."""
    if not os.path.exists(PROGRESS_FILE):
        return {"error": "Progress file not found."}
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def write_progress(data: dict):
    """Updates the progress.json file with new scores or stats."""
    try:
        if isinstance(data, str):
            data = json.loads(data)
            
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"--- [Disk] progress.json updated at {time.strftime('%H:%M:%S')} ---")
        
        # Trigger UI notification if page is available
        if _page_ref[0]:
            page = _page_ref[0]
            page.snack_bar = ft.SnackBar(
                content=ft.Text("Progress saved to database."),
                duration=2000
            )
            page.snack_bar.open = True
            page.update()
            
        return "Progress updated successfully."
    except Exception as e:
        print(f"Error writing progress: {e}")
        return f"Error: {str(e)}"

def get_audio_path(bengali_text):
    """Generates TTS audio and returns the path."""
    try:
        tts = gTTS(text=bengali_text, lang='bn')
        fd, temp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        tts.save(temp_path)
        return temp_path
    except Exception as e:
        print(f"TTS Error: {e}")
        return None

def play_audio_file(path):
    """Plays an audio file based on OS."""
    if not path or not os.path.exists(path):
        return
    
    if os.name == 'nt':
        # Use PowerShell to play audio and wait for it to finish (playState 1 is Stopped/MediaEnded)
        # We use a simplified version that is more likely to work across different PS versions
        path = os.path.abspath(path)
        cmd = f'powershell -c "$m = New-Object -ComObject WMPlayer.OCX; $m.url = \'{path}\'; $m.controls.play(); while($m.playState -ne 1 -and $m.playState -ne 10 -and $m.playState -ne 8){{Start-Sleep -m 100}}"'
        os.system(cmd)
    elif sys.platform == 'darwin':
        os.system(f'afplay {path}')
    else:
        # Using -q for quiet mode
        os.system(f'mpg123 -q {path}')

def strip_audio_tags(text):
    """Removes <audio>...</audio> tags from the text for clean display."""
    if not text: return ""
    return re.sub(r'<audio>.*?</audio>', '', text).strip()

class Message(ft.Column):
    def __init__(self, text, is_user, audio_segments=None):
        super().__init__()
        self.text = text
        self.is_user = is_user
        self.audio_segments = audio_segments or []
        
        # Internal controls for updating
        self.text_display = ft.Text("", color=ft.Colors.WHITE, selectable=True, width=450, no_wrap=False)
        self.play_button = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_FILL_OUTLINED,
            icon_color=ft.Colors.BLUE_400,
            icon_size=20,
            on_click=self.on_message_click,
            visible=bool(self.audio_segments),
            tooltip="Play audio"
        )
        
        # Alignment and colors
        alignment = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START
        bg_color = ft.Colors.BLUE_700 if is_user else ft.Colors.GREY_800
        
        self.container = ft.Container(
            content=self.text_display,
            bgcolor=bg_color,
            padding=12,
            border_radius=ft.BorderRadius.all(12),
        )
        
        # Row for the message bubble and the play button
        # For bot messages (is_user=False), play button on the right
        row_controls = [self.container, self.play_button] if not is_user else [self.play_button, self.container]
        
        self.controls = [
            ft.Row(
                controls=row_controls,
                alignment=alignment,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5
            )
        ]
        self._update_content()

    def _update_content(self):
        clean_text = strip_audio_tags(self.text)
        self.text_display.value = clean_text
        self.play_button.visible = bool(self.audio_segments)

    def update_message(self, text, audio_segments=None):
        self.text = text
        self.audio_segments = audio_segments or []
        self._update_content()
        self.update()

    def on_message_click(self, e):
        if self.audio_segments:
            threading.Thread(target=self.play_all_audio, daemon=True).start()

    def play_all_audio(self):
        for segment in self.audio_segments:
            path = get_audio_path(segment)
            if path:
                play_audio_file(path)
                try: os.remove(path)
                except: pass

def main(page: ft.Page):
    _page_ref[0] = page
    page.title = "Bangla Bot - Practice"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.window_width = 600
    page.window_height = 800
    
    if not api_key:
        page.add(ft.Text("Error: GOOGLE_API_KEY not found in environment variables.", color=ft.Colors.RED))
        page.update()
        return

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        page.add(ft.Text(f"Failed to initialize Gemini Client: {str(e)}", color=ft.Colors.RED))
        page.update()
        return
    
    with open("GEMINI.md", "r", encoding="utf-8") as f:
        system_instructions = f.read()

    tools = [read_progress, write_progress]
    config = types.GenerateContentConfig(
        system_instruction=system_instructions,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
    )

    current_model_name = [PRIMARY_MODEL]
    chat_session = [client.chats.create(model=current_model_name[0], config=config)]
    
    # UI Elements
    model_indicator = ft.Text(f"Model: {current_model_name[0]}", size=12, italic=True, color=ft.Colors.GREY_500)
    
    welcome_header = ft.Column([
        ft.Text("Bangla Bot", size=32, weight=ft.FontWeight.BOLD),
        ft.Text("Learn the Kolkata dialect (Cholitobhasha) through practice.", size=16),
        ft.Row([model_indicator], alignment=ft.MainAxisAlignment.END),
        ft.Divider()
    ])

    chat_history = ft.ListView(
        expand=True,
        spacing=10,
        auto_scroll=True,
    )

    def send_message(e):
        if not user_input.value:
            return
        
        msg_text = user_input.value
        user_input.value = ""
        user_input.disabled = True
        send_button.disabled = True
        
        # Add user message to UI
        chat_history.controls.append(Message(msg_text, is_user=True))
        
        # Add thinking indicator
        thinking_msg = Message("...", is_user=False)
        chat_history.controls.append(thinking_msg)
        page.update()
        
        # Explicitly scroll to bottom
        chat_history.scroll_to(offset=-1, duration=300)

        # Start thinking thread
        threading.Thread(target=process_response, args=(msg_text, thinking_msg), daemon=True).start()

    def process_response(text, thinking_msg=None):
        try:
            response = send_with_handling(text)
            
            # Extract audio segments
            audio_segments = re.findall(r'<audio>(.*?)</audio>', response.text)
            
            # Update the thinking indicator or add a new message
            if thinking_msg:
                thinking_msg.update_message(response.text, audio_segments)
            else:
                chat_history.controls.append(Message(response.text, is_user=False, audio_segments=audio_segments))
            
            user_input.disabled = False
            send_button.disabled = False
            page.update()
            
            # Explicitly scroll to bottom to ensure the new message is visible
            chat_history.scroll_to(offset=-1, duration=300)

        except Exception as ex:
            error_text = f"Error: {str(ex)}"
            if thinking_msg:
                thinking_msg.update_message(error_text)
            else:
                chat_history.controls.append(ft.Text(error_text, color=ft.Colors.RED))
            user_input.disabled = False
            send_button.disabled = False
            page.update()
            chat_history.scroll_to(offset=-1, duration=300)

    def send_with_handling(message_text):
        while True:
            try:
                return chat_session[0].send_message(message=message_text)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    time.sleep(10)
                    continue
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    if current_model_name[0] == PRIMARY_MODEL:
                        current_model_name[0] = FALLBACK_MODEL
                        model_indicator.value = f"Model: {current_model_name[0]} (Fallback)"
                        model_indicator.color = ft.Colors.ORANGE_300
                        page.update()
                        history = chat_session[0].get_history()
                        chat_session[0] = client.chats.create(model=current_model_name[0], config=config, history=history)
                        continue
                raise e

    user_input = ft.TextField(
        hint_text="Type your response here...",
        expand=True,
        on_submit=send_message,
        border_radius=20,
    )
    send_button = ft.IconButton(
        icon=ft.Icons.SEND,
        on_click=send_message,
        icon_color=ft.Colors.BLUE_400,
    )

    input_row = ft.Row(
        controls=[
            user_input,
            send_button
        ],
    )

    page.add(
        welcome_header,
        ft.Container(
            content=chat_history,
            expand=True,
        ),
        input_row
    )

    # Initial prompt
    thinking_msg = Message("...", is_user=False)
    chat_history.controls.append(thinking_msg)
    page.update()
    threading.Thread(target=process_response, args=("The user is about to start. Acknowledge and wait for their first request.", thinking_msg), daemon=True).start()

if __name__ == "__main__":
    if not api_key:
        print("Please set GOOGLE_API_KEY environment variable.")
        sys.exit(1)
    ft.run(main)
