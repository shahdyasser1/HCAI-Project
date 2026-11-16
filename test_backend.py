"""Offline tests for the backend (no API key needed: the model call is replaced by a fake).
Run:  python test_backend.py
These tests check the safeguards, retrieval, citation check, retry and error paths.
They do NOT test the real model: use test_first_call.py with your own API key for that."""
from fastapi.testclient import TestClient
import app as A

client = TestClient(A.app)
LEAFLET = A.SAMPLE_LEAFLET

def post(q, leaflet=LEAFLET):
    return client.post("/chat", json={"message": q, "leaflet_text": leaflet}).json()

def no_model(*_a, **_k):
    raise AssertionError("the model must not be called for this question")

def check(name, got, expected):
    ok = got == expected
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  (expected {expected!r}, got {got!r})"))
    return ok

results = []
A.call_model = no_model
results.append(check("dose question is blocked before the model", post("How many tablets should I take a day?")["status"], "boundary"))
results.append(check("Arabic dose question is blocked", post("كم قرص آخذ في اليوم؟")["status"], "boundary"))
results.append(check("diagnosis question is blocked", post("Do I have a liver problem? My eyes look yellow.")["status"], "boundary"))
results.append(check("chest pain gets the urgent message", post("I have chest pain and trouble breathing after taking it.")["status"], "urgent"))
results.append(check("swollen face gets the urgent message", post("My face and lips are swollen after I took it.")["status"], "urgent"))
results.append(check("too many tablets gets the urgent message", post("I think I took too many tablets by mistake.")["status"], "urgent"))
results.append(check("greeting gets a friendly reply", post("hello")["status"], "clarify"))
results.append(check("too short is clarified", post("?")["status"], "clarify"))
results.append(check("unrelated question falls back without the model", post("Who won the football match yesterday?")["status"], "fallback"))
results.append(check("empty leaflet is an error message", post("What are the side effects?", "")["status"], "error"))

A.call_model = lambda s, u: "NOT_IN_LEAFLET"
results.append(check("interaction question reaches the model, then falls back", post("Can I take Examplamine with grapefruit juice?")["status"], "fallback"))

A.call_model = lambda s, u: 'Contraindicated means it must not be used together with MAO inhibitors [S3]. The leaflet says "contraindicated with MAO inhibitors" [S3].'
r = post("What does contraindicated with MAO inhibitors mean?")
results.append(check("good answer is accepted", r["status"], "answered"))
results.append(check("only the cited section is returned as source", [s["id"] for s in r["sources"]], ["S3"]))
results.append(check("the quoted sentence is returned for highlighting", r["quotes"], ["contraindicated with MAO inhibitors"]))

calls = {"n": 0}
def wrong_id(s, u):
    calls["n"] += 1
    return "It is safe with everything [S9]."
A.call_model = wrong_id
results.append(check("unknown citation ID: fallback", post("What does contraindicated with MAO inhibitors mean?")["status"], "fallback"))
results.append(check("unknown citation ID: retried once", calls["n"], 2))

A.call_model = lambda s, u: 'It is fine. The leaflet says "totally safe for everyone" [S3].'
results.append(check("invented quote: fallback", post("What does contraindicated with MAO inhibitors mean?")["status"], "fallback"))

def boom(s, u): raise RuntimeError("network")
A.call_model = boom
results.append(check("model or network failure: friendly error", post("What does contraindicated with MAO inhibitors mean?")["status"], "error"))

print(f"\n{sum(results)} of {len(results)} checks passed")
raise SystemExit(0 if all(results) else 1)
