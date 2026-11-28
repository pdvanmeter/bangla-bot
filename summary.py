from curriculum_manager import load_grammar, load_vocabulary, select_review_words
from progress_manager import (
    PROGRESS_FILE,
    SRS_INTERVAL_DAYS,
    SRS_LEVEL_LABELS,
    compute_progress_summary,
    ensure_progress_file,
    is_item_due,
)


def generate_summary(progress_file: str = PROGRESS_FILE):
    progress_data = ensure_progress_file(progress_file)
    _, vocab_by_id, all_vocab = load_vocabulary()
    grammar_list, grammar_by_id = load_grammar()

    summary = compute_progress_summary(
        progress_data, total_vocab=len(all_vocab), total_grammar=len(grammar_list)
    )

    pct_vocab = (
        (summary["learned_vocab"] / summary["total_vocab"]) * 100
        if summary["total_vocab"] > 0
        else 0.0
    )

    print("=====================================================")
    print(" Bengali Learning Progress Summary (5-Level SRS)")
    print("=====================================================")
    print(f"Curriculum Vocabulary:  {summary['total_vocab']:,} words")
    print(f"Words Encountered:      {summary['learned_vocab']:,} ({pct_vocab:.1f}%)")
    print(f"Words Due Today:        {summary['due_vocab']:,}")
    print(f"Sessions Completed:     {summary['sessions_completed']:,}")
    print("-----------------------------------------------------")
    print("Vocabulary by SRS Level:")
    for lvl in range(1, 6):
        cnt = summary["vocab_by_level"][lvl]
        print(
            f"  {SRS_LEVEL_LABELS[lvl]:<24} ({SRS_INTERVAL_DAYS[lvl]:>2}d): {cnt:>5,}"
        )

    focus_words = select_review_words(
        progress_data, count=10, vocab_by_id=vocab_by_id
    )
    if focus_words:
        print("\nTop Priority Review Words (Due / Lowest SRS):")
        for item in focus_words:
            due_tag = " [DUE]" if item["is_due"] else ""
            print(
                f"  - [{item['id']}] {item['bengali']} ({item['transliteration']} - {item['english']}): "
                f"L{item['srs_level']}{due_tag} | First: {item['first_encountered'] or '-'} | "
                f"Recent: {item['last_practiced'] or '-'}"
            )
    else:
        print("\nNo vocabulary practiced yet. Start a Learning session!")

    print("\nGrammar Concepts Status:")
    print(f"  Total in Curriculum:  {summary['total_grammar']}")
    print(f"  Encountered:          {summary['learned_grammar']}")
    print(f"  Due Today:            {summary['due_grammar']}")
    grammar_records = progress_data.get("grammar", {})
    if grammar_records:
        for gid, rec in sorted(
            grammar_records.items(),
            key=lambda x: (x[1].get("srs_level", 1), x[1].get("next_review_due", "")),
        ):
            concept = grammar_by_id.get(gid, {}).get("concept", gid)
            due_tag = " [DUE]" if is_item_due(rec) else ""
            print(
                f"  * [{gid}] {concept}: L{rec.get('srs_level', 1)}{due_tag} "
                f"(encounters: {rec.get('encounters', 1)}, due: {rec.get('next_review_due', '-')})"
            )

    print("=====================================================")


if __name__ == "__main__":
    generate_summary()
