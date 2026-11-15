import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { HTTP_BASE } from "./config";
import { demoParts } from "./format";
import { useMediaQuery } from "./hooks";
import { initialState, reducer } from "./state";
import { useSocket } from "./useSocket";
import type { Cond, DemoItem } from "./types";
import Header from "./components/Header";
import LotBoard from "./components/LotBoard";
import Controls from "./components/Controls";
import Transcript from "./components/Transcript";
import Summary from "./components/Summary";
import ReviewQueue, { type Fields } from "./components/ReviewQueue";
import Ledger from "./components/Ledger";
import PlaybackBar from "./components/PlaybackBar";
import { Confirm, TokenDialog, Toast } from "./components/Dialogs";

type Theme = "dark" | "light";
const loadTheme = (): Theme => { try { return localStorage.getItem("ucc-theme") === "light" ? "light" : "dark"; } catch { return "dark"; } };

export default function App() {
  const [s, dispatch] = useReducer(reducer, initialState);
  const send = useSocket(dispatch);
  const [cond, setCond] = useState<Cond>("clean");
  const [speed, setSpeed] = useState(1);
  const [sound, setSound] = useState(true);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [toast, setToast] = useState<{ msg: string; kind: "error" | "success" | "info" } | null>(null);
  const [askReset, setAskReset] = useState(false);
  const [pending, setPending] = useState<{ lot: string; cond: string }[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const phone = useMediaQuery("(max-width: 1000px)");

  const notify = useCallback((msg: string, kind: "error" | "success" | "info" = "error") => {
    setToast({ msg, kind }); window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), kind === "success" ? 3200 : 5000);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("theming");                                   // short colour transition only while switching
    root.dataset.theme = theme;
    const t = window.setTimeout(() => root.classList.remove("theming"), 320);
    try { localStorage.setItem("ucc-theme", theme); } catch { /* private mode */ }
    return () => window.clearTimeout(t);
  }, [theme]);
  useEffect(() => { if (s.notice) notify(s.notice.message, s.notice.kind); }, [s.notice, notify]);

  // The clip's own audio plays in the browser while the ledger fills (the same file the server streams to the speech service).
  useEffect(() => {
    audio.current?.pause();
    if (!s.clip || !sound) return;
    const a = new Audio(HTTP_BASE + s.clip.audioUrl);
    a.playbackRate = s.clip.speed;
    a.play().catch(() => { /* autoplay blocked: the ledger still fills */ });
    audio.current = a;
    return () => a.pause();
  }, [s.clip?.id, sound]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!s.playing) audio.current?.pause(); }, [s.playing]);

  const effSpeed = s.mode === "live" ? 1 : speed;
  const start = useCallback((items: { lot: string; cond: string }[], token?: string) => {
    if (send({ type: "play", items, speed: effSpeed, token })) dispatch({ type: "play_sent" }); else notify("Not connected to the server yet. Please wait a moment.");
  }, [send, effSpeed, notify]);

  const play = useCallback((items: { lot: string; cond: string }[]) => {
    if (s.needsToken) {
      let tok: string | null = null;
      try { tok = sessionStorage.getItem("ucc-token"); } catch { /* ignore */ }
      if (!tok) { setPending(items); return; }
      start(items, tok); return;
    }
    start(items);
  }, [s.needsToken, start]);

  const itemFor = (d: DemoItem) => ({ lot: d.lot, cond: d.force_cond ?? cond });

  // confirm=false: an edit is saved as a correction only. confirm=true ("Save & Confirm" on the review card): a person also confirms it.
  const save = (id: number, f: Fields, confirm: boolean) => {
    if (!f.species || !f.price || !f.buyer) { notify("Please fill in the fish, price and buyer."); return; }
    send({ type: "update", id, species: f.species, price: Number(f.price), buyer: f.buyer });
    if (confirm) send({ type: "confirm", id });
  };

  const check = (id: number) => {
    const el = document.getElementById(`review-${id}`);
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); window.setTimeout(() => el.focus({ preventScroll: true }), 350); }
  };

  const receipt = async (id: number) => {
    setBusy(id);
    try {
      const r = await fetch(`${HTTP_BASE}/api/receipt/${id}`);
      if (!r.ok) { const j = await r.json().catch(() => ({})); notify("Receipt unavailable: " + (j.error ?? r.status)); return; }
      const a = new Audio(URL.createObjectURL(await r.blob()));
      await a.play();
    } catch (e) { notify("Receipt failed: " + (e as Error).message); } finally { setBusy(null); }
  };

  const playingDemo = s.playing && s.clip ? s.demo.find((d) => d.lot === s.clip!.lot) : undefined;

  return (
    <div className="app">
      <Header mode={s.mode} connected={s.connected} sound={sound} theme={theme}
        onSound={setSound} onTheme={() => setTheme(theme === "dark" ? "light" : "dark")} onReset={() => setAskReset(true)} />
      <main className="layout">
        <div className="area-board">
          {s.loaded
            ? <LotBoard board={s.board} clip={s.clip} processing={s.processing} live={s.mode === "live"} onCheck={check} />
            : <div className="hero skel" aria-busy="true" aria-label="Loading"><div className="skeleton w30" /><div className="skeleton w60 tall" /></div>}
        </div>
        <div className="area-controls">
          {s.loaded
            ? <Controls demo={s.demo} cond={cond} speed={effSpeed} mode={s.mode} playing={s.playing} clip={s.clip}
                onCond={setCond} onSpeed={setSpeed} onPlayOne={(d) => play([itemFor(d)])} onPlayAll={() => play(s.demo.map(itemFor))}
                onStop={() => send({ type: "stop" })} />
            : <div className="card panel" aria-busy="true"><div className="skeleton w60" /><div className="skeleton tall" /><div className="skeleton" /></div>}
        </div>
        <div className="area-main">
          <Summary lots={s.lots} />
          <ReviewQueue lots={s.lots} species={s.species} roster={s.roster} onSave={(id, f) => save(id, f, true)} />
          <Ledger lots={s.lots} species={s.species} roster={s.roster} flashId={s.flashId} busy={busy} loaded={s.loaded}
            onReceipt={receipt} onConfirm={(id) => send({ type: "confirm", id })} onSave={(id, f) => save(id, f, false)} onCheck={check} />
          <p className="source">
            {s.mode === "saved"
              ? "Source: saved Prisma transcripts of synthetic test auctions (Gnani Timbre voice), replayed at the speed of the audio. This is not a live call."
              : "Source: live Prisma speech-to-text."}
          </p>
        </div>
        <div className="area-transcript"><Transcript lines={s.lines} partial={s.partial} processing={s.processing} /></div>
      </main>
      {phone && s.playing && <PlaybackBar label={playingDemo ? demoParts(playingDemo).fish : s.clip?.lot ?? "audio"} onStop={() => send({ type: "stop" })} />}
      {askReset && <Confirm title="Clear the whole ledger?" body="This removes every lot and its history from this demo. Export the CSV first if you want to keep a copy."
        yes="Clear ledger" no="Keep it" danger onNo={() => setAskReset(false)} onYes={() => { send({ type: "reset" }); setAskReset(false); }} />}
      {pending && <TokenDialog onClose={() => setPending(null)} onSubmit={(t) => { try { sessionStorage.setItem("ucc-token", t); } catch { /* ignore */ } start(pending, t); setPending(null); }} />}
      <Toast message={toast?.msg ?? null} kind={toast?.kind ?? "info"} />
    </div>
  );
}
