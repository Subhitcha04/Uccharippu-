import { Stop } from "./Icons";

/** On a phone the Stop button would scroll out of reach, so a bar stays at the bottom while audio plays. */
export default function PlaybackBar({ label, onStop }: { label: string; onStop: () => void }) {
  return (
    <div className="playbar" role="region" aria-label="Playback">
      <span className="eq" aria-hidden><i /><i /><i /></span><span className="grow">Playing {label}</span>
      <button className="btn stop" onClick={onStop}><Stop /> Stop</button>
    </div>
  );
}
