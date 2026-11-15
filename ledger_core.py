"""
ledger_core.py -- the brain of the harbour ledger. No network, no web framework: everything here is unit-tested offline.

    LotSegmenter   streaming text from Prisma -> one finished lot at a time (species, price, buyer, review flags)
    Ledger         the book of lots, with corrections kept as an audit trail, CSV export
    receipt_text   what the clerk's voice reads back (spoken by Timbre)

It REUSES `auction_eval.extract_ours` (v5, arm B = verbatim, no word boosting), so the product does exactly what was validated.
Do not edit auction_eval.py / ennam.py: they are the extraction logic that was tested; the product must behave exactly like it.
"""
import csv
import io
import json
import pathlib
import time
from datetime import datetime, timezone

import auction_eval as ae          # frozen v5 evaluator: extract_ours, sim, best, tokens, find_peru, CLOSING
import make_script                 # say(): price -> Tamil words (used only for the spoken receipt)

START_WORDS = ("ஸ்டார்ட்", "ஸ்டார்டா", "ஸ்டாட்டா")        # 'ஸ்டார்ட் ஆகுது' opens the next lot (seen in the vlogs and in our script)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------------------- segmentation
class LotSegmenter:
    """Feed it FINAL transcript text as it arrives; it hands back finished lots.

    A lot is finished when, after the closing word / buyer prompt, either
      (1) a clear roster name follows (the buyer),                      -> normal case
      (2) the NEXT lot starts ('<species> ஸ்டார்ட் ஆகுது'),              -> buyer was not recognised: flagged, not merged into the next lot
      (3) there is silence (tick), or the audio ends (flush).           -> flagged
    PITFALL: partial (non-final) text must NEVER be fed here: Prisma revises partials, and a revised word would be counted twice.
    """

    def __init__(self, species, roster, silence_s: float = 2.5, hard_silence_s: float = 8.0):
        self.species, self.roster = set(species), list(roster)
        self.silence_s, self.hard_silence_s = silence_s, hard_silence_s
        self.buf: list = []
        self.last_activity = None

    # -- helpers
    def _is_prompt(self, t):
        """The buyer prompt (பேரு/பேர்/பெயர்). A word that matches a roster NAME at least as well is a name, not the prompt (v5 fix)."""
        ps = max(ae.sim(t, p) for p in ae.PERU_FORMS)
        return ps >= 0.6 and max(ae.sim(t, r) for r in self.roster) < ps

    def _anchor(self, toks):
        """Index of the FIRST closing word / buyer prompt, or None. PITFALL: the buffer can hold several lots (a late burst of
        text), so the end of the FIRST lot is the first marker, never the last one."""
        for i, t in enumerate(toks):
            if any(ae.sim(t, w) >= 0.75 for w in ae.CLOSING) or self._is_prompt(t):
                return i
        return None

    def _split_point(self, toks):
        """Exclusive end index of the finished lot at the head of `toks`, or None if it is not finished yet."""
        a = self._anchor(toks)
        if a is not None:
            for j in range(a + 1, min(a + 4, len(toks))):                 # (1) a clear buyer name after the marker
                name, s, margin = ae.best(toks[j], self.roster)
                if s >= 0.85 and margin >= 0.10:
                    return j + 1
        starts = [j for j, t in enumerate(toks) if any(ae.sim(t, w) >= 0.75 for w in START_WORDS)]
        if len(starts) >= 2 and starts[1] - starts[0] >= 4:               # (2) the NEXT lot's start phrase (each lot has exactly one);
            return max(starts[1] - 1, 1)                                  #     its species word precedes it and belongs to the next lot
        return None

    def _finish(self, toks, forced: str = ""):
        res = ae.extract_ours(" ".join(toks), self.species, self.roster)
        reasons = [r for r in res["flag_reason"].split("|") if r]
        if forced:
            reasons.append(forced)
        return {"species": res["species"] or None, "price": int(res["final"]) if res["final"] is not None else None,
                "buyer": res["buyer"] or None, "seq": res["seq"], "flags": reasons, "transcript": " ".join(toks),
                "review": bool(reasons) or not (res["species"] and res["final"] and res["buyer"])}

    # -- public
    def feed(self, text: str, now=None) -> list:
        """Add final text. Returns a list of finished lots (usually 0 or 1)."""
        toks = ae.tokens(text)
        if not toks:
            return []
        self.buf += toks
        self.last_activity = now if now is not None else time.monotonic()
        done = []
        while True:
            end = self._split_point(self.buf)
            if end is None:
                break
            done.append(self._finish(self.buf[:end]))
            self.buf = self.buf[end:]
        return done

    def tick(self, now=None) -> list:
        """Call every ~0.5 s. Applies the silence rules; returns finished lots."""
        if not self.buf or self.last_activity is None:
            return []
        idle = (now if now is not None else time.monotonic()) - self.last_activity
        if idle >= self.silence_s and self._anchor(self.buf) is not None:
            return [self._take_all("silence")]
        if idle >= self.hard_silence_s:
            return [self._take_all("silence-no-closing")]
        return []

    def flush(self) -> list:
        """The audio ended: whatever is buffered is a (probably incomplete) lot."""
        return [self._take_all("audio-ended")] if self.buf else []

    def _take_all(self, why):
        lot = self._finish(self.buf, forced=why)
        self.buf = []
        return lot

    def preview(self) -> dict:
        """The lot in progress, for the live scoreboard: current species, price so far, bids heard."""
        if not self.buf:
            return {"species": None, "price": None, "seq": [], "words": 0}
        res = ae.extract_ours(" ".join(self.buf), self.species, self.roster)
        return {"species": res["species"] or None, "price": int(res["final"]) if res["final"] is not None else None,
                "seq": res["seq"], "words": len(self.buf)}


# ----------------------------------------------------------------------------- ledger
class Ledger:
    """The book. A correction never overwrites history: the machine's answer stays in `original`, every edit in `history`.
    That audit trail is the point for loans and grants: it shows what was heard and what a human changed."""

    FIELDS = ("species", "price", "buyer")

    def __init__(self, path=None):
        self.path = pathlib.Path(path) if path else None
        self.lots: list = []
        if self.path and self.path.exists():
            self.lots = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self):
        if self.path:
            self.path.write_text(json.dumps(self.lots, ensure_ascii=False, indent=1), encoding="utf-8")   # utf-8: Tamil

    def add(self, lot: dict, source: str, audio: str = "") -> dict:
        rec = {"id": (max((l["id"] for l in self.lots), default=0) + 1), "time": now_iso(), "species": lot["species"],
               "price": lot["price"], "buyer": lot["buyer"], "seq": lot["seq"], "flags": lot["flags"],
               "status": "review" if lot["review"] else "ok", "transcript": lot["transcript"], "source": source, "audio": audio,
               "original": {k: lot[k] for k in self.FIELDS}, "history": []}
        self.lots.append(rec)
        self._save()
        return rec

    def get(self, lot_id: int) -> dict:
        for l in self.lots:
            if l["id"] == lot_id:
                return l
        raise KeyError(lot_id)

    def update(self, lot_id: int, **fields) -> dict:
        rec = self.get(lot_id)
        changed = {}
        for k, v in fields.items():
            if k not in self.FIELDS:
                raise ValueError(f"cannot edit {k}")
            if k == "price":
                v = int(v) if v not in (None, "") else None
            if rec[k] != v:
                changed[k] = {"from": rec[k], "to": v}
                rec[k] = v
        if changed:
            rec["history"].append({"time": now_iso(), "action": "edit", "changes": changed})
            rec["status"] = "corrected"
            self._save()
        return rec

    def confirm(self, lot_id: int) -> dict:
        rec = self.get(lot_id)
        if None in (rec["species"], rec["price"], rec["buyer"]):
            raise ValueError("fill in species, price and buyer before confirming")     # PITFALL: never confirm a half-empty lot
        rec["history"].append({"time": now_iso(), "action": "confirm"})
        rec["status"] = "confirmed" if rec["status"] != "corrected" else "corrected"
        rec["confirmed"] = True
        self._save()
        return rec

    def clear(self):
        self.lots = []
        self._save()

    def to_csv(self) -> str:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["id", "time", "species", "price_rs", "buyer", "status", "flags", "machine_said", "source"])
        for l in self.lots:
            o = l["original"]
            w.writerow([l["id"], l["time"], l["species"], l["price"], l["buyer"], l["status"], "|".join(l["flags"]),
                        f"{o['species']}/{o['price']}/{o['buyer']}", l["source"]])
        return "\ufeff" + out.getvalue()            # BOM so Excel shows Tamil correctly


def receipt_text(lot: dict) -> str:
    """The sentence Timbre reads back: '<species>, <price in words> ரூபாய், <buyer>'. Falls back to digits for odd prices."""
    price = lot.get("price")
    if price is None:
        words = ""
    else:
        try:
            if price % 50 == 0 and price < 10000:
                words = make_script.say(int(price), "thu")
            else:
                words = str(price)
        except Exception:
            words = str(price)
    return ", ".join(p for p in (lot.get("species"), f"{words} ரூபாய்" if words else None, lot.get("buyer")) if p)
