import os
import requests

from flask import Flask, request, jsonify, send_from_directory

from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__, static_folder="static")

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

GCP_PROJECT_ID = os.environ.get(
    "GCP_PROJECT_ID",
    "chatbot-visione-497608"
)

GCP_LOCATION = os.environ.get(
    "GCP_LOCATION",
    "global"
)

DATASTORE_ID = os.environ.get(
    "DATASTORE_ID",
    "visionedatastore_1779872407393"
)

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

# ─────────────────────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────────────────────


def get_session(sid):

    if sid not in sessions:

        sessions[sid] = {
            "track": None,
            "history": []
        }

    return sessions[sid]


# ─────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────


def gcp_token():

    creds, _ = default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )

    creds.refresh(Request())

    return creds.token


# ─────────────────────────────────────────────────────────────
# LANGUAGE
# ─────────────────────────────────────────────────────────────


def is_italian(text):

    markers = [
        " il ", " la ", " le ", " gli ",
        " della ", " del ",
        " non ", " per ",
        "ciao", "grazie",
        "come", "dove",
    ]

    lower = " " + text.lower() + " "

    return sum(1 for m in markers if m in lower) >= 2


# ─────────────────────────────────────────────────────────────
# TRACK DETECTION
# ─────────────────────────────────────────────────────────────


def detect_track(text):

    clean = text.strip().lower()

    valid = {
        "1": "1",
        "2": "2",
        "3": "3",
        "track 1": "1",
        "track 2": "2",
        "track 3": "3",
        "track1": "1",
        "track2": "2",
        "track3": "3",
    }

    return valid.get(clean)


# ─────────────────────────────────────────────────────────────
# QUERY ENRICHMENT
# ─────────────────────────────────────────────────────────────


def enrich_query(query, track):

    if not track:
        return query

    track_name = TRACKS.get(track, "")

    return (
        f"{query}. "
        f"Focus specifically on papers from {track_name}."
    )


# ─────────────────────────────────────────────────────────────
# ANSWER API
# ─────────────────────────────────────────────────────────────


def ask_vertex(query, track=None, language="en"):

    token = gcp_token()

    enriched_query = enrich_query(query, track)

    if language == "it":

        preamble = """
Sei l'assistente ufficiale della conferenza VISIONE.

Rispondi in italiano.

Fornisci risposte accademiche naturali e ben scritte.

Quando possibile:
- sintetizza informazioni tra più paper,
- menziona i titoli dei paper in modo naturale,
- evita filename tecnici,
- evita dump di snippet,
- spiega relazioni concettuali.
"""

    else:

        preamble = """
You are the official assistant of the VISIONE conference.

Answer in English.

Provide academically professional and natural responses.

When possible:
- synthesize information across papers,
- mention paper titles naturally,
- avoid technical filenames,
- avoid snippet dumps,
- explain conceptual relationships.
"""

    payload = {
        "query": {
            "text": enriched_query
        },

        "answerGenerationSpec": {

            "includeCitations": False,

            "ignoreAdversarialQuery": True,

            "ignoreNonAnswerSeekingQuery": False,

            "ignoreLowRelevantContent": False,

            "modelSpec": {
                "modelVersion": "stable"
            },

            "promptSpec": {
                "preamble": preamble
            }
        },

        "relatedQuestionsSpec": {
            "enable": False
        }
    }

    response = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=60,
    )

    # DEBUG
    if response.status_code != 200:
        raise Exception(
            f"Vertex API Error {response.status_code}: {response.text}"
        )

    data = response.json()

    answer = (
        data.get("answer", {})
        .get("answerText", "")
        .strip()
    )

    return answer, track


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────


@app.route("/", methods=["GET"])
def index():

    return send_from_directory(
        "static",
        "index.html"
    )


@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "ok"
    })


@app.route("/chat", methods=["POST"])
def chat():

    data = request.get_json(
        silent=True
    ) or {}

    message = data.get(
        "message",
        ""
    ).strip()

    session_id = data.get(
        "session_id",
        "default"
    )

    ui_track = data.get("track")

    if not message:

        return jsonify({
            "error": "empty_message"
        }), 400

    session = get_session(session_id)

    language = (
        "it"
        if is_italian(message)
        else "en"
    )

    # TRACK FROM UI

    if ui_track in ("1", "2", "3"):
        session["track"] = ui_track

    # TRACK COMMAND

    detected_track = detect_track(message)

    if detected_track:

        session["track"] = detected_track

        track_name = TRACKS[detected_track]

        reply = (
            f"Track {detected_track} selezionato: {track_name}."
            if language == "it"
            else
            f"Track {detected_track} selected: {track_name}."
        )

        return jsonify({
            "answer": reply,
            "track": detected_track,
            "language": language,
        })

    # QUERY

    try:

        answer, source_track = ask_vertex(
            query=message,
            track=session.get("track"),
            language=language
        )

    except Exception as e:

        app.logger.error(f"Vertex answer error: {e}")

        answer = None

    if not answer:

        reply = (
            "Non ho trovato informazioni rilevanti nei documenti della conferenza."
            if language == "it"
            else
            "I couldn't find relevant information in the conference documents."
        )

    else:

        reply = answer

    session["history"].append({
        "user": message,
        "assistant": reply
    })

    session["history"] = session["history"][-MAX_HISTORY:]

    return jsonify({
        "answer": reply,
        "track": session.get("track"),
        "language": language,
    })


@app.route("/chat/reset", methods=["POST"])
def reset_chat():

    data = request.get_json(
        silent=True
    ) or {}

    session_id = data.get(
        "session_id",
        "default"
    )

    if session_id in sessions:
        del sessions[session_id]

    return jsonify({
        "status": "reset"
    })


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 8080)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
