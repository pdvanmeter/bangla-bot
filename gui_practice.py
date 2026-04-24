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
        os.system(f'start /wait {path}')
    elif os.uname().sysname == 'Darwin':
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
        
        clean_text = strip_audio_tags(text)
        
        # Internal controls for updating
        self.text_display = ft.Text(clean_text, color=ft.Colors.WHITE, selectable=True, width=400, no_wrap=False)
        
        # Alignment and colors
        alignment = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START
        bg_color = ft.Colors.BLUE_700 if is_user else ft.Colors.GREY_800
        
        self.container = ft.Container(
            content=self.text_display,
            bgcolor=bg_color,
            padding=10,
            border_radius=ft.BorderRadius.all(10),
            on_click=self.on_message_click if self.audio_segments else None
        )
        
        self.controls = [
            ft.Row(
                controls=[self.container],
                alignment=alignment
            )
        ]

    def update_message(self, text, audio_segments=None):
        self.text = text
        self.audio_segments = audio_segments or []
        clean_text = strip_audio_tags(text)
        self.text_display.value = clean_text
        self.container.on_click = self.on_message_click if self.audio_segments else None
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
    page.vertical_alignment = ft.MainAxisAlignment.END
    
    if not api_key:
        chat_history.controls.append(ft.Text("Error: GOOGLE_API_KEY not found in environment variables.", color=ft.Colors.RED))
        page.update()
        return

    try:
        client = genai.Client(api_key=api_key)
        # Test the client with a dummy call or just proceed
    except Exception as e:
        chat_history.controls.append(ft.Text(f"Failed to initialize Gemini Client: {str(e)}", color=ft.Colors.RED))
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

    current_model = [PRIMARY_MODEL] # Use list to be mutable in nested scopes
    chat_session = [client.chats.create(model=current_model[0], config=config)]
    
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

            # Play audio automatically if present
            if audio_segments:
                for segment in audio_segments:
                    path = get_audio_path(segment)
                    if path:
                        play_audio_file(path)
                        try: os.remove(path)
                        except: pass
        except Exception as ex:
            error_text = f"Error: {str(ex)}"
            if thinking_msg:
                thinking_msg.update_message(error_text)
            else:
                chat_history.controls.append(ft.Text(error_text, color=ft.Colors.RED))
            user_input.disabled = False
            send_button.disabled = False
            page.update()

    def send_with_handling(message_text):
        while True:
            try:
                return chat_session[0].send_message(message=message_text)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    time.sleep(10) # Simple wait for GUI
                    continue
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    if current_model[0] == PRIMARY_MODEL:
                        current_model[0] = FALLBACK_MODEL
                        history = chat_session[0].get_history()
                        chat_session[0] = client.chats.create(model=current_model[0], config=config, history=history)
                        continue
                raise e

    user_input = ft.TextField(
        hint_text="Type your response here...",
        expand=True,
        on_submit=send_message,
    )
    send_button = ft.IconButton(
        icon=ft.Icons.SEND,
        on_click=send_message
    )

    input_row = ft.Row(
        controls=[
            user_input,
            send_button
        ],
    )

    page.add(
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
