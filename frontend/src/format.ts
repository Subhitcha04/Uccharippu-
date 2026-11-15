import type { Change, DemoItem, Lot } from "./types";

export const rupees = (p: number | null | undefined): string => (p == null ? "₹ —" : "₹ " + Number(p).toLocaleString("en-IN"));
export const num = (p: number): string => Number(p).toLocaleString("en-IN");

export const STATUS_LABEL: Record<string, string> = { ok: "Auto-recorded", review: "Needs review", corrected: "Corrected", confirmed: "Confirmed" };
export const COND_LABEL: Record<string, string> = { clean: "clean audio", snr20: "20 dB noise", snr10: "10 dB noise", snr5: "5 dB noise" };

// Plain-language explanations. The clerk never sees a flag code.
const SENTENCE: Record<string, string> = {
  "buyer?": "The buyer's name was not clear.",
  "species?": "The fish name was not clear.",
  "no-price": "No price was heard for this lot.",
  "final-called-once": "The final price was heard only once, so please check it.",
  "no-closing-word": "The auctioneer's closing call was not heard.",
  "garbled-near-end": "The end of the call was hard to hear.",
  "audio-ended": "The recording ended before the lot was finished.",
  silence: "The call stopped after a pause.",
  "silence-no-closing": "There was a long pause before the lot was closed.",
  "rest-also-unsure": "A second check of the recording was also unsure.",
};
const PRIORITY = ["buyer?", "species?", "no-price", "final-called-once", "garbled-near-end", "no-closing-word", "audio-ended", "silence-no-closing", "silence", "rest-also-unsure"];

export function reasons(l: Lot): string[] {
  const flags = [...(l.flags || [])].sort((a, b) => (PRIORITY.indexOf(a) + 99) % 99 - (PRIORITY.indexOf(b) + 99) % 99);
  const out: string[] = [];
  for (const f of flags) {
    const s = SENTENCE[f] ?? (f.startsWith("final-") ? "The final price was repaired from a hard-to-hear call, so please check it." : "");
    if (s && !out.includes(s)) out.push(s);
  }
  return out;
}

/** The one question the clerk needs to answer for a flagged lot. */
export function question(l: Lot): string {
  if (l.buyer == null) return "Who purchased this lot?";
  if (l.species == null) return "Which fish was this?";
  if (l.price == null) return "What was the final price?";
  return "Please check the details below.";
}

export const isConfirmed = (l: Lot): boolean => l.confirmed === true || l.status === "confirmed";
export const wasEdited = (l: Lot): boolean => (l.history || []).some((h) => h.action === "edit");

export function fmtClock(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}
export function fmtSeconds(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
export const fmtMs = (ms: number): string => fmtSeconds(new Date(ms).toISOString());

export const FIELD_LABEL: Record<string, string> = { species: "Fish", price: "Price", buyer: "Buyer" };
export function showValue(field: string, v: unknown): string {
  if (v == null || v === "") return "—";
  return field === "price" ? rupees(Number(v)) : String(v);
}
export function changeList(changes: Record<string, Change> | undefined): { field: string; from: string; to: string }[] {
  return Object.entries(changes ?? {}).map(([f, c]) => ({ field: FIELD_LABEL[f] ?? f, from: showValue(f, c.from), to: showValue(f, c.to) }));
}

/** Manifest labels look like "Plain hundreds · நெத்திலி": the Tamil fish name is the last part. */
export function demoParts(d: DemoItem): { fish: string; about: string; note: string } {
  const i = d.label.lastIndexOf(" · ");
  const fish = i >= 0 ? d.label.slice(i + 3) : d.label;
  const about = i >= 0 ? d.label.slice(0, i) : "";
  const note = d.force_cond ? `Always plays with ${COND_LABEL[d.force_cond] ?? d.force_cond}` : "";
  return { fish, about, note };
}

export const NOISE_HELP: Record<string, string> = {
  clean: "A clear recording with no background noise.",
  snr20: "Light harbour noise in the background.",
  snr10: "Busy harbour noise. Harder to hear.",
  snr5: "Very loud harbour noise. The hardest case.",
};
