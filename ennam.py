"""
[v6: SPOKEN hundred-roots generated like the others: அஞ்சூறு / அஞ்சுநூறு (500), நாலுநூறு / நாநூறு (400), ரெண்டுநூறு, மூணுநூறு, எட்டுநூறு (800), ஒம்பதுநூறு (900), with the -த்தம்பது / -ற்று forms]
[v5: more spelling variants of 800/200 and merged '-ற்றம்பது' / collapsed 950 forms; found in validation lots 31-50]
[v4: skips a duplicated thousand word after a merged thousand: Prisma writes 'இரண்டாயிரத்தி ஆயிரத்தி ...']
ennam.py -- Tamil spoken numbers -> integers, plus auction-chant repair.

Why this exists: Prisma's Tamil ITN (format=transcribe) fails on the "-த்தி" thousand form ("ஆறு ஆயிரத்தி
நானூறு" comes back as "6 ஆயிரத்தி ₹400"), so we parse the verbatim words ourselves and also salvage ITN garble.

    from ennam import parse_numbers, repair_chant
    parse_numbers("முப்பத்தி ரெண்டு ஆயிரத்தி ஐநூறு ரூபாய்")      -> [32500]
    parse_numbers("2 ஆயிரத்தி ₹200")                              -> [2200]     (ITN garble salvaged)
    parse_numbers("ஐநூறு ஐநூறு ஐநூறு")                            -> [500, 500, 500]   (a CHANT, not 1500)
    parse_numbers(chant_text, step=50)                             -> bids are multiples of 50: resolves 'X ஐம்பது | ஆயிரத்து ...'  
    parse_numbers("எட்டரை")                                        -> [8.5]      (shorthand: needs a scale, see repair_chant)
"""
import re
import unicodedata
from dataclasses import dataclass

# ----------------------------------------------------------------------------- lexicon
UNITS = {"ஒன்று": 1, "ஒன்னு": 1, "ஒரு": 1, "ஓர்": 1, "இரண்டு": 2, "ரெண்டு": 2, "இரு": 2, "மூன்று": 3, "மூணு": 3,
         "நான்கு": 4, "நாலு": 4, "ஐந்து": 5, "அஞ்சு": 5, "ஆறு": 6, "ஏழு": 7, "எட்டு": 8, "ஒன்பது": 9, "ஒம்பது": 9}
TEENS = {"பத்து": 10, "பதினொன்று": 11, "பன்னிரண்டு": 12, "பன்னிரெண்டு": 12, "பதிமூன்று": 13, "பதின்மூன்று": 13,
         "பதிமூணு": 13, "பதினான்கு": 14, "பதிநாலு": 14, "பதினைந்து": 15, "பதினஞ்சு": 15, "பதினாறு": 16,
         "பதினேழு": 17, "பதினெட்டு": 18, "பத்தொன்பது": 19}
TENS = {"இருபது": 20, "முப்பது": 30, "நாற்பது": 40, "நாப்பது": 40, "ஐம்பது": 50, "அம்பது": 50, "அறுபது": 60,
        "எழுபது": 70, "எண்பது": 80, "தொண்ணூறு": 90}
TEN_STEMS = {"இருபத்": 20, "முப்பத்": 30, "நாற்பத்": 40, "நாப்பத்": 40, "ஐம்பத்": 50, "அம்பத்": 50, "அறுபத்": 60,
             "எழுபத்": 70, "எண்பத்": 80, "தொண்ணூற்": 90}
# sandhi remainders: stem + remainder = a merged 21-99 word (இருபத் + தைந்து = இருபத்தைந்து)
REM = {"தொன்று": 1, "தொன்னு": 1, "திரண்டு": 2, "திரெண்டு": 2, "துமூன்று": 3, "துமூணு": 3, "துநான்கு": 4,
       "துநாலு": 4, "தைந்து": 5, "தஞ்சு": 5, "தாறு": 6, "தேழு": 7, "தெட்டு": 8, "தொன்பது": 9, "தொம்பது": 9}
REM_90 = {"றொன்று": 1, "றிரண்டு": 2, "றிரெண்டு": 2, "றைந்து": 5, "றாறு": 6, "றேழு": 7, "றெட்டு": 8, "றொன்பது": 9}
HUND = {}
for _v, _forms in {100: ("நூறு", "நூற்று", "நூற்றி"), 200: ("இருநூறு", "இருநூற்று", "இருநூற்றி"),
                   300: ("முன்னூறு", "முந்நூறு", "முன்னூற்று", "முன்னூற்றி"), 400: ("நானூறு", "நானூற்று", "நானூற்றி"),
                   500: ("ஐநூறு", "ஐந்நூறு", "ஐநூற்று", "ஐநூற்றி"), 600: ("அறுநூறு", "அறுநூற்று", "அறுநூற்றி"),
                   700: ("எழுநூறு", "எழுநூற்று", "எழுநூற்றி"), 800: ("எண்ணூறு", "எண்ணூற்று", "எண்ணூற்றி"),
                   900: ("தொள்ளாயிரம்", "தொள்ளாயிரத்து", "தொள்ளாயிரத்தி")}.items():
    for _f in _forms:
        HUND[_f] = _v
# Human speech differs from Timbre's: spelling variants (அறநூறு, ஏழுநூறு), colloquial -த்து forms, merged hundred+fifty words
# (நானூற்றிம்பது = 450) and fused hundred+thousand words. The number vocabulary is closed, so these are GENERATED, not patched one by one.
HUND_ROOTS = {1: ["நூ"], 2: ["இருநூ", "இரநூ", "ரெண்டுநூ"], 3: ["முன்னூ", "முந்நூ", "மூணுநூ"], 4: ["நானூ", "நாநூ", "நாலுநூ"], 5: ["ஐநூ", "ஐந்நூ", "அஞ்சூ", "அஞ்சுநூ", "அய்நூ"],
              6: ["அறநூ", "அறுநூ", "ஆறுநூ"], 7: ["எழுநூ", "ஏழுநூ", "ஏழ்நூ", "எழநூ"], 8: ["எண்ணூ", "எட்நூ", "எண்நூ", "எட்டுநூ"],
              9: ["ஒம்பதுநூ", "ஒன்பதுநூ", "ஒம்போதுநூ"]}                                   # v6: how it is SAID: அஞ்சூறு, நாலுநூறு, எட்டுநூறு, ஒம்பதுநூறு ...
MERGED, FUSED = {}, {}
for _v, _roots in HUND_ROOTS.items():
    for _r in _roots:
        for _suf in ("று", "ற்று", "ற்றி", "த்து", "த்தி"):
            HUND[_r + _suf] = _v * 100
        for _suf in ("ற்றைம்பது", "ற்றிம்பது", "த்தைம்பது", "த்திம்பது", "ற்றம்பது", "த்தம்பது"):   # 450 = நானூற்றிம்பது / நானூற்றம்பது
            MERGED[_r + _suf] = _v * 100 + 50
        for _suf in ("ற்றாயிரத்தி", "ற்றாயிரத்து", "ற்றாயிரம்", "த்தாயிரத்தி", "த்தாயிரத்து", "த்தாயிரம்"):
            FUSED[_r + _suf] = _v * 1000                # முன்னூற்றாயிரத்தி: 'மூன்று ஆயிரத்தி' heard with a hundred-word head
for _suf in ("த்தைம்பது", "த்திம்பது", "த்தம்பது"):
    MERGED["தொள்ளாயிர" + _suf] = 950
for _w in ("தொண்ணூத்தம்பது", "தொண்ணூற்றம்பது"):          # 'தொள்ளாயிரத்து ஐம்பது' collapsed (heard as 'ninety-fifty'): only 950 makes sense in a bid
    MERGED[_w] = 950
THOUSAND = {"ஆயிரம்", "ஆயிரத்து", "ஆயிரத்தி"}
LAKH = {"லட்சம்", "லட்சத்து", "லட்சத்தி", "இலட்சம்"}
HALF = {"அறரை": 6.5, "ஒன்றரை": 1.5, "இரண்டரை": 2.5, "மூன்றரை": 3.5, "நான்கரை": 4.5, "நாலரை": 4.5, "ஐந்தரை": 5.5, "அஞ்சரை": 5.5,
        "ஆறரை": 6.5, "ஏழரை": 7.5, "எட்டரை": 8.5, "எட்டுரை": 8.5, "ஒன்பதரை": 9.5, "பத்தரை": 10.5, "அரை": 0.5}

COMP = {}                                           # merged 21..99 words and "stem + connector" words
for _s, _v in TEN_STEMS.items():
    for _r, _u in (REM_90 if _s == "தொண்ணூற்" else REM).items():
        COMP[_s + _r] = _v + _u
TENSTEM = {}                                        # "முப்பத்தி" / "முப்பத்து" = thirty-and-... (unit follows)
for _s, _v in TEN_STEMS.items():
    if _s != "தொண்ணூற்":
        TENSTEM[_s + "தி"] = _v
        TENSTEM[_s + "து"] = _v
ALL_SMALL = {**UNITS, **TEENS, **TENS, **COMP}
SPECIAL_PREFIX = {"மூவ": 3, "ஐய": 5}               # மூவாயிரம் (3000), ஐயாயிரம் (5000)
DIGITS = re.compile(r"^[₹]?(\d[\d,]*)$")


def strip_edges(tok: str) -> str:
    s, e = 0, len(tok)
    while s < e and unicodedata.category(tok[s])[0] in "PS" and tok[s] != "₹":
        s += 1
    while e > s and unicodedata.category(tok[e - 1])[0] in "PS":
        e -= 1
    return unicodedata.normalize("NFC", tok[s:e])


def classify(tok: str):
    """-> (kind, value). kinds: unit teen tens comp tenstem hund thou lakh mthou half dig none"""
    m = DIGITS.match(tok)
    if m:
        return "dig", int(m.group(1).replace(",", ""))
    if tok in UNITS: return "unit", UNITS[tok]
    if tok in TEENS: return "teen", TEENS[tok]
    if tok in TENS: return "tens", TENS[tok]
    if tok in COMP: return "comp", COMP[tok]
    if tok in TENSTEM: return "tenstem", TENSTEM[tok]
    if tok in HUND: return "hund", HUND[tok]
    if tok in THOUSAND: return "thou", 1000
    if tok in LAKH: return "lakh", 100000
    if tok in HALF: return "half", HALF[tok]
    if tok in MERGED: return "hmerge", MERGED[tok]
    if tok in FUSED: return "mthou", FUSED[tok]
    i = tok.find("ாயிர")                             # merged: இரண்டாயிரத்தி, பன்னிரெண்டாயிரம், இருபதாயிரம்
    if i > 0 and tok[i + 4:] in ("ம்", "த்து", "த்தி"):
        pre = tok[:i]
        v = SPECIAL_PREFIX.get(pre) or ALL_SMALL.get(pre + "ு")
        if v:
            return "mthou", v * 1000
    return "none", 0


_CANON = None


def _letters(w):
    return "".join(c for c in unicodedata.normalize("NFC", w) if unicodedata.category(c)[0] in ("L", "M"))


def _sim(a, b):
    a, b = _letters(a), _letters(b)
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1 - prev[-1] / max(len(a), len(b))


def fuzzy_classify(tok, min_sim=0.85, min_margin=0.04):
    """Last resort for an UNKNOWN word inside a price span: snap to the nearest number word if it is a clear, unambiguous match.
    Only the closed number vocabulary is searched, and a near-tie between two DIFFERENT values is rejected."""
    global _CANON
    if _CANON is None:
        keys = set(UNITS) | set(TEENS) | set(TENS) | set(COMP) | set(TENSTEM) | set(HUND) | set(THOUSAND) | set(LAKH) | set(MERGED) | set(FUSED)
        _CANON = {k: classify(k) for k in keys}
    if len(_letters(tok)) < 4:
        return ("none", 0)
    scored = sorted(((_sim(tok, k), k) for k in _CANON), reverse=True)
    top_s, top_k = scored[0]
    if top_s < min_sim:
        return ("none", 0)
    rival = next((s for s, k in scored[1:] if _CANON[k] != _CANON[top_k]), 0.0)
    return _CANON[top_k] if top_s - rival >= min_margin else ("none", 0)


@dataclass
class Num:
    value: float
    kind: str          # "words" | "digits" | "half" | "mixed"
    text: str


def read_number(toks, kinds, i, step=None):
    """Read ONE number starting at i. Levels must strictly descend (thousand > hundred > tens > unit), so a
    repeated word starts a NEW number: 'ஐநூறு ஐநூறு' is a chant of two 500s, never 1000."""
    mult_open = False                                 # last multiplier was ஆயிரத்து/ஆயிரத்தி (a remainder follows)
    last_kind = None
    total = cur = pending = state = last_mult = 0   # state: 0 empty, 1 after hundred, 2 after tens, 3 after unit, 4 tenstem
    has_word, j = False, i
    while j < len(toks):
        kind, v = kinds[j]
        nk = kinds[j + 1][0] if j + 1 < len(toks) else "none"
        # Prisma sometimes writes a SECOND, spurious thousand word right after a merged thousand ('இரண்டாயிரத்தி ஆயிரத்தி
        # தொள்ளாயிரத்தி ஐம்பது'). Two thousands cannot follow each other inside one number, so the second is a duplicate: skip it.
        if kind == "thou" and last_kind == "mthou" and cur == 0 and last_mult == 1000:
            j += 1
            continue
        # 'முன்னூறு ஆயிரத்தி' (three hundred thousand) is implausible for a price: Prisma wrote the HUNDRED-word for the UNIT
        # (மூன்று / முன்னூறு sound alike in fast speech). A hundred directly before a thousand is really unit x 1000.
        if kind == "hund" and v >= 200 and nk == "thou" and state == 0 and not cur and last_mult in (0, 100000):
            kind, v = "unit", v // 100
        # A multiplier (ஆயிரம் / லட்சம்) comes BEFORE the hundreds in Tamil. So a small number that is followed by one
        # can only be the HEAD of a number: if we already hold hundreds/tens/units (cur) it starts the NEXT call of a
        # chant ('மூன்று ஆயிரத்து தொள்ளாயிரம் | மூன்று ஆயிரத்து ...'), and if a thousand was already taken it cannot repeat.
        if kind in ("unit", "teen", "tens", "comp", "tenstem", "dig") and nk in ("thou", "lakh"):
            if cur > 0:
                # hundreds already held: this small number usually starts the NEXT call ('...தொள்ளாயிரம் | மூன்று ஆயிரத்து...').
                # With a step hint (bids are multiples of 50) it ATTACHES instead when that makes a valid bid
                # ('...தொள்ளாயிரத்து ஐம்பது | ஆயிரத்து...': 1,950 is a bid, 50,000 is not) and a thousand is already taken.
                attach = bool(step) and last_mult == 1000 and (total + cur + pending + kinds[j][1]) % step == 0
                if not attach:
                    break
            if last_mult == 1000 and nk == "thou" and not mult_open:
                break                                   # plain 'ஆயிரம்' closed the thousands: 'ஆறு ஆயிரம் | ஆறு ஆயிரம்'
            if last_mult and nk == "lakh":
                break
        # a thousand cannot repeat inside one number, and hundreds cannot precede a thousand: either starts a new call
        if kind in ("thou", "lakh") and (cur >= 100 or (kind == "thou" and last_mult not in (0, 100000)) or (kind == "lakh" and last_mult)):
            break
        if kind == "dig":
            joins = has_word or nk in ("thou", "lakh", "hund", "mthou") or (last_mult and j > i)
            if not joins:
                break
            if v >= 1000 and v % 1000 == 0 and state == 0 and cur == 0 and last_mult in (0, 100000):
                total += v; last_mult = 1000; has_word = True        # ITN wrote '2,000' then words follow
            elif v < 10 and (nk in ("thou", "lakh") or state in (0, 1, 4)):
                if state == 4: cur += pending + v; pending = 0; state = 3
                elif state in (0, 1): cur += v; state = 3
                else: break
            elif v < 100 and state in (0, 1) and not pending:
                cur += v; state = 2
            elif v < 1000 and state == 0:
                cur += v; state = 1
            else:
                break
            has_word = True
        elif kind in ("unit",):
            if state == 4: cur += pending + v; pending = 0; state = 3
            elif state in (0, 1): cur += v; state = 3
            else: break
        elif kind in ("teen", "tens", "comp"):
            if state in (0, 1): cur += v; state = 2
            else: break
        elif kind == "tenstem":
            if state in (0, 1): pending = v; state = 4
            else: break
        elif kind == "hmerge":
            if state == 0:
                cur += v; state = 2
            else: break
        elif kind == "hund":
            if state == 3 and 1 <= cur <= 9 and v == 100:             # இரண்டு நூறு = 200
                cur *= 100; state = 1
            elif state == 0:
                cur += v; state = 1
            else: break
        elif kind in ("thou", "lakh"):
            mult = 1000 if kind == "thou" else 100000
            cur += pending; pending = 0
            total += (cur or 1) * mult
            cur = state = 0; last_mult = mult
            mult_open = toks[j].endswith(("த்து", "த்தி"))
        elif kind == "mthou":
            if state == 0 and not cur and last_mult in (0, 100000):
                total += v; last_mult = 1000
                mult_open = toks[j].endswith(("த்து", "த்தி"))
            else: break
        else:                                                            # half / none: not part of this number
            break
        has_word = has_word or kind != "dig"
        last_kind = kind
        j += 1
    if j == i:
        return None, i
    return total + cur + pending, j


def parse_numbers(text: str, step=None, fuzzy=False, skip=()) -> list:
    """All numbers in a transcript, in order, as ints (or floats for 'X-அரை' shorthand)."""
    return [n.value for n in parse_spans(text, step, fuzzy, skip)]


def parse_spans(text: str, step=None, fuzzy=False, skip=()) -> list:
    toks = [t for t in (strip_edges(x) for x in text.split()) if t]
    kinds = [classify(t) for t in toks]
    if fuzzy:
        kinds = [fuzzy_classify(t) if (k[0] == "none" and t not in skip) else k for t, k in zip(toks, kinds)]
    out, i = [], 0
    while i < len(toks):
        kind = kinds[i][0]
        if kind == "half":
            v = kinds[i][1]
            if i + 1 < len(toks) and kinds[i + 1][0] == "thou":
                out.append(Num(v * 1000, "half", " ".join(toks[i:i + 2]))); i += 2
            else:
                out.append(Num(v, "half", toks[i])); i += 1
            continue
        if kind in ("none",):
            i += 1
            continue
        val, j = read_number(toks, kinds, i, step)
        if val is None:
            if kind == "dig":                      # a plain '₹3,000' or '850' that joins no word: still a number
                out.append(Num(kinds[i][1], "digits", toks[i]))
            i += 1
            continue
        k = "digits" if all(kinds[x][0] == "dig" for x in range(i, j)) else \
            ("mixed" if any(kinds[x][0] == "dig" for x in range(i, j)) else "words")
        out.append(Num(val, k, " ".join(toks[i:j])))
        i = j
    return out


# ----------------------------------------------------------------------------- auction chant rules
def repair_chant(values, step=50, max_up=300, max_down=200):
    """Repair one session's bid sequence using the auction's own rules (HYPOTHESES from vlog captions, not yet
    validated on audio with ground truth):  R1 bids rise in steps of ~50;  R2 a small fall (<= max_down) is
    tolerated and flagged;  R3 a clean price far from the last bid means a NEW lot (reset down / jump up).
    Repairs: extra zero ('6000' after 550 -> 600), dropped leading digits ('950' after 2950 -> 2950),
    half-shorthand ('8.5' after 800 -> 850).  Fragments (0, 00, 10, 49 ...) are never repaired: they are
    marked 'suspect' and do NOT move the reference price, so one bad token cannot poison the rest of the lot.
    Returns [{raw, value, action}], action in keep / fall / extra-zero / dropped-lead / scale / reset / jump / suspect."""
    out, prev = [], None

    def window(c):                                   # is c a believable next bid after prev?
        return c == int(c) and c >= 100 and c % step == 0 and (prev is None or -max_down <= c - prev <= max_up)

    for x in values:
        if x == int(x) and (x == 0 or 20 <= x < 100):          # a fragment, not a price
            out.append({"raw": x, "value": x, "action": "suspect"})
            continue
        cands = [(x, "keep", 0)]
        if x == int(x) and x >= 1000 and x % 10 == 0:
            cands.append((x // 10, "extra-zero", 1))
        if x == int(x) and x >= 10000 and x % 100 == 0:
            cands.append((x // 100, "extra-zero", 2))
        if x != int(x) or x < 20:
            cands += [(x * m, "scale", 1) for m in (10, 100, 1000)]
        if prev is not None and x == int(x) and len(str(int(x))) < len(str(int(prev))):
            p_, sx = str(int(prev)), str(int(x))
            cands.append((int(p_[:len(p_) - len(sx)] + sx), "dropped-lead", 1))
        # a REPAIR needs strong evidence: it must land on a repeat or within two steps of the previous bid;
        # anything else is left as typed (and becomes a 'reset', i.e. a new lot, if it is a big fall)
        ok = [(c, a, pen) for c, a, pen in cands
              if window(c) and (a == "keep" or prev is None or -step <= c - prev <= 2 * step)]
        if ok:
            c, a, pen = min(ok, key=lambda t: (t[2], abs(t[0] - prev) if prev is not None else 0))
            out.append({"raw": x, "value": int(c), "action": "fall" if (a == "keep" and prev is not None and c < prev) else a})
            prev = int(c)
        elif prev is not None and x == int(x) and 100 <= x <= 9999 and x % step == 0:
            # a clean price that cannot be repaired and is far from the last bid: a NEW lot starts there
            out.append({"raw": x, "value": int(x), "action": "reset" if x < prev else "jump"})
            prev = int(x)
        else:
            out.append({"raw": x, "value": x, "action": "suspect"})
    return out
