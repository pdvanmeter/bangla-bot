from progress_manager import PROGRESS_FILE, reset_progress_data


def reset_progress(file_path: str = PROGRESS_FILE):
    reset_progress_data(file_path)
    print("=====================================================")
    print(f" Success: {file_path} has been reset (v2 SRS schema).")
    print(" All vocabulary, grammar SRS levels, and history are cleared.")
    print("=====================================================")


if __name__ == "__main__":
    confirm = input("Are you sure you want to reset all progress? (y/n): ")
    if confirm.strip().lower() == "y":
        reset_progress()
    else:
        print("Reset cancelled.")
