import { useRef } from "react";
import type { Board, Clip } from "../state";
import { COND_LABEL, num, rupees } from "../format";
import { Alert, Check, Spinner } from "./Icons";

type View = "idle" | "listening" | "processing" | "recorded" | "review";

function Waves({ on }: { on: boolean }) {
  return <span className={"waves" + (on ? " on" : "")} aria-hidden><i /><i /><i /><i /><i /></span>;
}

interface Props { board: Board; clip: Clip | null; processing: boolean; live: boolean; onCheck: (id: number) => void }

export default function LotBoard({ board, clip, processing, live, onCheck }: Props) {
  const view: View = board.phase === "recorded" ? (board.review ? "review" : "recorded")
    : processing ? "processing" : board.phase === "listening" || board.phase === "hearing" ? "listening" : "idle";
  const seq = board.seq ?? [];
  const lotNo = board.lotId;
  const priceRef = useRef<HTMLDivElement>(null);

  const label = {
    idle: { ta: "அடுத்த ஏலத்திற்குத் தயார்", en: "Ready for the next lot" },
    listening: { ta: "கேட்டுக்கொண்டிருக்கிறது", en: "Listening" },
    processing: { ta: "செயலாக்கப்படுகிறது", en: "Processing auction details" },
    recorded: { ta: "பதிவு செய்யப்பட்டது", en: `Recorded · Lot ${lotNo}` },
    review: { ta: "சரிபார்க்கவும்", en: `Check this auction · Lot ${lotNo}` },
  }[view];

  return (
    <section className="hero" data-state={view} aria-label="Current lot" data-testid="hero">
      <div className="hero-top">
        <div className="state-pill" role="status" aria-live="polite">
          {view === "listening" && <Waves on />}
          {view === "processing" && <Spinner />}
          {view === "recorded" && <span className="tick" key={lotNo}><Check /></span>}
          {view === "review" && <Alert />}
          {view === "idle" && <Waves on={false} />}
          <span className="pill-ta" lang="ta">{label.ta}</span>
          <span className="pill-en" data-testid="hero-state">{label.en}</span>
        </div>
        <div className="hero-meta">
          <span lang="ta">{live ? "நேரலை ஏலம்" : "ஏலம்"}</span> · {live ? "Live auction" : "Auction"}
          {clip && <span className="clipmeta"> · {clip.lot} · {COND_LABEL[clip.cond] ?? clip.cond}</span>}
        </div>
      </div>

      {view === "processing" && <div className="progress" aria-hidden><span /></div>}

      <div className="hero-main">
        <div className="hero-cell">
          <div className="eyebrow">Fish · <span lang="ta">மீன்</span></div>
          <div className={"species" + (board.species ? "" : " dim")} lang="ta" data-testid="board-species">{board.species ?? "—"}</div>
        </div>
        <div className="hero-cell">
          <div className="eyebrow">{view === "recorded" || view === "review" ? "Final price" : "Price so far"} · <span lang="ta">விலை</span></div>
          <div ref={priceRef} className={"price" + (board.price != null ? "" : " dim")} data-testid="board-price">{rupees(board.price)}</div>
        </div>
        <div className="hero-cell">
          <div className="eyebrow">Bids heard</div>
          <div className="ladder" data-testid="board-bids">
            {seq.length === 0 && <span className="bid ghost">—</span>}
            {seq.map((b, i) => (
              <span className="step" key={i}>{i > 0 && <span className="arrow" aria-hidden>→</span>}<span className={"bid" + (i === seq.length - 1 ? " last" : "")}>{num(b)}</span></span>
            ))}
          </div>
          <div className="eyebrow buyer-eyebrow">Buyer · <span lang="ta">வாங்குபவர்</span></div>
          <div className={"buyer" + (board.buyer ? "" : " none")} lang={board.buyer ? "ta" : undefined} data-testid="board-buyer">
            {board.buyer ?? (view === "recorded" || view === "review" ? "Not identified" : "—")}
          </div>
        </div>
      </div>

      {view === "idle" && <p className="hero-hint">Choose a recorded lot on the left, or press “Play all lots”. Each result appears here the moment it is recorded.</p>}
      {view === "review" && (
        <div className="hero-note">
          <p>{board.note || "Please check the details of this lot."}</p>
          {lotNo != null && <button className="btn amber" onClick={() => onCheck(lotNo)}>Check this auction</button>}
        </div>
      )}
    </section>
  );
}
