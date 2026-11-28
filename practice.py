import os
import re
import sys
import time
from google import genai

from curriculum_manager import POS_FILES, load_grammar, load_vocabulary, query_vocabulary
from progress_manager import SRS_LEVEL_LABELS, compute_progress_summary, ensure_progress_file
from session_builder import (
    SessionPlan,
    build_kickoff_message,
    build_session_system_instructions,
    create_conversation_session,
    create_custom_session,
    create_learn_session,
    create_review_session,
    make_session_score_tool,
)
from tutor_core import (
    AVAILABLE_MODELS,
    PRIMARY_MODEL,
    build_generate_config,
    extract_audio_segments,
    play_audio_segments,
    prefetch_audio_segments,
    strip_audio_tags,
)


def _prompt_int(label: str, default: int, minimum: int = 0, maximum: int = 50) -> int:
    raw = input(f"  {label} [default {default}]: ").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, val))


def print_dashboard_header() -> dict:
    _, _, all_vocab = load_vocabulary()
    grammar_list, _ = load_grammar()
    progress = ensure_progress_file()
    summary = compute_progress_summary(progress, len(all_vocab), len(grammar_list))

    print("\n=====================================================")
    print(" Bangla Bot — Kolkata Dialect (Cholitobhasha) Tutor")
    print("=====================================================")
    print(
        f" Vocabulary: {summary['learned_vocab']:,} / {summary['total_vocab']:,} learned "
        f"| Due today: {summary['due_vocab']:,}"
    )
    print(
        f" Grammar:    {summary['learned_grammar']} / {summary['total_grammar']} learned "
        f"| Due today: {summary['due_grammar']}"
    )
    levels_line = " | ".join(
        f"L{lvl}:{summary['vocab_by_level'][lvl]}" for lvl in range(1, 6)
    )
    print(f" SRS Levels: {levels_line} | Sessions: {summary['sessions_completed']}")
    print("-----------------------------------------------------")
    return summary


def browse_vocabulary_cli():
    _, _, all_vocab = load_vocabulary()
    progress = ensure_progress_file()

    print("\n--- Vocabulary Browser ---")
    search = input("  Search (Bengali/translit/English/ID, Enter for all): ").strip()
    pos_options = ", ".join(p for p, _ in POS_FILES)
    pos_filter = input(f"  POS filter ({pos_options}, Enter for all): ").strip().lower() or "all"
    status_filter = (
        input("  Status (all/encountered/unseen/due/level_1..level_5, Enter for all): ")
        .strip()
        .lower()
        or "all"
    )
    sort_by = (
        input("  Sort (frequency/srs_level/first_encountered/last_practiced, Enter for frequency): ")
        .strip()
        .lower()
        or "frequency"
    )

    page = 0
    page_size = 15
    while True:
        items, total = query_vocabulary(
            progress=progress,
            search=search,
            pos_filter=pos_filter,
            status_filter=status_filter,
            sort_by=sort_by,
            offset=page * page_size,
            limit=page_size,
            all_vocab=all_vocab,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        print(f"\nShowing page {page + 1}/{total_pages} ({total:,} matches):")
        if not items:
            print("  (No matching words.)")
        for it in items:
            lvl = it["srs_level"]
            srs_tag = "Unseen" if lvl == 0 else f"L{lvl}"
            if it["is_due"]:
                srs_tag += " DUE"
            loan = " [Loanword]" if it.get("is_loanword") else ""
            first_d = it["first_encountered"] or "-"
            last_d = it["last_practiced"] or "-"
            print(
                f"  {it['id']:<10} {it['bengali']} ({it['transliteration']}) — {it['english']} "
                f"[{it['pos']}{loan}] | {srs_tag} | First:{first_d} Last:{last_d}"
            )

        nav = input("\n  [n]ext, [p]rev, or [Enter] to return to menu: ").strip().lower()
        if nav == "n" and page + 1 < total_pages:
            page += 1
        elif nav == "p" and page > 0:
            page -= 1
        else:
            break


def build_custom_session_cli() -> SessionPlan | None:
    _, vocab_by_id, all_vocab = load_vocabulary()
    grammar_list, _ = load_grammar()
    progress = ensure_progress_file()

    print("\n--- Custom Session Picker ---")
    print("  Tip: Enter word IDs (e.g. noun_0001, verb_0002) or search keywords.")
    selected_vocab_ids: list[str] = []

    while True:
        raw = input("  Enter IDs or search term (Enter when done selecting words): ").strip()
        if not raw:
            break
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
        matched_direct = [t for t in tokens if t in vocab_by_id]
        if matched_direct:
            for vid in matched_direct:
                if vid not in selected_vocab_ids:
                    selected_vocab_ids.append(vid)
                    w = vocab_by_id[vid]
                    print(f"    + Added {vid}: {w['bengali']} ({w['transliteration']}) — {w['english']}")
        else:
            hits, total = query_vocabulary(progress=progress, search=raw, limit=10, all_vocab=all_vocab)
            if not hits:
                print("    No matching words found.")
                continue
            for idx, h in enumerate(hits, start=1):
                print(f"    {idx}. [{h['id']}] {h['bengali']} ({h['transliteration']}) — {h['english']}")
            pick = input("  Select numbers (e.g. 1,3) or Enter to skip: ").strip()
            for part in pick.split(","):
                part = part.strip()
                if part.isdigit():
                    i = int(part) - 1
                    if 0 <= i < len(hits):
                        vid = hits[i]["id"]
                        if vid not in selected_vocab_ids:
                            selected_vocab_ids.append(vid)
                            print(f"    + Added {vid}")

    print("\n  Grammar concepts:")
    for idx, g in enumerate(grammar_list, start=1):
        print(f"    {idx}. [{g['id']}] {g['concept']}")
    gram_pick = input("  Select grammar numbers (comma-separated, Enter for none): ").strip()
    selected_grammar_ids: list[str] = []
    for part in gram_pick.split(","):
        part = part.strip()
        if part.isdigit():
            i = int(part) - 1
            if 0 <= i < len(grammar_list):
                selected_grammar_ids.append(grammar_list[i]["id"])

    style_raw = input("  Session style — [1] Full (default) or [2] Conversation Only: ").strip()
    submode = "conversation_only" if style_raw == "2" else "full"

    try:
        return create_custom_session(
            vocab_ids=selected_vocab_ids,
            grammar_ids=selected_grammar_ids,
            submode=submode,
        )
    except ValueError as ex:
        print(f"  {ex}")
        return None


def run_cli_session(client: genai.Client, plan: SessionPlan):
    print(f"\nStarting {plan.summary_label()} ...")
    print("Commands: 'r'/'repeat' = replay audio | 'finish' = conclude & score | 'menu' = back to menu")

    system_instructions = build_session_system_instructions(plan)
    score_saved_flag = [False]

    def on_scores_saved(result: dict):
        score_saved_flag[0] = True
        print(f"\n[SRS Progress Saved: {len(result.get('updated', []))} items updated]")

    score_tool = make_session_score_tool(plan, on_scores_saved=on_scores_saved)
    current_model = PRIMARY_MODEL
    chat = client.chats.create(
        model=current_model,
        config=build_generate_config(current_model, system_instructions, tools=[score_tool]),
    )
    last_audio_segments: list[str] = []

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
                                config=build_generate_config(
                                    current_model, system_instructions, tools=[score_tool]
                                ),
                                history=history,
                            )
                        except Exception:
                            current_model = next_model
                            chat = client.chats.create(
                                model=current_model,
                                config=build_generate_config(
                                    current_model, system_instructions, tools=[score_tool]
                                ),
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
        response = send_with_handling(build_kickoff_message(plan))
    except Exception as ex:
        print(f"\nError starting session: {ex}")
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
            print("\nReturning to menu.")
            break

        if not user_input:
            continue
        low = user_input.lower()
        if low in ("r", "repeat"):
            if last_audio_segments:
                play_audio_segments(last_audio_segments)
            else:
                print("\n[No audio to repeat.]")
            continue
        if low in ("menu", "back", "quit", "exit", "q"):
            break
        if low == "finish":
            user_input = (
                "Please conclude the session now: summarize my performance on every "
                "session item and call `submit_session_scores` with all required item_ids."
            )

        print(f"\nThinking ({current_model})...")
        try:
            response = send_with_handling(user_input)
        except Exception as ex:
            print(f"\nError during API call: {ex}")
            break


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        api_key = input("Enter your Google API Key: ").strip()
        os.environ["GOOGLE_API_KEY"] = api_key

    client = genai.Client(api_key=api_key)

    while True:
        print_dashboard_header()
        print("  1. Start Learning Session (new + review + grammar)")
        print("  2. Start Review Session (review translations + conversation)")
        print("  3. Start Conversation Session (conversation only)")
        print("  4. Start Custom Session")
        print("  5. Browse / Filter Vocabulary List")
        print("  6. Quit")

        choice = input("\nSelect an option (1-6): ").strip()
        if choice == "1":
            n_new = _prompt_int("New words", 5, 0, 25)
            n_rev = _prompt_int("Review words", 5, 0, 30)
            n_gram = _prompt_int("Grammar concepts", 2, 0, 5)
            try:
                plan = create_learn_session(n_new, n_rev, n_gram)
                run_cli_session(client, plan)
            except ValueError as ex:
                print(f"\n{ex}")
        elif choice == "2":
            n_rev = _prompt_int("Review words", 10, 1, 30)
            n_gram = _prompt_int("Grammar concepts", 2, 0, 5)
            try:
                plan = create_review_session(n_rev, n_gram)
                run_cli_session(client, plan)
            except ValueError as ex:
                print(f"\n{ex}")
        elif choice == "3":
            n_rev = _prompt_int("Target words", 10, 1, 30)
            n_gram = _prompt_int("Grammar concepts", 2, 0, 5)
            try:
                plan = create_conversation_session(n_rev, n_gram)
                run_cli_session(client, plan)
            except ValueError as ex:
                print(f"\n{ex}")
        elif choice == "4":
            plan = build_custom_session_cli()
            if plan:
                run_cli_session(client, plan)
        elif choice == "5":
            browse_vocabulary_cli()
        elif choice == "6" or choice.lower() in ("q", "quit", "exit"):
            print("\nBhalo thakben (Stay well)!")
            break
        else:
            print("Invalid selection.")


if __name__ == "__main__":
    main()
