import type { DemoItem, Lot, Mode, ServerMessage } from "./types";
import { reasons } from "./format";

export type Phase = "idle" | "listening" | "hearing" | "recorded";
export interface Board { species: string | null; price: number | null; buyer: string | null; seq: number[]; phase: Phase; lotId: number | null; review: boolean; note: string }
export interface Clip { id: number; lot: string; cond: string; seconds: number; speed: number; audioUrl: string }
export interface Line { id: number; text: string; at: number }
export interface Notice { id: number; message: string; kind: "error" | "success" }

export interface State {
  loaded: boolean;            // false until the server's first snapshot arrives: only then do skeletons show
  connected: boolean;
  mode: Mode;
  lots: Lot[];
  species: string[];
  roster: string[];
  demo: DemoItem[];
  needsToken: boolean;
  playing: boolean;
  processing: boolean;        // a phrase was recognised and the system is still working out the lot
  clip: Clip | null;
  lines: Line[];
  partial: string;
  board: Board;
  flashId: number | null;
  notice: Notice | null;
}

const emptyBoard: Board = { species: null, price: null, buyer: null, seq: [], phase: "idle", lotId: null, review: false, note: "" };

export const initialState: State = {
  loaded: false, connected: false, mode: "saved", lots: [], species: [], roster: [], demo: [], needsToken: false, playing: false,
  processing: false, clip: null, lines: [], partial: "", board: emptyBoard, flashId: null, notice: null,
};

export type Action = { type: "conn"; connected: boolean } | { type: "msg"; m: ServerMessage } | { type: "play_sent" };

let clipCounter = 0, noticeCounter = 0, lineCounter = 0;
const latest = (lots: Lot[]): Board | null => (lots.length ? boardFor(lots[lots.length - 1]) : null);
const boardFor = (l: Lot): Board => ({
  species: l.species, price: l.price, buyer: l.buyer, seq: l.seq, phase: "recorded", lotId: l.id,
  review: l.status === "review", note: l.status === "review" ? reasons(l).slice(0, 2).join(" ") : "",
});

export function reducer(s: State, a: Action): State {
  if (a.type === "conn") return { ...s, connected: a.connected };
  if (a.type === "play_sent") return { ...s, playing: true };
  const m = a.m;
  switch (m.type) {
    case "snapshot":
      return { ...s, loaded: true, mode: m.mode, lots: m.lots, species: m.species, roster: m.roster, demo: m.demo, needsToken: m.live_needs_token,
        playing: m.playing, processing: false, lines: [], partial: "", clip: null,
        board: latest(m.lots) ?? emptyBoard };   // after a reload the hero shows the latest lot, never a blank screen
    case "clip":
      if (m.state !== "start") return s;
      return { ...s, lines: [], partial: "", processing: false, board: { ...emptyBoard, phase: "listening" },
        clip: { id: ++clipCounter, lot: m.lot, cond: m.cond, seconds: m.seconds ?? 0, speed: m.speed ?? 1, audioUrl: m.audio_url ?? "" } };
    case "speech":
      return s.board.phase === "listening" ? { ...s, board: { ...s.board, phase: "hearing" } } : s;
    case "partial":
      return { ...s, partial: m.text };
    case "final":
      return { ...s, partial: "", processing: true, lines: [...s.lines, { id: ++lineCounter, text: m.text, at: Date.now() }] };
    case "live": {
      const pv = m.preview;
      const empty = pv.species == null && pv.price == null && (!pv.seq || pv.seq.length === 0);
      if (empty) return { ...s, processing: false };           // keep showing the recorded lot instead of blanking the board
      return { ...s, processing: false, board: { ...emptyBoard, species: pv.species, price: pv.price, seq: pv.seq ?? [], phase: "hearing" } };
    }
    case "lot": {
      const prev = s.lots.find((l) => l.id === m.lot.id);
      const lots = prev ? s.lots.map((l) => (l.id === m.lot.id ? m.lot : l)) : [...s.lots, m.lot];
      if (prev) {                                              // an edit or a confirmation
        const board = s.board.lotId === m.lot.id ? boardFor(m.lot) : s.board;
        let notice = s.notice;
        if (m.lot.confirmed && !prev.confirmed) notice = { id: ++noticeCounter, kind: "success", message: `Lot ${m.lot.id} saved and confirmed` };
        else if ((m.lot.history?.length ?? 0) > (prev.history?.length ?? 0)) notice = { id: ++noticeCounter, kind: "success", message: `Lot ${m.lot.id} updated` };
        return { ...s, lots, board, notice };
      }
      return { ...s, lots, flashId: m.lot.id, processing: false, board: boardFor(m.lot) };
    }
    case "done":
      // playback ended or was stopped: keep the last recorded lot on the board, never fall back to an empty screen
      return { ...s, playing: false, processing: false, board: s.board.phase === "recorded" ? s.board : (latest(s.lots) ?? emptyBoard) };
    case "error":
      return { ...s, playing: false, processing: false, board: s.board.phase === "recorded" ? s.board : (latest(s.lots) ?? emptyBoard),
        notice: { id: ++noticeCounter, kind: "error", message: m.message } };
    default:
      return s;
  }
}
