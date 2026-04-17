import os
import re
import json
import time
import sys
import tempfile
from google import genai
from google.genai import types, errors
from gtts import gTTS

# Configure Gemini API
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    api_key = input("Enter your Google API Key: ")
    os.environ["GOOGLE_API_KEY"] = api_key

client = genai.Client(api_key=api_key)

PROGRESS_FILE = "progress.json"
PRIMARY_MODEL = "gemini-3-flash-preview"
FALLBACK_MODEL = "gemini-2.5-flash"

def read_progress():
    """Reads the current learner's progress from progress.json."""
    if not os.path.exists(PROGRESS_FILE):
        return {"error": "Progress file not found."}
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def write_progress(data: dict):
    """Updates the progress.json file with new scores or stats."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            return "Error: Invalid data format."
            
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return "Progress updated successfully."

def play_audio(bengali_text):
    """Generates and plays TTS audio for the given Bengali text."""
    try:
        tts = gTTS(text=bengali_text, lang='bn')
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            temp_path = fp.name
        
        tts.save(temp_path)
        
        if os.name == 'nt':
            os.system(f'start /wait {temp_path}')
        elif os.uname().sysname == 'Darwin':
            os.system(f'afplay {temp_path}')
        else:
            os.system(f'mpg123 -q {temp_path}') 
            
    except Exception as e:
        print(f"\n[Audio Error: Could not play audio. {e}]")
    finally:
        if os.name == 'nt':
             try: os.remove(temp_path)
             except: pass
        elif os.path.exists(temp_path):
            os.remove(temp_path)

def strip_audio_tags(text):
    """Removes <audio>...</audio> tags from the text for clean display."""
    if not text: return ""
    return re.sub(r'<audio>.*?</audio>', '', text).strip()

def main():
    print("=====================================================")
    print(" 🇧🇩  Bengali Tutor: Practice Environment  🇧🇩")
    print("=====================================================")
    print("\nHow to use:")
    print("  - Type 'Start practicing' to begin a new session.")
    print("  - Type 'r' or 'repeat' to hear the last audio again.")
    print("  - Type 'quit' or 'exit' to end the session.")
    print("=====================================================\n")

    if not os.path.exists("GEMINI.md"):
        print("Error: GEMINI.md not found. Please ensure it's in the current directory.")
        return

    with open("GEMINI.md", "r", encoding="utf-8") as f:
        system_instructions = f.read()

    tools = [read_progress, write_progress]
    config = types.GenerateContentConfig(
        system_instruction=system_instructions,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
    )

    current_model = PRIMARY_MODEL
    chat = client.chats.create(model=current_model, config=config)
    
    last_audio_segments = []
    
    print(f"Initializing with {current_model}...")
    
    def send_with_handling(message_text):
        nonlocal chat, current_model
        while True:
            try:
                return chat.send_message(message=message_text)
            except Exception as e:
                error_str = str(e)
                
                # Handle 429 (Rate Limit)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    if "PerDay" in error_str:
                        print("\n[Daily Quota Exceeded] Please try again tomorrow.")
                        sys.exit(0)
                    
                    wait_time = 60
                    match = re.search(r"retry in ([\d\.]+)s", error_str)
                    if match:
                        wait_time = int(float(match.group(1))) + 1
                    
                    print(f"\n[Rate Limit Hit] Waiting {wait_time}s...")
                    for i in range(wait_time, 0, -1):
                        sys.stdout.write(f"\rRetrying in {i}s... [{'#' * (wait_time-i)}{'-' * i}]")
                        sys.stdout.flush()
                        time.sleep(1)
                    sys.stdout.write("\r" + " " * 80 + "\r")
                    continue

                # Handle 503 (High Demand / Fallback)
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    if current_model == PRIMARY_MODEL:
                        print(f"\n[High Demand] {PRIMARY_MODEL} is currently busy.")
                        print(f"Falling back to {FALLBACK_MODEL} to continue your session...")
                        
                        try:
                            # Capture history and switch models
                            history = chat.get_history()
                            current_model = FALLBACK_MODEL
                            chat = client.chats.create(model=current_model, config=config, history=history)
                        except Exception as history_error:
                            print(f"[Fallback Error] Could not retrieve history: {history_error}")
                            print("Starting a fresh session with the fallback model...")
                            current_model = FALLBACK_MODEL
                            chat = client.chats.create(model=current_model, config=config)
                        
                        # Immediate retry with new model
                        continue
                    else:
                        # If fallback model is also 503, wait briefly
                        print("\n[Service Busy] Both models are under high demand. Waiting 10s before retrying...")
                        time.sleep(10)
                        continue
                
                # If we get here, it's an unhandled error
                raise e

    try:
        response = send_with_handling("The user is about to start. Acknowledge and wait for their first request.")
    except Exception as e:
        print(f"\nError during initialization: {e}")
        return

    while True:
        clean_text = strip_audio_tags(response.text)
        if clean_text:
            print(f"\nTutor:\n{clean_text}")

        if response.text:
            current_audio = re.findall(r'<audio>(.*?)</audio>', response.text)
            if current_audio:
                last_audio_segments = current_audio
                print("\n[Playing Audio...]")
                for segment in last_audio_segments:
                    play_audio(segment)

        user_input = input("\nYou: ").strip()
        
        if user_input.lower() in ['r', 'repeat']:
            if last_audio_segments:
                print("\n[Repeating Audio...]")
                for segment in last_audio_segments:
                    play_audio(segment)
            else:
                print("\n[No audio to repeat.]")
            continue

        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\nEnding session. Bhalo thakben (Stay well)!")
            break
            
        print(f"\nThinking ({current_model})...")
        try:
            response = send_with_handling(user_input)
        except Exception as e:
            print(f"\nError during API call: {e}")
            break

if __name__ == "__main__":
    main()
