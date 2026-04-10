import json
import os

def load_progress(file_path='progress.json'):
    if not os.path.exists(file_path):
        return None
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_summary(data):
    if not data:
        print("No progress data found.")
        return

    vocab = data.get('vocabulary', {})
    grammar = data.get('grammar', {})

    total_words = len(vocab)
    practiced_words = [w for w, stats in vocab.items() if stats['encounters'] > 0]
    avg_mastery = sum(stats['mastery_score'] for stats in vocab.values()) / total_words if total_words > 0 else 0

    print("=====================================================")
    print(" Bengali Learning Progress Summary")
    print("=====================================================")
    print(f"Total Vocabulary Words: {total_words}")
    print(f"Words Encountered:      {len(practiced_words)} ({(len(practiced_words)/total_words)*100:.1f}%)")
    print(f"Overall Mastery Score:  {avg_mastery:.2f}/1.0")
    print("-----------------------------------------------------")

    # Weakest words (encountered at least once, sorted by mastery)
    weak_words = sorted(
        [{"word": w, **stats} for w, stats in vocab.items() if stats['encounters'] > 0],
        key=lambda x: x['mastery_score']
    )[:5]

    if weak_words:
        print("\nTop 5 Weakest Words (Focus Areas):")
        for item in weak_words:
            print(f"- {item['word']} ({item['meaning']}): {item['mastery_score']:.2f}")
    else:
        print("\nPractice more to see weakest words!")

    # Grammar Status
    print("\nGrammar Concepts Status:")
    status_counts = {"learning": 0, "not_started": 0, "mastered": 0}
    for g, stats in grammar.items():
        status = stats.get('status', 'not_started')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in status_counts.items():
        print(f"- {status.capitalize().replace('_', ' ')}: {count}")

    print("=====================================================")

if __name__ == "__main__":
    progress_data = load_progress()
    generate_summary(progress_data)
