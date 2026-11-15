r"""
test_app.py -- end-to-end test of the server in SAVED mode (no network, no credits).   python test_app.py
Needs demo/ and auction_script_val2.json (the answer key) next to this file.
Checks that the pipeline reproduces the validated answers, that low-confidence lots are flagged, and the edit/confirm/export/security paths.
"""
import json
import os
import pathlib
import sys

os.environ["STT_MODE"] = "saved"
os.environ.pop("GNANI_API_KEY", None)
sys.stdout.reconfigure(encoding="utf-8")
from fastapi.testclient import TestClient

import app as A

HERE = pathlib.Path(__file__).resolve().parent
KEY = {l["id"]: l for l in json.loads((HERE / "auction_script_val2.json").read_text(encoding="utf-8"))["lots"]}
SURE = ["lot61", "lot55", "lot62", "lot52", "lot70"]            # arm B was right on these at ALL four noise levels in validation 2
passed = []


def check(name, cond, detail=""):
    assert cond, f"FAIL: {name} {detail}"
    passed.append(name)
    print("PASS", name)


def collect(ws, until="done", limit=2000):
    events = []
    for _ in range(limit):
        e = ws.receive_json()
        events.append(e)
        if e["type"] == until:
            return events
    raise AssertionError("never reached " + until)


A.ledger.clear()
with TestClient(A.app) as client:
    h = client.get("/api/health").json()
    check("health: saved mode, demo clips present", h["mode"] == "saved" and h["demo_clips"] >= 24, h)
    with client.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        check("snapshot has species list, roster and 6 demo lots", snap["type"] == "snapshot" and len(snap["roster"]) == 20 and len(snap["demo"]) == 6 and len(snap["species"]) > 50)

        # -- 1. play the five reliable lots at clean and at 10 dB, fast
        for cond in ("clean", "snr10"):
            ws.send_json({"type": "play", "items": [{"lot": l, "cond": cond} for l in SURE], "speed": 60})
            ev = collect(ws)
            lots = [e["lot"] for e in ev if e["type"] == "lot"]
            check(f"{cond}: 5 clips -> exactly 5 lots", len(lots) == 5, [l["audio"] for l in lots])
            for l in lots:
                lid = l["audio"].split("/")[0]
                t = KEY[lid]
                check(f"{cond} {lid}: {t['species']} Rs{t['final_price']} {t['buyer']} reproduced",
                      (l["species"], l["price"], l["buyer"]) == (t["species"], t["final_price"], t["buyer"]) and l["status"] == "ok",
                      (l["species"], l["price"], l["buyer"], l["status"], l["flags"]))
            check(f"{cond}: partial and final text were streamed, scoreboard updated", any(e["type"] == "partial" for e in ev) and any(e["type"] == "final" for e in ev) and any(e["type"] == "live" and e["preview"]["price"] for e in ev))
        n_before = len(A.ledger.lots)

        # -- 2. the flagged lot
        ws.send_json({"type": "play", "items": [{"lot": "lot63", "cond": "snr10"}], "speed": 60})
        lots = [e["lot"] for e in collect(ws) if e["type"] == "lot"]
        bad = lots[-1]
        check("lot63@10dB: flagged for review, buyer not guessed", bad["status"] == "review" and bad["buyer"] is None and "buyer?" in bad["flags"], (bad["status"], bad["buyer"], bad["flags"]))
        check("lot63@10dB: species and price still captured", bad["species"] == KEY["lot63"]["species"] and bad["price"] is not None)

        # -- 3. confirm refuses a half-empty lot; edit fixes it; the audit trail keeps what the machine heard
        ws.send_json({"type": "confirm", "id": bad["id"]})
        check("cannot confirm a lot with a missing buyer", ws.receive_json()["type"] == "error")
        ws.send_json({"type": "update", "id": bad["id"], "buyer": "NOT-A-BUYER"})
        check("a buyer outside the roster is rejected", ws.receive_json()["type"] == "error")
        ws.send_json({"type": "update", "id": bad["id"], "buyer": KEY["lot63"]["buyer"], "price": KEY["lot63"]["final_price"]})
        fixed = ws.receive_json()["lot"]
        check("edit: status corrected, values now match the truth", fixed["status"] == "corrected" and fixed["buyer"] == KEY["lot63"]["buyer"] and fixed["price"] == KEY["lot63"]["final_price"])
        check("edit: machine's original answer is preserved", fixed["original"]["buyer"] is None and len(fixed["history"]) == 1 and fixed["history"][0]["changes"]["buyer"]["from"] is None)
        ws.send_json({"type": "confirm", "id": bad["id"]})
        check("confirm after fixing works", ws.receive_json()["lot"].get("confirmed") is True)

        # -- 4. bad input never reaches the filesystem or the ledger
        ws.send_json({"type": "play", "items": [{"lot": "../../etc/passwd", "cond": "clean"}], "speed": 1})
        check("path traversal in a lot name is rejected", ws.receive_json()["type"] == "error")
        ws.send_json({"type": "play", "items": [{"lot": "lot61", "cond": "../x"}], "speed": 1})
        check("path traversal in the noise level is rejected", ws.receive_json()["type"] == "error")
        ws.send_json({"type": "update", "id": 1, "price": -5})
        check("a negative price is rejected", ws.receive_json()["type"] == "error")
        ws.send_json({"type": "play", "items": [{"lot": "lot99", "cond": "clean"}], "speed": 60})
        ev = collect(ws)
        check("a missing clip shows an error, not a crash", any(e["type"] == "error" for e in ev) and ev[-1]["type"] == "done")

    # -- 5. http
    csv_text = client.get("/api/export.csv").content.decode("utf-8")
    rows = csv_text.lstrip("\ufeff").strip().splitlines()
    check("CSV export: header + all lots, Tamil intact, BOM for Excel", len(rows) == 1 + n_before + 1 and KEY["lot61"]["species"] in csv_text and csv_text.startswith("\ufeff"), len(rows))
    r = client.get("/api/receipt/1")
    check("receipt without a key or cache is a clear 503 with the sentence it would say", r.status_code == 503 and r.json().get("text"), r.text)
    check("receipt for an unknown lot is 404", client.get("/api/receipt/9999").status_code == 404)
    check("demo audio route serves a real clip", client.get("/demo-audio/clean/lot61.wav").status_code == 200)
    check("demo audio route does NOT serve saved_transcripts.json", client.get("/demo-audio/clean/saved_transcripts.json").status_code == 404 and client.get("/demo-audio/..%2Fmanifest.json/x").status_code == 404)
    check("the page itself is served", "Uccharippu" in client.get("/").text)

A.ledger.clear()
print(f"\nALL {len(passed)} CHECKS PASSED")
