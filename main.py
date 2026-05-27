# ONLY SHOWING NEW CORE LOGIC TO REPLACE

# ADD IMPORT
import google.generativeai as genai


# ─────────────────────────────────────────────────────────────
# GEMINI CONFIG
# ─────────────────────────────────────────────────────────────

genai.configure()

gemini_model = genai.GenerativeModel(
    "gemini-2.5-flash"
)


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
        "across papers",
        "state of the art",

        "confronta",
        "differenze",
        "somiglianze",
        "trend",
        "temi",
        "riassumi",
        "panoramica",
        "metodologie",
    ]

    if len(q.split()) > 14:
        return True

    return any(m in q for m in complex_markers)


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

Use ONLY the conference material provided below.

User query:
{query}

Conference material:
{context_text}

Instructions:
- Write a concise academic synthesis.
- Mention relevant papers naturally.
- Avoid raw snippet dumps.
- Compare contributions when useful.
- Keep the answer readable and elegant.
- Avoid hallucinations.
- If evidence is weak, say so briefly.

{lang_instruction}
"""

    response = gemini_model.generate_content(
        prompt
    )

    return response.text.strip()
