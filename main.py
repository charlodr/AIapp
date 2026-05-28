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

# ─────────────────────────────────────────────────────────────
# STATIC LOGISTICS — answered directly without Vertex AI
# ─────────────────────────────────────────────────────────────

LOGISTICS = {
    "coffee_break": {
        "en": (
            "There are two coffee breaks during the conference:\n"
            "\u2022 First coffee break: **11:05 \u2013 11:35**\n"
            "\u2022 Second coffee break: **15:40 \u2013 16:10**"
        ),
        "it": (
            "Ci sono due pause caff\u00e8 durante la conferenza:\n"
            "\u2022 Prima pausa caff\u00e8: **11:05 \u2013 11:35**\n"
            "\u2022 Seconda pausa caff\u00e8: **15:40 \u2013 16:10**"
        ),
    },
    "lunch": {
        "en": "**Light lunch** is served from **13:00 to 14:00**.",
        "it": "Il **pranzo leggero** \u00e8 servito dalle **13:00 alle 14:00**.",
    },
    "social_dinner": {
        "en": (
            "The informal social dinner takes place on the evening of June 5th at\n"
            "**Al Pero \u2013 Imbarco sul Po**\n"
            "Located just behind Castello del Valentino, with a view over the Po River. "
            "Within easy walking distance from the venue.\n"
            "Website: imbarcoalpero.com\n"
            "For info: visioneuid@gmail.com"
        ),
        "it": (
            "La cena sociale informale si svolge la sera del 5 giugno presso\n"
            "**Al Pero \u2013 Imbarco sul Po**\n"
            "Si trova appena dietro il Castello del Valentino, con vista sul Po. "
            "A pochi minuti a piedi dalla sede.\n"
            "Website: imbarcoalpero.com\n"
            "Per info: visioneuid@gmail.com"
        ),
    },
    "venue": {
        "en": (
            "**Salone d'Onore (Great Salon), Castello del Valentino**\n"
            "Department of Architecture and Design, Politecnico di Torino\n"
            "Viale Mattioli 39, 10125 Turin, Italy\n"
            "Website: castellodelvalentino.polito.it\n\n"
            "**How to reach the venue:**\n"
            "\u2022 By metro: Line 1, station Dante or Re Umberto\n"
            "\u2022 By tram: Lines 9, 16 \u2014 stop Valentino\n"
            "\u2022 By taxi: ask for Viale Mattioli 39, Castello del Valentino"
        ),
        "it": (
            "**Salone d'Onore, Castello del Valentino**\n"
            "Dipartimento di Architettura e Design, Politecnico di Torino\n"
            "Viale Mattioli 39, 10125 Torino\n"
            "Website: castellodelvalentino.polito.it\n\n"
            "**Come raggiungere la sede:**\n"
            "\u2022 Metro: Linea 1, fermata Dante o Re Umberto\n"
            "\u2022 Tram: Linee 9, 16 \u2014 fermata Valentino\n"
            "\u2022 Taxi: Viale Mattioli 39, Castello del Valentino"
        ),
    },
    "contact": {
        "en": "For any questions contact the Organizing Committee: **visioneuid@gmail.com**",
        "it": "Per qualsiasi domanda contatta il Comitato Organizzativo: **visioneuid@gmail.com**",
    },
    "registration": {
        "en": "Registration is from **08:30 to 09:00**.",
        "it": "La registrazione \u00e8 dalle **08:30 alle 09:00**.",
    },
    "opening": {
        "en": "The conference opening ceremony is at **09:00**.",
        "it": "La cerimonia di apertura della conferenza \u00e8 alle **09:00**.",
    },
    "awards": {
        "en": "**Best Paper Awards** ceremony is at **18:15**, followed by closing remarks at **18:20**.",
        "it": "La cerimonia **Best Paper Awards** \u00e8 alle **18:15**, seguita dalle conclusioni alle **18:20**.",
    },
    "round_table": {
        "en": "The **Final Round Table** is from **17:15 to 18:15**.",
        "it": "La **tavola rotonda finale** \u00e8 dalle **17:15 alle 18:15**.",
    },
}

LOGISTICS_TRIGGERS = {
    "coffee_break": [
        "coffee break", "coffee", "coffe break", "coffe", "caff",
        "pausa caff", "break time", "coffee time",
    ],
    "lunch": [
        "lunch", "pranzo", "light lunch", "pausa pranzo", "lunch break",
    ],
    "social_dinner": [
        "social dinner", "dinner", "cena", "al pero", "imbarco",
        "evening", "serata",
    ],
    "venue": [
        "venue", "location", "address", "where", "sede", "indirizzo",
        "dove si tiene", "castello", "valentino", "viale mattioli",
        "how to get", "come arrivare", "dove",
    ],
    "contact": [
        "contact", "email", "contatto", "contattare", "write to",
        "get in touch",
    ],
    "registration": [
        "registration", "registrazione", "sign in", "check in",
        "when do i register",
    ],
    "opening": [
        "opening", "apertura", "when does it start", "what time start",
        "quando inizia", "start time",
    ],
    "awards": [
        "award", "premio", "best paper", "closing", "chiusura",
    ],
    "round_table": [
        "round table", "tavola rotonda", "roundtable",
    ],
}


def check_logistics(text, language):
    """Return static answer if query matches a logistics topic."""
    lower = text.lower().strip()
    for key, triggers in LOGISTICS_TRIGGERS.items():
        if any(t in lower for t in triggers):
            return LOGISTICS[key][language]
    return None




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
        "Answer using only the indexed conference documents. "
        "The available documents are: "
        "ConferenceDay.pdf (the conference programme and cronoprogram — NOT an academic paper; use it for session times, keynote slots, track session schedules and timing of presentations), "
        "ScientificCommittee.pdf (scientific committee members and affiliations), "
        "OrganizingCommittee.pdf (organizing committee members), "
        "Logistics.pdf (venue address, social dinner at Al Pero, contact email), "
        "track1_*.pdf (academic papers for Track 1), "
        "track2_*.pdf (academic papers for Track 2), "
        "track3_*.pdf (academic papers for Track 3). "
        "IMPORTANT RESPONSE RULES: "
        "1. For logistical questions (coffee break, lunch, schedule, venue, social dinner, "
        "wifi, address, timing, registration, opening, closing, awards) — answer with ONLY "
        "the essential facts in 1-3 sentences maximum. "
        "NEVER mention papers, contributions or research topics in logistical answers. "
        "NEVER add sentences like 'there are no papers about this topic'. "
        "For contact information always refer to the Organizing Committee at visioneuid@gmail.com. "
        "2. For questions about papers, contributions, authors or research topics — provide "
        "complete and detailed answers including titles and authors. "
        "3. When listing papers always include title and authors. "
        "4. If information is not in the documents, say so briefly. "
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
        "what are the papers", "elenca i paper", "elenca i contributi", "tutti i paper",
    ]
    lower_q = query.lower()
    if any(t in lower_q for t in list_triggers):
        # Always use track context if available — never list all tracks together
        effective_track = track
        # Try to detect track number from query itself
        import re
        m = re.search(r'track[\s]*([123])', lower_q)
        if m:
            effective_track = m.group(1)
        if effective_track:
            track_name = TRACKS[effective_track]
            query = (
                f"What are all the papers and their authors in Track {effective_track} "
                f"({track_name}) of the VISION_E conference? "
                f"List only the papers from track{effective_track}_*.pdf documents. "
                f"Include each paper title and author."
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

    # Check static logistics first — no need to call Vertex AI
    logistics_answer = check_logistics(message, language)
    if logistics_answer:
        return jsonify({
            "answer": logistics_answer,
            "track": session.get("track"),
            "language": language,
        })

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
