from flask import Flask, jsonify, request
import bible_searcher
import requests

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@app.route("/game/start", methods=["GET"])
def start_game():
    steps = request.args.get("steps", default=6, type=int)
    try:
        result = bible_searcher.generate_verse_chain(steps=steps)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chapter/<book>/<int:chapter>")
def get_whole_chapter_verses(book: str, chapter: int) -> list[dict]:
    book_id = bible_searcher.BOOK_MAP[book]
    url = f"https://bolls.life/get-chapter/ESV/{book_id}/{chapter}/"
    res = requests.get(url)

    if res.status_code == 200:
        data = res.json()
        return [
            {
                "verse": item["verse"],
                "text": item["text"].replace("<pb/>", "").strip(),
            }
            for item in data
        ]
    return []


@app.route("/refs/<book>/<int:chapter>")
def get_refrenced_verses(book, chapter):
    refrenced = bible_searcher.get_chapter_references_with_origin(book, chapter)
    return jsonify({"refs": list(refrenced)})


@app.route("/correlations/<book>/<int:chapter>/<int:verse>")
def get_correlations(book, chapter, verse):
    name = f"{book}.{chapter}.{verse}"
    corrolations = bible_searcher.get_edges_from_verse(
        bible_searcher.name_to_verse(name)
    )
    return jsonify({"correlations": list(corrolations)})


@app.route("/batch-verses", methods=["POST"])
def batch_verses():
    payload = request.get_json()
    res = requests.post("https://bolls.life/get-verses/", json=payload)
    return jsonify(res.json()), res.status_code


if __name__ == "__main__":
    app.run(debug=True, port=5000)