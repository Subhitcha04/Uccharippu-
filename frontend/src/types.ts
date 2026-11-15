export interface Original { species: string | null; price: number | null; buyer: string | null }
export interface Change { from: unknown; to: unknown }
export interface HistoryEntry { time: string; action: string; changes?: Record<string, Change>; [k: string]: unknown }

export interface Lot {
  id: number;
  time: string;
  species: string | null;
  price: number | null;
  buyer: string | null;
  seq: number[];
  flags: string[];
  status: string;            // ok | review | corrected | confirmed
  transcript: string;
  source: string;            // saved | live | live+rest ...
  audio: string;
  original: Original;
  history: HistoryEntry[];
  confirmed?: boolean;
}

export interface DemoItem { lot: string; label: string; force_cond?: string }
export interface Preview { species: string | null; price: number | null; seq: number[]; words?: number }
export type Cond = "clean" | "snr20" | "snr10" | "snr5";
export type Mode = "saved" | "live";

export type ServerMessage =
  | { type: "snapshot"; mode: Mode; lots: Lot[]; species: string[]; roster: string[]; demo: DemoItem[]; live_needs_token: boolean; playing: boolean }
  | { type: "clip"; state: "start" | "end"; lot: string; cond: string; seconds?: number; speed?: number; audio_url?: string }
  | { type: "speech"; state: string }
  | { type: "partial"; text: string }
  | { type: "final"; text: string }
  | { type: "live"; preview: Preview }
  | { type: "lot"; lot: Lot }
  | { type: "done" }
  | { type: "error"; message: string };

export type ClientMessage =
  | { type: "play"; items: { lot: string; cond: string }[]; speed: number; token?: string }
  | { type: "stop" }
  | { type: "reset" }
  | { type: "update"; id: number; species?: string; price?: number; buyer?: string }
  | { type: "confirm"; id: number };
