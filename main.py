import os
import json
import re
import requests
from flask import Flask, request, jsonify, Response
from google.auth import default
from google.auth.transport.requests import Request

app = Flask(__name__)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
VERIFY_TOKEN     = os.environ.get("VERIFY_TOKEN", "visione2025")
WA_TOKEN         = os.environ.get("WA_TOKEN", "")
PHONE_NUMBER_ID  = os.environ.get("PHONE_NUMBER_ID", "1047204695138200")
GCP_PROJECT_ID   = os.environ.get("GCP_PROJECT_ID", "chatbot-visione")
GCP_LOCATION     = os.environ.get("GCP_LOCATION", "eu")
DATASTORE_ID     = os.environ.get("DATASTORE_ID", "atlascardone_1773418764471")

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
        "prefix":  "track1"
    },
    "2": {
        "name_en": "AI for Heritage Conservation and Enhancement",
        "name_it": "AI per la Conservazione e la Valorizzazione del Patrimonio",
        "prefix":  "track2"
    },
    "3": {
        "name_en": "AI for Education and Learning",
        "name_it": "AI per l'Educazione e l'Apprendimento",
        "prefix":  "track3"
    }
}

# ─── MESSAGES ─────────────────────────────────────────────────────────────────
WELCOME_MESSAGE = (
    "Welcome to the ∀ISION_E Conference Day! 👋\n\n"
    "This bot provides essential information about the venue, the programme "
    "and all contributions across the three tracks of today's event:\n\n"
    "1️⃣  AI for Representation and Design\n"
    "2️⃣  AI for Heritage Conservation and Enhancement\n"
    "3️⃣  AI for Education and Learning\n\n"
    "Please select your track by replying with 1, 2 or 3,\n"
    "or ask me anything directly. Enjoy the day! 🎉\n\n"
    "───────────────────────────\n\n"
    "Benvenuto alla giornata di conferenza ∀ISION_E! 👋\n\n"
    "Questo bot fornisce informazioni essenziali sulla sede, il programma "
    "e tutti i contributi dei tre track dell'evento di oggi:\n\n"
    "1️⃣  AI per la Rappresentazione e il Design\n"
    "2️⃣  AI per la Conservazione e la Valorizzazione del Patrimonio\n"
    "3️⃣  AI per l'Educazione e l'Apprendimento\n\n"
    "Seleziona il tuo track rispondendo con 1, 2 o 3,\n"
    "oppure fai direttamente una domanda. Buona giornata! 🎉"
)

TRACK_SELECTED_EN = (
    "✅ Track {n} selected: *{name}*\n\n"
    "Ask me anything about the contributions in this track. "
    "You can also mention a specific contribution, for example:\n"
    "_\"Tell me more about the contribution by Smith on digital twins\"\n_"
    "or switch track at any time by typing 1, 2 or 3."
)

TRACK_SELECTED_IT = (
    "✅ Track {n} selezionato: *{name}*\n\n"
    "Chiedimi qualsiasi cosa sui contributi di questo track. "
    "Puoi anche citare un contributo specifico, ad esempio:\n"
    "_\"Dimmi di più sul contributo di Rossi sui gemelli digitali\"\n_"
    "o cambia track in qualsiasi momento scrivendo 1, 2 o 3."
)

TRACK_SWITCH_EN = (
    "🔄 I found relevant information in Track {n} "
    "(*{name}*).\n\n{answer}\n\n"
    "Your active track has been updated to Track {n}."
)

TRACK_SWITCH_IT = (
    "🔄 Ho trovato informazioni rilevanti nel Track {n} "
    "(*{name}*).\n\n{answer}\n\n"
    "Il tuo track attivo è stato aggiornato al Track {n}."
)

OUT_OF_SCOPE_EN = (
    "I'm sorry, I can only answer questions related to the ∀ISION_E conference "
    "contributions, programme, venue and logistics. "
    "For other information please reach out to the staff on site."
)

OUT_OF_SCOPE_IT = (
    "Mi dispiace, posso rispondere solo a domande riguardanti i contributi, "
    "il programma, la sede e la logistica della conferenza ∀ISION_E. "
    "Per altre informazioni rivolgiti allo staff presente in sede."
)

# ─── IN-MEMORY STATE ──────────────────────────────────────────────────────────
# { user_id: { "track": "1"|"2"|"3"|None, "history": [...], "greeted": bool } }
user_state = {}
MAX_HISTORY = 6


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_state(user_id: str) -> dict:
    if user_id not in user_state:
        user_state[user_id] = {
            "track":   None,
            "history": [],
            "greeted": False
        }
    return user_state[user_id]


def get_gcp_token() -> str:
    credentials, _ = default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    return credentials.token


def detect_language(text: str) -> str:
    """Heuristic: count Italian markers."""
    italian_markers = [
        "ciao", "buongiorno", "grazie", "come", "cosa", "dove", "quando",
        "perché", "chi", "quale", "posso", "puoi", "vorrei", "dimmi",
        " il ", " la ", " le ", " gli ", " del ", " della ", " dei ",
        " che ", " non ", " per ", " con ", " una ", " uno ", " sono ",
        " questo ", " questi ", " quale ", " riguardo", " contributo"
    ]
    lower = " " + text.lower() + " "
    score = sum(1 for m in italian_markers if m in lower)
    return "it" if score >= 2 else "en"


def detect_track_selection(text: str) -> str | None:
    """Return '1', '2', '3' if user is selecting a track, else None."""
    clean = text.strip()
    if clean in ("1", "2", "3"):
        return clean
    patterns = [
        r"\btrack\s*([123])\b",
        r"\btrack\s+([one|two|three|uno|due|tre])\b",
        r"\b(one|uno)\b", r"\b(two|due)\b", r"\b(three|tre)\b"
    ]
    for p in patterns:
        m = re.search(p, clean.lower())
        if m:
            g = m.group(1) if m.lastindex else m.group(0)
            mapping = {"one": "1", "uno": "1", "two": "2", "due": "2",
                       "three": "3", "tre": "3"}
            return mapping.get(g, g if g in ("1", "2", "3") else None)
    return None


def detect_contribution_reference(text: str) -> str | None:
    """
    Detect if user is referencing a specific contribution.
    Returns the extracted reference string or None.
    Handles: 'about the contribution by X', 'riguardo al contributo di X',
             'about X's paper', 'sul paper di X', etc.
    """
    patterns = [
        r"(?:about|regarding|on)\s+(?:the\s+)?(?:contribution|paper|talk|work)\s+(?:by|from|of)\s+(.+)",
        r"(?:riguardo|parlami|dimmi|sull[ao]?)\s+(?:al\s+)?(?:contributo|paper|lavoro|intervento)\s+(?:di|del|della|dei)\s+(.+)",
        r"(?:contribution|paper)\s+(?:by|from)\s+(.+)",
        r"(?:contributo|paper)\s+(?:di|del)\s+(.+)",
    ]
    lower = text.lower()
    for p in patterns:
        m = re.search(p, lower)
        if m:
            return m.group(1).strip()
    return None


def build_system_prompt(language: str, track: str | None,
                        contribution_ref: str | None) -> str:
    track_context = ""
    if track:
        t = TRACKS[track]
        name = t["name_en"] if language == "en" else t["name_it"]
        if language == "en":
            track_context = (
                f"The user is currently interested in Track {track}: {name}. "
                f"Prioritise documents whose filename starts with 'track{track}_'. "
            )
        else:
            track_context = (
                f"L'utente è attualmente interessato al Track {track}: {name}. "
                f"Dai priorità ai documenti il cui nome inizia con 'track{track}_'. "
            )

    contrib_context = ""
    if contribution_ref:
        if language == "en":
            contrib_context = (
                f"The user is asking specifically about the contribution "
                f"related to: '{contribution_ref}'. Focus on that document. "
            )
        else:
            contrib_context = (
                f"L'utente sta chiedendo specificamente del contributo "
                f"relativo a: '{contribution_ref}'. Concentrati su quel documento. "
            )

    if language == "en":
        return (
            "You are the official assistant for the ∀ISION_E conference. "
            "Answer ONLY questions related to the conference contributions, "
            "programme, venue and logistics, using exclusively the information "
            "in the provided documents. The document 'ConferenceDay.pdf' contains "
            "general event information (venue, schedule, logistics). "
            f"{track_context}"
            f"{contrib_context}"
            "If you cannot find relevant information in the documents, "
            "reply with exactly: OUT_OF_SCOPE. "
            "Be clear, concise and helpful."
        )
    else:
        return (
            "Sei l'assistente ufficiale della conferenza ∀ISION_E. "
            "Rispondi SOLO a domande relative ai contributi della conferenza, "
            "al programma, alla sede e alla logistica, usando esclusivamente "
            "le informazioni contenute nei documenti forniti. Il documento "
            "'ConferenceDay.pdf' contiene informazioni generali sull'evento "
            "(sede, orari, logistica). "
            f"{track_context}"
            f"{contrib_context}"
            "Se non riesci a trovare informazioni pertinenti nei documenti, "
            "rispondi esattamente con: OUT_OF_SCOPE. "
            "Sii chiaro, conciso e utile."
        )


def query_vertex_ai(user_message: str, history: list, language: str,
                    track: str | None,
                    contribution_ref: str | None) -> tuple[str, str | None]:
    """
    Query Vertex AI. Returns (answer_text, detected_track_from_sources).
    detected_track_from_sources is set if answer came from a different track.
    """
    token = get_gcp_token()

    # Build conversation context from history
    query_turns = []
    for turn in history[-MAX_HISTORY:]:
        query_turns.append({
            "userInput": {"query": {"text": turn["user"]}},
            "reply":     {"summary": {"summaryText": turn["assistant"]}}
        })

    payload = {
        "query": {"text": user_message},
        "answerGenerationSpec": {
            "modelSpec":        {"modelVersion": "stable"},
            "promptSpec":       {"preamble": build_system_prompt(
                                    language, track, contribution_ref)},
            "includeCitations": True
        }
    }

    if query_turns:
        payload["conversationContext"] = {"queryHistory": query_turns}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json"
    }

    resp = requests.post(
        DISCOVERY_ENGINE_URL, headers=headers, json=payload, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()

    # Extract answer text
    try:
        answer = data["answer"]["answerText"].strip()
    except (KeyError, TypeError):
        return "OUT_OF_SCOPE", None

    # Detect which track the sources came from
    detected_track = None
    try:
        refs = data["answer"].get("references", [])
        for ref in refs:
            uri = ref.get("unstructuredDocumentInfo", {}).get("uri", "")
            for t_num in ("1", "2", "3"):
                if f"/track{t_num}/" in uri or f"track{t_num}_" in uri:
                    detected_track = t_num
                    break
            if detected_track:
                break
    except Exception:
        pass

    return answer, detected_track


def send_whatsapp(to: str, text: str):
    """Send a WhatsApp text message."""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_TOKEN}",
        "Content-Type":  "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "text",
        "text":              {"body": text}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()


# ─── CORE LOGIC ───────────────────────────────────────────────────────────────

def handle_message(sender: str, text: str):
    state    = get_state(sender)
    language = detect_language(text)

    # ── 1. Welcome (first message only) ───────────────────────────────────
    if not state["greeted"]:
        state["greeted"] = True
        send_whatsapp(sender, WELCOME_MESSAGE)
        return

    # ── 2. Track selection ─────────────────────────────────────────────────
    selected = detect_track_selection(text)
    if selected:
        state["track"] = selected
        t = TRACKS[selected]
        if language == "it":
            msg = TRACK_SELECTED_IT.format(
                n=selected, name=t["name_it"])
        else:
            msg = TRACK_SELECTED_EN.format(
                n=selected, name=t["name_en"])
        send_whatsapp(sender, msg)
        return

    # ── 3. Detect contribution reference ──────────────────────────────────
    contrib_ref = detect_contribution_reference(text)

    # ── 4. Query Vertex AI ─────────────────────────────────────────────────
    try:
        answer, source_track = query_vertex_ai(
            text, state["history"], language,
            state["track"], contrib_ref
        )
    except Exception as e:
        app.logger.error(f"Vertex AI error: {e}")
        reply = OUT_OF_SCOPE_IT if language == "it" else OUT_OF_SCOPE_EN
        send_whatsapp(sender, reply)
        return

    # ── 5. Out of scope ────────────────────────────────────────────────────
    if "OUT_OF_SCOPE" in answer.upper():
        reply = OUT_OF_SCOPE_IT if language == "it" else OUT_OF_SCOPE_EN

    # ── 6. Answer from a different track → notify and update ──────────────
    elif source_track and state["track"] and source_track != state["track"]:
        t = TRACKS[source_track]
        if language == "it":
            reply = TRACK_SWITCH_IT.format(
                n=source_track, name=t["name_it"], answer=answer)
        else:
            reply = TRACK_SWITCH_EN.format(
                n=source_track, name=t["name_en"], answer=answer)
        state["track"] = source_track

    else:
        # Update track if not set and we detected a source
        if source_track and not state["track"]:
            state["track"] = source_track
        reply = answer

    # ── 7. Update history and send ─────────────────────────────────────────
    state["history"].append({"user": text, "assistant": reply})
    state["history"] = state["history"][-MAX_HISTORY:]
    send_whatsapp(sender, reply)


# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        app.logger.info("Webhook verified.")
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json(silent=True)
    app.logger.info(f"Payload: {json.dumps(data)}")
    try:
        value = data["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return jsonify({"status": "ok"}), 200
        message = value["messages"][0]
        if message.get("type") != "text":
            return jsonify({"status": "ok"}), 200
        sender = message["from"]
        text   = message["text"]["body"]
        handle_message(sender, text)
    except (KeyError, IndexError, TypeError) as e:
        app.logger.error(f"Parse error: {e}")
    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


# ─── WEB CHAT API ─────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def web_chat():
    """
    Web chat endpoint — used by the browser interface.
    Accepts JSON: { "message": "...", "session_id": "...", "track": "1"|"2"|"3"|null }
    Returns JSON: { "answer": "...", "track": "..." }
    """
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    user_message = data.get("message", "").strip()
    session_id   = data.get("session_id", "web-user")
    track_req    = data.get("track", None)

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Get or create session state
    state = get_state(f"web-{session_id}")

    # Override track if specified in request
    if track_req in ("1", "2", "3"):
        state["track"] = track_req

    language    = detect_language(user_message)
    contrib_ref = detect_contribution_reference(user_message)

    # Check for track selection in message
    selected = detect_track_selection(user_message)
    if selected:
        state["track"] = selected
        t = TRACKS[selected]
        name = t["name_it"] if language == "it" else t["name_en"]
        return jsonify({
            "answer": f"✅ Track {selected} selected: {name}.\n\nAsk me anything about the contributions in this track.",
            "track":  selected
        })

    try:
        answer, source_track = query_vertex_ai(
            user_message, state["history"], language,
            state["track"], contrib_ref
        )
    except Exception as e:
        app.logger.error(f"Vertex AI web error: {e}")
        msg = OUT_OF_SCOPE_IT if language == "it" else OUT_OF_SCOPE_EN
        return jsonify({"answer": msg, "track": state["track"]}), 200

    # Handle out of scope
    if "OUT_OF_SCOPE" in answer.upper():
        reply = OUT_OF_SCOPE_IT if language == "it" else OUT_OF_SCOPE_EN

    # Handle track switch
    elif source_track and state["track"] and source_track != state["track"]:
        t = TRACKS[source_track]
        name = t["name_it"] if language == "it" else t["name_en"]
        if language == "it":
            reply = TRACK_SWITCH_IT.format(n=source_track, name=name, answer=answer)
        else:
            reply = TRACK_SWITCH_EN.format(n=source_track, name=name, answer=answer)
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
    """Reset session state for a given session_id."""
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "web-user")
    key        = f"web-{session_id}"
    if key in user_state:
        del user_state[key]
    return jsonify({"status": "reset"})


# ─── WEB CHAT UI ──────────────────────────────────────────────────────────────

WEB_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>∀ISION_E — Conference Bot</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--surface:#111118;--surface2:#1a1a24;--border:#2a2a3a;--accent:#7c6af7;--accent2:#a78bfa;--text:#e8e8f0;--muted:#6b6b80;--bot:#1e1e2e;--user:#2d2257;--ok:#4ade80;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden;}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(ellipse 60% 40% at 20% 20%,rgba(124,106,247,.08) 0%,transparent 60%),radial-gradient(ellipse 40% 60% at 80% 80%,rgba(167,139,250,.06) 0%,transparent 60%);pointer-events:none;z-index:0;}
header{position:relative;z-index:10;padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;background:rgba(10,10,15,.9);backdrop-filter:blur(12px);}
.logo{font-family:'Space Mono',monospace;font-size:16px;font-weight:700;color:var(--accent2);}
.logo span{color:var(--muted);font-weight:400;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 6px var(--ok);animation:pulse 2s infinite;margin-left:auto;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.4;}}
.track-bar{position:relative;z-index:10;padding:10px 20px;border-bottom:1px solid var(--border);display:flex;gap:6px;background:rgba(10,10,15,.7);backdrop-filter:blur(8px);overflow-x:auto;}
.track-bar::-webkit-scrollbar{height:2px;}
.track-bar::-webkit-scrollbar-thumb{background:var(--border);}
.tbtn{padding:5px 12px;border-radius:16px;border:1px solid var(--border);background:transparent;color:var(--muted);font-size:11px;font-family:'Space Mono',monospace;cursor:pointer;transition:all .2s;white-space:nowrap;}
.tbtn:hover{border-color:var(--accent);color:var(--accent2);}
.tbtn.active{background:rgba(124,106,247,.15);border-color:var(--accent);color:var(--accent2);}
#msgs{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:14px;position:relative;z-index:1;}
#msgs::-webkit-scrollbar{width:3px;}
#msgs::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}
.msg{display:flex;gap:10px;max-width:82%;animation:fi .25s ease;}
@keyframes fi{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
.msg.user{align-self:flex-end;flex-direction:row-reverse;}
.msg.bot{align-self:flex-start;}
.av{width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-family:'Space Mono',monospace;font-size:9px;font-weight:700;flex-shrink:0;}
.av.b{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;}
.av.u{background:var(--surface2);border:1px solid var(--border);color:var(--muted);}
.bub{padding:10px 14px;border-radius:10px;font-size:13px;line-height:1.65;word-break:break-word;}
.bot .bub{background:var(--bot);border:1px solid var(--border);border-top-left-radius:2px;}
.user .bub{background:var(--user);border:1px solid rgba(124,106,247,.3);border-top-right-radius:2px;}
.badge{display:inline-block;padding:2px 7px;border-radius:9px;font-size:9px;font-family:'Space Mono',monospace;background:rgba(124,106,247,.15);border:1px solid rgba(124,106,247,.3);color:var(--accent2);margin-bottom:5px;}
.typing{display:flex;gap:3px;padding:12px 14px;background:var(--bot);border:1px solid var(--border);border-radius:10px;border-top-left-radius:2px;}
.typing span{width:5px;height:5px;border-radius:50%;background:var(--accent);animation:ty 1.2s infinite;}
.typing span:nth-child(2){animation-delay:.2s;}
.typing span:nth-child(3){animation-delay:.4s;}
@keyframes ty{0%,60%,100%{transform:translateY(0);opacity:.4;}30%{transform:translateY(-5px);opacity:1;}}
.input-area{position:relative;z-index:10;padding:14px 20px;border-top:1px solid var(--border);background:rgba(10,10,15,.9);backdrop-filter:blur(12px);display:flex;gap:10px;align-items:flex-end;}
#inp{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:10px 14px;color:var(--text);font-family:'DM Sans',sans-serif;font-size:13px;resize:none;outline:none;min-height:40px;max-height:100px;transition:border-color .2s;line-height:1.5;}
#inp:focus{border-color:var(--accent);}
#inp::placeholder{color:var(--muted);}
#send{width:40px;height:40px;border-radius:9px;border:none;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .2s;flex-shrink:0;}
#send:hover{transform:scale(1.05);}
#send:active{transform:scale(.95);}
#send:disabled{opacity:.4;cursor:not-allowed;transform:none;}
.welcome{text-align:center;padding:50px 20px;opacity:.55;}
.wtitle{font-family:'Space Mono',monospace;font-size:22px;color:var(--accent2);margin-bottom:8px;}
.wsub{font-size:12px;color:var(--muted);line-height:1.7;}
.reset-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:5px 10px;border-radius:7px;font-size:11px;cursor:pointer;font-family:'Space Mono',monospace;transition:all .2s;margin-left:8px;}
.reset-btn:hover{border-color:var(--accent);color:var(--accent2);}
</style>
</head>
<body>
<header>
  <div class="logo">∀ISION<span>_E</span></div>
  <div style="font-size:11px;color:var(--muted);font-family:'Space Mono',monospace;">Conference Bot</div>
  <div style="display:flex;align-items:center;gap:8px;margin-left:auto;">
    <button class="reset-btn" onclick="resetChat()">↺ Reset</button>
    <div class="dot"></div>
  </div>
</header>
<div class="track-bar">
  <button class="tbtn active" onclick="selTrack('all',this)">All Tracks</button>
  <button class="tbtn" onclick="selTrack('1',this)">T1 · Representation &amp; Design</button>
  <button class="tbtn" onclick="selTrack('2',this)">T2 · Heritage Conservation</button>
  <button class="tbtn" onclick="selTrack('3',this)">T3 · Education &amp; Learning</button>
</div>
<div id="msgs">
  <div class="welcome">
    <div class="wtitle">∀ISION_E</div>
    <div class="wsub">Welcome to the Conference Bot<br>Ask anything about the contributions, programme or logistics</div>
  </div>
</div>
<div class="input-area">
  <textarea id="inp" placeholder="Ask about the conference..." rows="1"
    onkeydown="handleKey(event)" oninput="resize(this)"></textarea>
  <button id="send" onclick="send()">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
  </button>
</div>
<script>
const TRACKS={'1':'AI for Representation and Design','2':'AI for Heritage Conservation and Enhancement','3':'AI for Education and Learning'};
let track='all', loading=false;
const sid='session-'+Math.random().toString(36).slice(2,9);

function selTrack(t,btn){
  track=t;
  document.querySelectorAll('.tbtn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(t!=='all'){
    addMsg('bot',`<span class="badge">TRACK ${t}</span><br>Switched to Track ${t}: <strong>${TRACKS[t]}</strong>. Ask me about the contributions.`);
  }
}

function addMsg(role,html){
  const m=document.getElementById('msgs');
  m.querySelector('.welcome')?.remove();
  const d=document.createElement('div');
  d.className=`msg ${role}`;
  const av=document.createElement('div');
  av.className=`av ${role==='bot'?'b':'u'}`;
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
    let html=data.answer?.replace(/\\n/g,'<br>')||'No response.';
    if(data.track&&data.track!==track&&track!=='all'){
      html=`<span class="badge">TRACK ${data.track}</span><br>`+html;
    }
    addMsg('bot',html);
  }catch(e){
    hideTyping();
    addMsg('bot','❌ Error connecting to the bot. Please try again.');
  }
  loading=false;
  document.getElementById('send').disabled=false;
  inp.focus();
}

async function resetChat(){
  await fetch('/chat/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid})});
  document.getElementById('msgs').innerHTML='<div class="welcome"><div class="wtitle">∀ISION_E</div><div class="wsub">Welcome to the Conference Bot<br>Ask anything about the contributions, programme or logistics</div></div>';
  track='all';
  document.querySelectorAll('.tbtn').forEach((b,i)=>{b.classList.toggle('active',i===0);});
}
</script>
</body>
</html>"""


@app.route("/", methods=["GET"])
def web_ui():
    """Serve the web chat interface."""
    return Response(WEB_UI, mimetype="text/html")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
