import json
import os

PROGRESS_FILE = "progress.json"
VOCAB_FILE = os.path.join("curriculum", "vocabulary.json")
GRAMMAR_FILE = os.path.join("curriculum", "grammar.json")


def load_json(file_path: str):
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_vocab_lookup(vocab_curriculum: dict | None) -> dict[str, dict]:
    """Maps transliteration key -> {'bengali': ..., 'english': ..., 'category': ...}."""
    lookup: dict[str, dict] = {}
    if not vocab_curriculum:
        return lookup
    for level, categories in vocab_curriculum.items():
        if not isinstance(categories, dict):
            continue
        for category, items in categories.items():
            if not isinstance(items, list):
                continue
            for entry in items:
                key = entry.get("transliteration")
                if key:
                    lookup[key] = {
                        "bengali": entry.get("bengali", ""),
                        "english": entry.get("english", ""),
                        "category": category,
                        "level": level,
                    }
    return lookup


def count_grammar_curriculum(grammar_curriculum: dict | None) -> int:
    if not grammar_curriculum:
        return 0
    total = 0
    for items in grammar_curriculum.values():
        if isinstance(items, list):
            total += len(items)
    return total


def generate_summary(progress_data: dict | None):
    if not progress_data:
        print("No progress data found.")
        return

    vocab_curriculum = load_json(VOCAB_FILE)
    grammar_curriculum = load_json(GRAMMAR_FILE)
    vocab_lookup = build_vocab_lookup(vocab_curriculum)

    vocab_progress = progress_data.get("vocabulary", {})
    grammar_progress = progress_data.get("grammar", {})

    total_curriculum_words = len(vocab_lookup) or len(vocab_progress)
    practiced_words = [
        (w, stats)
        for w, stats in vocab_progress.items()
        if stats.get("encounters", 0) > 0
    ]
    avg_vocab_mastery = (
        sum(stats.get("mastery_score", 0.0) for _, stats in practiced_words)
        / len(practiced_words)
        if practiced_words
        else 0.0
    )

    print("=====================================================")
    print(" Bengali Learning Progress Summary")
    print("=====================================================")
    print(f"Curriculum Vocabulary:  {total_curriculum_words} words")
    if total_curriculum_words > 0:
        pct = (len(practiced_words) / total_curriculum_words) * 100
        print(f"Words Encountered:      {len(practiced_words)} ({pct:.1f}%)")
    else:
        print(f"Words Encountered:      {len(practiced_words)}")
    print(f"Average Word Mastery:   {avg_vocab_mastery:.2f} / 1.00")
    print("-----------------------------------------------------")

    weak_words = sorted(
        [{"word": w, **stats} for w, stats in practiced_words],
        key=lambda x: (x.get("mastery_score", 0.0), x.get("encounters", 0)),
    )[:5]

    if weak_words:
        print("\nTop 5 Weakest Words (Focus Areas):")
        for item in weak_words:
            word = item["word"]
            meta = vocab_lookup.get(word, {})
            bengali = meta.get("bengali", "")
            meaning = meta.get("english", "custom/unlisted")
            label = f"{bengali} ({word} - {meaning})" if bengali else f"{word} ({meaning})"
            print(
                f"- {label}: mastery {item.get('mastery_score', 0.0):.2f} "
                f"({item.get('encounters', 0)} encounters)"
            )
    else:
        print("\nPractice more to see weakest words!")

    total_grammar = count_grammar_curriculum(grammar_curriculum)
    practiced_grammar = [
        (g, stats)
        for g, stats in grammar_progress.items()
        if stats.get("encounters", 0) > 0
    ]
    print("\nGrammar Concepts Status:")
    print(f"- Total in Curriculum: {total_grammar}")
    print(f"- Encountered:         {len(practiced_grammar)}")
    if practiced_grammar:
        for concept, stats in sorted(
            practiced_grammar, key=lambda x: x[1].get("mastery_score", 0.0)
        ):
            print(
                f"  * {concept}: mastery {stats.get('mastery_score', 0.0):.2f} "
                f"({stats.get('encounters', 0)} encounters)"
            )

    print("=====================================================")


if __name__ == "__main__":
    progress_data = load_json(PROGRESS_FILE)
    generate_summary(progress_data)
