import type { Lot } from "../types";
import { changeList, fmtSeconds, reasons, rupees } from "../format";
import { Check, Machine, Person } from "./Icons";

const sentence = (a: string) => { const t = a.replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };

function Node({ who, title, time, children }: { who: "machine" | "person"; title: string; time?: string; children?: React.ReactNode }) {
  return (
    <li className={"node " + who}>
      <span className="marker" aria-hidden>{who === "person" ? <Person /> : <Machine />}</span>
      <div className="node-body">
        <div className="node-head"><b>{title}</b><span className="who">{who === "person" ? "Person" : "Machine"}</span>{time && <time>{time}</time>}</div>
        {children}
      </div>
    </li>
  );
}

/** What the machine heard, what was recorded, and every human change: machine and person are clearly different. */
export default function Timeline({ lot }: { lot: Lot }) {
  const o = lot.original;
  const val = (v: string | null) => v ?? "—";
  const why = reasons(lot);
  return (
    <div className="timeline-wrap" data-testid={`audit-${lot.id}`}>
      <ol className="timeline">
        <Node who="machine" title="Machine heard" time={fmtSeconds(lot.time)}>
          <p className="quote" lang="ta">{lot.transcript}</p>
        </Node>
        <Node who="machine" title="Recorded by the system">
          <dl className="vals"><div><dt>Fish</dt><dd lang="ta">{val(o.species)}</dd></div><div><dt>Price</dt><dd>{o.price != null ? rupees(o.price) : "—"}</dd></div><div><dt>Buyer</dt><dd lang="ta">{val(o.buyer)}</dd></div></dl>
          {why.length > 0 && <p className="note">Flagged because: {why.join(" ")}</p>}
        </Node>
        {lot.history.map((h, i) => {
          if (h.action === "edit") return (
            <Node key={i} who="person" title="Edited by a person" time={fmtSeconds(h.time)}>
              <ul className="changes">{changeList(h.changes).map((c) => (
                <li key={c.field}><span className="f">{c.field}</span><span className="from" lang="ta">{c.from}</span><span className="arr" aria-hidden>→</span><span className="to" lang="ta">{c.to}</span></li>))}</ul>
            </Node>);
          if (h.action === "confirm") return <Node key={i} who="person" title="Confirmed by a person" time={fmtSeconds(h.time)}><p className="ok"><Check /> Checked and accepted</p></Node>;
          return <Node key={i} who="machine" title={sentence(String(h.action))} time={fmtSeconds(h.time)} />;
        })}
      </ol>
      {lot.flags.length > 0 && <details className="dev"><summary>Technical details</summary><code>{lot.flags.join(", ")}</code></details>}
    </div>
  );
}
