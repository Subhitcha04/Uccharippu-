"""
auction_eval.py -- Gate H: does Ennam + chant rules + word boosting beat Prisma's own ITN on noisy auction lots?

    python auction_eval.py run          # ~360 STT calls (30 lots x 4 noise conditions x 3 arms), ~45 credits worst case
    python auction_eval.py report       # reprint the tables from auction_eval_results.csv
    python auction_eval.py rescore      # re-extract from the SAVED auction_out\\transcripts.json with the current parser: FREE, no API calls

Needs (next to this file): noisy\\{clean,snr20,snr10,snr5}\\lotNN.wav (from noise_mix.py), auction_script.json,
species_ta.json, ennam.py.   Setup (PowerShell):  pip install requests ;  $env:GNANI_API_KEY = "<the NEW key>"

Three arms, per lot and per noise condition:
  A  baseline : Prisma /stt/v3 ta-IN format=transcribe (its own ITN), numbers = digits in the text, names = exact match
  B  ours     : format=verbatim -> Ennam number parser -> chant-repair rules -> fuzzy match of species and buyer
  C  ours+boost: B, but Prisma is told the species words and the buyer roster (bias_list, score 1.0, 91 of 100 slots)
Lot-level exact = species AND final price AND buyer all correct. Every live response is cached in auction_out\\cache.
"""
import argparse, csv, hashlib, json, math, os, pathlib, re, statistics, sys, time, unicodedata, wave

import requests

import ennam as E

sys.stdout.reconfigure(encoding="utf-8")          # PITFALL (Windows): cp1252 crashes on Tamil text

STT_URL = "https://api.vachana.ai/stt/v3"
HERE = pathlib.Path(__file__).resolve().parent


def locate(name: str):
    """Find an input file in the current folder, next to this script, or one level up (PowerShell users cd around)."""
    for base in (pathlib.Path.cwd(), HERE, pathlib.Path.cwd().parent, HERE.parent):
        if (base / name).exists():
            return base / name
    return None


def find_noisy():
    """The noisy/ folder: ./noisy, or the current folder itself if you ran this from INSIDE noisy/, or ../noisy."""
    cands = [NOISY_DIR] if NOISY_DIR else [pathlib.Path.cwd() / "noisy", pathlib.Path.cwd(), HERE / "noisy", HERE, pathlib.Path.cwd().parent / "noisy"]
    for cand in cands:
        if (cand / "clean").is_dir() and (cand / "snr10").is_dir():
            return cand
    return None


def preflight():
    """Stop BEFORE any API call, with plain instructions, if an input is missing. Returns (key_file, species_file, noisy_dir)."""
    problems = []
    key_file, species_file, noisy = locate(SCRIPT_NAME), locate("species_ta.json"), find_noisy()
    if not key_file:
        problems.append(f"{SCRIPT_NAME} not found (the answer key; copy it next to this script)")
    if not species_file:
        problems.append("species_ta.json not found (copy it next to this script)")
    if not noisy:
        problems.append("noisy folder not found. Expected noisy\\clean\\lot01.wav ... noisy\\snr5\\lot30.wav. "
                        "Run this from the folder that CONTAINS noisy\\, or from inside it. "
                        f"(current folder: {pathlib.Path.cwd()})")
    elif key_file:
        ids = [l["id"] for l in json.loads(key_file.read_text(encoding="utf-8"))["lots"]]
        for cond in CONDS:
            missing = [i for i in ids if not (noisy / cond / f"{i}.wav").exists()]
            if missing:
                problems.append(f"{noisy / cond}: {len(ids) - len(missing)} of {len(ids)} lot files found; missing e.g. {missing[:3]} (re-run noise_mix.py?)")
    if problems:
        sys.exit("CANNOT START, nothing was sent to the API:\n  - " + "\n  - ".join(problems))
    return key_file, species_file, noisy


OUT = pathlib.Path("auction_out")
CACHE, RESULTS, TRANSCRIPTS = OUT / "cache", OUT / "auction_eval_results.csv", OUT / "transcripts.json"
SCRIPT_NAME, NOISY_DIR = "auction_script.json", None


def configure(out=None, script=None, noisy=None) -> None:
    """--out / --script / --noisy let a FRESH validation set run through the same frozen code."""
    global OUT, CACHE, RESULTS, TRANSCRIPTS, SCRIPT_NAME, NOISY_DIR
    if out:
        OUT = pathlib.Path(out)
        CACHE, RESULTS, TRANSCRIPTS = OUT / "cache", OUT / "auction_eval_results.csv", OUT / "transcripts.json"
    if script:
        SCRIPT_NAME = script
    if noisy:
        NOISY_DIR = pathlib.Path(noisy)
CONDS = ["clean", "snr20", "snr10", "snr5"]
ARMS = {"A": "baseline (Prisma ITN)", "B": "ours (Ennam + chant rules)", "C": "ours + word boosting",
        "D": "names from C + numbers from B (post-hoc)"}
PAUSE_S, MAX_RETRIES = 0.3, 5
BIAS_SCORE = "1.0"
STT_CREDITS_PER_MIN = 0.5
GATE_LIFT, GATE_MIN_FIXED, GATE_FALSE_FLAG, GATE_CATCH = 0.20, 4, 0.10, 0.50
# Name-review thresholds, FIXED BEFORE ANY REAL PRISMA DATA (tuned only on a simulator). In a closed roster the margin over the
# runner-up matters more than raw similarity: flag a name only if it barely matches (< 0.70) or is nearly a tie (margin < 0.15).
NAME_FLAG_SIM, NAME_FLAG_MARGIN = 0.70, 0.15
CLOSING = ["முடிஞ்சிச்சு", "போயிடுச்சு", "அவ்ளோதான்", "எடுத்துட்டாங்க", "அவ்வளோதான்", "அவ்வளோ"]
PERU = "பேரு"
PERU_FORMS = ("பேரு", "பேர்", "பெயர்")                          # Prisma writes all three for the buyer prompt
FUNC = {"ஸ்டார்ட்", "ஆகுது", "ஸ்டார்டா", "ஸ்டாட்டா", "ஆச்சு", "தான்", "அவ்வளோ"}      # never snap these to numbers
DEV_MAX = 15        # lots 01..15 = DEVELOPMENT (parser variants were derived from them); 16..30 = HELD-OUT TEST
MAX_CLIP_S = 29.0   # the live API enforces 30 s (its docs say 60 s)
GEMINATE = re.compile("([\u0b95-\u0bb9])\u0bcd\\1")


# ----------------------------------------------------------------------------- text similarity
def norm(s: str) -> str:
    """Letters + combining marks only, gemination folded (க்கு ~ கு). PITFALL: \\w / isalpha would delete Tamil vowel signs."""
    s = unicodedata.normalize("NFC", s)
    return GEMINATE.sub(r"\1", "".join(c for c in s if unicodedata.category(c)[0] in ("L", "M")))


def lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def sim(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    return 0.0 if not a or not b else 1 - lev(a, b) / max(len(a), len(b))


def best(word: str, cands) -> tuple:
    """(best candidate, similarity, margin over the runner-up)."""
    scored = sorted(((sim(word, c), c) for c in cands), reverse=True)
    if not scored:
        return "", 0.0, 0.0
    return scored[0][1], scored[0][0], scored[0][0] - (scored[1][0] if len(scored) > 1 else 0.0)


def tokens(text: str) -> list:
    out = []
    for t in text.split():
        s, e = 0, len(t)
        while s < e and unicodedata.category(t[s])[0] in "PS" and t[s] != "₹":
            s += 1
        while e > s and unicodedata.category(t[e - 1])[0] in "PS":
            e -= 1
        if t[s:e]:
            out.append(t[s:e])
    return out


def find_peru(toks, fuzzy=True, roster=None):
    """Index of the buyer prompt (பேரு / பேர் / பெயர்). With a roster, a word that matches a roster NAME at least as well as it
    matches the prompt is a name, not the prompt. (v4 bug found by validation: பீட்டர் scores 0.60 against பேர், was taken for the
    prompt, and left the buyer empty in 12 of 80 lot-conditions.)"""
    def is_prompt(t):
        ps = max(sim(t, p) for p in PERU_FORMS)
        return ps >= 0.6 and not (roster and max(sim(t, r) for r in roster) >= ps)
    idx = [i for i, t in enumerate(toks) if (is_prompt(t) if fuzzy else t == PERU)]
    return idx[-1] if idx else None


# ----------------------------------------------------------------------------- the two extractors
def extract_baseline(text: str, species: set, roster: list) -> dict:
    """What a straightforward developer gets from Prisma's ITN: digits only, exact string matches, no repair."""
    toks = tokens(text)
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text)]
    p = find_peru(toks, fuzzy=False)
    buyer = toks[p + 1] if p is not None and p + 1 < len(toks) else (toks[-1] if toks else "")
    return {"species": toks[0] if toks and toks[0] in species else "", "final": nums[-1] if nums else None,
            "buyer": buyer if buyer in roster else "", "seq": [], "flag": "", "flag_reason": ""}


def extract_ours(text: str, species: set, roster: list) -> dict:
    toks = tokens(text)
    reasons = []
    # species: best fuzzy match among the first three words
    sp, sp_sim, sp_margin = "", 0.0, 0.0
    for t in toks[:3]:
        c, s, m = best(t, species)
        if s > sp_sim:
            sp, sp_sim, sp_margin = c, s, m
    if sp_sim < 0.6:
        sp = ""
    if sp_sim < NAME_FLAG_SIM or sp_margin < NAME_FLAG_MARGIN:
        reasons.append("species?")
    # where do prices end? first closing word, else the buyer prompt
    p = find_peru(toks, True, roster)
    closing = next((i for i, t in enumerate(toks) if any(sim(t, c) >= 0.75 for c in CLOSING)), None)
    end = closing if closing is not None else (p if p is not None else len(toks))
    if closing is None:
        reasons.append("no-closing-word")
    start = 1 if sp else 0
    spans = E.parse_spans(" ".join(toks[start:end]), step=50, fuzzy=True, skip=FUNC)   # bids are multiples of 50 (hypothesis)
    rep = E.repair_chant([float(n.value) for n in spans]) if spans else []
    good = [r for r in rep if r["action"] != "suspect"]
    final = good[-1]["value"] if good else None
    if final is None:
        reasons.append("no-price")
    else:
        # the chant itself is the confidence signal: a final price called >= 2 times in a row, unrepaired, is trusted
        support = 0
        for r in reversed(good):
            if r["value"] != final:
                break
            support += 1
        tail = rep[-3:]
        if support < 2:
            reasons.append("final-called-once")
        # NOTE: flagging by how the final price was ENTERED (instead of its last repetition) was tried and REVERTED: it caught
        # the same errors on the test lots but added false flags.
        if good[-1]["action"] in ("extra-zero", "dropped-lead", "jump", "reset"):
            reasons.append(f"final-{good[-1]['action']}")         # 'scale' (shorthand read against the chant) and 'fall' are not alarms
        if any(r["action"] == "suspect" for r in tail):
            reasons.append("garbled-near-end")
    seq = []
    for r in good:
        if not seq or seq[-1] != int(r["value"]):
            seq.append(int(r["value"]))
    # buyer: the word(s) after the buyer prompt, fuzzy-matched to the roster
    buyer, b_sim, b_margin = "", 0.0, 0.0
    after = toks[p + 1:p + 3] if p is not None else toks[-1:]
    for cand in ([after[0]] if after else []) + ([" ".join(after)] if len(after) > 1 else []):
        c, s, m = best(cand, roster)
        if s > b_sim:
            buyer, b_sim, b_margin = c, s, m
    if b_sim < 0.6:
        buyer = ""
    if b_sim < NAME_FLAG_SIM or b_margin < NAME_FLAG_MARGIN:
        reasons.append("buyer?")
    return {"species": sp, "final": final, "buyer": buyer, "seq": seq,
            "flag": int(bool(reasons)), "flag_reason": "|".join(reasons)}


# ----------------------------------------------------------------------------- Prisma
def stt(wav: bytes, fmt: str, bias: list, key: str):
    """-> (transcript, processing_time, error). bias=[] means no boosting."""
    params = {"language_code": "ta-IN", "format": fmt}
    if bias:
        params.update({"bias_list": json.dumps(bias, ensure_ascii=False), "bias_score": BIAS_SCORE})
    ck = hashlib.sha256(wav + json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
    path = CACHE / f"{ck}.json"
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        return d["text"], d.get("latency"), None
    last = "unknown"
    for attempt in range(MAX_RETRIES):
        try:
            # PITFALL: no manual Content-Type; the API key goes only in this header.
            resp = requests.post(STT_URL, headers={"X-API-Key-ID": key}, files={"audio_file": ("clip.wav", wav, "audio/wav")},
                                 data=params, timeout=90)
        except requests.RequestException as exc:
            last = f"network: {exc}"
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 200:
            js = resp.json()
            text = (js.get("transcript") or (js.get("output") or {}).get("literal") or "").strip()
            path.write_text(json.dumps({"text": text, "latency": js.get("processing_time")}, ensure_ascii=False), encoding="utf-8")
            time.sleep(PAUSE_S)
            return text, js.get("processing_time"), None
        last = f"HTTP {resp.status_code}: {resp.text[:160]}"
        if resp.status_code not in (429, 502, 503, 504):
            break
        try:
            time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
        except ValueError:
            time.sleep(2 ** attempt)
    return "", None, last


def wav_seconds(path: pathlib.Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


# ----------------------------------------------------------------------------- run
FIELDS = ["lot", "cond", "arm", "species_ok", "final_ok", "buyer_ok", "lot_ok", "seq_ok", "flag", "flag_reason",
          "pred_species", "pred_final", "pred_buyer", "true_species", "true_final", "true_buyer", "transcript"]


def split_wav(wav: bytes, max_s: float = MAX_CLIP_S) -> list:
    """Cut a WAV longer than the API limit at its QUIETEST 200 ms between 35% and 65% (a pause between calls). Repeats if needed."""
    import array, io
    with wave.open(io.BytesIO(wav)) as w:
        sr, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
    if width != 2 or ch != 1:
        return [wav]                                   # only the 16-bit mono files noise_mix.py writes
    pieces, todo = [], [a]
    while todo:
        x = todo.pop(0)
        if len(x) / sr <= max_s:
            pieces.append(x)
            continue
        win, lo, hi = int(0.2 * sr), int(len(x) * 0.35), int(len(x) * 0.65)
        cut = min(range(lo, hi - win, max(1, win // 4)), key=lambda i: sum(abs(v) for v in x[i:i + win])) + win // 2
        todo = [x[:cut], x[cut:]] + todo
    out = []
    for x in pieces:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
        out.append(buf.getvalue())
    return out


def stt_long(wav: bytes, fmt: str, bias: list, key: str):
    """-> (text, processing_time, error), transcribing in <= 29 s pieces and joining the text."""
    texts, lat = [], None
    for chunk in split_wav(wav):
        t, l, err = stt(chunk, fmt, bias, key)
        if err:
            return "", None, err
        texts.append(t)
        lat = l if l is not None else lat
    return " ".join(texts), lat, None


def score_row(lot, cond, arm, text, species, roster) -> dict:
    pred = extract_baseline(text, species, roster) if arm == "A" else extract_ours(text, species, roster)
    ok_s, ok_f, ok_b = pred["species"] == lot["species"], pred["final"] == lot["final_price"], pred["buyer"] == lot["buyer"]
    return {"lot": lot["id"], "cond": cond, "arm": arm, "species_ok": int(ok_s), "final_ok": int(ok_f), "buyer_ok": int(ok_b),
            "lot_ok": int(ok_s and ok_f and ok_b), "seq_ok": int(pred["seq"] == lot["distinct_prices"]) if arm != "A" else "",
            "flag": pred["flag"], "flag_reason": pred["flag_reason"], "pred_species": pred["species"], "pred_final": pred["final"],
            "pred_buyer": pred["buyer"], "true_species": lot["species"], "true_final": lot["final_price"], "true_buyer": lot["buyer"],
            "transcript": text}


def score_rows(lot, cond, tx, species, roster) -> list:
    """Rows for A, B, C and the derived arm D.  D = species and buyer from the BOOSTED decode (boosting helped names), final price
    from the UNBOOSTED decode (boosting slightly hurt numbers). D was chosen AFTER seeing the first results, so it must be confirmed on fresh recordings."""
    rows = [score_row(lot, cond, arm, tx[arm], species, roster) for arm in "ABC"]
    pB, pC = extract_ours(tx["B"], species, roster), extract_ours(tx["C"], species, roster)
    names = {r for r in pC["flag_reason"].split("|") if r in ("species?", "buyer?")}
    nums = {r for r in pB["flag_reason"].split("|") if r and r not in ("species?", "buyer?")}
    reasons = sorted(names | nums)
    pD = {"species": pC["species"], "buyer": pC["buyer"], "final": pB["final"], "seq": pB["seq"],
          "flag": int(bool(reasons)), "flag_reason": "|".join(reasons)}
    ok_s, ok_f, ok_b = pD["species"] == lot["species"], pD["final"] == lot["final_price"], pD["buyer"] == lot["buyer"]
    rows.append({"lot": lot["id"], "cond": cond, "arm": "D", "species_ok": int(ok_s), "final_ok": int(ok_f), "buyer_ok": int(ok_b),
                 "lot_ok": int(ok_s and ok_f and ok_b), "seq_ok": int(pD["seq"] == lot["distinct_prices"]), "flag": pD["flag"],
                 "flag_reason": pD["flag_reason"], "pred_species": pD["species"], "pred_final": pD["final"], "pred_buyer": pD["buyer"],
                 "true_species": lot["species"], "true_final": lot["final_price"], "true_buyer": lot["buyer"], "transcript": tx["C"]})
    return rows


def split_of(lot_id: str) -> str:
    return "dev" if int(re.sub(r"\D", "", lot_id)) <= DEV_MAX else "test"


def write_results(rows) -> None:
    OUT.mkdir(exist_ok=True)
    with RESULTS.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def rescore(tx_path: pathlib.Path) -> None:
    """Re-extract every row from SAVED transcripts with the CURRENT parser. No API calls, no credits."""
    key_file, species_file = locate(SCRIPT_NAME), locate("species_ta.json")
    if not (key_file and species_file and tx_path.exists()):
        sys.exit("need auction_script.json, species_ta.json and the transcripts file")
    lots = {l["id"]: l for l in json.loads(key_file.read_text(encoding="utf-8"))["lots"]}
    species = set(json.loads(species_file.read_text(encoding="utf-8"))["boost_candidates"])
    roster = sorted(set(json.loads(key_file.read_text(encoding="utf-8")).get("roster") or {l["buyer"] for l in lots.values()}))
    tx = json.loads(tx_path.read_text(encoding="utf-8"))
    rows, skipped = [], []
    for k, t in sorted(tx.items()):
        cond, lid = k.split("/")
        if not any(t.values()):
            skipped.append(k)                           # every arm failed (e.g. audio over the 30 s limit): NOT a wrong answer
            continue
        rows += score_rows(lots[lid], cond, t, species, roster)
    write_results(rows)
    print(f"rescored {len(rows)} rows from {len(tx) - len(skipped)} lot-conditions; skipped {len(skipped)} with no transcript ({sorted({k.split('/')[1] for k in skipped})})")
    for sp in ("dev", "test", "all"):
        report(None if sp == "all" else sp)


def run() -> None:
    key = os.environ.get("GNANI_API_KEY")
    if not key:
        sys.exit("Set GNANI_API_KEY first:  $env:GNANI_API_KEY = '<new key>'")
    key_file, species_file, noisy = preflight()
    lots = json.loads(key_file.read_text(encoding="utf-8"))["lots"]
    sp_doc = json.loads(species_file.read_text(encoding="utf-8"))
    species = set(sp_doc["boost_candidates"])
    roster = sorted(set(json.loads(key_file.read_text(encoding="utf-8")).get("roster") or {l["buyer"] for l in lots}))
    bias = sorted(species) + roster
    if len(bias) > 100:
        sys.exit(f"boost list has {len(bias)} words; the API cap is 100 (needs phase-switching)")
    CACHE.mkdir(parents=True, exist_ok=True)
    rows, transcripts, errors, lat, secs, changed = [], {}, [], [], 0.0, 0
    for cond in CONDS:
        for lot in lots:
            path = noisy / cond / f"{lot['id']}.wav"
            if not path.exists():
                errors.append(f"missing {path}")
                continue
            wav = path.read_bytes()
            dur = wav_seconds(path)
            if dur > MAX_CLIP_S:
                print(f"NOTE {cond}/{lot['id']}: {dur:.0f}s exceeds the API's 30 s limit; it will be split at a pause")
            tx, failed = {}, False
            for arm, fmt, b in (("A", "transcribe", []), ("B", "verbatim", []), ("C", "verbatim", bias)):
                text, l, err = stt_long(wav, fmt, b, key)
                if err:
                    errors.append(f"{cond}/{lot['id']}/{arm}: {err}")
                    failed = True
                tx[arm] = text
                secs += dur
                if l is not None:
                    lat.append(float(l))
            changed += int(tx["B"] != tx["C"])
            if failed:                                  # a failed call is an INFRASTRUCTURE problem, not a wrong answer
                transcripts[f"{cond}/{lot['id']}"] = {a_: "" for a_ in "ABC"}
                continue
            transcripts[f"{cond}/{lot['id']}"] = tx
            rows += score_rows(lot, cond, tx, species, roster)
    if not rows:
        sys.exit("NO RESULTS: every lot failed. First errors:\n  " + "\n  ".join(errors[:5]))
    if errors:
        print(f"WARNING: {len(errors)} of {len(CONDS) * len(lots) * 3} calls failed; their rows are missing. First: {errors[0]}")
    write_results(rows)
    TRANSCRIPTS.write_text(json.dumps(transcripts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} rows -> {RESULTS.resolve()}   (errors: {len(errors)})")
    print(f"audio sent: {secs / 60:.1f} min -> about {secs / 60 * STT_CREDITS_PER_MIN:.0f} credits if nothing was cached")
    if lat:
        print(f"STT processing  p50 {statistics.median(lat):.2f}s   p95 {sorted(lat)[int(0.95 * (len(lat) - 1))]:.2f}s")
    print(f"boosting changed the transcript on {changed}/{len(transcripts)} lot-conditions")
    for e in errors[:10]:
        print("ERROR:", e)
    report()


# ----------------------------------------------------------------------------- report
def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def f(k, n):
    lo, hi = wilson(k, n)
    return f"{k:2d}/{n:<2d} {k / n if n else 0:4.2f} [{lo:.2f}-{hi:.2f}]"


def report(split=None) -> None:
    if not RESULTS.exists():
        sys.exit("no results yet: run `python auction_eval.py run`")
    with RESULTS.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if split:
        rows = [r for r in rows if split_of(r["lot"]) == split]
        print("\n" + "#" * 100 + f"\n#  {split.upper()} lots " + ("(1-15: parser variants were derived from these, so treat as OPTIMISTIC)" if split == "dev" else "(16-30: HELD OUT, never used to build the parser)") + "\n" + "#" * 100)
    for r in rows:
        for k in ("species_ok", "final_ok", "buyer_ok", "lot_ok"):
            r[k] = int(r[k])
        r["flag"] = int(r["flag"] or 0)
    by = {}
    for r in rows:
        by.setdefault((r["cond"], r["arm"]), {})[r["lot"]] = r
    print("\n=== LOT-LEVEL EXACT (species AND final price AND buyer) ===")
    print(f" {'noise':<7} {'A baseline ITN':<22} {'B ours':<22} {'C ours + boost':<22} {'D names:C numbers:B'}")
    for cond in CONDS:
        cells = []
        for arm in "ABCD":
            d = by.get((cond, arm), {})
            cells.append(f(sum(r["lot_ok"] for r in d.values()), len(d)) if d else "n/a")
        print(f" {cond:<7} {cells[0]:<22} {cells[1]:<22} {cells[2]:<22} {cells[3]}")
    print("\n=== WHERE THE POINTS COME FROM (all noise levels pooled) ===")
    print(f" {'arm':<26} {'species':<16} {'final price':<16} {'buyer':<16} {'price sequence'}")
    for arm in "ABCD":
        rs = [r for (c, a), d in by.items() if a == arm for r in d.values()]
        n = len(rs)
        seq = f"{sum(int(r['seq_ok']) for r in rs)}/{n}" if arm != "A" else "n/a"
        print(f" {arm + ' ' + ARMS[arm]:<26} {sum(r['species_ok'] for r in rs):3d}/{n:<3d}        {sum(r['final_ok'] for r in rs):3d}/{n:<3d}        "
              f"{sum(r['buyer_ok'] for r in rs):3d}/{n:<3d}        {seq}")

    print("\n=== REVIEW FLAGS (a flag = 'ask the clerk to check this lot') ===")
    print(f" {'noise':<7} {'arm':<4} {'errors caught':<18} {'false flags (correct lots flagged)'}")
    for cond in CONDS:
        for arm in "CD":
            d = by.get((cond, arm), {})
            err = [r for r in d.values() if not r["lot_ok"]]
            ok = [r for r in d.values() if r["lot_ok"]]
            print(f" {cond:<7} {arm:<4} {sum(r['flag'] for r in err):2d}/{len(err):<2d} caught     {sum(r['flag'] for r in ok):2d}/{len(ok):<2d}  {sum(r['flag'] for r in ok) / len(ok) if ok else 0:.0%}")

    # ---- honesty table: the script INCLUDES lots built to break Prisma's ITN (the -த்தி form) and to test a shorthand hypothesis,
    # so the headline lift is partly designed in. The 'neutral' row is the fair one.
    kf = locate(SCRIPT_NAME)
    styles = {l["id"]: l["style"] for l in json.loads(kf.read_text(encoding="utf-8"))["lots"]} if kf else {}
    groups = {"neutral (plain forms)": {"full", "thu"}, "ITN-defect form ஆயிரத்தி": {"thi"}, "half-shorthand X-அரை": {"half"}}
    print("\n=== LOT-LEVEL EXACT BY LOT TYPE (the fair comparison is the neutral row) ===")
    print(f" {'lot type':<36} {'noise':<6} {'A baseline':<12} {'B ours':<12} {'C ours+boost':<13} {'D'}")
    for gname, st in groups.items():
        for cond in ("clean", "snr10"):
            ids = [l for l, s_ in styles.items() if s_ in st]
            cells = []
            for arm in "ABCD":
                d = by.get((cond, arm), {})
                cells.append(f"{sum(d[l]['lot_ok'] for l in ids if l in d)}/{len([l for l in ids if l in d])}")
            print(f" {gname:<36} {cond:<6} {cells[0]:<12} {cells[1]:<12} {cells[2]:<13} {cells[3]}")

    def gate(arm, label):
        a, c = by.get(("snr10", "A"), {}), by.get(("snr10", arm), {})
        if not (a and c):
            return
        n = len(a)
        lift = (sum(r["lot_ok"] for r in c.values()) - sum(r["lot_ok"] for r in a.values())) / n
        fixed = sum(1 for l in a if not a[l]["lot_ok"] and c[l]["lot_ok"])
        broken = sum(1 for l in a if a[l]["lot_ok"] and not c[l]["lot_ok"])
        ok_c = [r for r in c.values() if r["lot_ok"]]
        err_c = [r for r in c.values() if not r["lot_ok"]]
        ff = sum(r["flag"] for r in ok_c) / len(ok_c) if ok_c else 0.0
        catch = sum(r["flag"] for r in err_c) / len(err_c) if err_c else None
        print(f"{label}: lift {lift:+.0%}   fixed {fixed}  broken {broken}   false flags {ff:.0%} ({sum(r['flag'] for r in ok_c)}/{len(ok_c)})   "
              f"catch rate {'n/a (no errors left)' if catch is None else f'{catch:.0%} ({sum(r['flag'] for r in err_c)}/{len(err_c)})'}")
        passed = lift >= GATE_LIFT and fixed >= GATE_MIN_FIXED and fixed >= 2 * broken and ff <= GATE_FALSE_FLAG and (catch is None or len(err_c) < 4 or catch >= GATE_CATCH)
        print(f"   -> {'PASS' if passed else 'FAIL'}")
        return err_c

    print("\n=== GATE H (at 10 dB) ===")
    print(f"pass needs: lift >= {GATE_LIFT:.0%}, fixed >= {GATE_MIN_FIXED}, fixed >= 2x broken, false flags <= {GATE_FALSE_FLAG:.0%}, catch >= {GATE_CATCH:.0%} (when >= 4 errors remain)")
    err_c = gate("C", "pre-registered  C vs A")
    gate("D", "post-hoc        D vs A (confirm on fresh recordings)")
    if err_c:
        print("\nfirst failures of arm C at 10 dB (truth -> predicted):")
        for r in err_c[:8]:
            print(f"  {r['lot']}: {r['true_species']}/{r['true_final']}/{r['true_buyer']} -> {r['pred_species']}/{r['pred_final']}/{r['pred_buyer']}   flags: {r['flag_reason'] or '-'}")
    for cond in CONDS:
        b, cc = by.get((cond, "B"), {}), by.get((cond, "C"), {})
    if rows and all(r["arm"] != "C" or r["transcript"] == next((x["transcript"] for x in rows if x["lot"] == r["lot"] and x["cond"] == r["cond"] and x["arm"] == "B"), None) for r in rows):
        print("\nWARNING: boosted transcripts are IDENTICAL to unboosted for every lot. Tamil-script boost words may be silently ignored.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "report", "rescore"])
    ap.add_argument("--transcripts", type=pathlib.Path, default=None)
    ap.add_argument("--script", default=None, help="answer key file name (default auction_script.json)")
    ap.add_argument("--noisy", default=None, help="folder with clean/ snr20/ snr10/ snr5/ (default: auto-detect)")
    ap.add_argument("--out", default=None, help="output folder (default auction_out)")
    a = ap.parse_args()
    configure(a.out, a.script, a.noisy)
    if a.cmd == "run":
        run()
    elif a.cmd == "rescore":
        rescore(a.transcripts or TRANSCRIPTS)
    else:
        report()


if __name__ == "__main__":
    main()
