"""
Medication Safety Literacy Assistant - Week 5 starter backend.

What it does:
  1. Safeguards: refuses dose / diagnosis / treatment questions and flags emergencies
     BEFORE any model call (human handover).
  2. Splits the pasted leaflet into sections (chunks) and picks the best ones for the question.
  3. Calls the model with strict grounding rules (answer only from chunks, cite chunk IDs).
  4. Verifies the citations in code. If they fail, it retries once, then returns the fallback message.

Weeks 6-7 additions: chat page served at "/" (index.html), /sample leaflet, /feedback log (SQLite).

Run:  uvicorn app:app --reload
Open: http://127.0.0.1:8000/        (chat page)
Docs: http://127.0.0.1:8000/docs
"""
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()

MODEL = os.getenv("MODEL_NAME", "qwen/qwen3.8-27b")
MAX_QUESTION_CHARS = 500
MAX_LEAFLET_CHARS = 20000

app = FastAPI(title="Medication Safety Literacy Assistant (Week 5)")

# ---------------------------------------------------------------- messages
FALLBACK = ("That is not in your leaflet, so I cannot answer it. "
            "You can rephrase the question, go back to the sections, or ask a pharmacist.")
BOUNDARY = ("I cannot advise on doses, diagnosis or treatment. "
            "Please ask your pharmacist or doctor. I can explain what your leaflet says about this medicine.")
URGENT = ("Serious symptoms need urgent help. Please contact your local emergency number "
          "or go to the nearest emergency department now.")
CLARIFY = "I did not fully understand. Do you mean a specific warning, side effect or term in the leaflet?"
SYSTEM_ERROR = "Something went wrong on my side. Your leaflet is still here. Please try again."
EMPTY_LEAFLET = "I could not read a leaflet. Please paste the leaflet text or try the sample."

# ---------------------------------------------------------------- safeguards
# Simple keyword rules for the first version. Replace with a classifier later and test with the
# 20 red-team prompts from the objectives (O2). Arabic keywords are a starting point only.
BOUNDARY_PATTERNS = [
    r"\bhow (much|many)\b.*\b(take|dose|tablet|pill|capsule)", r"\bdos(e|age)\b", r"\bshould i (take|stop|skip|double)\b",
    r"\bcan i (stop|skip|double)\b", r"\bcan i (take|have|use)\b(?!.*\bwith\b)", r"\bwhat (do|should) i take for\b", r"\bdo i have\b", r"\bdiagnos",
    r"\bwhich (medicine|drug) is best\b", r"\binstead of\b.*\b(medicine|drug|tablet)",
    r"جرعة", r"كام (قرص|حبة|مرة)", r"كم (قرص|حبة|مرة|حبوب)", r"اخد|آخذ|اوقف|أوقف|أبطل",
]
EMERGENCY_PATTERNS = [
    r"chest pain", r"too many (tablets|pills|capsules)|took (extra|too much)|accidentally (took|swallowed)", r"(face|lips|tongue|throat) (is|are|feel|feels|got|became) swollen", r"can.?t breathe|cannot breathe|trouble breathing|short(ness)? of breath", r"swollen (face|lips|tongue|throat)",
    r"faint(ed|ing)|passed out|unconscious", r"overdos", r"suicid", r"seizure", r"severe allergic",
    r"ألم في الصدر|مش قادر اتنفس|اغماء|إغماء|جرعة زائدة",
]

GREETINGS = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "مرحبا", "اهلا", "أهلا", "شكرا", "شكراً", "السلام عليكم"}
GREETING_REPLY = "Hi! Ask me about a section of your leaflet, for example the warnings or the side effects."

def check_safeguards(question: str) -> Optional[str]:
    q = question.lower()
    if any(re.search(p, q) for p in EMERGENCY_PATTERNS):
        return "urgent"
    if any(re.search(p, q) for p in BOUNDARY_PATTERNS):
        return "boundary"
    return None

# ---------------------------------------------------------------- chunking + retrieval
SECTION_TITLES = [
    "what it is for", "what is it for", "indications", "do not take", "contraindications", "warnings",
    "precautions", "interactions", "side effects", "adverse reactions", "ingredients", "how to store", "how to take",
]

def split_into_chunks(leaflet: str) -> list[dict]:
    """Split on lines that look like section titles. Each chunk gets an ID like S1, S2, ..."""
    chunks, title, buf = [], "Start", []
    def flush():
        text = " ".join(buf).strip()
        if text:
            chunks.append({"id": f"S{len(chunks) + 1}", "section": title, "text": text})
    for line in leaflet.splitlines():
        stripped = line.strip().rstrip(":")
        if stripped and len(stripped) < 40 and not line.strip().endswith(".") and any(t in stripped.lower() for t in SECTION_TITLES):
            flush(); title, buf = stripped, []
        elif stripped:
            buf.append(stripped)
    flush()
    return chunks

STOPWORDS = {"the", "a", "an", "is", "are", "was", "of", "in", "on", "to", "and", "or", "it", "this", "that", "with",
             "for", "i", "my", "me", "do", "does", "what", "how", "can", "if", "you", "your", "be", "have", "not", "any"}

def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS and len(w) > 1}

# Tiny Arabic-to-English bridge so the keyword baseline can match an English leaflet.
# Replace with multilingual embeddings (for example multilingual-e5) and a vector store.
AR_EN = {"جانبية": "side effects", "الآثار": "side effects", "اثار": "side effects", "تحذير": "warnings", "تحذيرات": "warnings",
         "ممنوع": "contraindicated", "تداخل": "interactions", "يتداخل": "interactions", "فائدة": "for", "مكونات": "ingredients",
         "تخزين": "store", "نعاس": "drowsiness", "كحول": "alcohol", "حمل": "pregnant", "رضاعة": "breastfeeding"}

def expand_arabic(question: str) -> str:
    extra = " ".join(en for ar, en in AR_EN.items() if ar in question)
    return question + " " + extra

def retrieve(question: str, chunks: list[dict], k: int = 3) -> list[dict]:
    """Keyword-overlap baseline. Later: swap for embeddings + a vector store."""
    q = tokens(expand_arabic(question))
    scored = sorted(chunks, key=lambda c: len(q & tokens(c["section"] + " " + c["text"])), reverse=True)
    return [c for c in scored[:k] if q & tokens(c["section"] + " " + c["text"])]

# ---------------------------------------------------------------- model call
def build_system_prompt(language: str, level: str) -> str:
    return f"""You explain medicine leaflets in plain language. Reply in {language}. Reading level: {level}.
Rules:
1. Use ONLY the leaflet chunks provided. Do not use outside knowledge about the medicine.
2. After each statement, cite the chunk ID in square brackets, for example [S2].
3. Include one short quote (under 15 words) copied exactly from a chunk, in double quotes, with its chunk ID.
4. If the chunks do not answer the question, reply with exactly: NOT_IN_LEAFLET
5. Never give dosage, diagnosis or treatment advice and never say whether the user should take or stop a medicine.
6. Explain medical terms in simple words. Keep the answer under 120 words."""

def call_model(system: str, user: str) -> str:
    from openai import OpenAI

    api_key = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Set LLM_API_KEY in .env to your Groq API key.")

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL") or "https://api.groq.com/openai/v1",
    )
    response = client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=600,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    answer = response.choices[0].message.content
    if not answer:
        raise RuntimeError("Groq returned an empty response.")
    return answer

def verify_citations(answer: str, used_chunks: list[dict]) -> bool:
    """Every [Sx] must be a real chunk ID, and every quoted sentence must appear in a chunk."""
    ids = {c["id"] for c in used_chunks}
    cited = set(re.findall(r"\[(S\d+)\]", answer))
    if not cited or not cited <= ids:
        return False
    all_text = " ".join(c["text"] for c in used_chunks).lower()
    quotes = re.findall(r"[\"\u201c](.+?)[\"\u201d]", answer)
    return all(q.lower().strip(" .") in all_text for q in quotes)

# ---------------------------------------------------------------- API
class ChatRequest(BaseModel):
    message: str
    leaflet_text: str = ""
    language: str = "English"
    level: str = "Simple"

class ChatResponse(BaseModel):
    status: str  # answered | boundary | urgent | fallback | clarify | error
    reply: str
    sources: list[dict] = []
    quotes: list[str] = []
    answer_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])

@app.get("/health")
def health():
    return {"ok": True, "model": MODEL}

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    question = req.message.strip()
    if len(question) < 3 or len(question) > MAX_QUESTION_CHARS:
        return ChatResponse(status="clarify", reply=CLARIFY)

    if question.lower().strip(" !?.") in GREETINGS:
        return ChatResponse(status="clarify", reply=GREETING_REPLY)

    # 1) safeguards first: no model call for blocked questions
    flag = check_safeguards(question)
    if flag == "urgent":
        return ChatResponse(status="urgent", reply=URGENT)
    if flag == "boundary":
        return ChatResponse(status="boundary", reply=BOUNDARY)

    # 2) leaflet check, chunking and retrieval
    leaflet = req.leaflet_text[:MAX_LEAFLET_CHARS]
    chunks = split_into_chunks(leaflet)
    if not chunks:
        return ChatResponse(status="error", reply=EMPTY_LEAFLET)
    used = retrieve(question, chunks)
    if not used:
        return ChatResponse(status="fallback", reply=FALLBACK)

    # 3) model call with grounding rules, 4) citation check, one retry, then fallback
    context = "\n\n".join(f"[{c['id']}] ({c['section']}) {c['text']}" for c in used)
    user_msg = f"Leaflet chunks:\n{context}\n\nQuestion: {question}"
    system = build_system_prompt(req.language, req.level)
    for _ in range(2):
        try:
            answer = call_model(system, user_msg)
        except Exception:
            return ChatResponse(status="error", reply=SYSTEM_ERROR)
        if "NOT_IN_LEAFLET" in answer:
            return ChatResponse(status="fallback", reply=FALLBACK)
        if verify_citations(answer, used):
            cited = set(re.findall(r"\[(S\d+)\]", answer))
            quotes = re.findall(r"[\"\u201c](.+?)[\"\u201d]", answer)
            # Show only the sections the answer actually cites, and the quoted sentences to highlight.
            return ChatResponse(status="answered", reply=answer, sources=[c for c in used if c["id"] in cited], quotes=quotes)
    return ChatResponse(status="fallback", reply=FALLBACK)


# ---------------------------------------------------------------- Weeks 6-7: chat page, sample, feedback
SAMPLE_LEAFLET = """Examplamine tablets (fictional medicine for training only)

What it is for
Examplamine tablets are used to relieve mild headache.

Do not take if
Do not use Examplamine if you are allergic to examplamine or to any other ingredient of this medicine.
Examplamine is contraindicated with MAO inhibitors, a group of medicines used for depression.
Do not use Examplamine if you have severe liver disease.

Warnings
Examplamine may cause drowsiness. Do not drive or use machines if you feel drowsy.
Avoid alcohol while taking Examplamine.
Ask your doctor or pharmacist before use if you are pregnant or breastfeeding.
Tell your doctor if you have kidney problems.

Interactions with other medicines
Tell your doctor or pharmacist if you are taking or have recently taken any other medicines, including MAO inhibitors and other medicines for headache.

How to take
Swallow the tablet whole with a glass of water, with or after food. Follow the instructions given by your doctor or pharmacist.

Side effects
Common: nausea, dizziness. Rare: skin rash.
Stop taking the medicine and get urgent medical help if you have swelling of the face, lips or tongue, or difficulty breathing.

Ingredients
Active ingredient: examplamine. Other ingredients: lactose, maize starch, magnesium stearate and gelatin (animal origin).

How to store
Store below 25 C. Keep out of the sight and reach of children.
"""

FEEDBACK_DB = Path(__file__).parent / "feedback.db"

class FeedbackRequest(BaseModel):
    answer_id: str
    reason: str  # unclear | wrong | missing
    comment: str = ""
    status: str = ""

@app.get("/")
def home():
    return FileResponse(Path(__file__).parent / "index.html")

@app.get("/sample")
def sample():
    return {"leaflet": SAMPLE_LEAFLET}

@app.post("/feedback")
def feedback(req: FeedbackRequest):
    """Stores the flag with the answer ID only. Never store names, contact details or the user's own medicines."""
    reason = req.reason if req.reason in {"unclear", "wrong", "missing"} else "other"
    con = sqlite3.connect(FEEDBACK_DB)
    con.execute("CREATE TABLE IF NOT EXISTS feedback (ts TEXT, answer_id TEXT, status TEXT, reason TEXT, comment TEXT)")
    con.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), req.answer_id, req.status, reason, req.comment[:500]))
    con.commit(); con.close()
    return {"ok": True}
