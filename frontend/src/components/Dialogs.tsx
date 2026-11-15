import { useEffect, useRef, useState } from "react";
import { Alert, CheckCircle } from "./Icons";

export function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>("input, button")?.focus();
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("keydown", k); prev?.focus?.(); };
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={box}><h3>{title}</h3>{children}</div>
    </div>
  );
}

export function Confirm({ title, body, yes, no, danger, onYes, onNo }: { title: string; body: string; yes: string; no: string; danger?: boolean; onYes: () => void; onNo: () => void }) {
  return (
    <Modal title={title} onClose={onNo}>
      <p>{body}</p>
      <div className="row end"><button className="btn" onClick={onNo}>{no}</button><button className={"btn " + (danger ? "danger" : "primary")} onClick={onYes}>{yes}</button></div>
    </Modal>
  );
}

export function TokenDialog({ onSubmit, onClose }: { onSubmit: (t: string) => void; onClose: () => void }) {
  const [t, setT] = useState("");
  return (
    <Modal title="Access token for live mode" onClose={onClose}>
      <p>Live playback spends speech credits, so this server asks for a token.</p>
      <input className="wide" type="password" value={t} onChange={(e) => setT(e.target.value)} onKeyDown={(e) => e.key === "Enter" && t && onSubmit(t)} aria-label="Access token" />
      <div className="row end"><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!t} onClick={() => onSubmit(t)}>Start</button></div>
    </Modal>
  );
}

export function Toast({ message, kind }: { message: string | null; kind: "error" | "success" | "info" }) {
  return (
    <div className={"toast " + kind + (message ? " show" : "")} role="status" aria-live="polite">
      {message && (kind === "success" ? <CheckCircle /> : <Alert />)}<span>{message}</span>
    </div>
  );
}
