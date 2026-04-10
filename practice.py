import subprocess
import re
import os
import tempfile
from gtts import gTTS

def play_audio(bengali_text):
    """Generates and plays TTS audio for the given Bengali text."""
    try:
        # 'bn' is the language code for Bengali
        tts = gTTS(text=bengali_text, lang='bn')
        
        # Create a temporary file for the mp3
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            temp_path = fp.name
        
        tts.save(temp_path)
        
        # Play the audio using native OS commands
        if os.name == 'nt':  # Windows
            os.system(f'start /wait {temp_path}')
        elif os.uname().sysname == 'Darwin':  # macOS
            os.system(f'afplay {temp_path}')
        else:  # Linux (requires mpg123 or similar installed)
            os.system(f'mpg123 -q {temp_path}') 
            
    except Exception as e:
        print(f"\n[Audio Error: Could not play audio. {e}]")
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)

def main():
    print("=====================================================")
    print(" Bengali Practice Environment Initialized")
    print(" Type your responses below. Type 'quit' to exit.")
    print("=====================================================\n")
    
    # Optional: Send an initial prompt to kick off the session based on the JSON
    initial_prompt = "Start a new session based on my progress.json file."
    
    # We maintain a loop to keep the script running
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("Ending session. Bhalo thakben (Stay well)!")
            break
            
        print("\nThinking...")
        
        # Call the Gemini CLI. 
        # Note: Ensure your CLI command matches how you installed it (e.g., 'gemini', 'gemini-cli')
        try:
            result = subprocess.run(
                ["gemini", user_input],
                capture_output=True,
                text=True,
                check=True
            )
            response = result.stdout
            
        except subprocess.CalledProcessError as e:
            print(f"Error calling Gemini CLI: {e.stderr}")
            continue
        except FileNotFoundError:
            print("Error: The 'gemini' command was not found. Make sure the CLI is installed and in your PATH.")
            break

        # Print the text response to the terminal
        print(f"\nTutor:\n{response}")
        
        # Extract and play audio
        # Regex looks for any text strictly between <audio> and </audio>
        audio_segments = re.findall(r'<audio>(.*?)</audio>', response)
        
        if audio_segments:
            print("\n[Playing Audio...]")
            for segment in audio_segments:
                play_audio(segment)

if __name__ == "__main__":
    main()