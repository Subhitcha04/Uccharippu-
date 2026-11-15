"""
stt_stream.py -- one interface, two sources of transcript text.

    SavedStream   replays a SAVED real Prisma transcript, released in proportion to the audio actually sent.
                  Offline demo, tests, and the safety net if the network or credits fail on camera. The UI labels it SAVED.
    PrismaStream  the live websocket (wss://api.vachana.ai/stt/v3/stream): API key and lang_code headers, raw PCM16 frames, one final
                  transcript per utterance (the server answers after it hears silence).

Both: `async with stream:` -> `await stream.send(pcm)` (raw PCM16, 16 kHz, mono) -> `await stream.finish()` ->
`async for tr in stream.results()` yields Transcript(text, is_final).
"""
import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime

BYTES_PER_SECOND = 32000          # 16 kHz * 2 bytes


class StreamError(RuntimeError):
    """The server said something is wrong (missing header, bad key, ...). Shown to the user: silence would look like 'no speech'."""


@dataclass
class Transcript:
    text: str
    is_final: bool
    event: str = "text"          # "text", or "speech_start": the server's VAD heard speech begin (no words yet)


# ----------------------------------------------------------------------------- saved replay
class SavedStream:
    def __init__(self, text: str, duration_s: float, chunk_words: int = 4):
        self.words = (text or "").split()
        self.duration_s = max(duration_s, 0.1)
        self.chunk_words = chunk_words
        self.sent = 0                 # bytes of audio sent so far: THIS paces the text, so replay speed follows the sender
        self.done = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, pcm: bytes):
        self.sent += len(pcm)

    async def finish(self):
        self.done = True

    async def results(self):
        emitted, last_partial = 0, ""
        while True:
            frac = 1.0 if self.done else min(1.0, self.sent / (self.duration_s * BYTES_PER_SECOND))
            avail = len(self.words) if self.done else int(len(self.words) * frac)
            while avail - emitted >= self.chunk_words or (self.done and avail > emitted):
                n = min(self.chunk_words, avail - emitted)
                yield Transcript(" ".join(self.words[emitted:emitted + n]), True)
                emitted += n
                last_partial = ""
            if avail > emitted:                                   # words heard but not yet a full chunk: show as a partial
                part = " ".join(self.words[emitted:avail])
                if part != last_partial:
                    last_partial = part
                    yield Transcript(part, False)
            if self.done and emitted >= len(self.words):
                return
            await asyncio.sleep(0.03)


# ----------------------------------------------------------------------------- live websocket
def normalize(raw, default_final: bool = False, force_final: bool = False) -> "Transcript | None":
    """Turn ONE websocket message into a Transcript, or None to ignore it.

    Tolerant on purpose: it accepts the field names the REST API uses ('transcript', 'output.literal') and a few common
    flag names. PITFALL: if the server sends PARTIALS and we mistake them for finals, every word is counted several times
    and the ledger fills with ghost lots. When in doubt we treat a message as NOT final.
    """
    if isinstance(raw, (bytes, bytearray)):
        return None
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None
    if str(msg.get("type", "")).lower() == "error" or (msg.get("error") and not msg.get("transcript")):
        # Seen from the real server: {"type":"error","message":"lang_code header is required (e.g. kn-IN, hi-IN)"}
        raise StreamError(str(msg.get("message") or msg.get("error")))
    out = msg.get("output") if isinstance(msg.get("output"), dict) else {}
    text = (msg.get("transcript") or msg.get("text") or out.get("literal") or out.get("transcript") or "").strip()
    if not text:
        return None
    flag = next((msg[k] for k in ("is_final", "isFinal", "final", "speech_final") if k in msg), None)
    if flag is None and isinstance(msg.get("type"), str):
        ty = msg["type"].lower()                  # only KNOWN markers decide; an unknown type (e.g. "transcript") stays undecided
        if ty in ("final", "transcript_final", "final_transcript"):
            flag = True
        elif ty in ("partial", "interim", "partial_transcript", "transcript_partial"):
            flag = False
    if flag is None:
        flag = default_final                      # the real server said partials_enabled=false: every transcript it sends is final
    return Transcript(text, True if force_final else bool(flag))


class PrismaStream:
    URL = "wss://api.vachana.ai/stt/v3/stream"
    # Measured on the real server (21 Oct 2026): it returns ONE transcript per utterance, about 0.4 s after it HEARS silence
    # following the speech. Without silence in the audio it never answers.
    TAIL_S = float(__import__("os").environ.get("PRISMA_TAIL_S", 6.0))       # most we wait for an answer after the last frame
    QUIET_S = float(__import__("os").environ.get("PRISMA_QUIET_S", 0.6))     # ... and we close once every utterance is answered and the line is quiet this long
    PAD_SILENCE_S = float(__import__("os").environ.get("PRISMA_PAD_S", 1.2)) # trailing silence appended after a CLIP (a live microphone supplies its own)

    def __init__(self, api_key: str, language: str = "ta-IN", extra_headers: dict = None, url: str = None):
        self.api_key, self.language, self.url = api_key, language, url or self.URL
        self.extra_headers = extra_headers or {}
        self.ws = None
        self.config = {}                           # filled from the server's first message: {"type":"connected","config":{...}}
        self.started, self.answered = set(), set() # utterance ids: speech_start seen / transcript received
        self.last_msg = time.monotonic()
        self.t0 = time.monotonic()
        self.finish_reason = None                  # "answered" | "deadline" | "closed by server": WHY we stopped waiting
        self.log_path = os.environ.get("PRISMA_LOG", "live_log.jsonl")     # every message, with times: the evidence when a lot comes back short. "" disables.

    def _log(self, **kw):
        if not self.log_path:
            return
        rec = {"t": round(time.monotonic() - self.t0, 3), "wall": datetime.now().isoformat(timespec="milliseconds"), **kw}
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass                                                    # logging must never break a lot

    async def __aenter__(self):
        try:
            from websockets.asyncio.client import connect          # websockets >= 13
            kw = "additional_headers"
        except ImportError:                                         # older websockets
            from websockets import connect
            kw = "extra_headers"
        # PITFALL: browsers cannot set these upgrade headers, which is why audio goes browser -> OUR server -> Prisma.
        # lang_code: REQUIRED, per the server's own error message when it was missing (21 Oct 2026). Header name has an
        # underscore, which some proxies strip: if a deployment behind a proxy loses it, that is why.
        headers = {"X-API-Key-ID": self.api_key, **({"lang_code": self.language} if self.language else {}), **self.extra_headers}
        self.ws = await connect(self.url, max_size=None, **{kw: headers})
        self.t0 = time.monotonic()
        self._log(dir="app", event="connected")
        return self

    async def __aexit__(self, *exc):
        if self.ws:
            await self.ws.close()
        return False

    async def send(self, pcm: bytes):
        try:
            await self.ws.send(pcm)                                 # raw binary frames of 1024 bytes
        except Exception as exc:
            if "close" not in type(exc).__name__.lower():
                raise
            await self._raise_server_reason(exc)

    async def _raise_server_reason(self, cause):
        """PITFALL: when the server hangs up (missing header, bad key, quota), a bare 'ConnectionClosedError 1008' is all send() sees,
        but the server usually sent its REASON as a message just before. Read what is still buffered and report that instead."""
        try:
            while True:
                normalize(await asyncio.wait_for(self.ws.recv(), 0.5))      # raises StreamError if the buffered message is an error
        except StreamError:
            raise
        except Exception:
            pass
        raise StreamError(f"the server closed the connection (code {getattr(self.ws, 'close_code', None)}: "
                          f"{getattr(self.ws, 'close_reason', '') or 'no reason given'})") from cause

    async def finish(self):
        """Close when every utterance the server started has been answered and the line has been quiet for QUIET_S; never wait more than
        TAIL_S. (No explicit end-of-audio message was seen in the real server's traffic.)"""
        self._log(dir="app", event="audio_done", pending=sorted(self.started - self.answered))
        t_wait, deadline, self.finish_reason = time.monotonic(), time.monotonic() + self.TAIL_S, "deadline"
        while time.monotonic() < deadline:
            if not (self.started - self.answered) and time.monotonic() - self.last_msg >= self.QUIET_S:
                self.finish_reason = "answered"
                break
            await asyncio.sleep(0.1)
        self._log(dir="app", event="closing", reason=self.finish_reason, waited_s=round(time.monotonic() - t_wait, 2),
                  still_pending=sorted(self.started - self.answered))
        await self.ws.close()

    def _learn_config(self, raw):
        """The server's first message states its settings (sample_rate 16000, chunk_size 512, partials_enabled, format 'verbatim').
        Remember them: they decide how transcripts are interpreted. Also track which utterances have been answered."""
        self.last_msg = time.monotonic()
        if isinstance(raw, (bytes, bytearray)):
            return None
        try:
            msg = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(msg, dict):
            return None
        kind = msg.get("type")
        self._log(dir="recv", type=kind, utterance_id=msg.get("utterance_id"), segment_index=msg.get("segment_index"),
                  is_final=msg.get("is_final"), audio_duration_ms=msg.get("audio_duration_ms"), latency=msg.get("latency"),
                  text=msg.get("text") or msg.get("transcript"), message=msg.get("message") if kind == "error" else None)
        if msg.get("type") == "connected" and isinstance(msg.get("config"), dict):
            self.config = msg["config"]
        elif msg.get("type") == "speech_start" and msg.get("utterance_id"):
            self.started.add(msg["utterance_id"])
        elif msg.get("utterance_id") and (msg.get("text") or msg.get("transcript")):
            self.answered.add(msg["utterance_id"])
        return kind

    async def results(self):
        try:
            async for raw in self.ws:
                if self._learn_config(raw) == "speech_start":
                    yield Transcript("", False, "speech_start")            # lets the UI show 'hearing speech' while the transcript is pending
                    continue
                off = self.config.get("partials_enabled") is False     # partials off: anything the server sends with text is a FINAL, whatever its flag says
                tr = normalize(raw, default_final=off, force_final=off)
                if tr:
                    yield tr
        except StreamError:
            raise                                                   # a server error message: let the app show it
        except Exception as exc:                                    # connection closed by us or by the server
            if "close" not in type(exc).__name__.lower():
                raise