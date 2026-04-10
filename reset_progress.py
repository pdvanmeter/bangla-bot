import json
import os

def reset_progress(file_path='progress.json'):
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Reset Vocabulary
    if 'vocabulary' in data:
        for word in data['vocabulary']:
            data['vocabulary'][word]['encounters'] = 0
            data['vocabulary'][word]['mastery_score'] = 0.0
            data['vocabulary'][word]['last_practiced'] = None
            data['vocabulary'][word]['struggle_notes'] = ""
    
    # Reset Grammar
    if 'grammar' in data:
        for concept in data['grammar']:
            data['grammar'][concept]['status'] = 'not_started' if 'not_started' in data['grammar'][concept].get('notes', '').lower() else 'learning'
            data['grammar'][concept]['last_practiced'] = None
            # We keep the notes as they contain the rules

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print("=====================================================")
    print(" Success: progress.json has been reset.")
    print(" All mastery scores and encounters are now zero.")
    print("=====================================================")

if __name__ == "__main__":
    confirm = input("Are you sure you want to reset all progress? (y/n): ")
    if confirm.lower() == 'y':
        reset_progress()
    else:
        print("Reset cancelled.")
