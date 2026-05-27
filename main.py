import os
import re
import string
import requests

from flask import Flask, request, jsonify, send_from_directory

from google.auth import default
from google.auth.transport.requests import Request

import google.generativeai as genai

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
# GEMINI
# ─────────────────────────────────────────────────────────────

genai.configure()

gemini_model = genai.GenerativeModel(
    "gemini-2.5-flash"
)

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
# COMPLEX QUERY DETECTION
# ─────────────────────────────────────────────────────────────

def is_complex_query(query):

    q = query.lower()

    complex_markers = [

        "compare",
        "differences",
        "similarities",
        "relationship",
        "connections",
        "trends",
        "themes",
        "summarize",
        "overview",
        "ethical",
        "philosophical",
        "methodologies",
        "specific approach",
        "specific methodology",
        "across papers",
        "state of the art",
        "which one",
        "how does",

        "confronta",
        "differenze",
        "somiglianze",
        "trend",
        "temi",
        "riassumi",
        "panoramica",
        "metodologie",
        "quale",
        "quale approccio",
    ]

    if len(q.split()) > 9:
        return True

    return any(m in q for m in complex_markers)

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
# TITLE EXTRACTION
# ─────────────────────────────────────────────────────────────

def extract_title(raw_title, snippet):

    bad_patterns = [
        "anonymous",
        "text",
        "conference",
        "track 1",
        "track 2",
        "track 3",
        "visione",
        "minor revisions",
    ]

    if raw_title:

        title = raw_title

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

        lower = title.lower()

        if not any(b in lower for b in bad_patterns):

            if len(title.split()) >= 4:
                return title

    if snippet:

        lines = re.split(r"[.!?\n]", snippet)

        for line in lines:

            line = line.strip()

            if len(line.split()) < 5:
                continue

            if len(line) > 180:
                continue

            lower = line.lower()

            if any(b in lower for b in bad_patterns):
                continue

            if re.search(r"\b(ai|llm|bim|design|heritage|learning)\b", lower):

                return line

    return None

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

    noise = [
        "VISIONE Conference June",
        "Track 1:",
        "Track 2:",
        "Track 3:",
        "Salone d'Onore",
        "minor revisions implemented",
        "∀ISION_E – Drawing a Vision",
    ]

    for n in noise:
        text = text.replace(n, "")

    text = text.strip()

    if len(text) > 280:
        text = text[:280] + "..."

    return text

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
# LOCAL SYNTHESIS
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
        "The most relevant conference contributions related to your query are:"
        if language == "en"
        else
        "I contributi più rilevanti rispetto alla tua richiesta sono:"
    )

    body = []

    for d in docs[:4]:

        text = (
            f"• {d['title']}\n"
            f"{d['snippet']}"
        )

        body.append(text)

    return (
        intro
        + "\n\n"
        + "\n\n".join(body)
    )

# ─────────────────────────────────────────────────────────────
# GEMINI SYNTHESIS
# ─────────────────────────────────────────────────────────────

def gemini_synthesis(query, docs, language="en"):

    context = []

    for d in docs:

        context.append(
            f"TITLE: {d['title']}\n"
            f"CONTENT: {d['snippet']}"
        )

    context_text = "\n\n".join(context)

    lang_instruction = (
        "Respond in Italian."
        if language == "it"
        else "Respond in English."
    )

    prompt = f"""
You are the official assistant of the VISIONE conference.

Use ONLY the conference material below.

User query:
{query}

Conference material:
{context_text}

Instructions:
- Answer naturally.
- Mention the most relevant paper.
- Explain WHY it is relevant.
- Compare approaches if useful.
- Avoid raw snippet dumps.
- Avoid listing filenames.
- Avoid hallucinations.
- Keep answer concise and elegant.

{lang_instruction}
"""

    response = gemini_model.generate_content(
        prompt
    )

    return response.text.strip()

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
            or ""
        )

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

        title = extract_title(
            raw_title,
            snippet
        )

        if not title:
            continue

        if title.lower() in seen_titles:
            continue

        seen_titles.add(title.lower())

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

    if is_complex_query(query):

        try:

            answer = gemini_synthesis(
                query=query,
                docs=docs,
                language=language
            )

        except Exception as e:

            app.logger.error(
                f"Gemini synthesis error: {e}"
            )

            answer = synthesize(
                query=query,
                docs=docs,
                language=language
            )

    else:

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
