# Revised `main.py` — Optimized Conference Bot (Vertex AI Search + Flask)

```python
import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__, static_folder="static")

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "chatbot-visione")
GCP_LOCATION   = os.environ.get("GCP_LOCATION", "eu")
DATASTORE_ID   = os.environ.get("DATASTORE_ID", "atlascardone_1773418764471")

ENDPOINT = (
    f"https://{GCP_LOCATION}-discoveryengine.googleapis.com/v1alpha/projects/"
    f"{GCP_PROJECT_ID}/locations/{GCP_LOCATION}/collections/default_collection/"
    f"dataStores/{DATASTORE_ID}/servingConfigs/default_search:answer"
)

TRACKS = {
    "1": "AI for Representation and Design",
    "2": "AI for Heritage Conservation and Enhancement",
    "3": "AI for Education and Learning",
}

# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────

sessions = {}


def get_session(session_id):
    if session_id not in sessions:
        sessions[session_id] = {
            "track": None,
        }
    return sessions[session_id]


# ──────────────────────────────────────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────────────────────────────────────


def gcp_token():
    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


# ──────────────────────────────────────────────────────────────────────────────
# LANGUAGE DETECTION
# ──────────────────────────────────────────────────────────────────────────────


def is_italian(text):
    markers = [
        " il ", " la ", " le ", " gli ", " del ", " della ",
        " che ", " non ", " per ", " con ", " una ",
        "ciao", "grazie", "dove", "quando", "come", "cosa",
    ]

    lower = " " + text.lower() + " "

    return sum(1 for m in markers if m in lower) >= 2


# ──────────────────────────────────────────────────────────────────────────────
# TRACK DETECTION
# ──────────────────────────────────────────────────────────────────────────────


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


# ──────────────────────────────────────────────────────────────────────────────
# PREAMBLE
# ──────────────────────────────────────────────────────────────────────────────


def build_preamble(language, track=None):

    lang_instruction = (
        "Respond in Italian."
        if language == "it"
        else "Respond in English."
    )

    track_instruction = ""

    if track:
        track_instruction = (
            f"The user is interested in Track {track}: {TRACKS[track]}. "
            f"Prioritize documents whose filename starts with track{track}_. "
        )

    return (
        "You are the official assistant of the VISION_E conference. "
        "Answer using only the indexed conference documents. "
        "Be accurate, informative and concise. "
        "When mentioning papers, include title and authors when available. "
        "If information is unavailable in the documents, say so briefly. "
        f"{track_instruction}"
        f"{lang_instruction}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# VERTEX AI SEARCH
# ──────────────────────────────────────────────────────────────────────────────


def ask_vertex(query, preamble, track=None):

    token = gcp_token()

    filter_expr = ""

    # REAL TRACK FILTERING
    if track:
        filter_expr = f'uri: ANY("track{track}")'

    payload = {
        "query": {
            "text": query
        },

        "answerGenerationSpec": {
            "modelSpec": {
                "modelVersion": "stable"
            },

            "promptSpec": {
                "preamble": preamble
            },

            "includeCitations": True,

            # IMPORTANT:
            # Let language follow prompt naturally
            # instead of forcing English.
        },

        "searchSpec": {
            "searchParams": {
                "maxReturnResults": 8,
                "filter": filter_expr,
            }
        }
    }

    response = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    answer_obj = data.get("answer", {})

    answer_text = answer_obj.get("answerText", "").strip()

    references = answer_obj.get("references", [])

    citations = []

    for ref in references[:5]:

        info = ref.get("unstructuredDocumentInfo", {})

        title = (
            info.get("title")
            or info.get("uri", "")
            .split("/")[-1]
            .replace("_", " ")
            .replace(".pdf", "")
        )

        if title and title not in citations:
            citations.append(title)

    return {
        "answer": answer_text,
        "citations": citations,
    }


# ──────────────────────────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────────────────────────


@app.route("/", methods=["GET"])
def index():
    return send_from_directory("static", "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok"
    })


@app.route("/chat", methods=["POST"])
def chat():

    data = request.get_json(silent=True) or {}

    message = data.get("message", "").strip()

    session_id = data.get("session_id", "default")

    ui_track = data.get("track")

    if not message:
        return jsonify({
            "error": "empty_message"
        }), 400

    session = get_session(session_id)

    language = "it" if is_italian(message) else "en"

    # UI track selection has priority
    if ui_track in ("1", "2", "3"):
        session["track"] = ui_track

    # Detect explicit typed track selection
    detected_track = detect_track(message)

    if detected_track:

        session["track"] = detected_track

        track_name = TRACKS[detected_track]

        reply = (
            f"Track {detected_track} selezionato: {track_name}."
            if language == "it"
            else f"Track {detected_track} selected: {track_name}."
        )

        return jsonify({
            "answer": reply,
            "track": detected_track,
            "language": language,
        })

    # IMPORTANT:
    # Keep original user query untouched.
    query = message

    preamble = build_preamble(
        language=language,
        track=session.get("track"),
    )

    try:

        result = ask_vertex(
            query=query,
            preamble=preamble,
            track=session.get("track"),
        )

        answer = result.get("answer")
        citations = result.get("citations", [])

    except Exception as e:

        app.logger.error(f"Vertex error: {e}")

        return jsonify({
            "answer": (
                "Errore temporaneo del sistema."
                if language == "it"
                else "Temporary system error."
            )
        }), 500

    # Fallback if Vertex returns empty answer
    if not answer:

        answer = (
            "Non ho trovato informazioni rilevanti nei documenti della conferenza."
            if language == "it"
            else "I could not find relevant information in the conference documents."
        )

    return jsonify({
        "answer": answer,
        "citations": citations,
        "track": session.get("track"),
        "language": language,
    })


@app.route("/chat/reset", methods=["POST"])
def reset_chat():

    data = request.get_json(silent=True) or {}

    session_id = data.get("session_id", "default")

    if session_id in sessions:
        del sessions[session_id]

    return jsonify({
        "status": "reset"
    })


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
```

# Main Improvements Applied

## Fixed Problems

### Removed harmful query rewriting

The previous version altered user queries aggressively, degrading Vertex semantic retrieval.

### Removed manual Italian→English replacements

Those replacements were damaging retrieval quality and confusing the search engine.

### Removed conversation history pollution

Conversation history was likely contaminating retrieval relevance.

### Added REAL track filtering

The old version stored track state but did not truly filter datastore retrieval.

Now the bot actually filters by:

```python
uri: ANY("track1")
```

etc.

### Reduced prompt complexity

The old prompt was too verbose and over-constrained Vertex generation.

### Fixed language inconsistency

The old code forced:

```python
answerLanguageCode = "en"
```

while simultaneously asking for Italian responses.

Now language follows prompt naturally.

### Improved citations handling

Now citations are cleaner and less noisy.

---

# Expected Improvements

You should now get:

* much closer behaviour to native Vertex AI Search UI
* more accurate semantic retrieval
* better short-query handling (LLM, BIM, VR, etc.)
* better Track-specific answers
* less hallucination
* less irrelevant expansion
* cleaner multilingual behaviour
* more stable responses

---

# Deployment

After replacing `main.py`:

```bash
gcloud run deploy visione-conference-bot \
--source . \
--region europe-west8 \
--allow-unauthenticated
```

Then test again on:

```text
https://visione-conference-bot-fovnlhypea-oc.a.run.app
```
