import { useEffect, useState } from "react";
import type { Lot } from "../types";
import { STATUS_LABEL, fmtClock, rupees, wasEdited } from "../format";
import { Alert, Check, CheckCircle, Clock, Pencil, Person, Spinner, Speaker } from "./Icons";
import Collapse from "./Collapse";
import { Confirm } from "./Dialogs";
import type { Fields } from "./ReviewQueue";
import Timeline from "./Timeline";

interface Props {
  lots: Lot[]; species: string[]; roster: string[]; flashId: number | null; busy: number | null; loaded: boolean;
  onReceipt: (id: number) => void; onConfirm: (id: number) => void; onSave: (id: number, f: Fields) => void; onCheck: (id: number) => void;
}

function StatusChip({ status }: { status: string }) {
  const icon = status === "review" ? <Alert /> : status === "corrected" ? <Pencil /> : status === "confirmed" ? <Person /> : <CheckCircle />;
  return <span className={"chip " + status}>{icon}{STATUS_LABEL[status] ?? status}</span>;
}

function EditPanel({ lot, species, roster, onSave, onClose }: { lot: Lot; species: string[]; roster: string[]; onSave: (id: number, f: Fields) => void; onClose: () => void }) {
  const init: Fields = { species: lot.species ?? "", price: lot.price != null ? String(lot.price) : "", buyer: lot.buyer ?? "" };
  const [f, setF] = useState<Fields>(init);
  const [ask, setAsk] = useState(false);
  const dirty = f.species !== init.species || f.price !== init.price || f.buyer !== init.buyer;
  const o = lot.original;
  const was = (v: string | number | null, price = false) => (v == null ? "—" : price ? rupees(Number(v)) : String(v));
  return (
    <div className="editpanel" data-testid={`edit-${lot.id}`}>
      <h4>Edit lot {lot.id}</h4>
      <p className="muted">Your change is saved as a correction. What the machine heard stays in the history.</p>
      <div className="fields">
        <label><span>Fish</span><select value={f.species} lang="ta" onChange={(e) => setF({ ...f, species: e.target.value })}><option value="">Select fish</option>{species.map((x) => <option key={x}>{x}</option>)}</select>
          <small>Machine heard: <span lang="ta">{was(o.species)}</span></small></label>
        <label><span>Price (₹)</span><input type="number" inputMode="numeric" min={1} step={50} value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} />
          <small>Machine heard: {was(o.price, true)}</small></label>
        <label><span>Buyer</span><select value={f.buyer} lang="ta" onChange={(e) => setF({ ...f, buyer: e.target.value })}><option value="">Select buyer</option>{roster.map((x) => <option key={x}>{x}</option>)}</select>
          <small>Machine heard: <span lang="ta">{was(o.buyer)}</span></small></label>
      </div>
      <div className="row-actions">
        <button className="btn primary" disabled={!dirty || !f.species || !f.price || !f.buyer} onClick={() => { onSave(lot.id, f); onClose(); }}>Save changes</button>
        <button className="btn" onClick={() => (dirty ? setAsk(true) : onClose())}>Cancel</button>
      </div>
      {ask && <Confirm title="Discard your changes?" body="You changed some details but have not saved them." yes="Discard changes" no="Keep editing" danger onYes={() => { setAsk(false); onClose(); }} onNo={() => setAsk(false)} />}
    </div>
  );
}

function LotCard({ lot, p, flash }: { lot: Lot; p: Props; flash: boolean }) {
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState(false);
  const confirmed = lot.confirmed === true || lot.status === "confirmed";
  return (
    <article className={"lot" + (flash ? " flash" : "")} data-status={lot.status} data-testid={`row-${lot.id}`}>
      <div className="lot-id"><span className="lotno">Lot {lot.id}</span><time>{fmtClock(lot.time)}</time></div>
      <div className="lot-fish" lang="ta">{lot.species ?? <span className="missing"><Alert /> Fish missing</span>}</div>
      <div className="lot-price">{lot.price != null ? rupees(lot.price) : <span className="missing"><Alert /> Price missing</span>}</div>
      <div className="lot-buyer"><span className="cap">Buyer</span>{lot.buyer ? <span lang="ta">{lot.buyer}</span> : <span className="missing"><Alert /> Buyer missing</span>}</div>
      <div className="lot-status">
        <StatusChip status={lot.status} />
        {lot.source.includes("rest") && <span className="tag" title="A second batch transcription checked this lot">re-checked</span>}
        {wasEdited(lot) && <span className="tag" title="A person changed what the machine heard">edited</span>}
      </div>
      <div className="lot-actions">
        {lot.status === "review" && <button className="btn amber" onClick={() => p.onCheck(lot.id)}><Alert /> Check this lot</button>}
        {lot.status !== "review" && !confirmed && <button className="btn confirm" onClick={() => p.onConfirm(lot.id)}><Check /> Confirm</button>}
        <button className="btn" disabled={p.busy === lot.id} onClick={() => p.onReceipt(lot.id)} aria-label={`Hear the Tamil receipt for lot ${lot.id}`}>
          {p.busy === lot.id ? <Spinner /> : <Speaker />} Hear receipt</button>
        <button className="btn" aria-expanded={editing} aria-label={`Edit lot ${lot.id}`} onClick={() => { setEditing(!editing); }}><Pencil /> Edit</button>
        <button className={"btn" + (history ? " on" : "")} aria-expanded={history} aria-label={`History of lot ${lot.id}`} onClick={() => setHistory(!history)}><Clock /> History</button>
      </div>
      <Collapse open={editing} area="area-edit"><EditPanel lot={lot} species={p.species} roster={p.roster} onSave={p.onSave} onClose={() => setEditing(false)} /></Collapse>
      <Collapse open={history} area="area-hist"><Timeline lot={lot} /></Collapse>
    </article>
  );
}

export default function Ledger(p: Props) {
  const [flash, setFlash] = useState<number | null>(null);
  useEffect(() => { if (p.flashId != null) { setFlash(p.flashId); const t = window.setTimeout(() => setFlash(null), 1800); return () => window.clearTimeout(t); } }, [p.flashId]);
  const rows = [...p.lots].reverse();
  return (
    <section className="card ledger" aria-label="Ledger" data-testid="ledger">
      <h2>Ledger {p.lots.length > 0 && <span className="count">{p.lots.length}</span>}<span className="sorted">Newest first</span></h2>
      {!p.loaded ? <div className="skeletons" aria-busy="true"><div className="skeleton" /><div className="skeleton" /></div>
        : p.lots.length === 0 ? (
          <div className="empty"><b>No lots recorded yet</b><p>Press “Play all lots” to hear a recorded auction, or choose one lot. Each result appears here the moment it is recorded.</p></div>
        ) : <div className="lots">{rows.map((l) => <LotCard key={l.id} lot={l} p={p} flash={p.flashId === l.id && flash === l.id} />)}</div>}
    </section>
  );
}
