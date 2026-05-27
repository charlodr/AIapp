import os
import re
import string
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

if GCP_LOCATION == "global":
    api_host = "discoveryengine.googleapis.com"
else:
    api_host = f"{GCP_LOCATION}-discoveryengine.googleapis.com"

ENDPOINT = (
    f"https://{api_host}/v1/projects/"
    f"{GCP_PROJECT_ID}/locations/{GCP_LOCATION}/collections/default_collection/"
    f"dataStores/{DATASTORE_ID}/servingConfigs/default_search:search"
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
        " del ", " della ", " che ",
        " non ", " per ", " con ",
        " una ", " sono ",
        "ciao", "grazie",
        "dove", "quando", "come",
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
# TITLE CLEANING
# ─────────────────────────────────────────────────────────────

def clean_title(raw):

    if not raw:
        return None

    title = raw

    title = re.sub(
        r"^track[123]",
        "",
        title,
        flags=re.IGNORECASE
    )

    title = re.sub(
        r"\.pdf$",
        "",
        title,
        flags=re.IGNORECASE
    )

    title = re.sub(
        r"[_\-]+",
        " ",
        title
    )

    title = re.sub(
        r"([a-z])([A-Z])",
        r"\1 \2",
        title
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    title = title.strip()

    if title.lower() in [
        "anonymous",
        "(anonymous)"
    ]:
        return None

    return title


# ─────────────────────────────────────────────────────────────
# SNIPPET CLEANING
# ─────────────────────────────────────────────────────────────

def clean_snippet(text):

    if not text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    text = text.strip()

    # Remove conference noise
    noise = [
        "VISIONE Conference June",
        "Track 1:",
        "Track 2:",
        "Track 3:",
        "Salone d'Onore",
    ]

    for n in noise:
        text = text.replace(n, "")

    if len(text) > 260:
        text = text[:260] + "..."

    return text.strip()


# ─────────────────────────────────────────────────────────────
# QUERY EXPANSION
# ─────────────────────────────────────────────────────────────

def normalize_query(query):

    q = query.lower()

    mapping = {

        "llm": (
            "large language models "
            "architectural design BIM AI"
        ),

        "hbim": (
            "HBIM heritage BIM conservation"
        ),

        "vr": (
            "virtual reality immersive learning"
        ),

        "ai": (
            "artificial intelligence design"
        ),

        "education": (
            "education learning pedagogy AI"
        ),

        "representation": (
            "architectural representation AI"
        ),
    }

    for k, v in mapping.items():

        if q.strip() == k:
            return v

    return q


# ─────────────────────────────────────────────────────────────
# SYNTHESIS
# ─────────────────────────────────────────────────────────────

def synthesize(query, docs, language="en"):

    if not docs:

        return (
            "Non ho trovato risultati rilevanti."
            if language == "it"
            else
            "I couldn't find relevant results."
        )

    intro = (
        "The conference includes several relevant contributions related to your query."
        if language == "en"
        else
        "La conferenza include diversi contributi rilevanti rispetto alla tua richiesta."
    )

    body = []

    for d in docs[:4]:

        title = d["title"]

        snippet = d["snippet"]

        text = (
            f"• {title}\n{snippet}"
        )

        body.append(text)

    outro = (
        "\n\nThese papers explore different perspectives on AI-assisted design, representation and digital cultural heritage."
        if language == "en"
        else
        "\n\nQuesti contributi esplorano differenti prospettive sull'AI applicata al design, alla rappresentazione e al patrimonio culturale digitale."
    )

    return (
        intro
        + "\n\n"
        + "\n\n".join(body)
        + outro
    )


# ─────────────────────────────────────────────────────────────
# VERTEX SEARCH
# ─────────────────────────────────────────────────────────────

def ask_vertex(query, track=None, language="en"):

    token = gcp_token()

    query = normalize_query(query)

    payload = {
        "query": query,
        "pageSize": 10,

        "contentSearchSpec": {

            "snippetSpec": {
                "returnSnippet": True
            }
        }
    }

    response = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    results = data.get("results", [])

    if not results:
        return None, None

    docs = []

    seen_titles = set()

    source_track = None

    for r in results:

        doc = r.get("document", {})

        derived = doc.get(
            "derivedStructData",
            {}
        )

        raw_title = (
            derived.get("title")
            or doc.get("id")
            or "Untitled"
        )

        title = clean_title(raw_title)

        if not title:
            continue

        if title.lower() in seen_titles:
            continue

        seen_titles.add(title.lower())

        snippets = derived.get(
            "snippets",
            []
        )

        snippet = ""

        if snippets:

            snippet = snippets[0].get(
                "snippet",
                ""
            )

        snippet = clean_snippet(snippet)

        if not snippet:
            continue

        docs.append({
            "title": title,
            "snippet": snippet
        })

        uri = derived.get(
            "link",
            ""
        )

        for t in ("1", "2", "3"):

            if f"track{t}" in uri.lower():
                source_track = t

    if not docs:
        return None, None

    answer = synthesize(
        query=query,
        docs=docs,
        language=language
    )

    return answer, source_track


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

    if ui_track in ("1", "2", "3"):
        session["track"] = ui_track

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

    try:

        answer, source_track = ask_vertex(
            query=message,
            track=session.get("track"),
            language=language
        )

    except Exception as e:

        app.logger.error(f"Vertex error: {e}")

        answer = None
        source_track = None

    if not answer:

        reply = (
            "Non ho trovato informazioni rilevanti nei documenti della conferenza."
            if language == "it"
            else
            "I couldn't find relevant information in the conference documents."
        )

    else:

        if source_track and not session["track"]:
            session["track"] = source_track

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
