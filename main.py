import os
import json
import re
import requests
from flask import Flask, request, jsonify, send_from_directory
from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__, static_folder="static")

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "chatbot-visione")
GCP_LOCATION   = os.environ.get("GCP_LOCATION", "eu")
DATASTORE_ID   = os.environ.get("DATASTORE_ID", "atlascardone_1773418764471")

DISCOVERY_ENGINE_URL = (
    f"https://{GCP_LOCATION}-discoveryengine.googleapis.com/v1alpha/projects/"
    f"{GCP_PROJECT_ID}/locations/{GCP_LOCATION}/collections/default_collection/"
    f"dataStores/{DATASTORE_ID}/servingConfigs/default_search:answer"
)

# ─── TRACK DEFINITIONS ────────────────────────────────────────────────────────
TRACKS = {
    "1": {
        "name_en": "AI for Representation and Design",
        "name_it": "AI per la Rappresentazione e il Design",
        "keywords": [
            # From keywords list
            "human-ai co-creation", "architectural design", "parametric design",
            "generative design", "design optimization", "performance-driven design",
            "design space exploration", "ai-driven spatial analysis", "ai for sustainable design",
            "ai in urban design", "climatic", "environmental analysis", "computational creativity",
            "computational aesthetics", "shared authorship", "morphological analysis",
            "form-finding", "algorithmic prototyping", "virtual prototyping", "style transfer",
            "building information modeling", "bim",
            # Short forms for user queries
            "representation", "design", "spatial", "parametric", "generative",
            "architectural", "urban", "sustainable", "morphological", "prototyping",
            "aesthetics", "creativity", "authorship", "form", "algorithmic"
        ]
    },
    "2": {
        "name_en": "AI for Heritage Conservation and Enhancement",
        "name_it": "AI per la Conservazione e la Valorizzazione del Patrimonio",
        "keywords": [
            # From keywords list
            "digital heritage", "digital survey", "terrestrial laser scanning",
            "photogrammetry", "geometric analysis", "scan-to-bim", "scan-to-hbim",
            "historical document analysis", "collaborative interpretation",
            "interactive digital documentation", "dynamic storytelling", "digital archives",
            "museum studies", "semantic enrichment", "knowledge representation",
            "linked open data", "heritage building information modeling", "hbim",
            "digital restoration", "digital reconstruction", "advanced diagnostics",
            "predictive conservation", "ai-driven accessibility",
            # Short forms for user queries
            "heritage", "conservation", "restoration", "historical", "cultural",
            "monument", "preservation", "documentation", "museum", "archive",
            "scanning", "photogrammetry", "diagnostics", "reconstruction", "accessibility"
        ]
    },
    "3": {
        "name_en": "AI for Education and Learning",
        "name_it": "AI per l'Educazione e l'Apprendimento",
        "keywords": [
            # From keywords list
            "ai in architecture and design education", "architectural pedagogy",
            "design studio pedagogy", "collaborative virtual environments",
            "ai-mediated learning", "personalized learning", "adaptive learning",
            "intelligent tutoring systems", "student modeling", "knowledge tracing",
            "learning analytics", "automated assessment", "automated feedback",
            "learning outcome validation", "hybrid contexts", "immersive learning",
            "gamification", "active engagement", "pedagogical agents", "academic integrity",
            # Short forms for user queries
            "education", "learning", "teaching", "pedagogy", "students", "tutoring",
            "assessment", "feedback", "gamification", "immersive", "curriculum",
            "workshop", "training", "didactic", "studio", "academic"
        ]
    }
}

# Common keywords relevant to ALL tracks
COMMON_KEYWORDS = [
    "extended intelligence", "human-ai collaboration", "hybrid cognitive",
    "interdisciplinary", "generative ai", "predictive ai", "multimodal ai",
    "agentic ai", "trustworthy ai", "explainable ai", "ai fairness", "ai bias",
    "ai ethics", "ai accountability", "ai safety", "ai literacy",
    "retrieval-augmented generation", "rag", "natural language processing", "nlp",
    "large language models", "llm", "llms", "diffusion models",
    "world models", "neural radiance fields", "nerf", "gaussian splatting", "3dgs",
    "generative adversarial networks", "gan", "gans", "semantic segmentation",
    "data-driven", "data augmentation", "digital twin", "extended reality", "xr",
    "image generation", "video generation", "3d generation", "procedural generation",
    "fine-tuning", "ai", "artificial intelligence", "machine learning", "deep learning",
    "paper", "papers", "contribution", "contributions", "research", "conference"
]

SUGGESTION_EN = (
    "\n\n💡 **Not sure what to ask?** Try one of these:\n"
    "• Type **1**, **2** or **3** to explore a specific track\n"
    "• Ask: *\"What papers are in Track 1?\"*\n"
    "• Ask: *\"Tell me about the contribution by [author name]\"*\n"
    "• Ask: *\"What is the conference schedule?\"*\n"
    "• Ask: *\"Where is the event taking place?\"*"
)

SUGGESTION_IT = (
    "\n\n💡 **Non sai cosa chiedere?** Prova uno di questi:\n"
    "• Scrivi **1**, **2** o **3** per esplorare un track specifico\n"
    "• Chiedi: *\"Quali paper ci sono nel Track 1?\"*\n"
    "• Chiedi: *\"Parlami del contributo di [nome autore]\"*\n"
    "• Chiedi: *\"Qual è il programma della conferenza?\"*\n"
    "• Chiedi: *\"Dove si svolge l'evento?\"*"
)

FALLBACK_EN = (
    "I couldn't find specific information about that in the conference documents. "
    "The ∀ISION_E conference covers AI applications in architecture, design, heritage "
    "conservation and education.\n\n"
    "Would you like to explore contributions from a specific track?\n"
    "• **Track 1** — AI for Representation and Design\n"
    "• **Track 2** — AI for Heritage Conservation and Enhancement\n"
    "• **Track 3** — AI for Education and Learning\n\n"
    "Type 1, 2 or 3 to get started, or try rephrasing your question."
)

FALLBACK_IT = (
    "Non ho trovato informazioni specifiche su questo nei documenti della conferenza. "
    "La conferenza ∀ISION_E tratta applicazioni dell'AI in architettura, design, "
    "conservazione del patrimonio ed educazione.\n\n"
    "Vuoi esplorare i contributi di un track specifico?\n"
    "• **Track 1** — AI per la Rappresentazione e il Design\n"
    "• **Track 2** — AI per la Conservazione e la Valorizzazione del Patrimonio\n"
    "• **Track 3** — AI per l'Educazione e l'Apprendimento\n\n"
    "Scrivi 1, 2 o 3 per iniziare, oppure riformula la tua domanda."
)

# ─── IN-MEMORY STATE ──────────────────────────────────────────────────────────
user_state = {}
MAX_HISTORY = 6


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_state(session_id: str) -> dict:
    if session_id not in user_state:
        user_state[session_id] = {
            "track":   None,
            "history": []
        }
    return user_state[session_id]


def get_gcp_token() -> str:
    credentials, _ = default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    return credentials.token


def detect_language(text: str) -> str:
    italian_markers = [
        "ciao", "buongiorno", "grazie", " il ", " la ", " le ", " gli ",
        " del ", " della ", " che ", " non ", " per ", " con ", " una ",
        " sono ", " questo ", "riguardo", "contributo", "dimmi", "posso",
        "dove", "quando", "come", "cosa", "quale", "voglio", "puoi"
    ]
    lower = " " + text.lower() + " "
    return "it" if sum(1 for m in italian_markers if m in lower) >= 2 else "en"


def detect_track_selection(text: str) -> str | None:
    """Only intercept very short, direct track selection messages."""
    clean = text.strip().lower()
    if clean in ("1", "2", "3",
                 "track 1", "track 2", "track 3",
                 "track1", "track2", "track3"):
        return clean[-1]
    return None


def detect_contribution_reference(text: str) -> str | None:
    patterns = [
        r"(?:about|regarding|on)\s+(?:the\s+)?(?:contribution|paper|talk|work)\s+(?:by|from|of)\s+(.+)",
        r"(?:riguardo|parlami|dimmi|sull[ao]?)\s+(?:al\s+)?(?:contributo|paper|lavoro)\s+(?:di|del|della)\s+(.+)",
        r"(?:contribution|paper)\s+(?:by|from)\s+(.+)",
        r"(?:contributo|paper)\s+(?:di|del)\s+(.+)",
    ]
    for p in patterns:
        m = re.search(p, text.lower())
        if m:
            return m.group(1).strip()
    return None


def guess_track_from_keywords(text: str) -> str | None:
    """Try to detect which track a query belongs to based on keywords."""
    lower = text.lower()

    # Check if it's a common keyword — don't force a specific track
    for kw in COMMON_KEYWORDS:
        if kw in lower:
            return None  # Let Vertex AI search all tracks

    scores = {}
    for t_num, t_data in TRACKS.items():
        score = sum(1 for kw in t_data["keywords"] if kw in lower)
        if score > 0:
            scores[t_num] = score
    if scores:
        return max(scores, key=scores.get)
    return None


def translate_query_to_english(text: str) -> str:
    """Translate common Italian conference terms to English and fix common typos."""
    lower = text.lower()
    translated = lower
    # Fix common typos
    typo_fixes = {
        "coffe break": "coffee break",
        "coffe": "coffee",
        "shcedule": "schedule",
        "schdule": "schedule",
        "venu ": "venue ",
        "keynot ": "keynote ",
        "committe": "committee",
        "comitee": "committee",
        "organiz": "organiz",
    }
    for typo, fix in typo_fixes.items():
        if typo in translated:
            translated = translated.replace(typo, fix)
    it_to_en = {
        "pausa caffe": "coffee break",
        "pausa caff\u00e8": "coffee break",
        "caff\u00e8": "coffee break",
        "caffe": "coffee break",
        "pausa pranzo": "lunch break",
        "pranzo": "lunch",
        "apertura": "opening ceremony",
        "chiusura": "closing",
        "sede": "venue",
        "orari": "schedule timings",
        "programma": "programme schedule",
        "relatori": "speakers",
        "contributi": "contributions papers",
        "tavola rotonda": "round table",
        "premi": "awards",
        "registrazione": "registration",
        "keynote": "keynote",
        "sessione": "session",
        "track": "track",
        "patrimonio": "heritage",
        "conservazione": "conservation",
        "rappresentazione": "representation",
        "progettazione": "design",
        "educazione": "education",
        "apprendimento": "learning",
        "conferenza": "conference",
    }
    for it_term, en_term in it_to_en.items():
        if it_term in translated:
            translated = translated.replace(it_term, en_term)
    return translated

def build_system_prompt(language: str, track: str | None,
                        contribution_ref: str | None) -> str:
    """Always returns English prompt — documents are in English.
    Language param only controls the response language instruction."""
    track_ctx = ""
    if track:
        name = TRACKS[track]["name_en"]
        track_ctx = (
            f"The user is focused on Track {track}: {name}. "
            f"Prioritise documents with 'track{track}_' in the filename. "
        )

    contrib_ctx = ""
    if contribution_ref:
        contrib_ctx = f"Focus specifically on the contribution related to: '{contribution_ref}'. "

    lang_instruction = (
        "Reply in Italian." if language == "it"
        else "Reply in English."
    )

    return (
        "You are the official assistant for the VISION_E conference on AI in architecture. "
        "Answer ANY question related to the conference: contributions, papers, speakers, "
        "programme, schedule, timings, coffee break, lunch break, venue, location, "
        "logistics, organizing committee, scientific committee, keynotes, sessions, "
        "tracks, best paper awards, registration, opening, closing, round table. "
        "Use ConferenceDay.pdf for all schedule, timing, timetable, cronoprogram and venue questions. The schedule is labelled CRONOPROGRAM in the document. "
        "ALL of the following are valid topics: "
        "AI, LLM, RAG, NLP, BIM, HBIM, generative design, parametric design, digital twin, "
        "heritage conservation, digital heritage, photogrammetry, education, pedagogy, "
        "human-AI collaboration, diffusion models, neural networks, GANs, NeRF, XR, "
        "computational creativity, morphological analysis, scan-to-BIM, learning analytics, "
        "coffee break, lunch, venue, schedule, awards, keynote, round table. "
        f"{track_ctx}{contrib_ctx}"
        "When listing contributions include title and author when available. "
        "Only reply OUT_OF_SCOPE for questions completely unrelated to the conference. "
        f"Be thorough, clear and helpful. {lang_instruction}"
    )


def query_vertex_ai(user_message: str, history: list, language: str,
                    track: str | None,
                    contribution_ref: str | None) -> tuple[str, str | None]:
    token = get_gcp_token()

    # Normalize query: lowercase and remove trailing punctuation
    import string
    normalized = user_message.strip().rstrip(string.punctuation).lower()

    # Translate Italian queries to English for better RAG matching
    query_text = translate_query_to_english(normalized)

    # Enrich short/vague queries with track context
    if track and len(query_text.split()) <= 5:
        track_name = TRACKS[track]["name_en"]
        query_text = f"{query_text} in Track {track} ({track_name})"

    # For very short queries (1-2 words), add conference context
    if len(query_text.split()) <= 2:
        query_text = f"conference {query_text} VISION_E schedule programme venue"

    query_turns = [
        {
            "userInput": {"query": {"text": t["user"]}},
            "reply": {"summary": {"summaryText": t["assistant"]}}
        }
        for t in history[-MAX_HISTORY:]
    ]

    payload = {
        "query": {"text": query_text},
        "answerGenerationSpec": {
            "modelSpec":        {"modelVersion": "stable"},
            "promptSpec":       {"preamble": build_system_prompt(language, track, contribution_ref)},
            "includeCitations": True
        }
    }

    if query_turns:
        payload["conversationContext"] = {"queryHistory": query_turns}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json"
    }

    resp = requests.post(DISCOVERY_ENGINE_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    try:
        answer = data["answer"]["answerText"].strip()
    except (KeyError, TypeError):
        return "OUT_OF_SCOPE", None

    # Detect source track from document URIs
    detected_track = None
    try:
        for ref in data["answer"].get("references", []):
            uri = ref.get("unstructuredDocumentInfo", {}).get("uri", "")
            for t_num in ("1", "2", "3"):
                if f"track{t_num}" in uri:
                    detected_track = t_num
                    break
            if detected_track:
                break
    except Exception:
        pass

    return answer, detected_track


# ─── WEB CHAT API ─────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def web_chat():
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    user_message = data.get("message", "").strip()
    session_id   = data.get("session_id", "default")
    track_req    = data.get("track", None)

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    state    = get_state(session_id)
    language = detect_language(user_message)

    # UI track selection always takes priority
    if track_req in ("1", "2", "3"):
        state["track"] = track_req
    elif track_req is None and state["track"]:
        # Keep existing track if UI is on "All Tracks" but session has a track
        pass

    # Detect explicit track selection in message
    selected = detect_track_selection(user_message)
    if selected:
        state["track"] = selected
        t = TRACKS[selected]
        name = t["name_it"] if language == "it" else t["name_en"]
        reply = (
            f"**Track {selected} — {name}**\n\n"
            f"{'Chiedimi qualsiasi cosa sui contributi di questo track. Puoi chiedere di un paper specifico, di un autore, o di un argomento.' if language == 'it' else 'Ask me anything about the contributions in this track. You can ask about a specific paper, author, or topic.'}"
        )
        return jsonify({"answer": reply, "track": selected})

    # Try to guess track from keywords if not set
    if not state["track"]:
        guessed = guess_track_from_keywords(user_message)
        if guessed:
            state["track"] = guessed

    # Detect contribution reference
    contrib_ref = detect_contribution_reference(user_message)

    # Query Vertex AI
    try:
        answer, source_track = query_vertex_ai(
            user_message, state["history"], language,
            state["track"], contrib_ref
        )
    except Exception as e:
        app.logger.error(f"Vertex AI error: {e}")
        reply = FALLBACK_IT if language == "it" else FALLBACK_EN
        return jsonify({"answer": reply, "track": state["track"], "language": language}), 200

    # Handle out of scope
    if "OUT_OF_SCOPE" in answer.upper():
        reply = FALLBACK_IT if language == "it" else FALLBACK_EN

    # Handle track switch
    elif source_track and state["track"] and source_track != state["track"]:
        t = TRACKS[source_track]
        name = t["name_it"] if language == "it" else t["name_en"]
        switch_note = (
            f"\n\n_ℹ️ Risposta trovata nel Track {source_track}: {name}_"
            if language == "it" else
            f"\n\n_ℹ️ Answer found in Track {source_track}: {name}_"
        )
        reply = answer + switch_note
        state["track"] = source_track

    else:
        if source_track and not state["track"]:
            state["track"] = source_track
        reply = answer

    # Update history
    state["history"].append({"user": user_message, "assistant": reply})
    state["history"] = state["history"][-MAX_HISTORY:]

    return jsonify({"answer": reply, "track": state["track"], "language": language})


@app.route("/chat/reset", methods=["POST"])
def web_chat_reset():
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    if session_id in user_state:
        del user_state[session_id]
    return jsonify({"status": "reset"})


# ─── WEB UI ───────────────────────────────────────────────────────────────────


@app.route("/", methods=["GET"])
def web_ui():
    return send_from_directory("static", "index.html")



@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
