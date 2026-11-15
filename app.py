"""
app.py -- Uccharippu harbour ledger server.

    uvicorn app:app --port 8000                      (STT_MODE=saved by default: replays saved REAL Prisma transcripts, no credits)
    $env:STT_MODE="live"; $env:GNANI_API_KEY="..."    -> streams the demo audio to Prisma for real (UI shows LIVE)

Pipeline per clip:   WAV --(1024-byte frames, real-time pace)--> STT stream --> final text --> LotSegmenter --> Ledger --> browser
The browser never sees the API key and never talks to Prisma: browsers cannot set the upgrade headers the websocket needs.
"""
import asyncio
import hashlib
import json
import os
import pathlib
import struct
import time
import wave

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

import ledger_core as lc
from frontend_mount import mount_frontend
from stt_stream import PrismaStream, SavedStream

HERE = pathlib.Path(__file__).resolve().parent
DEMO = HERE / "demo"
RECEIPTS = HERE / "receipts"
MODE = os.environ.get("STT_MODE", "saved").lower()            # saved | live
API_KEY = os.environ.get("GNANI_API_KEY", "")
PLAY_TOKEN = os.environ.get("PLAY_TOKEN", "")                 # if set, live playback needs it (a public URL must not burn credits)
TTS_VOICE = os.environ.get("TTS_VOICE", "Brinda")
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"
FRAME_BYTES = 1024                                            # 512 samples = 32 ms of 16 kHz PCM16
FRAME_S = FRAME_BYTES / 32000

SPECIES = sorted(json.loads((HERE / "species_ta.json").read_text(encoding="utf-8"))["boost_candidates"])
ROSTER = json.loads((HERE / "roster.json").read_text(encoding="utf-8"))["buyers"]
ledger = lc.Ledger(HERE / "ledger.json")
app = FastAPI(title="Uccharippu harbour ledger")


mount_frontend(app)          # new React frontend at '/', old UI at '/legacy'
# ----------------------------------------------------------------------------- helpers
def read_pcm(path: pathlib.Path):
    """-> (pcm bytes, seconds). Only 16 kHz mono 16-bit WAV (what noise_mix.py writes) is accepted, with a clear error otherwise."""
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"{path.name}: need 16 kHz mono 16-bit WAV, got {w.getframerate()} Hz / {w.getnchannels()} ch")
        return w.readframes(w.getnframes()), w.getnframes() / 16000


def fix_wav_header(wav: bytes) -> bytes:
    """PITFALL: Timbre's WAV header declares a placeholder data size (0xFFFFFFFF); browsers then play it wrongly or not at all.
    Walk the RIFF chunks, ignore the declared size, and rewrite a correct header."""
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("not a WAV")
    pos, fmt = 12, None
    while pos + 8 <= len(wav):
        cid, size = wav[pos:pos + 4], struct.unpack("<I", wav[pos + 4:pos + 8])[0]
        if cid == b"fmt ":
            ch, rate = struct.unpack("<HI", wav[pos + 10:pos + 16])
            bits = struct.unpack("<H", wav[pos + 22:pos + 24])[0]
            fmt = (rate, ch, bits)
        elif cid == b"data":
            rate, ch, bits = fmt
            pcm = wav[pos + 8:]
            return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
                    struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits) +
                    b"data" + struct.pack("<I", len(pcm)) + pcm)
        pos += 8 + size + (size & 1)
    raise ValueError("no data chunk")


def load_saved() -> dict:
    p = DEMO / "saved_transcripts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_manifest() -> list:
    p = DEMO / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


# ----------------------------------------------------------------------------- hub
class Hub:
    def __init__(self):
        self.clients = set()
        self.task = None                      # the one running playback

    async def broadcast(self, event: dict):
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except Exception:
                self.clients.discard(ws)


hub = Hub()


def snapshot() -> dict:
    return {"type": "snapshot", "mode": MODE, "lots": ledger.lots, "species": SPECIES, "roster": ROSTER,
            "demo": load_manifest(), "live_needs_token": bool(PLAY_TOKEN) and MODE == "live", "playing": bool(hub.task and not hub.task.done())}


async def emit_lot(lot: dict, audio: str):
    rec = ledger.add(lot, source=MODE, audio=audio)
    await hub.broadcast({"type": "lot", "lot": rec})


# ----------------------------------------------------------------------------- the pipeline
async def send_audio(stream, pcm: bytes, speed: float):
    """Send 1024-byte frames on an ABSOLUTE schedule. PITFALL: sleeping a fixed 32 ms per frame drifts (Windows timers are ~15 ms
    coarse), so the audio would play slower than real time. Schedule against a start time instead."""
    start = time.monotonic()
    pcm = pcm + bytes(int(32000 * getattr(stream, "PAD_SILENCE_S", 0)))          # live: trailing silence lets the server's VAD end the last utterance
    for n, i in enumerate(range(0, len(pcm), FRAME_BYTES)):
        await stream.send(pcm[i:i + FRAME_BYTES])
        delay = start + (n + 1) * FRAME_S / speed - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
    await stream.finish()


async def tick_loop(seg: lc.LotSegmenter, audio: str):
    while True:
        await asyncio.sleep(0.5)
        for lot in seg.tick():
            await emit_lot(lot, audio)


async def run_clip(lot_id: str, cond: str, speed: float):
    path = DEMO / cond / f"{lot_id}.wav"
    pcm, dur = read_pcm(path)
    audio = f"{lot_id}/{cond}"
    seg = lc.LotSegmenter(SPECIES, ROSTER)
    if MODE == "live":
        stream = PrismaStream(API_KEY, url=os.environ.get("PRISMA_WS_URL") or None)       # PRISMA_WS_URL: only for tests against a mock server
    else:
        text = load_saved().get(f"{cond}/{lot_id}")
        if text is None:
            raise KeyError(f"no saved transcript for {cond}/{lot_id}")
        stream = SavedStream(text, dur)
    await hub.broadcast({"type": "clip", "state": "start", "lot": lot_id, "cond": cond, "seconds": round(dur, 1), "speed": speed,
                         "audio_url": f"/demo-audio/{cond}/{lot_id}.wav"})
    async with stream:
        sender = asyncio.create_task(send_audio(stream, pcm, speed))
        ticker = asyncio.create_task(tick_loop(seg, audio))
        try:
            async for tr in stream.results():
                if tr.event == "speech_start":
                    await hub.broadcast({"type": "speech", "state": "start"})
                    continue
                if tr.is_final:
                    await hub.broadcast({"type": "final", "text": tr.text})
                    for lot in seg.feed(tr.text):
                        await emit_lot(lot, audio)
                    await hub.broadcast({"type": "live", "preview": seg.preview()})
                else:
                    await hub.broadcast({"type": "partial", "text": tr.text})
            await sender
        finally:
            sender.cancel()
            ticker.cancel()
            await asyncio.gather(sender, ticker, return_exceptions=True)      # collect them so no 'exception never retrieved' noise
    for lot in seg.flush():                       # the clip ended: whatever is left is an incomplete lot, flagged for review
        await emit_lot(lot, audio)
    await hub.broadcast({"type": "live", "preview": seg.preview()})
    await hub.broadcast({"type": "clip", "state": "end", "lot": lot_id, "cond": cond})


async def play(items: list, speed: float, gap_s: float):
    try:
        for k, it in enumerate(items):
            await run_clip(it["lot"], it["cond"], speed)
            if k < len(items) - 1:
                await asyncio.sleep(gap_s / speed)
    except asyncio.CancelledError:
        raise
    except Exception as exc:                      # show the failure in the UI instead of dying silently
        await hub.broadcast({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        await hub.broadcast({"type": "done"})


# ----------------------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    await ws.send_json(snapshot())
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            try:
                if kind == "play":
                    if hub.task and not hub.task.done():
                        raise ValueError("already playing: press Stop first")
                    if MODE == "live" and PLAY_TOKEN and msg.get("token") != PLAY_TOKEN:
                        raise ValueError("live mode needs the access token")
                    items = [{"lot": str(i["lot"]), "cond": str(i["cond"])} for i in msg["items"]]
                    for it in items:                       # PITFALL: never build a path from raw client input
                        if not (it["lot"].startswith("lot") and it["lot"][3:].isdigit() and it["cond"] in ("clean", "snr20", "snr10", "snr5")):
                            raise ValueError("bad lot or condition")
                    speed = min(max(float(msg.get("speed", 1.0)), 0.5), 60.0)
                    if MODE == "live" and not os.environ.get("ALLOW_FAST_LIVE"):
                        speed = 1.0                         # PITFALL: a real-time voice-activity service expects audio at the pace it is spoken;
                        #                                     faster-than-real-time streaming is out of spec and a suspect for truncated lots
                    hub.task = asyncio.create_task(play(items, speed, gap_s=1.5))
                elif kind == "stop":
                    if hub.task and not hub.task.done():
                        hub.task.cancel()
                elif kind == "update":
                    f = {}
                    if "species" in msg:
                        if msg["species"] not in SPECIES:
                            raise ValueError("species must be one from the list")
                        f["species"] = msg["species"]
                    if "buyer" in msg:
                        if msg["buyer"] not in ROSTER:
                            raise ValueError("buyer must be one from the roster")
                        f["buyer"] = msg["buyer"]
                    if "price" in msg:
                        price = int(msg["price"])
                        if not 1 <= price <= 10_000_000:
                            raise ValueError("price out of range")
                        f["price"] = price
                    await hub.broadcast({"type": "lot", "lot": ledger.update(int(msg["id"]), **f)})
                elif kind == "confirm":
                    await hub.broadcast({"type": "lot", "lot": ledger.confirm(int(msg["id"]))})
                elif kind == "reset":
                    if hub.task and not hub.task.done():
                        hub.task.cancel()
                    ledger.clear()
                    await hub.broadcast(snapshot())
            except (ValueError, KeyError) as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


# ----------------------------------------------------------------------------- http
@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"mode": MODE, "lots": len(ledger.lots), "has_key": bool(API_KEY), "demo_clips": len(list(DEMO.glob("*/*.wav")))}


@app.get("/api/export.csv")
def export_csv():
    return Response(ledger.to_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=harbour_ledger.csv"})


@app.get("/api/receipt/{lot_id}")
async def receipt(lot_id: int):
    """Spoken receipt: Timbre reads '<species>, <price in words> ரூபாய், <buyer>' back to the clerk. Cached by text."""
    try:
        text = lc.receipt_text(ledger.get(lot_id))
    except KeyError:
        return JSONResponse({"error": "no such lot"}, status_code=404)
    RECEIPTS.mkdir(exist_ok=True)
    path = RECEIPTS / (hashlib.sha256(f"{text}|{TTS_VOICE}".encode("utf-8")).hexdigest()[:20] + ".wav")
    if path.exists():
        return Response(path.read_bytes(), media_type="audio/wav")
    if not API_KEY:
        return JSONResponse({"error": "no API key on the server and this receipt was not pre-generated", "text": text}, status_code=503)
    import requests
    body = {"text": text, "voice": TTS_VOICE, "model": "timbre-v2.5", "language": "ta-IN", "speed": 1.0,      # model: the SDK default (v2.0) now returns 400
            "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2, "encoding": "linear_pcm", "container": "wav"}}
    resp = await asyncio.to_thread(lambda: requests.post(TTS_URL, headers={"X-API-Key-ID": API_KEY}, json=body, timeout=60))
    if resp.status_code != 200 or "json" in resp.headers.get("Content-Type", "") or len(resp.content) < 1000:
        return JSONResponse({"error": f"TTS failed: HTTP {resp.status_code}", "text": text}, status_code=502)
    wav = fix_wav_header(resp.content)
    path.write_bytes(wav)
    return Response(wav, media_type="audio/wav")


@app.get("/demo-audio/{cond}/{name}")
def demo_audio(cond: str, name: str):
    """The browser plays the clip while the ledger fills. PITFALL: serve ONLY validated lotNN.wav paths: mounting the whole demo
    folder would also publish saved_transcripts.json and anything else dropped in there."""
    if cond not in ("clean", "snr20", "snr10", "snr5") or not (name.startswith("lot") and name.endswith(".wav") and name[3:-4].isdigit()):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = DEMO / cond / name
    return FileResponse(path, media_type="audio/wav") if path.exists() else JSONResponse({"error": "not found"}, status_code=404)


(HERE / "static").mkdir(exist_ok=True)
DEMO.mkdir(exist_ok=True)


# live microphone: browser -> /ws/mic -> Prisma -> ledger (see mic_ws.py)
from mic_ws import mount_mic  # noqa: E402
mount_mic(app, globals())
