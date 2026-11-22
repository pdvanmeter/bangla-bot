import json
import os

PROGRESS_FILE = "progress.json"


def reset_progress(file_path: str = PROGRESS_FILE):
    data = {"vocabulary": {}, "grammar": {}}
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("=====================================================")
    print(f" Success: {file_path} has been reset.")
    print(" All vocabulary and grammar mastery scores are cleared.")
    print("=====================================================")


if __name__ == "__main__":
    confirm = input("Are you sure you want to reset all progress? (y/n): ")
    if confirm.strip().lower() == "y":
        reset_progress()
    else:
        print("Reset cancelled.")
