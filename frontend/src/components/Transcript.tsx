import { useEffect, useRef } from "react";
import type { Line } from "../state";
import { fmtMs } from "../format";
import { Spinner } from "./Icons";

export default function Transcript({ lines, partial, processing }: { lines: Line[]; partial: string; processing: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight, behavior: "smooth" }); }, [lines, partial, processing]);
  const empty = lines.length === 0 && !partial;
  return (
    <section className="card panel" aria-label="What the system heard" data-testid="transcript">
      <h2>What the system heard</h2>
      <div className="feed" ref={box}>
        {empty && <p className="feed-empty">When an auction plays, the words appear here as they are recognised.</p>}
        {lines.map((l, i) => (
          <div key={l.id} className={"utt" + (i === lines.length - 1 && !partial ? " latest" : "")}>
            <time>{fmtMs(l.at)}</time><span lang="ta">{l.text}</span>
          </div>
        ))}
        {partial && <div className="utt latest partial"><time>now</time><span lang="ta">{partial}</span></div>}
        {processing && <div className="utt working"><Spinner /> <span>Working out the lot…</span></div>}
      </div>
    </section>
  );
}
