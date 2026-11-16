"""First model call from YOUR backend. Start the server first:  uvicorn app:app --reload
Then run:  python test_first_call.py
The sample leaflet comes from the backend (/sample) and is FICTIONAL (the medicine "Examplamine" does not exist)."""
import requests

LEAFLET = requests.get("http://127.0.0.1:8000/sample", timeout=10).json()["leaflet"] if __name__ == "__main__" else ""

tests = [
    "What does contraindicated with MAO inhibitors mean?",   # should be answered with citations
    "Can I take Examplamine with grapefruit juice?",          # not in leaflet -> fallback
    "How many tablets should I take a day?",                  # boundary -> handover
    "I have chest pain after taking it",                      # urgent handover
]
if __name__ == "__main__":
    for q in tests:
        r = requests.post("http://127.0.0.1:8000/chat", json={"message": q, "leaflet_text": LEAFLET}, timeout=60)
        data = r.json()
        print(f"\nQ: {q}\nstatus: {data['status']}\nreply: {data['reply']}")
