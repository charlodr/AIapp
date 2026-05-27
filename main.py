import os
import re
import requests
from flask import Flask, request, jsonify, send_from_directory
from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__, static_folder="static")

# ── Configuration ──────────────────────────────────────────────────────────────
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

# ── State ──────────────────────────────────────────────────────────────────────
sessions = {}  # { session_id: { "track": str|None, "history": list } }
MAX_HISTORY = 5


def get_session(sid):
    if sid not in sessions:
        sessions[sid] = {"track": None, "history": []}
    return sessions[sid]


# ── Auth ───────────────────────────────────────────────────────────────────────
def gcp_token():
    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


# ── Language detection ─────────────────────────────────────────────────────────
def is_italian(text):
    markers = [" il ", " la ", " le ", " gli ", " del ", " della ", " che ",
               " non ", " per ", " con ", " una ", " sono ", "ciao", "grazie",
               "dove", "quando", "come", "cosa", "quale", "riguardo", "pausa"]
    lower = " " + text.lower() + " "
    return sum(1 for m in markers if m in lower) >= 2


# ── Track selection detection ──────────────────────────────────────────────────
def detect_track(text):
    clean = text.strip().lower()
    if clean in ("1", "2", "3", "track 1", "track 2", "track 3",
                 "track1", "track2", "track3"):
        return clean[-1]
    return None


# ── Vertex AI call ─────────────────────────────────────────────────────────────
def ask_vertex(query, history, preamble):
    token = gcp_token()

    turns = [
        {
            "userInput": {"query": {"text": t["user"]}},
            "reply": {"summary": {"summaryText": t["assistant"]}}
        }
        for t in history[-MAX_HISTORY:]
    ]

    payload = {
        "query": {"text": query},
        "answerGenerationSpec": {
            "modelSpec": {"modelVersion": "stable"},
            "promptSpec": {"preamble": preamble},
            "includeCitations": True,
            "answerLanguageCode": "en",
        },
        "searchSpec": {
            "searchParams": {
                "maxReturnResults": 10,
                "filter": "",
            }
        }
    }
    if turns:
        payload["conversationContext"] = {"queryHistory": turns}

    resp = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    answer = data.get("answer", {}).get("answerText", "").strip()

    # Detect source track
    source_track = None
    for ref in data.get("answer", {}).get("references", []):
        uri = ref.get("unstructuredDocumentInfo", {}).get("uri", "")
        for t in ("1", "2", "3"):
            if f"track{t}" in uri:
                source_track = t
                break
        if source_track:
            break

    return answer or None, source_track


# ── Build preamble ─────────────────────────────────────────────────────────────
def build_preamble(language, track, contribution_ref):
    lang_instruction = "Respond in Italian." if language == "it" else "Respond in English."

    track_ctx = ""
    if track:
        track_ctx = (
            f"The user is interested in Track {track}: {TRACKS[track]}. "
            f"Prioritize documents whose filename starts with 'track{track}_'. "
        )

    contrib_ctx = ""
    if contribution_ref:
        contrib_ctx = f"Focus on the contribution related to: '{contribution_ref}'. "

    return (
        "You are the official assistant for the VISION_E conference on AI in architecture, "
        "design, heritage conservation and education, held on June 5th 2026 at Castello del "
        "Valentino, Turin. "
        "Answer questions as completely and helpfully as possible using the provided documents. "
        "The documents available are: "
        "ConferenceDay.pdf (full schedule, timetable, coffee breaks, lunch, venue, logistics), "
        "ScientificCommittee.pdf (scientific committee members and affiliations), "
        "OrganizingCommittee.pdf (organizing committee members), "
        "Logistics.pdf (venue address, social dinner at Al Pero, contact email), "
        "track1_*.pdf files (academic papers for Track 1), "
        "track2_*.pdf files (academic papers for Track 2), "
        "track3_*.pdf files (academic papers for Track 3). "
        f"{track_ctx}"
        f"{contrib_ctx}"
        "When listing papers, always include the title and authors. "
        "When asked about schedule or timing, provide the full timetable from ConferenceDay.pdf. "
        "If information is genuinely not available in any document, say so briefly. "
        f"{lang_instruction}"
    )


# ── Contribution reference detection ──────────────────────────────────────────
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


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return send_from_directory("static", "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/chat", methods=["POST"])
def chat():
    data     = request.get_json(silent=True) or {}
    message  = data.get("message", "").strip()
    sid      = data.get("session_id", "default")
    track_ui = data.get("track")  # track selected in UI

    if not message:
        return jsonify({"error": "empty"}), 400

    session  = get_session(sid)
    language = "it" if is_italian(message) else "en"

    # Track selection from UI always wins
    if track_ui in ("1", "2", "3"):
        session["track"] = track_ui
    # Track selection from typed message
    sel = detect_track(message)
    if sel:
        session["track"] = sel
        name = TRACKS[sel]
        reply = (
            f"Track {sel} selezionato: **{name}**. Chiedimi dei contributi, autori o argomenti."
            if language == "it" else
            f"Track {sel} selected: **{name}**. Ask me about the papers, authors or topics."
        )
        return jsonify({"answer": reply, "track": sel, "language": language})

    contrib_ref = detect_contribution(message)
    preamble    = build_preamble(language, session["track"], contrib_ref)

    # Normalize query: lowercase, strip trailing punctuation
    import string
    query = message.strip().rstrip(string.punctuation + " ").lower()
    # Common Italian→English terms
    it_en = {
        "pausa caff\u00e8": "coffee break", "pausa caffe": "coffee break",
        "caff\u00e8": "coffee", "pranzo": "lunch", "pausa pranzo": "lunch break",
        "sede": "venue location", "programma": "schedule programme",
        "orari": "schedule timetable", "relatori": "speakers",
        "contributi": "contributions papers", "comitato scientifico": "scientific committee",
        "comitato organizzativo": "organizing committee", "cena": "social dinner",
        "dove": "where location", "quando": "when time",
    }
    for it, en in it_en.items():
        if it in query:
            query = query.replace(it, en)

    try:
        answer, source_track = ask_vertex(query, session["history"], preamble)
    except Exception as e:
        app.logger.error(f"Vertex error: {e}")
        answer, source_track = None, None

    if not answer:
        reply = (
            "Non ho trovato questa informazione nei documenti. Prova a riformulare."
            if language == "it" else
            "I couldn't find that in the conference documents. Try rephrasing your question."
        )
    else:
        # Update track from source if not set
        if source_track and not session["track"]:
            session["track"] = source_track
        reply = answer

    session["history"].append({"user": message, "assistant": reply})
    session["history"] = session["history"][-MAX_HISTORY:]

    return jsonify({
        "answer": reply,
        "track": session["track"],
        "language": language,
    })


@app.route("/chat/reset", methods=["POST"])
def chat_reset():
    data = request.get_json(silent=True) or {}
    sid  = data.get("session_id", "default")
    if sid in sessions:
        del sessions[sid]
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
