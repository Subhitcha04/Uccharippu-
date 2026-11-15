r"""test_receipt.py -- the spoken receipt: sentence text, Timbre's placeholder WAV header, caching. Mocked TTS response, no network.   python test_receipt.py"""
import io, json, os, struct, sys, wave
os.environ["STT_MODE"] = "saved"; os.environ["GNANI_API_KEY"] = "TESTKEY"
sys.stdout.reconfigure(encoding="utf-8")
from fastapi.testclient import TestClient
import app as A, ledger_core as lc

# 1. the sentences the clerk hears (spot-check by eye: price spelled in Tamil words)
for lot, want in [({"species": "நெத்திலி", "price": 800, "buyer": "கோபி"}, "நெத்திலி, எண்ணூறு ரூபாய், கோபி"),
                  ({"species": "இறால்", "price": 1450, "buyer": "அன்வர்"}, "இறால், ஆயிரத்து நானூற்று ஐம்பது ரூபாய், அன்வர்"),
                  ({"species": "சுறா", "price": 3500, "buyer": "இசக்கி"}, "சுறா, மூன்று ஆயிரத்து ஐநூறு ரூபாய், இசக்கி"),
                  ({"species": "சுறா", "price": 12345, "buyer": "ஜான்"}, "சுறா, 12345 ரூபாய், ஜான்"),          # odd price: digits, never a wrong word
                  ({"species": None, "price": 800, "buyer": None}, "எண்ணூறு ரூபாய்")]:
    got = lc.receipt_text(lot); assert got == want, (got, want); print("PASS receipt text:", got)

# 2. Timbre's WAV header declares data size 0xFFFFFFFF; the fix must produce a header the stdlib reads with the TRUE duration
pcm = b"\x01\x00" * 16000 * 2                                              # 2.0 s of 16 kHz mono PCM16
bad = b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) + b"data" + struct.pack("<I", 0xFFFFFFFF) + pcm
fixed = A.fix_wav_header(bad)
with wave.open(io.BytesIO(fixed)) as w:
    assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (16000, 1, 32000), "header not repaired"
print("PASS placeholder-size WAV repaired: 2.0 s, 16 kHz, mono")

# 3. the 200 path: a mocked TTS reply is repaired, cached, and not requested twice
calls = []
class R:
    status_code = 200; headers = {"Content-Type": "audio/wav"}; content = bad
import requests
requests.post = lambda url, headers=None, json=None, timeout=None: (calls.append((url, headers, json)) or R())
A.ledger.clear()
with TestClient(A.app) as c:
    A.ledger.add({"species": "நெத்திலி", "price": 800, "buyer": "கோபி", "seq": [800], "flags": [], "review": False, "transcript": "x"}, "saved")
    r1 = c.get("/api/receipt/1"); r2 = c.get("/api/receipt/1")
assert r1.status_code == 200 and r1.headers["content-type"] == "audio/wav" and r1.content == fixed, "receipt not served repaired"
url, hdr, body = calls[0]
assert len(calls) == 1 and r2.content == r1.content, "second request must come from the cache"
assert hdr == {"X-API-Key-ID": "TESTKEY"} and body["model"] == "timbre-v2.5" and body["voice"] == "Brinda" and body["language"] == "ta-IN" and body["text"] == "நெத்திலி, எண்ணூறு ரூபாய், கோபி"
print("PASS TTS request: model timbre-v2.5, voice Brinda, key only in the header, text = the receipt; reply repaired; 2nd request served from cache")
import shutil; shutil.rmtree(A.RECEIPTS, ignore_errors=True); A.ledger.clear()
print("\nRECEIPT TESTS PASSED")
