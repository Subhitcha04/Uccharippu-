import { useState } from "react";
import type { Lot } from "../types";
import { question, reasons } from "../format";
import { Alert, Check } from "./Icons";

export interface Fields { species: string; price: string; buyer: string }

function Card({ lot, species, roster, onSave }: { lot: Lot; species: string[]; roster: string[]; onSave: (id: number, f: Fields) => void }) {
  const [f, setF] = useState<Fields>({ species: lot.species ?? "", price: lot.price != null ? String(lot.price) : "", buyer: lot.buyer ?? "" });
  const why = reasons(lot);
  const missing = { species: lot.species == null, price: lot.price == null, buyer: lot.buyer == null };
  const ready = f.species && f.price && f.buyer;
  return (
    <article className="review-card" id={`review-${lot.id}`} tabIndex={-1} data-testid={`review-${lot.id}`} aria-label={`Lot ${lot.id} needs your attention`}>
      <div className="review-head"><Alert /><div><div className="review-title">Needs your attention · <span lang="ta">சரிபார்க்கவும்</span></div>
        <div className="lotline">Lot {lot.id}</div></div></div>
      <ul className="problem">{(why.length ? why.slice(0, 2) : ["Please check this lot."]).map((w) => <li key={w}>{w}</li>)}</ul>

      <dl className="detected">
        <div><dt>Fish</dt><dd lang="ta" className={missing.species ? "gap" : ""}>{lot.species ?? "Not identified"}</dd></div>
        <div><dt>Price</dt><dd className={missing.price ? "gap" : ""}>{lot.price != null ? "₹ " + lot.price.toLocaleString("en-IN") : "Not identified"}</dd></div>
        <div><dt>Buyer</dt><dd lang="ta" className={missing.buyer ? "gap" : ""}>{lot.buyer ?? "Not identified"}</dd></div>
      </dl>

      <h3 className="ask">{question(lot)}</h3>
      <div className="fields">
        <label className={missing.species ? "need" : ""}><span>Fish</span>
          <select value={f.species} lang="ta" onChange={(e) => setF({ ...f, species: e.target.value })}>
            <option value="">Select fish</option>{species.map((x) => <option key={x}>{x}</option>)}</select></label>
        <label className={missing.price ? "need" : ""}><span>Price (₹)</span>
          <input type="number" inputMode="numeric" min={1} step={50} value={f.price} placeholder="Enter price" onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
        <label className={missing.buyer ? "need" : ""}><span>Buyer</span>
          <select value={f.buyer} lang="ta" onChange={(e) => setF({ ...f, buyer: e.target.value })}>
            <option value="">Select buyer</option>{roster.map((x) => <option key={x}>{x}</option>)}</select></label>
      </div>
      <div className="review-actions">
        <button className="btn big primary" disabled={!ready} onClick={() => onSave(lot.id, f)}><Check /> Save &amp; Confirm</button>
        {!ready && <span className="muted">Fill in all three to confirm.</span>}
      </div>
      <details className="heard-box" open><summary>What the system heard</summary><p lang="ta">{lot.transcript}</p></details>
    </article>
  );
}

export default function ReviewQueue({ lots, species, roster, onSave }: { lots: Lot[]; species: string[]; roster: string[]; onSave: (id: number, f: Fields) => void }) {
  const review = lots.filter((l) => l.status === "review");
  if (review.length === 0) return null;
  return (
    <section className="review" aria-label="Lots that need review" data-testid="review">
      {review.map((l) => <Card key={l.id} lot={l} species={species} roster={roster} onSave={onSave} />)}
    </section>
  );
}
