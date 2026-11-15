"""
mic_ws.py -- LIVE MICROPHONE.   browser mic --(16 kHz PCM16 over /ws/mic)--> this server --> Prisma realtime --> LotSegmenter --> ledger

It reuses exactly what the recorded-lot replay uses: PrismaStream, LotSegmenter, the ledger and the hub that updates every open browser.
Nothing in app.py changes except two appended lines.

Protocol on /ws/mic:  client sends BINARY frames (little-endian int16, 16 kHz, mono) and finally the text "stop".
                      server answers {"type":"ready"} once Prisma is connected (the client starts capturing only then, so audio goes in
                      at the pace it is spoken), or {"type":"error","message":...} and closes.
PITFALLS handled here:
  * the real server answers only after it HEARS silence after speech, so on stop we send ~1.2 s of silence before closing.
  * a microphone left on spends credits: sessions end by themselves after MIC_MAX_S seconds (default 20 minutes).
  * on a public URL the same PLAY_TOKEN that protects live playback protects the microphone.
"""
import asyncio
import os
import time

from fastapi import WebSocket

from stt_stream import PrismaStream, StreamError

FRAME = 1024                                   # bytes per frame sent to Prisma: 512 samples = 32 ms at 16 kHz
FRAME_S = FRAME / 32000
MAX_S = float(os.environ.get("MIC_MAX_S", 1200))


def mount_mic(app, g: dict) -> None:
    hub, ledger, lc = g["hub"], g["ledger"], g["lc"]
    state = {"active": False}

    @app.get("/api/mic")
    def mic_info():
        return {"available": bool(g.get("API_KEY")), "needs_token": bool(g.get("PLAY_TOKEN")), "active": state["active"], "max_seconds": MAX_S}

    async def emit(lot: dict, kind: str = "mic"):
        rec = ledger.add(lot, source="live", audio=kind)             # audio = "mic" or "file": the ledger always says which
        await hub.broadcast({"type": "lot", "lot": rec})

    @app.websocket("/ws/mic")
    async def ws_mic(ws: WebSocket):
        await ws.accept()

        async def refuse(message: str):
            try:
                await ws.send_json({"type": "error", "message": message})
                await ws.close()
            except Exception:
                pass

        key = g.get("API_KEY")
        if not key:
            return await refuse("Live recording needs the Gnani API key on the server. Start it with GNANI_API_KEY set.")
        if g.get("PLAY_TOKEN") and ws.query_params.get("token") != g["PLAY_TOKEN"]:
            return await refuse("This server needs its access token for live recording.")
        if state["active"]:
            return await refuse("A recording is still running or finishing. Please wait a moment.")
        if hub.task and not hub.task.done():
            return await refuse("A recorded lot is playing. Press Stop playback first.")

        kind = "file" if ws.query_params.get("source") == "file" else "mic"       # a file played in real time is NOT a microphone: label it honestly
        state["active"] = True
        seg = lc.LotSegmenter(g["SPECIES"], g["ROSTER"])
        q: asyncio.Queue = asyncio.Queue()
        tasks: list = []
        failure = None
        try:
            try:
                stream_cm = PrismaStream(key, url=os.environ.get("PRISMA_WS_URL") or None)
                stream = await stream_cm.__aenter__()
            except Exception as exc:                                    # bad key, no network, quota ...
                return await refuse(f"Could not reach the speech service: {type(exc).__name__}: {exc}")
            try:
                await ws.send_json({"type": "ready"})
                await hub.broadcast({"type": "clip", "state": "start", "lot": "live", "cond": kind, "seconds": 0, "speed": 1, "audio_url": ""})

                async def intake():                                      # browser -> queue
                    try:
                        while True:
                            m = await ws.receive()
                            if m["type"] == "websocket.disconnect":
                                break
                            if m.get("bytes"):
                                await q.put(m["bytes"])
                            elif m.get("text") == "stop":
                                break
                    except Exception:
                        pass
                    finally:
                        await q.put(None)

                async def feeder():                                      # queue -> Prisma, in 1024-byte frames
                    buf = bytearray()
                    t_end = time.monotonic() + MAX_S
                    while True:
                        try:
                            chunk = await asyncio.wait_for(q.get(), timeout=max(0.1, t_end - time.monotonic()))
                        except asyncio.TimeoutError:
                            chunk = None
                            await hub.broadcast({"type": "error", "message": f"Recording stopped after {int(MAX_S // 60)} minutes."})
                        if chunk is None:
                            break
                        buf += chunk
                        while len(buf) >= FRAME:
                            await stream.send(bytes(buf[:FRAME]))
                            del buf[:FRAME]
                    if buf:
                        await stream.send(bytes(buf).ljust(FRAME, b"\0"))
                    for _ in range(int(PrismaStream.PAD_SILENCE_S / FRAME_S)):      # let the server's VAD end the last utterance
                        await stream.send(bytes(FRAME))
                        await asyncio.sleep(FRAME_S)
                    await stream.finish()

                async def ticker():
                    while True:
                        await asyncio.sleep(0.5)
                        for lot in seg.tick():
                            await emit(lot, kind)

                async def reader():
                    async for tr in stream.results():
                        if tr.event == "speech_start":
                            await hub.broadcast({"type": "speech", "state": "start"})
                            continue
                        if tr.is_final:
                            await hub.broadcast({"type": "final", "text": tr.text})
                            for lot in seg.feed(tr.text):
                                await emit(lot, kind)
                            await hub.broadcast({"type": "live", "preview": seg.preview()})
                        else:
                            await hub.broadcast({"type": "partial", "text": tr.text})

                tasks = [asyncio.create_task(intake()), asyncio.create_task(feeder()), asyncio.create_task(ticker()), asyncio.create_task(reader())]
                done, _ = await asyncio.wait({tasks[1], tasks[3]}, return_when=asyncio.FIRST_EXCEPTION)
                for t in done:
                    if t.exception():
                        failure = t.exception()
                if failure is None:
                    await asyncio.gather(tasks[1], tasks[3], return_exceptions=True)
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await stream_cm.__aexit__(None, None, None)
            for lot in seg.flush():                                      # the recording ended mid-lot: flagged for a person to check
                await emit(lot, kind)
            await hub.broadcast({"type": "live", "preview": seg.preview()})
            if failure is not None:
                text = str(failure) if isinstance(failure, StreamError) else f"{type(failure).__name__}: {failure}"
                await hub.broadcast({"type": "error", "message": "The speech service stopped: " + text})
        finally:
            state["active"] = False
            await hub.broadcast({"type": "done"})
            try:
                await ws.close()
            except Exception:
                pass
