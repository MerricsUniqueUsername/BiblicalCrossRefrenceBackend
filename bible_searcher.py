import random
import psycopg
import requests
import os

BOOK_MAP = {
    # Old Testament
    "Gen": 1, "Exod": 2, "Lev": 3, "Num": 4, "Deut": 5, "Josh": 6, "Judg": 7,
    "Ruth": 8, "1Sam": 9, "2Sam": 10, "1Kgs": 11, "2Kgs": 12, "1Chr": 13,
    "2Chr": 14, "Ezra": 15, "Neh": 16, "Esth": 17, "Job": 18, "Ps": 19,
    "Prov": 20, "Eccl": 21, "Song": 22, "Isa": 23, "Jer": 24, "Lam": 25,
    "Ezek": 26, "Dan": 27, "Hos": 28, "Joel": 29, "Amos": 30, "Obad": 31,
    "Jonah": 32, "Mic": 33, "Nah": 34, "Hab": 35, "Zeph": 36, "Hag": 37,
    "Zech": 38, "Mal": 39,
    # New Testament
    "Matt": 40, "Mark": 41, "Luke": 42, "John": 43, "Acts": 44, "Rom": 45,
    "1Cor": 46, "2Cor": 47, "Gal": 48, "Eph": 49, "Phil": 50, "Col": 51,
    "1Thess": 52, "2Thess": 53, "1Tim": 54, "2Tim": 55, "Titus": 56,
    "Phlm": 57, "Heb": 58, "Jas": 59, "1Pet": 60, "2Pet": 61, "1John": 62,
    "2John": 63, "3John": 64, "Jude": 65, "Rev": 66,
}
DB_URL = os.getenv("DB_URL")


def get_edges_from_verse(verse_id: int) -> list[tuple[str, str]]:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_verse, to_end_verse FROM edge WHERE from_verse = %s",
                (verse_id,),
            )
            return [
                (verse_num_to_name(row[0]), verse_num_to_name(row[1]))
                for row in cur.fetchall()
            ]


def verse_num_to_name(verse_id: int) -> str:
    book_num = verse_id // 1_000_000
    chapter = (verse_id // 1_000) % 1_000
    verse = verse_id % 1_000
    book_name = next(name for name, num in BOOK_MAP.items() if num == book_num)
    return f"{book_name}.{chapter}.{verse}"


def name_to_verse(name: str) -> int:
    book_name, chapter, verse = name.split(".")
    chapter = int(chapter)
    verse = int(verse)
    book_num = BOOK_MAP[book_name]
    return book_num * 1_000_000 + chapter * 1_000 + verse


def get_verse_text(verse_range: tuple[int, int]) -> str:
    start_verse, end_verse = verse_range

    b1, c1, v1 = verse_num_to_name(start_verse).split(".")
    b2, c2, v2 = verse_num_to_name(end_verse).split(".")

    # Format the query string properly for bible-api.com
    if start_verse == end_verse:
        query = f"{b1} {c1}:{v1}"
    elif c1 == c2:
        query = f"{b1} {c1}:{v1}-{v2}"
    else:
        query = f"{b1} {c1}:{v1}-{c2}:{v2}"

    response = requests.get(f"https://bible-api.com/{query}")

    if response.status_code == 200:
        data = response.json()
        return data.get("text", "").strip()

    return f"Error fetching {query}: {response.status_code}"


def get_chapter_references_with_origin(book: str, chapter: int) -> set[str]:
    book_num = BOOK_MAP[book]
    start_verse_id = book_num * 1_000_000 + chapter * 1_000
    end_verse_id = start_verse_id + 999

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT from_verse, to_verse, to_end_verse 
                FROM edge 
                WHERE from_verse >= %s AND from_verse <= %s
                ORDER BY from_verse
                """,
                (start_verse_id, end_verse_id),
            )
            return {verse_num_to_name(row[0]) for row in cur.fetchall() if row[0]}


def get_whole_chapter_text(book: str, chapter: int) -> str:
    query = f"{book} {chapter}"
    response = requests.get(f"https://bible-api.com/{query}")

    if response.status_code == 200:
        data = response.json()
        return data.get("text", "").strip()

    return f"Error fetching {query}: {response.status_code}"


# ==========================================
# 10-Hop Random Walk Algorithm
# ==========================================

def get_chapter_id(verse_id: int) -> int:
    """Strips the verse portion: book_num * 1_000_000 + chapter * 1_000."""
    return (verse_id // 1_000) * 1_000


def get_random_starting_verse(cur) -> int:
    """Picks a random originating verse that has at least one outgoing reference."""
    cur.execute("SELECT from_verse FROM edge ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    if not row:
        raise ValueError("No edges found in the database.")
    return row[0]


def get_outgoing_targets_for_chapter(cur, chapter_id: int) -> list[tuple[int, int]]:
    """Returns pairs of (from_verse, to_verse) originating from this chapter."""
    start_range = chapter_id
    end_range = chapter_id + 999

    cur.execute(
        """
        SELECT from_verse, to_verse 
        FROM edge 
        WHERE from_verse >= %s AND from_verse <= %s
        """,
        (start_range, end_range),
    )
    return cur.fetchall()


def generate_verse_chain(steps: int = 10, max_retries: int = 50) -> list[dict]:
    """
    Returns a sequence of hops.
    Each hop contains:
      - 'from_verse': exact verse in current chapter to click
      - 'to_verse': the destination verse you land on
    """
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for _ in range(max_retries):
                start_verse = get_random_starting_verse(cur)
                # First node: start location
                path_hops = []
                visited_chapters = {get_chapter_id(start_verse)}

                def dfs(current_verse: int, current_step: int) -> bool:
                    if current_step == steps:
                        return True

                    curr_chap = get_chapter_id(current_verse)
                    potential_edges = get_outgoing_targets_for_chapter(cur, curr_chap)
                    random.shuffle(potential_edges)

                    for exit_verse, next_verse in potential_edges:
                        next_chap = get_chapter_id(next_verse)

                        if next_chap not in visited_chapters:
                            visited_chapters.add(next_chap)
                            path_hops.append((exit_verse, next_verse))

                            if dfs(next_verse, current_step + 1):
                                return True

                            path_hops.pop()
                            visited_chapters.remove(next_chap)

                    return False

                if dfs(start_verse, 0):
                    formatted_path = [
                        {
                            "from": verse_num_to_name(exit_v),
                            "to": verse_num_to_name(target_v),
                        }
                        for exit_v, target_v in path_hops
                    ]
                    return {
                        "start": verse_num_to_name(start_verse),
                        "target": formatted_path[-1]["to"],
                        "path": formatted_path,
                    }

    raise RuntimeError("Could not find a valid path within the retry limit.")


if __name__ == "__main__":
    chain = generate_verse_chain(steps=10)
    print(f"Path generated ({len(chain) - 1} steps):\n")
    for idx, verse in enumerate(chain):
        if idx == 0:
            print(f"Start:      {verse}")
        elif idx == len(chain) - 1:
            print(f"Destination:{verse}")
        else:
            print(f"Hop {idx:2d}:     {verse}")