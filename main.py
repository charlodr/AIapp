import os
import re
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
# STATIC LOGISTICS
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
    lower = text.lower().strip()
    for key, triggers in LOGISTICS_TRIGGERS.items():
        if any(t in lower for t in triggers):
            return LOGISTICS[key][language]
    return None


# ─────────────────────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────────────────────

def get_session(sid):
    if sid not in sessions:
        sessions[sid] = {"track": None, "history": []}
    return sessions[sid]


# ─────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────

def gcp_token():
    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token



# ─────────────────────────────────────────────────────────────
# BUCKET LISTING — list papers directly from Cloud Storage
# ─────────────────────────────────────────────────────────────

BUCKET_NAME = os.environ.get("BUCKET_NAME", "visione-bucket")


def list_papers_from_bucket(track=None):
    """List paper filenames directly from the GCS bucket."""
    token = gcp_token()
    results = {}

    tracks_to_list = [track] if track else ["1", "2", "3"]

    for t in tracks_to_list:
        prefix = f"track{t}/"
        url = (
            f"https://storage.googleapis.com/storage/v1/b/{BUCKET_NAME}/o"
            f"?prefix={prefix}&fields=items(name)"
        )
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code != 200:
            continue

        items = resp.json().get("items", [])
        papers = []
        for item in items:
            name = item["name"]
            # Strip folder prefix and .pdf extension, clean up filename
            filename = name.replace(prefix, "").replace(".pdf", "").strip()
            if filename:
                papers.append(filename)

        results[t] = papers

    return results


def format_paper_list(bucket_results, language="en"):
    """Format bucket listing into a readable response."""
    lines = []
    for t, papers in sorted(bucket_results.items()):
        track_name = TRACKS.get(t, f"Track {t}")
        if language == "it":
            lines.append(f"**Track {t} — {track_name}** ({len(papers)} contributi):")
        else:
            lines.append(f"**Track {t} — {track_name}** ({len(papers)} contributions):")
        for p in papers:
            lines.append(f"\u2022 {p}")
        lines.append("")
    return "\n".join(lines).strip()

# ─────────────────────────────────────────────────────────────
# LANGUAGE
# ─────────────────────────────────────────────────────────────

def is_italian(text):
    markers = [
        " il ", " la ", " le ", " gli ", " della ", " del ",
        " non ", " per ", " con ", " una ", " sono ",
        "ciao", "grazie", "come", "dove", "quando", "cosa",
        "riguardo", "pausa", "programma", "orari", "sede",
    ]
    lower = " " + text.lower() + " "
    return sum(1 for m in markers if m in lower) >= 2


# ─────────────────────────────────────────────────────────────
# TRACK DETECTION
# ─────────────────────────────────────────────────────────────

def detect_track(text):
    clean = text.strip().lower()
    valid = {
        "1": "1", "2": "2", "3": "3",
        "track 1": "1", "track 2": "2", "track 3": "3",
        "track1": "1", "track2": "2", "track3": "3",
    }
    return valid.get(clean)


# ─────────────────────────────────────────────────────────────
# PREAMBLE
# ─────────────────────────────────────────────────────────────

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
        "ConferenceDay.pdf (conference programme — use ONLY for schedule, session times, "
        "keynote slots and pitch timings), "
        "ScientificCommittee.pdf (scientific committee members and affiliations), "
        "track1_*.pdf (full academic papers for Track 1 — AI for Representation and Design), "
        "track2_*.pdf (full academic papers for Track 2 — AI for Heritage Conservation), "
        "track3_*.pdf (full academic papers for Track 3 — AI for Education and Learning). "
        "For paper content, abstracts, authors or research use the track_*.pdf files. "
        "For schedule and timing questions use ConferenceDay.pdf. "
        "Provide complete detailed answers about papers and research. "
        "If information is not in the documents say so briefly. "
        f"{track_instr}"
        f"{lang_instr}"
    )



# ─────────────────────────────────────────────────────────────
# PAPERS LIST — hardcoded from ContributionsList_Tracks.xlsx
# ─────────────────────────────────────────────────────────────

PAPERS = {
    "1": [
        ("Intimacy as Agency: Rethinking the Artist Through Human\u2013AI Creative Relations", "Mor Peled"),
        ("Regenerating matter: computational design processes for the reuse of manufacturing waste", "Giorgio Buratti, Andrea Rossi"),
        ("Algorithmic Ideology and Epistemic Erasure: A Methodological Intervention", "Tommaso Durante"),
        ("The phenomenology of \"EkphrAIsis\". Intersection of the verbal and the visual in the age of Artificial Intelligence", "Donato Maniello, Lorena Cangiano"),
        ("Co-Creation with AI: Artistic Practices as Critical Laboratories", "Mathilde Nourisson-Moncey"),
        ("Attuning to computational creativity: A socio-technical imaginary", "Jasmin Pfefferkorn, Emilie K. Sunde"),
        ("Portraits, Staffage and Back Figures: Patterns for addressing the public resulting from human-machine collaborations", "Anna Schober"),
        ("Arduino Research Lab. A framework for AI integration within user research processes at company scale", "Martina Ricca"),
        ("Extended Bodies: Representations of the Human Body and Extended Intelligences between Art, Neuroscience, and Generative AI", "Chiara Canali"),
        ("Posthuman Cartography: between Human Imagination and Machine Intelligence", "Maria Medushevskaya"),
        ("Toward a Minor Ethico-Aesthetics of Machine Relationality", "Isil Ezgi Celik"),
        ("From Human-Machine Co-Creativity to Distributed Creativity: The Case of AI Integration in Filmmaking", "Pierluigi Masai, Lorenzo Carta, Mateusz Miroslaw Lis"),
        ("Folding with the Machine: Recursive Co-Construction in Large Language Models", "Philipe Barsamian"),
        ("Generative AI as a Visual Mediator for Landscape Governance: A Customizable Pipeline for Participatory Design Scenarios", "Andrea Migliosi, Fabio Bianconi, Marco Filippucci"),
        ("Evoking New Urban Imaginaries Through Generative AI", "Greta Montanari, Andrea Giordano, Federica Maietti"),
        ("Co-generating Visions: Inclusive Representation and Reflective Visuality in the Era of Extended Intelligences", "Tiziana Iorio, Alessia Segalerba"),
        ("Human\u2013AI Co-Design for Construction Management: Integrating BIM and Large Language Models for morphological exploration", "Daniela Antonelli, Matteo Del Giudice, Fabio Manzone"),
        ("VISIO LIMINALIS: Visionary Narratives of AI", "Cesare Battelli"),
        ("Artificial Exaptation in Design: Intersemiotic Translation and Metasemic Writing", "Fabrizio Gay, Irene Cazzaro"),
        ("The Second Coming of the Creative Director: Redefining the Role of the Artist in the Age of AI", "Bill Balaskas"),
        ("Bridging BIM and Diffusion Models: Local ControlNet-Based Rendering for Early Design Exploration", "Giulio Lucio Sergio Sacco, Matilde Ridella"),
        ("Postcards from Solaris: AI Interpretations of Lem's Speculative \"Architecture\"", "Paola Sabbion, Gian Luca Porcile"),
        ("The Designer Does Not Play Dice", "Emiliano Cappellini"),
        ("LLM-DRIVEN REPRESENTATION. An AI-Augmented Computational Workflows for CNC Fabrication", "Michele Calvano, Roberto Cognoli"),
        ("From Noise to Intention: \"Artistic Intention\" in Hybrid Autoregressive\u2013Diffusion Pipelines and Diffusion Language Models for Drawing with AI", "Giovanni Rasetti"),
        ("Generative UI as a new vision to draw usable interfaces", "Elena Benedetto"),
        ("From Prompt to Geometry. A Critical Assessment of NLP Tools for Modeling Vaulted Systems", "Fabrizio Natta, Andrea Tomalini, Melanie Nicole Giler Pinargote"),
        ("AI and Representation Discipline: The REAACH Symposium Observatory", "Andrea Giordano, Michele Russo, Roberta Spallone"),
    ],
    "2": [
        ("Collaborative Futures: Human\u2013AI Ecologies in the Documentation of Intangible Heritage", "Gabriella Giannachi, Gaby Wijers, Annet Dekker, Steve Benford, Rachael Garrett, Karen Lancel, Hermen Maat"),
        ("From Absence to Simulation: Generative AI-Based Digital Reconstruction of Lost Architectural Elements. A Case Study on the Corinthian Capital of Temple B in Largo Argentina, Rome", "Giorgia Mingotto, Nicola Gulmini, Graziano Mario Valenti"),
        ("Restore the damaged frame: using generative image editing models for plausible film restoration", "Erica Andreose, Mateusz Miroslaw Lis, Massimo Toniato"),
        ("Extended Intelligence for Built Heritage: AI, Ontologies and Knowledge Graphs in Data Interpretation", "Chiara Marcantonio, Federica Maietti"),
        ("AI and Intangible Cultural Heritage Protection: Sensitive Data and Cultural Misinterpretation Challenges in Preserving Southwest China's Folk Dance Traditions", "MingZhu Zhang"),
        ("The sketch in motion. The landscape of Calle Nueva York in Berisso, Argentina", "Anal\u00eda Jara, Camila Mart\u00edn, Mar\u00eda Bel\u00e9n Trivi"),
        ("Quantifying Interpretive Deviations in AI-Generated 3D Architectural Models", "Chiara Mommi, Fabio Bianconi, Marco Filippucci"),
        ("Giving Voice to Absent Matter: Human\u2013Machine Narrative Practices for Endangered Mediterranean Heritage", "Maria Trombetta"),
        ("From semantic segmentation to image-to-3D processes: a methodological framework for the extensive modeling and valorization of archival documents", "Sonia Mollica"),
        ("Drawing, AI and Built Heritage Conservation: From Metric Rigour to Perceptual Depth, the Rotonda di San Tom\u00e8 Case Study", "Alessio Cardaci, Antonella Versaci, Pietro Azzola"),
        ("Is AI biased? Some thoughts from the Cultural Heritage perspective", "Veronica Tronconi"),
        ("Artificial Intelligence and Integrity: Digital Documentation of Disappearing Rural Built Heritage in UNESCO Landscapes", "Benjamin Ennemoser, Fabrizio Aimar"),
    ],
    "3": [
        ("Data-Driven Group Formation in Architectural Design Studios: An Extended-Intelligence Method with a Case Study", "Ali JahaniRahaei, Michele Armando, Giacomo Chiesa"),
        ("Cultivating Sympoietic Literacy: Reimagining Design Education in the AI Era", "Ian McArthur"),
        ("Drawing the Imaginary: AI-Augmented Representation of Visual Memory in Architectural Culture", "Francesca Condorelli"),
        ("Generative AI as a cognitive mediator: reducing cognitive load and fostering creative autonomy in VR design education", "Daniele Rossi, Francesca Cicero"),
        ("Art Odyssey Vehicles: Redefining Cultural Equity through Mobile Immersive Learning Hubs", "Martha Ioannidou, Argyro Ioannidou"),
        ("Speaking with Artefacts of the Future: how AI can raise techno-ethical awareness", "Joanna Sleigh, Alessandro Blasimme, Rita Sevastjanova"),
        ("Synthetic Futures: Decolonising design futuring through synthetic data", "Sarah Cosentino"),
        ("Echoes of the Oracle: Accelerating Heritage Gamification with AI process", "Alessandro Basso, Maurizio Perticarini"),
    ],
}


def format_papers_static(track=None, language="en"):
    """Return hardcoded paper list for given track(s)."""
    tracks_to_show = [track] if track else ["1", "2", "3"]
    lines = []
    for t in tracks_to_show:
        track_name = TRACKS.get(t, f"Track {t}")
        count = len(PAPERS[t])
        if language == "it":
            lines.append(f"**Track {t} \u2014 {track_name}** ({count} contributi):\n")
        else:
            lines.append(f"**Track {t} \u2014 {track_name}** ({count} contributions):\n")
        for title, authors in PAPERS[t]:
            lines.append(f"\u2022 {title} \u2014 {authors}")
        lines.append("")
    return "\n".join(lines).strip()

# ─────────────────────────────────────────────────────────────
# VERTEX AI
# ─────────────────────────────────────────────────────────────

LIST_TRIGGERS = [
    "list all papers", "list papers", "all papers", "all contributions",
    "papers in track", "contributions in track", "papers and authors",
    "what are the papers", "elenca i paper", "elenca i contributi",
    "tutti i paper", "tutti i contributi",
]


def ask_vertex(query, track=None, language="en"):
    token = gcp_token()
    lower_q = query.lower()

    # Detect list-papers intent → return hardcoded list
    if any(t in lower_q for t in LIST_TRIGGERS):
        effective_track = track
        m = re.search(r'track[\s]*([123])', lower_q)
        if m:
            effective_track = m.group(1)
        return format_papers_static(effective_track, language)

    # Detect schedule/speaker timing queries → use ConferenceDay.pdf
    elif any(t in lower_q for t in [
        "what time", "when does", "when is", "what slot", "time slot",
        "speaking", "speak", "speaker", "pitch", "pitching", "pitches",
        "presentation", "presenting", "presents", "talk", "talking",
        "session time", "scheduled", "on stage", "takes the floor",
        "a che ora", "quando parla", "quando presenta", "orario di",
        "intervento di", "presentazione di", "pitch di", "slot di",
    ]):
        query = (
            f"Using the ConferenceDay.pdf cronoprogram, what is the scheduled time "
            f"for the following: {query}? "
            f"Look for the name or title in the session schedule and return the exact time slot."
        )

    # Enrich very short queries with conference context
    elif len(query.strip().split()) <= 3:
        query = (
            f"Tell me about '{query}' in the context of the "
            f"VISION_E conference contributions and papers"
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
    return data.get("answer", {}).get("answerText", "").strip()


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

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
        name = TRACKS[detected]
        reply = (
            f"Track {detected} selezionato: **{name}**."
            if language == "it"
            else f"Track {detected} selected: **{name}**."
        )
        return jsonify({"answer": reply, "track": detected, "language": language})

    # Static logistics — bypass Vertex AI
    logistics_answer = check_logistics(message, language)
    if logistics_answer:
        return jsonify({
            "answer": logistics_answer,
            "track": session.get("track"),
            "language": language,
        })

    # Vertex AI
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
