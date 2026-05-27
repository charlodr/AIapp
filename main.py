import os
import re
import string
import requests

from flask import Flask, request, jsonify, send_from_directory

from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__, static_folder="static")

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
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

# IMPORTANT FIX FOR GLOBAL DATASTORE
if GCP_LOCATION == "global":
    api_host = "discoveryengine.googleapis.com"
else:
    api_host = f"{GCP_LOCATION}-discoveryengine.googleapis.com"

ENDPOINT = (
    f"https://{api_host}/v1/projects/"
    f"{GCP_PROJECT_ID}/locations/{GCP_LOCATION}/collections/default_collection/"
    f"dataStores/{DATASTORE_ID}/servingConfigs/default_search:answer"
)

TRACKS = {
    "1": "AI for Representation and Design",
    "2": "AI for Heritage Conservation and Enhancement",
    "3": "AI for Education and Learning",
}

# ─────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────

sessions = {}

MAX_HISTORY = 5


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
# LANGUAGE DETECTION
# ─────────────────────────────────────────────────────────────

def is_italian(text):

    markers = [
        " il ", " la ", " le ", " gli ",
        " del ", " della ", " che ",
        " non ", " per ", " con ",
        " una ", " sono ",
        "ciao", "grazie",
        "dove", "quando", "come",
        "cosa", "quale",
        "riguardo", "pausa"
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
# CONTRIBUTION DETECTION
# ─────────────────────────────────────────────────────────────

def detect_contribution(text):

    patterns = [
        r"(?:about|regarding|on)\s+(?:the\s+)?(?:contribution|paper|talk|work)\s+(?:by|from|of)\s+(.+)",
        r"(?:contribution|paper)\s+(?:by|from)\s+(.+)",
        r"(?:riguardo|parlami|dimmi)\s+(?:al\s+)?(?:contributo|paper)\s+(?:di|del)\s+(.+)",
        r"(?:contributo|paper)\s+(?:di|del)\s+(.+)",
    ]

    for p in patterns:

        m = re.search(p, text.lower())

        if m:
            return m.group(1).strip()

    return None


# ─────────────────────────────────────────────────────────────
# PREAMBLE
# ─────────────────────────────────────────────────────────────

def build_preamble(language, track=None, contribution_ref=None):

    lang_instruction = (
        "Respond in Italian."
        if language == "it"
        else "Respond in English."
    )

    track_instruction = ""

    if track:

        track_instruction = (
            f"The user is interested in Track {track}: "
            f"{TRACKS[track]}. "
            f"Prioritize documents whose filename "
            f"contains 'track{track}'. "
        )

    contribution_instruction = ""

    if contribution_ref:

        contribution_instruction = (
            f"Focus on the contribution related to "
            f"'{contribution_ref}'. "
        )

    return (
        "You are the official assistant for the "
        "VISION_E conference on AI in architecture, "
        "representation, heritage conservation, "
        "design and education. "

        "Answer questions ONLY using the indexed "
        "conference documents. "

        "The available documents include: "

        "ConferenceDay.pdf "
        "(schedule, coffee breaks, venue, logistics), "

        "ScientificCommittee.pdf, "

        "OrganizingCommittee.pdf, "

        "Logistics.pdf, "

        "track1_*.pdf papers, "

        "track2_*.pdf papers, "

        "track3_*.pdf papers. "

        f"{track_instruction}"
        f"{contribution_instruction}"

        "When listing papers always include "
        "title and authors if available. "

        "If the information is not available "
        "inside the conference documents, "
        "say so briefly. "

        f"{lang_instruction}"
    )


# ─────────────────────────────────────────────────────────────
# VERTEX AI SEARCH
# ─────────────────────────────────────────────────────────────

def ask_vertex(query, history, preamble, track=None):

    token = gcp_token()

    turns = [
        {
            "userInput": {
                "query": {
                    "text": t["user"]
                }
            },
            "reply": {
                "summary": {
                    "summaryText": t["assistant"]
                }
            }
        }
        for t in history[-MAX_HISTORY:]
    ]

    filter_expr = ""

    if track:
        filter_expr = f'uri: ANY("track{track}")'

    payload = {

        "query": {
            "text": query
        },

        "relatedQuestionsSpec": {
            "enable": False
        },

        "answerGenerationSpec": {

            "ignoreAdversarialQuery": True,
            "ignoreNonAnswerSeekingQuery": False,
            "ignoreLowRelevantContent": False,

            "modelSpec": {
                "modelVersion": "stable"
            },

            "promptSpec": {
                "preamble": preamble
            },

            "includeCitations": True,
            "answerLanguageCode": "en",
        },

        "searchSpec": {
            "searchResultMode": "DOCUMENTS"
        }
    }

    if filter_expr:
        payload["searchSpec"]["filter"] = filter_expr

    if turns:

        payload["conversationContext"] = {
            "queryHistory": turns
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

    answer_obj = data.get("answer", {})

    answer = answer_obj.get(
        "answerText",
        ""
    ).strip()

    refs = answer_obj.get(
        "references",
        []
    )

    source_track = None

    for ref in refs:

        uri = ref.get(
            "unstructuredDocumentInfo",
            {}
        ).get(
            "uri",
            ""
        )

        for t in ("1", "2", "3"):

            if f"track{t}" in uri:
                source_track = t
                break

        if source_track:
            break

    # Fallback from refs
    if not answer and refs:

        titles = []

        for ref in refs[:5]:

            info = ref.get(
                "unstructuredDocumentInfo",
                {}
            )

            title = (
                info.get("title")
                or info.get("uri", "")
                .split("/")[-1]
                .replace("_", " ")
                .replace(".pdf", "")
            )

            chunk = ""

            chunks = info.get(
                "chunkContents",
                []
            )

            if chunks:
                chunk = chunks[0].get(
                    "content",
                    ""
                )

            if title:

                if chunk:

                    titles.append(
                        f"- **{title}**: {chunk[:180]}..."
                    )

                else:

                    titles.append(
                        f"- **{title}**"
                    )

        if titles:

            answer = (
                "Based on the conference documents, "
                "relevant contributions include:\n\n"
                + "\n".join(titles)
            )

    return answer or None, source_track


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

    # UI selection wins
    if ui_track in ("1", "2", "3"):
        session["track"] = ui_track

    # Typed selection
    detected_track = detect_track(message)

    if detected_track:

        session["track"] = detected_track

        track_name = TRACKS[detected_track]

        reply = (
            f"Track {detected_track} selezionato: "
            f"{track_name}."
            if language == "it"
            else
            f"Track {detected_track} selected: "
            f"{track_name}."
        )

        return jsonify({
            "answer": reply,
            "track": detected_track,
            "language": language,
        })

    contribution_ref = detect_contribution(message)

    preamble = build_preamble(
        language=language,
        track=session.get("track"),
        contribution_ref=contribution_ref,
    )

    query = message.strip().rstrip(
        string.punctuation + " "
    ).lower()

    # Expand short queries
    if len(query) <= 5 and not any(c.isspace() for c in query):

        query = (
            f"conference papers and contributions about {query}"
        )

    # Italian → English semantic normalization
    it_en = {
        "pausa caffè": "coffee break",
        "pausa caffe": "coffee break",
        "pranzo": "lunch",
        "programma": "conference schedule",
        "orari": "conference timetable",
        "sede": "venue location",
        "contributi": "conference papers",
        "relatori": "speakers",
        "comitato scientifico": "scientific committee",
        "comitato organizzativo": "organizing committee",
        "cena": "social dinner",
    }

    for it, en in it_en.items():

        if it in query:
            query = query.replace(it, en)

    try:

        answer, source_track = ask_vertex(
            query=query,
            history=session["history"],
            preamble=preamble,
            track=session.get("track"),
        )

    except Exception as e:

        app.logger.error(f"Vertex error: {e}")

        answer = None
        source_track = None

    if not answer:

        reply = (
            "Non ho trovato informazioni rilevanti "
            "nei documenti della conferenza. "
            "Prova a riformulare."
            if language == "it"
            else
            "I couldn't find relevant information "
            "in the conference documents. "
            "Try rephrasing your question."
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
