import type { Clip } from "../state";
import type { Cond, DemoItem, Mode } from "../types";
import { NOISE_HELP, demoParts } from "../format";
import { Play, Stop } from "./Icons";

interface Props {
  demo: DemoItem[]; cond: Cond; speed: number; mode: Mode; playing: boolean; clip: Clip | null;
  onCond: (c: Cond) => void; onSpeed: (s: number) => void;
  onPlayOne: (d: DemoItem) => void; onPlayAll: () => void; onStop: () => void;
}
const CONDS: [Cond, string][] = [["clean", "Clean"], ["snr20", "20 dB"], ["snr10", "10 dB"], ["snr5", "5 dB"]];
const SPEEDS = [1, 2, 4];

function Bars() { return <span className="eq" aria-hidden><i /><i /><i /></span>; }

export default function Controls(p: Props) {
  const live = p.mode === "live";
  const nowPlaying = p.playing && p.clip ? p.demo.find((d) => d.lot === p.clip!.lot) : undefined;
  return (
    <section className="card panel" aria-label="Auction controls" data-testid="controls">
      <h2>Auction</h2>

      {p.playing ? (
        <button className="btn big stop" onClick={p.onStop}><Stop /> Stop playback</button>
      ) : (
        <button className="btn big primary" disabled={p.demo.length === 0} onClick={p.onPlayAll}><Play /> Play all lots</button>
      )}
      <div className={"nowplaying" + (p.playing ? " on" : "")} aria-live="polite">
        {p.playing
          ? <><Bars /><span>Playing <b lang="ta">{nowPlaying ? demoParts(nowPlaying).fish : ""}</b> <span className="muted">{p.clip?.lot}</span></span></>
          : <span className="muted">Choose one lot below, or play them all.</span>}
      </div>

      <fieldset className="group">
        <legend>Background noise</legend>
        <div className="seg" role="radiogroup" aria-label="Background noise">
          {CONDS.map(([v, t]) => (
            <button key={v} role="radio" aria-checked={p.cond === v} className={p.cond === v ? "on" : ""} onClick={() => p.onCond(v)}>{t}</button>
          ))}
        </div>
        <p className="help">{NOISE_HELP[p.cond]} Lower dB means louder noise.</p>
      </fieldset>

      <fieldset className="group">
        <legend>Playback speed</legend>
        <div className="seg" role="radiogroup" aria-label="Playback speed">
          {SPEEDS.map((s) => (
            <button key={s} role="radio" aria-checked={(live ? 1 : p.speed) === s} className={(live ? 1 : p.speed) === s ? "on" : ""}
              disabled={live && s !== 1} onClick={() => p.onSpeed(s)}>{s}×</button>
          ))}
        </div>
        <p className="help">{live ? "Live mode listens in real time, so the speed stays at 1×." : "Use 2× or 4× to see results sooner."}</p>
      </fieldset>

      <div className="group">
        <div className="legend">Recorded lots</div>
        <ul className="demos">
          {p.demo.map((d) => {
            const { fish, about, note } = demoParts(d);
            const active = p.playing && p.clip?.lot === d.lot;
            return (
              <li key={d.lot}>
                <button className={"demo" + (active ? " active" : "")} disabled={p.playing && !active} aria-label={`Play ${about || d.lot}, ${fish}`}
                  aria-pressed={active} onClick={() => p.onPlayOne(d)}>
                  <span className="playcircle">{active ? <Bars /> : <Play size={22} />}</span>
                  <span className="demo-text">
                    <span className="fish" lang="ta">{fish}</span>
                    <span className="about">{about}{note && <> · {note}</>}</span>
                  </span>
                  <span className="lotid">{d.lot}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
