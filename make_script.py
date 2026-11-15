"""
make_script.py -- generate 30 auction "lots" for you to read aloud, with an answer key.

    python make_script.py        ->  auction_script.json (answer key, for the evaluator)  +  auction_script.md (read-aloud sheet)

Each lot = one continuous utterance:  <species> ஸ்டார்ட் ஆகுது.  <price chant>.  <closing word>.  பேரு?  <buyer>.
The chant rises in steps of 50 (observed in the vlog captions, a HYPOTHESIS), each price repeated 2-3 times.
Number styles: "thu" / "thi" = the two thousand forms (ஆயிரத்து / ஆயிரத்தி: ITN breaks on the second),
               "half"      = X-அரை shorthand at hundred scale (எட்டரை = 850), a hypothesis from one vlog.
All names are fictional. Seeded, so the sheet is reproducible.
"""
import json, random
from ennam import parse_numbers

H_STAND = {1: "நூறு", 2: "இருநூறு", 3: "முன்னூறு", 4: "நானூறு", 5: "ஐநூறு", 6: "அறுநூறு", 7: "எழுநூறு", 8: "எண்ணூறு", 9: "தொள்ளாயிரம்"}
H_COMB = {1: "நூற்று", 2: "இருநூற்று", 3: "முன்னூற்று", 4: "நானூற்று", 5: "ஐநூற்று", 6: "அறுநூற்று", 7: "எழுநூற்று", 8: "எண்ணூற்று", 9: "தொள்ளாயிரத்து"}
UNITS = {2: "இரண்டு", 3: "மூன்று", 4: "நான்கு", 5: "ஐந்து", 6: "ஆறு", 7: "ஏழு", 8: "எட்டு", 9: "ஒன்பது"}
HALF = {1: "ஒன்றரை", 2: "இரண்டரை", 3: "மூன்றரை", 4: "நான்கரை", 5: "ஐந்தரை", 6: "ஆறரை", 7: "ஏழரை", 8: "எட்டரை", 9: "ஒன்பதரை"}
SPECIES_LOW = ["நண்டு", "பாறை", "வாலை", "மடவை", "மத்தி", "நெத்திலி", "கணவாய்"]            # hundred-scale lots
SPECIES_HIGH = ["சங்கரா", "வஞ்சரம்", "கொடுவா", "சுறா", "இறால்", "ஸ்குவிட்", "ஆக்டோபஸ்"]  # thousand-scale lots
CLOSING = ["முடிஞ்சிச்சு", "போயிடுச்சு", "அவ்ளோதான்", "எடுத்துட்டாங்க"]
BUYERS = ["செய்யது", "கோபி", "முத்துக்குமார்", "ராஜா", "மணிவண்ணன்", "சேகர்", "முருகன்", "குமார்", "ரமேஷ்", "சுரேஷ்",
          "பாலு", "அன்வர்", "ஜான்", "அந்தோணி", "ஹரி", "கண்ணன்", "செல்வம்", "இசக்கி", "பீட்டர்", "மகேஷ்"]


def below_1000(n):
    h, r = divmod(n, 100)
    assert r in (0, 50)
    if h == 0:
        return "ஐம்பது"
    return H_STAND[h] if r == 0 else H_COMB[h] + " ஐம்பது"


def say(n, style="thu"):
    """Spell a price (multiple of 50, < 10,000) the way it is read aloud."""
    if style == "half" and n < 1000 and n % 100 == 50:
        return HALF[n // 100]
    if n < 1000:
        return below_1000(n)
    th, rem = divmod(n, 1000)
    assert th < 10
    mult = "ஆயிரம்" if rem == 0 else ("ஆயிரத்து" if style != "thi" else "ஆயிரத்தி")
    head = mult if th == 1 else f"{UNITS[th]} {mult}"
    return head if rem == 0 else f"{head} {below_1000(rem)}"


def chant(rng, start, n_distinct):
    prices, p = [], start
    for _ in range(n_distinct):
        prices.append(p)
        p += 100 if rng.random() < 0.1 else 50
    calls = [x for x in prices for _ in range(rng.choice((2, 2, 3)))]
    return prices, calls


def build(seed=2026, count=30, first_id=1):
    rng = random.Random(seed)
    if count == 30:
        plan = [("low", "full")] * 10 + [("low", "half")] * 6 + [("high", "thu")] * 7 + [("high", "thi")] * 7
    else:                                                  # same mix, scaled (e.g. 20 -> 7/4/5/4)
        n = [round(count * w / 30) for w in (10, 6, 7)]
        plan = ([("low", "full")] * n[0] + [("low", "half")] * n[1] + [("high", "thu")] * n[2] + [("high", "thi")] * (count - sum(n)))
    rng.shuffle(plan)
    lots = []
    for i, (scale, style) in enumerate(plan, 1):
        species = rng.choice(SPECIES_LOW if scale == "low" else SPECIES_HIGH)
        start = rng.choice(range(300, 750, 50)) if scale == "low" else rng.choice(range(1000, 4050, 50))
        prices, calls = chant(rng, start, rng.randint(3, 5))
        sty = "thu" if style == "full" else style
        buyer, closing = rng.choice(BUYERS), rng.choice(CLOSING)
        text = f"{species} ஸ்டார்ட் ஆகுது. " + ", ".join(say(c, sty) for c in calls) + f". {closing}. பேரு? {buyer}."
        lots.append({"id": f"lot{first_id + i - 1:02d}", "scale": scale, "style": style, "species": species, "start": prices[0],
                     "distinct_prices": prices, "calls": calls, "final_price": prices[-1], "closing": closing,
                     "buyer": buyer, "text": text})
    return lots


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--start", type=int, default=1, help="number of the first lot (validation lots start at 31)")
    ap.add_argument("--out", default="auction_script", help="file stem for the .json answer key and .md reading sheet")
    ap.add_argument("--folder", default="lots", help="folder name to print in the recording instructions")
    a = ap.parse_args()
    # self-check: our own parser must read back exactly what the sheet says (catches typos in the spelling tables)
    for n in range(300, 9950, 50):
        for sty in ("thu", "thi"):
            assert parse_numbers(say(n, sty)) == [n], (n, sty, say(n, sty), parse_numbers(say(n, sty)))
    for n in range(150, 1000, 100):
        assert parse_numbers(say(n, "half")) == [(n // 100) + 0.5], (n, say(n, "half"))
    lots = build(a.seed, a.count, a.start)
    json.dump({"_note": "Answer key. Fictional names. Do not show to the evaluator before it has run.", "roster": BUYERS, "seed": a.seed, "lots": lots},
              open(f"{a.out}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    first, last = lots[0]["id"], lots[-1]["id"]
    out = [f"# Auction reading sheet ({a.count} lots: {first} to {last})\n",
           f"**Record each lot as ONE take**, in the order below, as a shouted-but-clear chant. File names: `{a.folder}\\{first}.m4a` ... `{last}.m4a`.\n",
           "- Quiet room, phone ~20 cm away, **mic gain low** (peaks must stay clear of full scale).",
           "- Read the numbers exactly as written. Where a lot says *shorthand*, say எட்டரை etc. as printed.",
           "- **Keep every lot under 25 seconds** (the API rejects audio over 30 s). If a lot runs long, say the chant a little faster; do not skip calls.",
           "- Do not re-record for small slips: real auctions are messy. If you stumble badly, note the lot number and redo it.\n"]
    for l in lots:
        tag = {"full": "hundreds, full words", "half": "hundreds, **shorthand**", "thu": "thousands", "thi": "thousands"}[l["style"]]
        out.append(f"### {l['id']}  ({tag})\n\n{l['text']}\n")
    open(f"{a.out}.md", "w", encoding="utf-8").write("\n".join(out))
    from collections import Counter
    print(len(lots), "lots |", dict(Counter(l["style"] for l in lots)), "| distinct buyers used:", len({l["buyer"] for l in lots}), "| roster:", len(BUYERS))
    print("longest lot:", max(len(l["calls"]) for l in lots), "price calls | self-checks passed")
