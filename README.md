# Medication Safety Literacy Assistant: backend and chat page

A chatbot that explains medicine leaflets in plain words. It answers only from the leaflet text, shows the sentence each
answer comes from, and refuses dose, diagnosis and treatment questions. Principle: Explainability.

Everything here uses a FICTIONAL sample leaflet ("Examplamine"). Do not put real patient data into it.

## Files
| File | What it is |
|---|---|
| `app.py` | FastAPI backend: safeguards, leaflet chunking, retrieval, model call, citation check, feedback log |
| `index.html` | Chat page served at `/` (three-stage onboarding, source box, Arabic/English, large text, high contrast, read aloud) |
| `test_backend.py` | Offline tests (no API key needed) |
| `test_first_call.py` | Sends 4 test questions to your running server, which calls the real model |
| `requirements.txt`, `env.example` | Dependencies and Groq settings template |

## Run it
1. `python -m venv .venv` and activate it
2. `pip install -r requirements.txt`
3. Copy `env.example` to `.env` and set `LLM_API_KEY` to your Groq API key. Never commit `.env`.
4. `uvicorn app:app --reload`
5. Open http://127.0.0.1:8000/ in your browser

The backend uses Groq's OpenAI-compatible API. Set `MODEL_NAME` to a model ID enabled for your Groq account. `LLM_BASE_URL` defaults to `https://api.groq.com/openai/v1`.

## Test it
- `python test_backend.py` runs 18 offline checks of the safeguards, citation check, retry and error paths.
- `python test_first_call.py` (server running) makes real model calls.

## How an answer is made
1. Safeguards run first: dose, diagnosis, treatment and emergency questions never reach the model.
2. The leaflet is split by section into chunks (S1, S2, ...). The best chunks for the question are retrieved.
3. The model is told to answer only from those chunks, cite chunk IDs, and quote a short sentence.
4. Code checks that cited IDs exist and quoted sentences really appear in the chunks. One retry, then the fallback message.
5. The page shows the answer, only the cited sections, and the quoted sentence highlighted.

## Known limits
- Safeguards are keyword rules. Test them against your red-team prompts and improve them.
- Retrieval is a keyword baseline with a tiny Arabic-to-English bridge. Typed Arabic questions are matched poorly until
  multilingual embeddings are added.
- The word explanations are a draft list of 5 terms. Have a pharmacist review them.
- This is a student prototype, not medical advice.

## Team commits
Every team member must commit from their own account. Never upload API keys or `feedback.db`.
