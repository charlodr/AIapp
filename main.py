import os
import json
import re
import requests
from flask import Flask, request, jsonify, Response
from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__)

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
    clean = text.strip()
    if clean in ("1", "2", "3"):
        return clean
    m = re.search(r'\btrack\s*([123])\b', clean.lower())
    if m:
        return m.group(1)
    # Check for word numbers
    mapping = {"one": "1", "uno": "1", "two": "2", "due": "2", "three": "3", "tre": "3"}
    for word, num in mapping.items():
        if re.search(rf'\b{word}\b', clean.lower()):
            return num
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


def build_system_prompt(language: str, track: str | None,
                        contribution_ref: str | None) -> str:
    track_ctx = ""
    if track:
        name = TRACKS[track]["name_en"] if language == "en" else TRACKS[track]["name_it"]
        if language == "en":
            track_ctx = (
                f"The user is focused on Track {track}: {name}. "
                f"Prioritise documents with 'track{track}_' in the filename. "
            )
        else:
            track_ctx = (
                f"L'utente è interessato al Track {track}: {name}. "
                f"Dai priorità ai documenti con 'track{track}_' nel nome. "
            )

    contrib_ctx = ""
    if contribution_ref:
        if language == "en":
            contrib_ctx = f"Focus specifically on the contribution related to: '{contribution_ref}'. "
        else:
            contrib_ctx = f"Concentrati specificamente sul contributo relativo a: '{contribution_ref}'. "

    if language == "en":
        return (
            "You are the official assistant for the ∀ISION_E conference on AI in architecture. "
            "Answer questions about the conference contributions, papers, speakers, programme, "
            "venue, schedule and logistics using the provided documents. "
            "ALL of the following topics are valid conference subjects — answer them fully: "
            "AI, LLM, RAG, NLP, BIM, HBIM, generative design, parametric design, digital twin, "
            "heritage conservation, digital heritage, photogrammetry, education, pedagogy, "
            "human-AI collaboration, diffusion models, neural networks, GANs, NeRF, XR, "
            "computational creativity, morphological analysis, scan-to-BIM, learning analytics, "
            "and any other AI-related topic in architecture, design, heritage or education. "
            "The document 'ConferenceDay.pdf' contains venue, schedule and logistics info. "
            f"{track_ctx}{contrib_ctx}"
            "When listing contributions, include title and author when available. "
            "Only reply OUT_OF_SCOPE if the question has absolutely nothing to do with "
            "AI, architecture, design, heritage, education or the conference. "
            "Be thorough, clear and helpful."
        )
    else:
        return (
            "Sei l'assistente ufficiale della conferenza ∀ISION_E sull'AI in architettura. "
            "Rispondi a domande sui contributi, paper, relatori, programma, sede, orari e logistica "
            "usando i documenti forniti. "
            "TUTTI i seguenti argomenti sono validi per la conferenza — rispondi esaurientemente: "
            "AI, LLM, RAG, NLP, BIM, HBIM, design generativo, design parametrico, digital twin, "
            "conservazione del patrimonio, heritage digitale, fotogrammetria, educazione, pedagogia, "
            "collaborazione uomo-AI, modelli diffusivi, reti neurali, GAN, NeRF, XR, "
            "creatività computazionale, analisi morfologica, scan-to-BIM, learning analytics, "
            "e qualsiasi altro argomento AI in architettura, design, patrimonio o educazione. "
            "Il documento 'ConferenceDay.pdf' contiene informazioni su sede, orari e logistica. "
            f"{track_ctx}{contrib_ctx}"
            "Quando elenchi i contributi, includi titolo e autore quando disponibili. "
            "Rispondi OUT_OF_SCOPE solo se la domanda non ha assolutamente nulla a che fare con "
            "AI, architettura, design, patrimonio, educazione o la conferenza. "
            "Sii esauriente, chiaro e utile."
        )


def query_vertex_ai(user_message: str, history: list, language: str,
                    track: str | None,
                    contribution_ref: str | None) -> tuple[str, str | None]:
    token = get_gcp_token()

    query_turns = [
        {
            "userInput": {"query": {"text": t["user"]}},
            "reply": {"summary": {"summaryText": t["assistant"]}}
        }
        for t in history[-MAX_HISTORY:]
    ]

    payload = {
        "query": {"text": user_message},
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

    # Override track from UI selection
    if track_req in ("1", "2", "3"):
        state["track"] = track_req

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
        return jsonify({"answer": reply, "track": state["track"]}), 200

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

    return jsonify({"answer": reply, "track": state["track"]})


@app.route("/chat/reset", methods=["POST"])
def web_chat_reset():
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    if session_id in user_state:
        del user_state[session_id]
    return jsonify({"status": "reset"})


# ─── WEB UI ───────────────────────────────────────────────────────────────────

WEB_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>&#8704;ISION_E — Conference Bot</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--surface:#111118;--surface2:#1a1a24;--border:#2a2a3a;--accent:#7c6af7;--accent2:#a78bfa;--text:#e8e8f0;--muted:#6b6b80;--bot:#1e1e2e;--user:#2d2257;--ok:#4ade80;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden;}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(ellipse 60% 40% at 20% 20%,rgba(124,106,247,.08) 0%,transparent 60%),radial-gradient(ellipse 40% 60% at 80% 80%,rgba(167,139,250,.06) 0%,transparent 60%);pointer-events:none;z-index:0;}
header{position:relative;z-index:10;padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;background:rgba(10,10,15,.9);backdrop-filter:blur(12px);}
.logo{font-family:'Space Mono',monospace;font-size:16px;font-weight:700;color:var(--accent2);}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 6px var(--ok);animation:pulse 2s infinite;margin-left:auto;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.4;}}
.track-bar{position:relative;z-index:10;padding:10px 20px;border-bottom:1px solid var(--border);display:flex;gap:6px;background:rgba(10,10,15,.7);overflow-x:auto;}
.track-bar::-webkit-scrollbar{height:0;}
.tbtn{padding:5px 12px;border-radius:16px;border:1px solid var(--border);background:transparent;color:var(--muted);font-size:11px;font-family:'Space Mono',monospace;cursor:pointer;transition:all .2s;white-space:nowrap;}
.tbtn:hover{border-color:var(--accent);color:var(--accent2);}
.tbtn.active{background:rgba(124,106,247,.15);border-color:var(--accent);color:var(--accent2);}
#msgs{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:14px;position:relative;z-index:1;}
#msgs::-webkit-scrollbar{width:3px;}
#msgs::-webkit-scrollbar-thumb{background:var(--border);}
.msg{display:flex;gap:10px;max-width:85%;animation:fi .25s ease;}
@keyframes fi{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
.msg.user{align-self:flex-end;flex-direction:row-reverse;}
.msg.bot{align-self:flex-start;}
.av{width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-family:'Space Mono',monospace;font-size:9px;font-weight:700;flex-shrink:0;margin-top:2px;}
.av.b{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;}
.av.u{background:var(--surface2);border:1px solid var(--border);color:var(--muted);}
.bub{padding:10px 14px;border-radius:10px;font-size:13px;line-height:1.7;word-break:break-word;}
.bot .bub{background:var(--bot);border:1px solid var(--border);border-top-left-radius:2px;}
.user .bub{background:var(--user);border:1px solid rgba(124,106,247,.3);border-top-right-radius:2px;}
.bub strong{color:var(--accent2);}
.bub em{color:var(--muted);font-style:italic;}
.badge{display:inline-block;padding:2px 7px;border-radius:9px;font-size:9px;font-family:'Space Mono',monospace;background:rgba(124,106,247,.15);border:1px solid rgba(124,106,247,.3);color:var(--accent2);margin-bottom:6px;margin-right:4px;}
.typing{display:flex;gap:3px;padding:12px 14px;background:var(--bot);border:1px solid var(--border);border-radius:10px;}
.typing span{width:5px;height:5px;border-radius:50%;background:var(--accent);animation:ty 1.2s infinite;}
.typing span:nth-child(2){animation-delay:.2s;}
.typing span:nth-child(3){animation-delay:.4s;}
@keyframes ty{0%,60%,100%{transform:translateY(0);opacity:.4;}30%{transform:translateY(-5px);opacity:1;}}
.input-area{position:relative;z-index:10;padding:14px 20px;border-top:1px solid var(--border);background:rgba(10,10,15,.9);display:flex;gap:10px;align-items:flex-end;}
#inp{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--text);font-family:'DM Sans',sans-serif;font-size:13px;resize:none;outline:none;min-height:40px;max-height:100px;transition:border-color .2s;line-height:1.5;}
#inp:focus{border-color:var(--accent);}
#inp::placeholder{color:var(--muted);}
#send{width:40px;height:40px;border-radius:9px;border:none;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .2s;flex-shrink:0;}
#send:hover{transform:scale(1.05);}
#send:disabled{opacity:.4;cursor:not-allowed;transform:none;}
.welcome{text-align:center;padding:40px 20px;}
.wtitle{font-family:'Space Mono',monospace;font-size:24px;color:var(--accent2);margin-bottom:8px;}
.wsub{font-size:13px;color:var(--muted);line-height:1.7;margin-bottom:24px;}
.quick-btns{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;}
.qbtn{padding:8px 14px;border-radius:20px;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:12px;cursor:pointer;transition:all .2s;font-family:'DM Sans',sans-serif;}
.qbtn:hover{border-color:var(--accent);color:var(--accent2);background:rgba(124,106,247,.08);}
.reset-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:5px 10px;border-radius:7px;font-size:11px;cursor:pointer;font-family:'Space Mono',monospace;margin-left:8px;transition:all .2s;}
.reset-btn:hover{border-color:var(--accent);color:var(--accent2);}
</style>
</head>
<body>
<header>
  <div class="logo">&#8704;ISION_E</div>
  <div style="font-size:11px;color:var(--muted);font-family:'Space Mono',monospace;">Conference Bot</div>
  <div style="display:flex;align-items:center;gap:8px;margin-left:auto;">
    <button class="reset-btn" onclick="resetChat()">&#8635; Reset</button>
    <div class="dot"></div>
  </div>
</header>
<div class="track-bar">
  <button class="tbtn active" onclick="selTrack('all',this)">All Tracks</button>
  <button class="tbtn" onclick="selTrack('1',this)">T1 &middot; Representation &amp; Design</button>
  <button class="tbtn" onclick="selTrack('2',this)">T2 &middot; Heritage Conservation</button>
  <button class="tbtn" onclick="selTrack('3',this)">T3 &middot; Education &amp; Learning</button>
</div>
<div id="msgs">
  <div class="welcome" id="welcome">
    <div class="wtitle">&#8704;ISION_E</div>
    <div class="wsub">Welcome to the Conference Bot<br>Ask anything about contributions, programme or logistics</div>
    <div class="quick-btns">
      <button class="qbtn" onclick="quickAsk('What are the papers in Track 1?')">Track 1 papers</button>
      <button class="qbtn" onclick="quickAsk('What are the papers in Track 2?')">Track 2 papers</button>
      <button class="qbtn" onclick="quickAsk('What are the papers in Track 3?')">Track 3 papers</button>
      <button class="qbtn" onclick="quickAsk('What is the conference schedule?')">Schedule</button>
      <button class="qbtn" onclick="quickAsk('Where is the event taking place?')">Venue</button>
      <button class="qbtn" onclick="quickAsk('Tell me about the contributions on LLM')">LLM contributions</button>
      <button class="qbtn" onclick="quickAsk('Tell me about the contributions on BIM')">BIM contributions</button>
    </div>
  </div>
</div>
<div class="input-area">
  <textarea id="inp" placeholder="Ask about the conference..." rows="1" onkeydown="handleKey(event)" oninput="resize(this)"></textarea>
  <button id="send" onclick="send()">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
  </button>
</div>
<script>
const TRACKS={'1':'AI for Representation and Design','2':'AI for Heritage Conservation and Enhancement','3':'AI for Education and Learning'};
let track='all',loading=false;
const sid='s'+Math.random().toString(36).slice(2,9);

function selTrack(t,btn){
  track=t;
  document.querySelectorAll('.tbtn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(t!=='all'){
    addMsg('bot','<span class="badge">TRACK '+t+'</span><br><strong>'+TRACKS[t]+'</strong><br><br>Ask me anything about the contributions in this track, or type a keyword like an author name, topic, or paper title.');
  }
}

function quickAsk(q){
  document.getElementById('inp').value=q;
  send();
}

function formatText(text){
  return text
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/_(.+?)_/g,'<em>$1</em>')
    .replace(/•/g,'&bull;')
    .replace(/\n/g,'<br>');
}

function addMsg(role,html){
  const m=document.getElementById('msgs');
  const d=document.createElement('div');
  d.className='msg '+role;
  const av=document.createElement('div');
  av.className='av '+(role==='bot'?'b':'u');
  av.textContent=role==='bot'?'AI':'YOU';
  const b=document.createElement('div');
  b.className='bub';
  b.innerHTML=html;
  d.appendChild(av);d.appendChild(b);
  m.appendChild(d);
  m.scrollTop=m.scrollHeight;
}

function showTyping(){
  const m=document.getElementById('msgs');
  const d=document.createElement('div');
  d.className='msg bot';d.id='typing';
  const av=document.createElement('div');
  av.className='av b';av.textContent='AI';
  const t=document.createElement('div');
  t.className='typing';
  t.innerHTML='<span></span><span></span><span></span>';
  d.appendChild(av);d.appendChild(t);
  m.appendChild(d);m.scrollTop=m.scrollHeight;
}

function hideTyping(){document.getElementById('typing')?.remove();}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}}
function resize(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,100)+'px';}

async function send(){
  const inp=document.getElementById('inp');
  const txt=inp.value.trim();
  if(!txt||loading)return;
  loading=true;
  document.getElementById('send').disabled=true;
  document.getElementById('welcome')?.remove();
  inp.value='';inp.style.height='auto';
  addMsg('user',txt);
  showTyping();
  try{
    const r=await fetch('/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:txt,session_id:sid,track:track==='all'?null:track})
    });
    const data=await r.json();
    hideTyping();
    const html=formatText(data.answer||'No response.');
    addMsg('bot',html);
    if(data.track&&data.track!==track){
      track=data.track;
      document.querySelectorAll('.tbtn').forEach((b,i)=>{
        b.classList.toggle('active',i===0&&data.track===null||b.textContent.includes('T'+data.track));
      });
    }
  }catch(e){
    hideTyping();
    addMsg('bot','Connection error. Please try again.');
  }
  loading=false;
  document.getElementById('send').disabled=false;
  inp.focus();
}

async function resetChat(){
  await fetch('/chat/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid})});
  document.getElementById('msgs').innerHTML='<div class="welcome" id="welcome"><div class="wtitle">&#8704;ISION_E</div><div class="wsub">Welcome to the Conference Bot<br>Ask anything about contributions, programme or logistics</div><div class="quick-btns"><button class="qbtn" onclick="quickAsk(\'What are the papers in Track 1?\')">Track 1 papers</button><button class="qbtn" onclick="quickAsk(\'What are the papers in Track 2?\')">Track 2 papers</button><button class="qbtn" onclick="quickAsk(\'What are the papers in Track 3?\')">Track 3 papers</button><button class="qbtn" onclick="quickAsk(\'What is the conference schedule?\')">Schedule</button><button class="qbtn" onclick="quickAsk(\'Where is the event taking place?\')">Venue</button><button class="qbtn" onclick="quickAsk(\'Tell me about the contributions on LLM\')">LLM contributions</button><button class="qbtn" onclick="quickAsk(\'Tell me about the contributions on BIM\')">BIM contributions</button></div></div>';
  track='all';
  document.querySelectorAll('.tbtn').forEach((b,i)=>b.classList.toggle('active',i===0));
}
</script>
</body>
</html>"""


@app.route("/", methods=["GET"])
def web_ui():
    return Response(WEB_UI, mimetype="text/html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
