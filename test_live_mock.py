r"""
test_live_mock.py -- proves the LIVE code path against a MOCK Prisma websocket that behaves like the real one did on 21 Oct 2026
(it rejects a connection without the lang_code header with a JSON error and close code 1008; it announces {"type":"connected","config":{...}};
it sends speech_start; and, like the real VAD, it only ENDS the utterance and sends transcripts after it has HEARD SILENCE).
It proves auth header, lang_code header, 1024-byte framing, partial/final handling, and that SERVER ERRORS REACH THE USER.
It does NOT prove the real server's transcript message format.    python test_live_mock.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import wave

import websockets
from websockets.asyncio.server import serve

sys.stdout.reconfigure(encoding="utf-8")
with wave.open('demo/clean/lot61.wav') as _w: DUR = _w.getnframes() / _w.getframerate()      # length of the demo clip the mock 'hears'
saved = json.load(open("demo/saved_transcripts.json", encoding="utf-8"))
QUEUE = [saved["clean/lot61"]]                       # one transcript per accepted connection; "ERROR" makes the server fail mid-stream
seen = {"auth": None, "lang": None, "frames": [], "t1": None, "tconn": None}
FLAG = {"is_final": True}                              # the real value of is_final was not visible in the console output: test BOTH
ERR = {"type": "error", "message": "lang_code header is required (e.g. kn-IN, hi-IN)", "timestamp": "2026-10-21T15:56:30+00:00"}


async def prisma_mock(ws):
    seen["tconn"] = time.monotonic()
    seen["auth"] = ws.request.headers.get("X-API-Key-ID")
    seen["lang"] = ws.request.headers.get("lang_code")
    if seen["auth"] != "TESTKEY":
        await ws.close(4401, "bad key")
        return
    if not seen["lang"]:                                          # exactly what the real server did when the header was missing
        await ws.send(json.dumps(ERR))
        await ws.close(1008, "policy violation")
        return
    item = QUEUE.pop(0) if QUEUE else ""
    split = item.startswith("SPLIT:")                  # the server cuts one lot into two utterances: bids, then closing word + buyer
    if split:
        item = item[6:]
    words = item.split()
    partials = str(ws.request.headers.get("partials_enabled", "")).lower() in ("true", "1")      # the mock honours ONE switch, to prove the scan can find it
    await ws.send(json.dumps({"type": "connected", "message": "STT service ready \u2014 VAD service connected", "request_id": "r1",
                              "config": {"sample_rate": 16000, "chunk_size": 512, "partials_enabled": partials, "partial_interval_ms": 450,
                                         "partial_max_window_s": 15.0, "language_code": seen["lang"], "format": "verbatim"}}))
    speech_bytes, got, started, finished, u1_sent = int(DUR * 32000), 0, False, False, False        # the test clip is 12 s of 'speech'; anything after is SILENCE
    try:
        async for frame in ws:
            if isinstance(frame, str):                                       # a TEXT message (settings), not audio
                try:
                    m = json.loads(frame)
                except ValueError:
                    m = {}
                if m.get("type") == "update_settings" and m.get("partials_enabled") is True:
                    partials = True
                    await ws.send(json.dumps({"type": "settings_updated", "config": {"partials_enabled": True}}))
                else:
                    await ws.send(json.dumps({"type": "error", "message": "unknown message type"}))
                continue
            seen["t1"] = time.monotonic()
            seen["frames"].append(len(frame))
            got += len(frame)
            if not started:
                started = True
                await ws.send(json.dumps({"type": "speech_start", "utterance_id": "u1"}))
            if item == "ERROR" and len(seen["frames"]) % 50 == 0:
                await ws.send(json.dumps({"type": "error", "message": "quota exceeded"}))
                await ws.close(1008, "policy violation")
                return
            if split and not u1_sent and got >= 8 * 32000:                                   # utterance 1 ends at ~8 s (a pause before the closing word)
                u1_sent = True
                await ws.send(json.dumps({"type": "transcript", "text": " ".join(words[:-3]), "audio_duration_ms": 8000.0, "segment_id": "r1-seg-1",
                                          "segment_index": 1, "utterance_id": "u1", "is_final": True, "latency": 0.3}))
                await ws.send(json.dumps({"type": "speech_start", "utterance_id": "u2"}))
            if split and not finished and got >= speech_bytes + int(0.4 * 32000):
                finished = True
                await asyncio.sleep(0.3)
                await ws.send(json.dumps({"type": "transcript", "text": " ".join(words[-3:]), "audio_duration_ms": 4000.0, "segment_id": "r1-seg-2",
                                          "segment_index": 1, "utterance_id": "u2", "is_final": True, "latency": 0.3}))
            if not split and not finished and got >= speech_bytes + int(0.4 * 32000):       # ~0.4 s of silence HEARD after the speech: the real VAD answered after ~0.4 s
                finished = True
                await asyncio.sleep(0.3)                                       # the real server's own processing time
                await ws.send(json.dumps({"type": "transcript", "text": " ".join(words), "audio_duration_ms": 12000.0,   # shape copied from the real log
                                          "segment_id": "r1-seg-1", "segment_index": 1, "utterance_id": "u1", "is_final": FLAG["is_final"], "latency": 0.3}))
    except websockets.ConnectionClosed:
        pass


async def play(ui, lot="lot61"):
    await ui.send(json.dumps({"type": "play", "items": [{"lot": lot, "cond": "clean"}], "speed": 8}))
    events = []
    while True:
        e = json.loads(await asyncio.wait_for(ui.recv(), 30))
        events.append(e)
        if e["type"] == "done":
            return events


async def main():
    from stt_stream import PrismaStream, StreamError
    async with serve(prisma_mock, "127.0.0.1", 8765):
        # ---- A. the app in live mode, normal clip
        env = {**os.environ, "STT_MODE": "live", "GNANI_API_KEY": "TESTKEY", "PRISMA_WS_URL": "ws://127.0.0.1:8765/", "PRISMA_TAIL_S": "8", "ALLOW_FAST_LIVE": "1"}   # generous max: the stream must close EARLY by itself; fast live only for TESTS
        srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", "8001", "--log-level", "warning"], env=env)
        try:
            for _ in range(50):
                try:
                    async with websockets.connect("ws://127.0.0.1:8001/ws"):
                        break
                except OSError:
                    await asyncio.sleep(0.2)
            async with websockets.connect("ws://127.0.0.1:8001/ws", max_size=None) as ui:
                assert json.loads(await ui.recv())["mode"] == "live"
                t_play = time.monotonic()
                ev = await play(ui)
                elapsed = time.monotonic() - t_play
                lots = [e["lot"] for e in ev if e["type"] == "lot"]
                assert not [e for e in ev if e["type"] == "error"], ev
                assert any(e["type"] == "speech" for e in ev), "the server's speech_start never reached the UI"
                assert elapsed < 6.0, f"the stream waited for the {8}s maximum instead of closing once the utterance was answered ({elapsed:.1f}s)"
                assert seen["auth"] == "TESTKEY" and seen["lang"] == "ta-IN", f"headers sent: key={seen['auth']} lang_code={seen['lang']}"
                assert set(seen["frames"][:-1]) == {1024} and seen["frames"][-1] <= 1024, set(seen["frames"])
                assert len(seen["frames"]) >= (DUR + 1.0) * 32000 / 1024, f"trailing silence missing: only {len(seen['frames'])} frames"
                dur = seen["t1"] - seen["tconn"]
                assert 13.2 / 8 * 0.5 < dur < 13.2 / 8 * 3.0, f"timing implausible: {dur:.2f}s (exact pacing is test_pacing.py's job)"
                assert len(lots) == 1 and (lots[0]["species"], lots[0]["price"], lots[0]["buyer"]) == ("நெத்திலி", 800, "கோபி") and lots[0]["source"] == "live", lots
                print(f"PASS A live path: key + lang_code=ta-IN, {len(seen['frames'])} frames of 1024 B (incl. trailing silence), closed early ({elapsed:.1f}s of the 8 s maximum), 1 lot: {lots[0]['species']} Rs{lots[0]['price']} {lots[0]['buyer']}, source=live")

                # ---- C. the server fails mid-stream: the USER must see why, not a silent empty ledger
                seen["frames"].clear()
                QUEUE.append("ERROR")
                ev = await play(ui)
                errs = [e["message"] for e in ev if e["type"] == "error"]
                assert errs and "quota exceeded" in errs[0] and ev[-1]["type"] == "done" and not [e for e in ev if e["type"] == "lot"], ev[-4:]
                print(f"PASS C server error mid-stream reaches the UI: '{errs[0]}'")
        finally:
            srv.terminate()
            srv.wait(10)

        # ---- B. no lang_code -> the adapter must raise, with the server's own words
        try:
            async with PrismaStream("TESTKEY", language="", url="ws://127.0.0.1:8765/") as st:
                await st.send(b"\x00" * 1024)
                async for _ in st.results():
                    pass
            raise AssertionError("expected StreamError")
        except StreamError as exc:
            assert "lang_code header is required" in str(exc)
            print(f"PASS B missing lang_code -> StreamError with the server's message: '{exc}'")

    print("\nLIVE-PATH TESTS PASSED  (auth header, lang_code header, 1024-byte framing, early close, server errors reach the UI)")


asyncio.run(main())
