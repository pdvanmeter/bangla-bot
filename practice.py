import os
import re
import sys
import time
from google import genai

from tutor_core import (
    AVAILABLE_MODELS,
    PRIMARY_MODEL,
    build_generate_config,
    extract_audio_segments,
    load_system_instructions,
    play_audio_segments,
    prefetch_audio_segments,
    strip_audio_tags,
)


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        api_key = input("Enter your Google API Key: ").strip()
        os.environ["GOOGLE_API_KEY"] = api_key

    client = genai.Client(api_key=api_key)

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

    system_instructions = load_system_instructions()
    current_model = PRIMARY_MODEL
    chat = client.chats.create(
        model=current_model,
        config=build_generate_config(current_model, system_instructions),
    )

    last_audio_segments: list[str] = []
    print(f"Initializing with {current_model}...")

    def send_with_handling(message_text: str):
        nonlocal chat, current_model
        tried_models = {current_model}
        while True:
            try:
                return chat.send_message(message=message_text)
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
                    if "PerDay" in error_str:
                        print("\n[Daily Quota Exceeded] Please try again tomorrow.")
                        sys.exit(0)

                    next_model = next(
                        (m for m in AVAILABLE_MODELS if m not in tried_models),
                        None,
                    )
                    if next_model:
                        tried_models.add(next_model)
                        print(f"\n[Model Switch] Switching from {current_model} to {next_model}...")
                        try:
                            history = chat.get_history()
                            current_model = next_model
                            chat = client.chats.create(
                                model=current_model,
                                config=build_generate_config(current_model, system_instructions),
                                history=history,
                            )
                        except Exception:
                            current_model = next_model
                            chat = client.chats.create(
                                model=current_model,
                                config=build_generate_config(current_model, system_instructions),
                            )
                        continue

                    wait_time = 10
                    match = re.search(r"retry in ([\d\.]+)s", error_str)
                    if match:
                        wait_time = int(float(match.group(1))) + 1

                    print(f"\n[Rate Limit / Busy] Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                raise e

    try:
        response = send_with_handling(
            "The user is about to start. Acknowledge briefly and wait for their first request."
        )
    except Exception as e:
        print(f"\nError during initialization: {e}")
        return

    while True:
        resp_text = response.text or ""
        clean_text = strip_audio_tags(resp_text)
        if clean_text:
            print(f"\nTutor:\n{clean_text}")

        current_audio = extract_audio_segments(resp_text)
        if current_audio:
            last_audio_segments = current_audio
            prefetch_audio_segments(last_audio_segments)
            print("\n[Playing Audio...]")
            play_audio_segments(last_audio_segments)

        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEnding session. Bhalo thakben (Stay well)!")
            break

        if not user_input:
            continue

        if user_input.lower() in ["r", "repeat"]:
            if last_audio_segments:
                print("\n[Repeating Audio...]")
                play_audio_segments(last_audio_segments)
            else:
                print("\n[No audio to repeat.]")
            continue

        if user_input.lower() in ["quit", "exit", "q"]:
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
