import { useEffect, useRef, useState } from "react";
import { HTTP_BASE } from "../config";
import { useMediaQuery } from "../hooks";
import type { Mode } from "../types";
import { Download, Moon, More, Sun } from "./Icons";
import Logo from "./Logo";

interface Props {
  mode: Mode; connected: boolean; sound: boolean; theme: "dark" | "light";
  onSound: (v: boolean) => void; onTheme: () => void; onReset: () => void;
}

function Switch({ checked, onChange, label, icons }: { checked: boolean; onChange: () => void; label: string; icons?: [React.ReactNode, React.ReactNode] }) {
  return (
    <button role="switch" aria-checked={checked} className="switch" onClick={onChange}>
      <span className="switch-label">{label}</span>
      <span className="track"><span className="thumb">{icons ? (checked ? icons[0] : icons[1]) : null}</span></span>
    </button>
  );
}

function Status({ mode, connected }: { mode: Mode; connected: boolean }) {
  const cls = !connected ? "off" : mode === "live" ? "live" : "saved";
  const text = !connected ? "Reconnecting…" : mode === "live" ? "Live · Prisma" : "Saved Prisma transcripts";
  const tip = !connected ? "Waiting for the server" : mode === "live" ? "Streaming the audio to Prisma in real time." : "Replaying real Prisma transcripts that were saved earlier. This is not a live call.";
  return <span className={"status " + cls} title={tip} data-testid="status"><span className="dot" />{text}</span>;
}

export default function Header({ mode, connected, sound, theme, onSound, onTheme, onReset }: Props) {
  const compact = useMediaQuery("(max-width: 1180px)");
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  return (
    <header className="top">
      <div className="brand">
        <Logo />
        <div>
          <div className="brand-line"><span className="brand-ta" lang="ta">உச்சரிப்பு</span><span className="brand-en">Uccharippu</span></div>
          <div className="brand-sub">Harbour Ledger · <span lang="ta">துறைமுகக் கணக்கு</span></div>
        </div>
      </div>
      <span className="spacer" />
      <Status mode={mode} connected={connected} />
      {!compact ? (
        <div className="actions">
          <Switch checked={sound} onChange={() => onSound(!sound)} label="Play audio" />
          <Switch checked={theme === "dark"} onChange={onTheme} label={theme === "dark" ? "Dark" : "Light"} icons={[<Moon key="m" />, <Sun key="s" />]} />
          <a className="btn" href={`${HTTP_BASE}/api/export.csv`}><Download /> Export CSV</a>
          <span className="vr" aria-hidden />
          <button className="btn quiet-danger" onClick={onReset}>Reset ledger</button>
        </div>
      ) : (
        <div className="menu-wrap" ref={wrap}>
          <button className="btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}><More /> More</button>
          {open && (
            <div className="menu" role="menu">
              <Switch checked={sound} onChange={() => onSound(!sound)} label="Play audio" />
              <Switch checked={theme === "dark"} onChange={onTheme} label={theme === "dark" ? "Dark mode" : "Light mode"} icons={[<Moon key="m" />, <Sun key="s" />]} />
              <a className="btn wide" role="menuitem" href={`${HTTP_BASE}/api/export.csv`}><Download /> Export CSV</a>
              <hr />
              <button className="btn wide quiet-danger" role="menuitem" onClick={() => { setOpen(false); onReset(); }}>Reset ledger</button>
            </div>
          )}
        </div>
      )}
    </header>
  );
}
