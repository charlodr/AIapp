import os
import requests

from flask import Flask, request, jsonify, send_from_directory

from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__, static_folder="static")

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "chatbot-visione-497608")
GCP_LOCATION   = os.environ.get("GCP_LOCATION", "global")
DATASTORE_ID   = os.environ.get("DATASTORE_ID", "visionedatastore_1779872407393")

SERVING_CONFIG = (
    f"projects/{GCP_PROJECT_ID}/locations/{GCP_LOCATION}/"
    f"collections/default_collection/dataStores/{DATASTORE_ID}/"
    f"servingConfigs/default_search"
)

ENDPOINT = (
    "https://discoveryengine.googleapis.com/v1/"
    f"{SERVING_CONFIG}:answer"
)

TRACKS = {
    "1": "AI for Representation and Design",
    "2": "AI for Heritage Conservation and Enhancement",
    "3": "AI for Education and Learning",
}

sessions = {}
MAX_HISTORY = 5


def get_session(sid):
    if sid not in sessions:
        sessions[sid] = {"track": None, "history": []}
    return sessions[sid]


def gcp_token():
    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


def is_italian(text):
    markers = [
        " il ", " la ", " le ", " gli ", " della ", " del ",
        " non ", " per ", " con ", " una ", " sono ",
        "ciao", "grazie", "come", "dove", "quando", "cosa",
        "riguardo", "pausa", "programma", "orari", "sede",
    ]
    lower = " " + text.lower() + " "
    return sum(1 for m in markers if m in lower) >= 2


def detect_track(text):
    clean = text.strip().lower()
    valid = {
        "1": "1", "2": "2", "3": "3",
        "track 1": "1", "track 2": "2", "track 3": "3",
        "track1": "1", "track2": "2", "track3": "3",
    }
    return valid.get(clean)


def build_preamble(language, track=None):
    lang_instr = "Respond in Italian." if language == "it" else "Respond in English."

    track_instr = ""
    if track:
        track_instr = (
            f"The user is interested in Track {track}: {TRACKS[track]}. "
            f"Prioritize documents whose filename starts with track{track}_. "
        )

    return (
        "You are the official assistant of the VISION_E conference on AI in "
        "architecture, design, heritage conservation and education, held on "
        "June 5th 2026 at Castello del Valentino, Turin. "
        "Answer questions as completely and helpfully as possible using the "
        "provided conference documents. "
        "The available documents are: "
        "ConferenceDay.pdf (full schedule, timetable, coffee breaks, lunch, "
        "venue, cronoprogram), "
        "ScientificCommittee.pdf (scientific committee members and affiliations), "
        "OrganizingCommittee.pdf (organizing committee members), "
        "Logistics.pdf (venue address, social dinner at Al Pero, contact email), "
        "track1_*.pdf (academic papers for Track 1 — AI for Representation and Design), "
        "track2_*.pdf (academic papers for Track 2 — AI for Heritage Conservation), "
        "track3_*.pdf (academic papers for Track 3 — AI for Education and Learning). "
        "When listing papers always include title and authors. "
        "When asked about schedule or timing provide the full timetable. "
        "Synthesize information naturally across documents when relevant. "
        "If information is genuinely not in the documents, say so briefly. "
        f"{track_instr}"
        f"{lang_instr}"
    )


def ask_vertex(query, track=None, language="en"):
    token = gcp_token()

    # Enrich short queries (≤3 words) with conference context
    words = query.strip().split()
    if len(words) <= 3:
        query = f"Tell me about {query} in the context of the VISION_E conference contributions and papers"

    # Detect list-papers intent and make it explicit
    list_triggers = [
        "list all papers", "list papers", "all papers", "all contributions",
        "papers in track", "contributions in track", "papers and authors",
        "elenca i paper", "elenca i contributi", "tutti i paper",
    ]
    lower_q = query.lower()
    if any(t in lower_q for t in list_triggers):
        if track:
            query = (
                f"What are all the papers and their authors in Track {track} "
                f"({TRACKS[track]}) of the VISION_E conference? "
                f"List each paper title and author."
            )
        else:
            query = (
                "What are all the papers and their authors at the VISION_E conference? "
                "List each paper title and author grouped by track."
            )

    preamble = build_preamble(language, track)

    payload = {
        "query": {"text": query},
        "answerGenerationSpec": {
            "includeCitations": False,
            "ignoreAdversarialQuery": True,
            "ignoreNonAnswerSeekingQuery": False,
            "ignoreLowRelevantContent": False,
            "modelSpec": {"modelVersion": "stable"},
            "promptSpec": {"preamble": preamble},
        },
        "relatedQuestionsSpec": {"enable": False},
    }

    resp = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )

    if resp.status_code != 200:
        raise Exception(f"Vertex API Error {resp.status_code}: {resp.text}")

    data = resp.json()
    answer = data.get("answer", {}).get("answerText", "").strip()
    return answer


@app.route("/", methods=["GET"])
def index():
    return send_from_directory("static", "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/chat", methods=["POST"])
def chat():
    data       = request.get_json(silent=True) or {}
    message    = data.get("message", "").strip()
    session_id = data.get("session_id", "default")
    ui_track   = data.get("track")

    if not message:
        return jsonify({"error": "empty_message"}), 400

    session  = get_session(session_id)
    language = "it" if is_italian(message) else "en"

    # UI track always wins
    if ui_track in ("1", "2", "3"):
        session["track"] = ui_track

    # Typed track command
    detected = detect_track(message)
    if detected:
        session["track"] = detected
        name  = TRACKS[detected]
        reply = (
            f"Track {detected} selezionato: **{name}**."
            if language == "it"
            else f"Track {detected} selected: **{name}**."
        )
        return jsonify({"answer": reply, "track": detected, "language": language})

    try:
        answer = ask_vertex(
            query=message,
            track=session.get("track"),
            language=language,
        )
    except Exception as e:
        app.logger.error(f"Vertex error: {e}")
        answer = None

    if not answer:
        reply = (
            "Non ho trovato informazioni rilevanti nei documenti della conferenza. Prova a riformulare."
            if language == "it"
            else "I couldn't find relevant information in the conference documents. Try rephrasing."
        )
    else:
        reply = answer

    session["history"].append({"user": message, "assistant": reply})
    session["history"] = session["history"][-MAX_HISTORY:]

    return jsonify({
        "answer": reply,
        "track": session.get("track"),
        "language": language,
    })


@app.route("/chat/reset", methods=["POST"])
def reset_chat():
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    if session_id in sessions:
        del sessions[session_id]
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
