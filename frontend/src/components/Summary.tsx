import type { Lot } from "../types";
import { isConfirmed, rupees } from "../format";

export default function Summary({ lots }: { lots: Lot[] }) {
  const total = lots.reduce((a, l) => a + (l.price ?? 0), 0);
  const review = lots.filter((l) => l.status === "review").length;
  const tile = (k: string, v: string | number, cls = "") => (
    <div className={"stat " + cls} key={k}><div className="k">{k}</div><div className="v">{v}</div></div>
  );
  return (
    <section className="summary" aria-label="Today's summary" data-testid="summary">
      {tile("Lots today", lots.length)}
      {tile("Total lot value", lots.length ? rupees(total) : "₹ —", "total")}
      {tile("Auto-recorded", lots.filter((l) => l.status === "ok").length)}
      {tile("Needs review", review, review > 0 ? "warn" : "")}
      {tile("Confirmed by a person", lots.filter(isConfirmed).length)}
    </section>
  );
}
