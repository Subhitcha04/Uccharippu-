"""
make_synth_chants.py -- an auctioneer that is not you.  Gnani TIMBRE speaks the chant sheets of your demo lots.

    $env:GNANI_API_KEY = "<your key>"
    python make_synth_chants.py                    # the 6 demo lots  ->  synth_demo\\lot61.wav ...
    python make_synth_chants.py --speed 1.1 --gap 0.45   # Timbre v2.5 only accepts speeds from 0.85 to 1.15
    python make_synth_chants.py --list             # see the exact words first, no credits used
    python make_synth_chants.py --hub              # the default chant style (each repeat dragged or clipped differently) + a busy harbour behind it
    python make_synth_chants.py --drag 0.9 --seed 4   # looser rhythm; another seed = another performance of the same lots
    python make_synth_chants.py --style fast --hub  # the previous version: tighter chant, 25% faster, busy harbour behind it (needs numpy)
    python make_synth_chants.py --hub --ambience C:\\sounds\\market.mp3     # same, with a REAL market recording behind it

Then in the app: press "Use an audio file instead" and choose a file from synth_demo\\.   It is played in real time through the same path as
the microphone: Prisma hears it, the numbers are parsed, the lot lands in the ledger.

STYLES
  --style fast (default)  an auctioneer's rhythm: each price is called in a quick burst, in COLLOQUIAL number forms (ஐநூத்தம்பது, ஆறரை, மூணாயிரத்து ...),
                          with a short breath between bursts. Because the speech service answers after every pause, the ledger updates burst by burst
                          WHILE THE CHANT IS STILL GOING instead of once at the end.
  --style plain           the whole chant sheet read in one go, in standard number forms (the first version).
  --forms spoken|slang|standard   (default spoken) how the numbers are spelled, and so how Timbre pronounces them. Timbre reads what is WRITTEN, so
                          'அஞ்சூறு' sounds like speech while 'ஐநூறு' sounds like a newsreader. If a spelling sounds wrong, try --forms slang.
  --list                  print what would be spoken, without calling Timbre.
The slang forms are common colloquial Tamil. They are NOT verified against any particular harbour's dialect: have someone from the coast listen
before you describe them as authentic.

HONESTY: this is a SYNTHETIC voice reading a script. It shows how spoken numbers become ledger entries. It is not a recording of a real auction
and says nothing about how well the system works on real harbour audio. Say "synthetic voice (Gnani Timbre)" wherever you show it.
Cost: about 0.13 credit per lot. Results are cached, so running it again is free.
"""
import argparse, hashlib, io, json, math, os, pathlib, re, struct, sys, time, wave

import requests

HERE = pathlib.Path(__file__).resolve().parent
TTS_URL = os.environ.get("TTS_URL", "https://api.vachana.ai/api/v1/tts/inference")
DEFAULT_LOTS = ["lot61", "lot55", "lot62", "lot52", "lot70", "lot63"]
NO_BUYER = {"lot63"}                      # the 'needs review' demo: the call ends BEFORE the buyer's name, so the system must flag it
RATE = 16000
LEAD_S, TAIL_S = 0.4, 1.2                 # silence before, and after: the speech service answers only after it HEARS a pause


# ---- how a price is SAID.  Standard forms vs the colloquial, run-together forms an auctioneer uses.
H_STD = {1: "நூறு", 2: "இருநூறு", 3: "முன்னூறு", 4: "நானூறு", 5: "ஐநூறு", 6: "அறுநூறு", 7: "எழுநூறு", 8: "எண்ணூறு", 9: "தொள்ளாயிரம்"}
H_STD50 = {1: "நூற்று ஐம்பது", 2: "இருநூற்று ஐம்பது", 3: "முன்னூற்று ஐம்பது", 4: "நானூற்று ஐம்பது", 5: "ஐநூற்று ஐம்பது", 6: "அறுநூற்று ஐம்பது", 7: "எழுநூற்று ஐம்பது", 8: "எண்ணூற்று ஐம்பது", 9: "தொள்ளாயிரத்து ஐம்பது"}
H_SLANG50 = {1: "நூத்தம்பது", 2: "இருநூத்தம்பது", 3: "முன்னூத்தம்பது", 4: "நானூத்தம்பது", 5: "ஐநூத்தம்பது", 6: "அறுநூத்தம்பது", 7: "எழுநூத்தம்பது", 8: "எண்ணூத்தம்பது", 9: "தொள்ளாயிரத்தம்பது"}
# பேச்சு வழக்கு: how the numbers are SAID, not how a newsreader reads them. Timbre pronounces what is spelled, so the spelling is what changes the sound.
H_SPOKEN_OLD = {1: "நூறு", 2: "இருநூறு", 3: "முன்னூறு", 4: "நானூறு", 5: "அஞ்சூறு", 6: "அறநூறு", 7: "எழநூறு", 8: "எட்டுநூறு", 9: "தொள்ளாயிரம்"}
H_SPOKEN = dict(H_STD)                       # spoken hundreds are the ordinary one-word numbers: எண்ணூறு, ஐநூறு (never a unit word + நூறு)
H_SPOKEN50_OLD = {1: "நூத்தம்பது", 2: "இருநூத்தம்பது", 3: "முன்னூத்தம்பது", 4: "நானூத்தம்பது", 5: "ஐநூத்தம்பது", 6: "அறநூத்தம்பது", 7: "எழநூத்தம்பது", 8: "எட்டுநூத்தம்பது", 9: "தொள்ளாயிரத்தம்பது"}
H_SPOKEN50 = dict(H_SLANG50)                   # ...நூத்தம்பது
HALF = {5: "அஞ்சரை", 6: "ஆறரை", 7: "ஏழரை", 8: "எட்டரை", 9: "ஒன்பதரை"}      # "X and a half" = X50, said when the calls come fast


TH_SPOKEN = {2: "ரெண்டாயிரத்து", 3: "மூணாயிரத்து", 4: "நாலாயிரத்து", 5: "அஞ்சாயிரத்து", 6: "ஆறாயிரத்து", 7: "ஏழாயிரத்து", 8: "எட்டாயிரத்து", 9: "ஒம்பதாயிரத்து"}
UNIT_STD = {2: "இரண்டு", 3: "மூன்று", 4: "நான்கு", 5: "ஐந்து", 6: "ஆறு", 7: "ஏழு", 8: "எட்டு", 9: "ஒன்பது"}


def say(n: int, style: str, forms: str) -> str:
    """One price as it is spoken. style is the lot's own style from the script: full (hundreds), half (X-அரை shorthand), thi (1xxx), thu (3xxx).
    forms: standard (written Tamil) | slang (colloquial -த்தம்பது forms) | spoken (slang hundreds + the colloquial thousands: மூணாயிரத்து) | spoken-old (the first version, with unit-word + நூறு forms)."""
    colloquial = forms in ("slang", "spoken", "spoken-old")
    thousands, rest = divmod(n, 1000)
    if rest == 0:                                                                  # 1000, 2000 ... on their own: ஆயிரம், ரெண்டாயிரம்
        if thousands == 1:
            return "ஆயிரம்"
        return (TH_SPOKEN[thousands].replace("த்து", "ம்") if colloquial else UNIT_STD[thousands] + " ஆயிரம்")
    lead = "" if thousands == 0 else ("ஆயிரத்தி " if colloquial else "ஆயிரத்து ") if thousands == 1 else (TH_SPOKEN[thousands] if colloquial else UNIT_STD[thousands] + " ஆயிரத்து") + " " if thousands in TH_SPOKEN else f"{thousands} ஆயிரத்து "
    h, tail = divmod(rest, 100)
    if tail == 50 and h == 0:
        word = "ஐம்பது"                                                           # 50, 1050, 2050 ...
    elif tail == 50:
        word = HALF[h] if (colloquial and style == "half" and h in HALF and not thousands) else {"standard": H_STD50, "slang": H_SLANG50, "spoken": H_SPOKEN50, "spoken-old": H_SPOKEN50_OLD}[forms][h]
    elif tail == 0 and h == 0:
        raise ValueError(f"cannot say {n}")
    elif tail == 0:
        word = (H_SPOKEN_OLD if forms == "spoken-old" else H_SPOKEN if forms == "spoken" else H_STD)[h]
    else:
        raise ValueError(f"cannot say {n}")
    return lead + word


def bursts(lot: dict, forms: str, no_buyer: bool) -> list:
    """The chant as phrases: an opening, one quick burst per price level, then the close and the buyer. One pause (= one utterance) between them."""
    out = [f"{lot['species']} ஸ்டார்ட் ஆகுது"]
    i, calls = 0, lot["calls"]
    while i < len(calls):
        j = i
        while j < len(calls) and calls[j] == calls[i]:
            j += 1
        out.append(" ".join([say(calls[i], lot["style"], forms)] * (j - i)))
        i = j
    out.append(lot["closing"] if no_buyer else f"{lot['closing']} பேரு {lot['buyer']}")
    return out


def trim(pcm: bytes, keep_s: float = 0.05) -> bytes:
    """Cut the silence Timbre puts around a phrase, so bursts follow each other at a chant's pace."""
    import array
    a = array.array("h"); a.frombytes(pcm)
    if not a:
        return pcm
    thr = max(abs(x) for x in a) * 0.04
    idx = [i for i, x in enumerate(a) if abs(x) > thr]
    if not idx:
        return pcm
    keep = int(keep_s * RATE)
    return a[max(0, idx[0] - keep): idx[-1] + keep].tobytes()


def fix_wav_header(wav: bytes) -> bytes:
    """PITFALL: Timbre's WAV header declares a placeholder size (0xFFFFFFFF). Walk the chunks and write a correct header."""
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("the speech service did not return a WAV file")
    pos, fmt = 12, None
    while pos + 8 <= len(wav):
        cid, size = wav[pos:pos + 4], struct.unpack("<I", wav[pos + 4:pos + 8])[0]
        if cid == b"fmt ":
            ch, rate = struct.unpack("<HI", wav[pos + 10:pos + 16]); bits = struct.unpack("<H", wav[pos + 22:pos + 24])[0]; fmt = (rate, ch, bits)
        elif cid == b"data":
            rate, ch, bits = fmt; pcm = wav[pos + 8:]
            return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits)
                    + b"data" + struct.pack("<I", len(pcm)) + pcm)
        pos += 8 + size + (size & 1)
    raise ValueError("no audio data in the WAV")


def to_pcm16k(wav: bytes) -> bytes:
    """-> mono 16-bit PCM at 16 kHz (resampled by linear interpolation if the service returned another rate)."""
    with wave.open(io.BytesIO(fix_wav_header(wav))) as w:
        rate, ch, sw, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"expected 16-bit audio, got {8 * sw}-bit")
    s = list(struct.unpack("<%dh" % (len(frames) // 2), frames))
    if ch > 1:
        s = [sum(s[i:i + ch]) // ch for i in range(0, len(s) - ch + 1, ch)]
    if rate != RATE:
        n = int(len(s) * RATE / rate); out = []
        for i in range(n):
            x = i * rate / RATE; j = int(x); f = x - j
            out.append(int(s[j] * (1 - f) + s[min(j + 1, len(s) - 1)] * f))
        s = out
    return struct.pack("<%dh" % len(s), *s)


_speed = {"use": None, "said": False}                     # the speed Timbre really accepts: found ONCE, then used for every phrase
LADDER = [1.2, 1.1, 1.3, 1.15, 1.4, 1.5, 1.75, 2.0]        # tried in this order if the requested speed is refused (closest to a chant first)


SCRIPT_VERSION = "2026-11-15 l"      # printed at the start of every run, so you can tell which script ran
_cfg = {"model": "timbre-v3.0", "cap": 0, "shout": "price", "simple": False, "ask": False, "steady": True, "mid": "full"}
V3_VOICES = ("Avinash", "Shivani", "Lakshmi", "Kalpana", "Shubham", "Prakash", "Devansh", "Yashraj", "Chetana", "Vasudha", "Riyaa", "Tarika", "Harshad")


def _post(text: str, voice: str, speed: float, key: str):
    body = {"text": text, "voice": voice, "model": _cfg["model"], "language": os.environ.get("TIMBRE_LANG", "ta-IN"), "speed": speed,
            "audio_config": {"sample_rate": RATE, "num_channels": 1, "sample_width": 2, "encoding": "linear_pcm", "container": "wav"}}
    scale = float(os.environ.get("TIMBRE_BACKOFF", "1")); r, err = None, None
    for attempt in range(6):
        try:
            r = requests.post(TTS_URL, headers={"X-API-Key-ID": key}, json=body, timeout=90)
        except requests.RequestException as e:                    # a dropped connection is retried like a server error
            r, err = None, e; time.sleep(min(2 ** attempt, 20) * scale); continue
        if r.status_code == 429:                                  # the account allows ONE active request at a time: 'wait a moment'
            time.sleep((1.0 + attempt) * scale); continue
        if r.status_code >= 500:                                  # 500 = Timbre's 'technical difficulties': usually gone in seconds. Waits 1,2,4,8,16,20 s
            time.sleep(min(2 ** attempt, 20) * scale); continue
        return r
    if r is None:
        raise RuntimeError(f"Timbre could not be reached: {err}")
    return r


def _cache_file(cache: pathlib.Path, text: str, voice: str, speed: float) -> pathlib.Path:
    # the speed in the key is the speed Timbre ACTUALLY used. Timbre v2.5 keeps the old key, so audio you already paid for is reused.
    k = f"v2|{text}|{voice}|{speed}" if _cfg["model"] == "timbre-v2.5" else f"v3|{_cfg['model']}|{text}|{voice}|{speed}"
    return cache / (hashlib.sha256(k.encode("utf-8")).hexdigest()[:20] + ".wav")


class EmptyAudio(RuntimeError):
    pass


def speak(text: str, voice: str, speed: float, key: str, cache: pathlib.Path) -> bytes:
    if re.search(r"\d", re.sub(r"<[a-z ]+>", " ", text)):
        raise ValueError(f"a digit got into the spoken text (Timbre would read it its own way): {text!r}")
    memo = cache / (f"speed_{voice}_{speed}.json" if _cfg["model"] == "timbre-v2.5" else f"speed_v3_{voice}_{speed}.json")
    if _speed["use"] is None and memo.exists():                   # remember what Timbre accepted, so a re-run does not probe (and pay) again
        _speed["use"] = json.loads(memo.read_text(encoding="utf-8"))["use"]
    use = _speed["use"] if _speed["use"] is not None else speed
    f = _cache_file(cache, text, voice, use)
    if f.exists():
        return f.read_bytes()
    r = _post(text, voice, use, key)
    if r.status_code == 400 and use != 1.0 and "speed" in r.text.lower():
        if not _speed["said"]:
            print(f"  Timbre refused speed {use}. Its full answer: {r.text.strip()}", file=sys.stderr); _speed["said"] = True
        named = sorted({float(x) for x in re.findall(r"\d+(?:\.\d+)?", r.text.split("peed", 1)[-1]) if 1.0 < float(x) <= 3.0 and float(x) != use})
        for c in [c for c in LADDER if c != use] + [n for n in named if n not in LADDER]:        # the speeds it names come after the sensible ones
            r = _post(text, voice, c, key)
            if r.status_code == 200:
                _speed["use"] = use = c; memo.write_text(json.dumps({"use": c}), encoding="utf-8")
                print(f"  Timbre accepts speed {c}: using it for every phrase", file=sys.stderr); break
        else:
            _speed["use"] = use = 1.0; memo.write_text(json.dumps({"use": 1.0}), encoding="utf-8"); print("  No faster speed was accepted: using 1.0 (normal). Make the chant feel faster with --gap 0.45.", file=sys.stderr)
            r = _post(text, voice, 1.0, key)
        f = _cache_file(cache, text, voice, use)
        if f.exists():
            return f.read_bytes()
    if r.status_code == 200 and len(r.content) < 1000 and re.search(r"<[a-z ]+>", text) and not _speed.get("retag"):
        plain = re.sub(r"<[a-z ]+>\s*", "", text).strip()          # Timbre sometimes returns an EMPTY wav (header only) for a short text with a tag: speak it without the tag
        if plain:
            r2 = _post(plain, voice, use, key)
            if r2.status_code == 200 and len(r2.content) >= 1000:
                f.write_bytes(r2.content); return r2.content
    if r.status_code != 200 or "json" in r.headers.get("Content-Type", "") or len(r.content) < 1000:
        hint = ""
        if r.status_code == 200:
            raise EmptyAudio(f"Timbre returned an empty clip for {text!r} (voice {voice})")
        if _cfg["model"] == "timbre-v3.0" and r.status_code in (400, 401, 402, 403) and any(w in r.text.lower() for w in ("model", "voice", "scope", "permission", "credit")):
            hint = "\n  If your key cannot use Timbre v3.0 yet, run:  python make_synth_chants.py --model timbre-v2.5 --voice Noopur"
        raise RuntimeError(f"Timbre said HTTP {r.status_code}: {r.text[:400]}{hint}")
    f.write_bytes(r.content)
    return r.content


# ======================================================================== sound processing (needs numpy:  pip install numpy)
def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        sys.exit("This option needs numpy:  pip install numpy")


def _f(pcm: bytes):
    return _np().frombuffer(pcm, dtype="<i2").astype("float64")


def _pcm(x) -> bytes:
    np = _np()
    return np.clip(x, -32768, 32767).astype("<i2").tobytes()


def tighten(pcm: bytes, min_pause: float = 0.15, keep: float = 0.08) -> bytes:
    """Timbre leaves a breath between repeated calls ("ஐநூறு ... ஐநூறு"). A chanter does not. Shorten every INNER pause longer than
    min_pause to `keep` seconds. Speech samples are untouched, only silence is removed."""
    np = _np(); x = _f(pcm); fr = int(0.01 * RATE); n = len(x) // fr
    if n < 10:
        return pcm
    env = np.sqrt((x[: n * fr].reshape(n, fr) ** 2).mean(1)); quiet = env < env.max() * 0.035
    keep_f = np.ones(n, bool); i = 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if i > 0 and j < n and (j - i) * 0.01 >= min_pause:
                keep_f[i + int(keep / 0.01): j] = False
            i = j
        else:
            i += 1
    return _pcm(np.concatenate([x[k * fr:(k + 1) * fr] for k in np.where(keep_f)[0]] + [x[n * fr:]]))


def stretch(pcm: bytes, factor: float) -> bytes:
    """Faster WITHOUT a higher pitch (WSOLA: overlap-add of speech frames chosen so that the waveform continues smoothly).
    factor 1.25 = 25% faster. Timbre itself stops at 1.15x."""
    if abs(factor - 1.0) < 1e-3:
        return pcm
    np = _np(); N = int(0.030 * RATE); Hs = N // 2; Ha = int(round(Hs * factor)); tol = int(0.008 * RATE)
    x = np.concatenate([np.zeros(N + tol), _f(pcm), np.zeros(N + tol + Ha * 2)]); win = np.hanning(N)
    frames = int((len(x) - 2 * N - 2 * tol) / Ha)
    out = np.zeros(frames * Hs + N); norm = np.zeros_like(out); prev = tol
    out[:N] += win * x[prev: prev + N]; norm[:N] += win
    for k in range(1, frames):
        nominal = tol + k * Ha; ref = x[prev + Hs: prev + Hs + N]               # what would naturally follow the last chosen frame
        cand = x[nominal - tol: nominal + tol + N]
        c = np.correlate(cand, ref, mode="valid")
        e = np.sqrt(np.convolve(cand ** 2, np.ones(N), mode="valid") + 1e-9)
        best = nominal - tol + int(np.argmax(c / e)); prev = best
        out[k * Hs: k * Hs + N] += win * x[best: best + N]; norm[k * Hs: k * Hs + N] += win
    out /= np.maximum(norm, 1e-6)
    return _pcm(out[: int(len(_f(pcm)) / factor)])


def _bandpass(sig, lo, hi):
    np = _np(); F = np.fft.rfft(sig); f = np.fft.rfftfreq(len(sig), 1 / RATE); F[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(F, len(sig))


TARGET_BED = ((0, 200, 15.3), (200, 1000, 44.2), (1000, 4000, 6.3), (4000, 8000, 5))   # tuned so that the 20 ms-frame measurement of the quietest 20% (measure_audio.py) reads about 40 / 45 / 10 % like the reference harbour video


SWELL_DB = 6.5


def shape_bed(bed, seed: int = 7):
    """Re-balance the synthetic bed to the measured shape of a real harbour (mostly low rumble and low-mid murmur, little above 1 kHz, but running on to 8 kHz),
    and give it a slow swell of about 3 dB, like a crowd coming and going. The texture (babble gating, clatter, shouts) is kept; only the balance moves."""
    np = _np(); rng = np.random.default_rng(seed + 1); n = len(bed)
    F = np.fft.rfft(bed); fq = np.fft.rfftfreq(n, 1 / RATE); P = np.abs(F) ** 2; tot = P.sum(); g = np.ones(len(fq))
    for lo, hi, share in TARGET_BED:
        m = (fq >= lo) & (fq < hi); g[m] = np.sqrt((share / 100.0) * tot / (P[m].sum() + 1e-9))
    k = max(int(len(fq) / (RATE / 2) * 60), 3); g = np.convolve(np.pad(g, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")      # no cliffs between bands
    y = np.fft.irfft(F * g, n); sw = _bandpass(rng.normal(size=n), 0.05, 0.4); sw = SWELL_DB * sw / (sw.std() + 1e-9)
    y = y * 10 ** (sw / 20)
    return y / (y.std() + 1e-9)


def harbour_ambience(n: int, seed: int = 7):
    """A synthetic fish-hub bed: engine rumble + lapping water + crowd babble (many overlapping 'voices' gated at syllable rate) + distant
    shouts + crate clatter + the odd gull. Built from noise and filters: it is NOT a recording. For the real thing use --ambience <file>."""
    np = _np(); rng = np.random.default_rng(seed); t = np.arange(n) / RATE; f = np.fft.rfftfreq(n, 1 / RATE)
    unit = lambda v: v / (v.std() + 1e-9)
    rumble = unit(_bandpass(rng.normal(size=n), 25, 170))
    water = unit(_bandpass(rng.normal(size=n), 250, 3800)) * (0.65 + 0.35 * np.sin(2 * np.pi * 0.23 * t + rng.uniform(0, 6.3)))
    babble = np.zeros(n)
    for _ in range(14):                                                       # 14 people talking at once, none intelligible
        mask = sum(np.exp(-((f - c) / w) ** 2) for c, w in ((rng.uniform(300, 700), 130), (rng.uniform(900, 1700), 250), (rng.uniform(2200, 3000), 350)))
        v = np.fft.irfft(np.fft.rfft(rng.normal(size=n)) * mask, n)
        gate = _bandpass(rng.normal(size=n), 0.4, rng.uniform(3.5, 6.0)); gate = np.clip(unit(gate) + 0.3, 0, None) ** 2
        babble += unit(v) * gate
    babble = unit(babble)
    shouts = np.zeros(n)
    for _ in range(max(1, int(n / RATE * 0.9))):                              # now and then somebody calls out, further away
        a = int(rng.uniform(0, max(1, n - RATE))); d = int(rng.uniform(0.3, 0.9) * RATE); d = min(d, n - a)
        f0 = rng.uniform(110, 230) * (1 + 0.25 * np.sin(2 * np.pi * rng.uniform(2, 4) * t[:d])) * np.linspace(1.15, 0.85, d)
        v = sum(np.sin(2 * np.pi * np.cumsum(f0) / RATE * h) / h for h in range(1, 14))
        shouts[a: a + d] += _bandpass(v, 250, 3200) * np.hanning(d) * rng.uniform(0.5, 1.0)
    clatter = np.zeros(n)
    for _ in range(max(1, int(n / RATE * 0.7))):                              # crates, buckets, a hose
        a = int(rng.uniform(0, max(1, n - 2000))); d = min(int(rng.uniform(0.02, 0.07) * RATE), n - a)
        clatter[a: a + d] += rng.normal(size=d) * np.exp(-np.arange(d) / (d / 4)) * rng.uniform(0.6, 1.4)
    clatter = _bandpass(clatter, 700, 6500)
    gulls = np.zeros(n)
    for _ in range(max(1, int(n / RATE / 5))):
        a = int(rng.uniform(0, max(1, n - RATE))); d = min(int(0.45 * RATE), n - a); tt = np.arange(d) / RATE
        gulls[a: a + d] += np.sin(2 * np.pi * np.cumsum(2300 + 700 * np.sin(2 * np.pi * 9 * tt) - 500 * tt / 0.45) / RATE) * np.hanning(d) * 0.5
    bed = 0.95 * rumble + 0.55 * water + 1.0 * babble + 0.55 * unit(shouts) * (np.abs(shouts) > 0) + 0.7 * unit(clatter) + 0.12 * gulls
    bed = bed / (bed.std() + 1e-9)
    return shape_bed(bed, seed) if os.environ.get("BED_SHAPE", "target") == "target" else bed


def find_ambience(folder: str) -> dict:
    """The real recordings in the ambience folder, picked by a word in the file name: base = 'tejo' / 'harbour' (not the horn), crowd = 'vismarkt' / 'market', horn = 'horn'."""
    import glob
    fs = sorted(f for f in glob.glob(os.path.join(folder, "*")) if os.path.isfile(f) and f.lower().endswith((".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".flac", ".aac"))); low = lambda f: os.path.basename(f).lower()
    return {"base": next((f for f in fs if any(k in low(f) for k in ("tejo", "harbour", "harbor")) and "horn" not in low(f)), None),
            "crowd": next((f for f in fs if any(k in low(f) for k in ("vismarkt", "market"))), None),
            "horn": next((f for f in fs if "horn" in low(f)), None)}


def decode(path: str):
    """Any audio file ffmpeg can read, as 16 kHz mono float samples (16-bit units)."""
    np = _np(); import subprocess
    exe = "ffmpeg"
    try:
        subprocess.run([exe, "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            import imageio_ffmpeg; exe = imageio_ffmpeg.get_ffmpeg_exe()                          # the copy that  pip install imageio-ffmpeg  brings along
        except Exception:
            sys.exit("The real ambience files need ffmpeg. Easiest:  pip install imageio-ffmpeg   (or: winget install Gyan.FFmpeg, then open a new PowerShell window)")
    try:
        raw = subprocess.run([exe, "-v", "error", "-i", path, "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("ffmpeg could not be started")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffmpeg could not read {path}: {e.stderr.decode(errors='replace').strip()[:160]}")
    return np.frombuffer(raw, dtype="<i2").astype("float64")


def loop_xfade(x, n: int, rng):
    """x repeated to n samples from a random start, each join a 1.5 s cross-fade so there is no click and no obvious loop."""
    np = _np(); xf = min(int(1.5 * RATE), len(x) // 4); x = np.roll(x, -int(rng.integers(0, len(x)))); out = x.copy()
    fo, fi = np.cos(np.linspace(0, np.pi / 2, xf)), np.sin(np.linspace(0, np.pi / 2, xf))
    while len(out) < n:
        out = np.concatenate([out[:-xf], out[-xf:] * fo + x[:xf] * fi, x[xf:]])
    return out[:n]


def _unit(v):
    return v / (v.std() + 1e-9)


def make_bed(files: dict, n: int, rng, busy: bool, crowd_gain: float = 1.0, base_gain: float = 0.3):
    """Real background. The fish-market recording is the MAIN layer (its clatter and splashes above 2 kHz are what make it recognisable): the quiet start of the
    recording for calm lots, the loud second half for busy ones. A little of its own low end, and the harbour recording under it at base_gain.
    A slow swell (4-12 s) and a faster flutter (0.5-1.5 s) keep it from sitting still."""
    np = _np(); t = np.arange(n) / RATE; bed = np.zeros(n)
    if files.get("crowd"):
        cr = decode(files["crowd"]); L = len(cr); lo, hi = (0.55, 1.0) if busy else (0.0, 0.45)
        a0 = int(rng.uniform(lo, max(lo, hi - n / L)) * L) if L > n else 0
        seg = cr[a0: a0 + n] if len(cr[a0: a0 + n]) == n else loop_xfade(cr, n, rng)
        bed = crowd_gain * _unit(_bandpass(seg, 100, 6500)) + 0.5 * _unit(_bandpass(seg, 40, 200))
    if files.get("base"):
        base = _unit(_bandpass(loop_xfade(decode(files["base"]), n, rng), 40, 7900))
        bed = bed + (base_gain if files.get("crowd") else 1.4) * (base + 0.5 * _bandpass(base, 40, 200))
    return _unit(bed * (1 + 0.5 * np.sin(2 * np.pi * t / float(rng.uniform(4, 12)) + rng.uniform(0, 6.28)) + 0.15 * np.sin(2 * np.pi * t / float(rng.uniform(0.5, 1.5)) + rng.uniform(0, 6.28))))


def add_horn(bed, horn_path: str, rng, gap_times: list):
    """One ship's horn, dull and low, starting in a breath between two price calls."""
    np = _np(); h = decode(horn_path)[int(0.2 * RATE): int(3.7 * RATE)]; h = _bandpass(h, 150, 1500); h = h / (np.abs(h).max() + 1e-9) * 0.35 * bed.std() * 3
    fade = int(0.3 * RATE); h[:fade] *= np.linspace(0, 1, fade); h[-fade:] *= np.linspace(1, 0, fade)
    if not gap_times or len(bed) <= len(h):
        return bed
    at = min(int(rng.choice(gap_times) * RATE), len(bed) - len(h)); bed = bed.copy(); bed[at: at + len(h)] += h
    return bed


def load_ambience(path: str, n: int, seed: int = 7):
    """A real recording (any format ffmpeg reads) as the background: converted to 16 kHz mono, looped, random start."""
    np = _np(); import subprocess
    if not os.path.exists(path):
        sys.exit(f"--ambience: I cannot find the file  {path}")
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    except FileNotFoundError:
        try:
            with wave.open(path) as w:                                       # no ffmpeg: only a plain 16 kHz mono 16-bit WAV can be read
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
                    sys.exit("Without ffmpeg only 16 kHz mono 16-bit WAV files can be used as --ambience.  winget install Gyan.FFmpeg  fixes that.")
                raw = w.readframes(w.getnframes())
        except wave.Error:
            sys.exit("Without ffmpeg only WAV files can be used as --ambience.  winget install Gyan.FFmpeg  fixes that.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"--ambience: ffmpeg could not read {path} as audio: {e.stderr.decode(errors='replace').strip()[:160]}")
    x = np.frombuffer(raw, dtype="<i2").astype("float64")
    if x.size < RATE:
        sys.exit(f"{path}: that recording is shorter than one second")
    x = np.tile(x, int(n / x.size) + 2)[np.random.default_rng(seed).integers(0, x.size): ][:n]
    return x / (x.std() + 1e-9)


def mix(pcm: bytes, bed, snr_db: float) -> bytes:
    """Mix a background in at snr_db, measured on the VOICED part of the speech (so quiet gaps do not flatter the number)."""
    np = _np(); x = _f(pcm); bed = bed[: len(x)]
    voiced = x[np.abs(x) > 0.05 * np.abs(x).max()]
    bed = bed * (np.sqrt(np.mean(voiced ** 2)) / (10 ** (snr_db / 20)))
    y = x + bed; m = float(np.abs(y).max())
    return _pcm(y * (31500.0 / m) if m > 31500.0 else y)      # samples are 16-bit units here (max 32767)                    # a loud shout on top of the background must not clip


# ======================================================================== chant rhythm: dragging and clipping words, never the same twice
def warp(pcm: bytes, speed) -> bytes:
    """Time-varying speed WITHOUT changing the pitch (WSOLA, as stretch(), but the speed may change along the sound).
    speed(p) gets the position p in 0..1 through the input and returns the local speed: 1 = as is, 0.5 = twice as long (a DRAG), 1.4 = clipped."""
    np = _np(); src = _f(pcm); L = len(src)
    if L < 1000:
        return pcm
    N = int(0.030 * RATE); Hs = N // 2; tol = int(0.008 * RATE); win = np.hanning(N)
    x = np.concatenate([np.zeros(N + tol), src, np.zeros(3 * N + tol)])
    cap = int(L / 0.35) + 4 * N
    out = np.zeros(cap); norm = np.zeros(cap); prev = tol; pos = 0.0; k = 0
    out[:N] += win * x[prev: prev + N]; norm[:N] += win
    while True:
        pos += Hs * float(speed(min(1.0, pos / L)))
        if pos >= L or (k + 2) * Hs + N >= cap:
            break
        k += 1; nominal = tol + int(round(pos)); ref = x[prev + Hs: prev + Hs + N]
        cand = x[nominal - tol: nominal + tol + N]
        c = np.correlate(cand, ref, mode="valid"); e = np.sqrt(np.convolve(cand ** 2, np.ones(N), mode="valid") + 1e-9)
        best = nominal - tol + int(np.argmax(c / e)); prev = best
        out[k * Hs: k * Hs + N] += win * x[best: best + N]; norm[k * Hs: k * Hs + N] += win
    out = out[: k * Hs + N] / np.maximum(norm[: k * Hs + N], 1e-6)
    return _pcm(out)


def glide(pcm: bytes, semitones: float, start: float = 0.55) -> bytes:
    """Bend the pitch of the last part of a word up or down by `semitones` (a chanter's voice rises or falls as the word is held).
    Done by reading the sound at a changing rate, which also changes its length: the caller re-times it afterwards."""
    if abs(semitones) < 0.05:
        return pcm
    np = _np(); x = _f(pcm); L = len(x); a = int(L * start); pos = [0.0]; p = 0.0
    while p < L - 1:
        st = 0.0 if p < a else semitones * min(1.0, (p - a) / max(1, L - a))
        p += 2 ** (st / 12); pos.append(p)
    pos = np.array(pos[:-1])
    return _pcm(np.interp(pos, np.arange(L), x))


def drag_unit(unit: bytes, speed: float, drag: float, bend: float, gain: float) -> bytes:
    """One call of a price, spoken the way chants are: `speed` rushes or relaxes the whole word, the LAST syllables are held `drag` times longer
    (1.0 = not held), with a pitch bend of `bend` semitones on the held part, and `gain` is the accent."""
    np = _np()
    if speed == 1.0 and drag <= 1.0 and not bend and gain == 1.0:
        return unit
    u = glide(unit, bend) if bend else unit
    tail_slow = speed / max(drag, 1.0)
    sp = lambda p: speed + (tail_slow - speed) * min(1.0, max(0.0, (p - 0.55) / 0.12))          # head at `speed`, a quick ramp, tail at `tail_slow`
    return _pcm(_f(warp(u, sp)) * gain)


def rhythm(rng, n: int, intensity: float) -> list:
    """The timing of the n repeats of one price. Real chants are not metronomes and not templates: usually the LAST call is held and stressed, but sometimes
    a middle one is, and sometimes a whole burst is just rushed; the first calls are clipped or relaxed; the breaths between repeats differ.
    intensity 0 = perfectly even (like plain TTS), 1 = very loose."""
    held_at = n - 1 if rng.random() < 0.7 else int(rng.integers(0, n))           # where the long one lands
    rushed_burst = n > 1 and rng.random() < 0.18 * intensity                      # now and then nothing is held at all
    out = []
    for i in range(n):
        last = i == n - 1; held_here = (i == held_at) and not rushed_burst
        speed = float(rng.uniform(1.0 - 0.14 * intensity, 1.0 + 0.45 * intensity)) if not (last and held_here) else float(rng.uniform(1.0 - 0.08 * intensity, 1.0 + 0.05 * intensity))
        if rushed_burst:
            speed *= 1.0 + 0.15 * intensity
        extra = intensity * 1.2 * float(rng.uniform(0.8, 1.5))                   # how much longer the end of the word is held, before the cap
        held = 1.0 + (extra if held_here else (0.3 * extra if rng.random() < 0.25 * intensity else 0.0))
        bend = float(rng.uniform(-2.5, 2.5)) * intensity if held > 1.1 else 0.0
        out.append({"speed": speed, "drag": min(held, 2.3), "bend": bend, "gain": 1.0 + (0.06 * i + (0.08 if last else 0.0)) * intensity,
                    "gap": 0.0 if last else 0.05 + float(rng.uniform(-0.04, 0.05)) * intensity})
    return out


def polish(pcm: bytes) -> bytes:
    """Gentle studio-style clean-up of the voices (before the background goes in): drop the rumble below 80 Hz, lift the 1.5-4.5 kHz 'presence' a little,
    then a slow, mild compressor that evens the level out so the last words (the buyer's name) are not quieter than the calls. Quiet gaps are left alone."""
    np = _np(); x = _f(pcm); x = _bandpass(x, 80, 4500); x = x + 0.35 * _bandpass(x, 300, 1000) + 0.05 * _bandpass(x, 1500, 4500)
    w = int(0.04 * RATE); env = np.sqrt(np.convolve(x * x, np.ones(w) / w, mode="same")) + 1.0
    live = env > 0.03 * env.max()
    target = float(np.percentile(env[live], 70)) if live.any() else 1.0
    g = np.clip((target / env) ** 0.4, 0.6, 2.0); g[~live] = 1.0
    g = np.convolve(g, np.ones(int(0.02 * RATE)) / int(0.02 * RATE), mode="same")
    y = x * g; m = float(np.abs(y).max())
    return _pcm(y * (28000.0 / m) if m > 0 else y)


def pitch(pcm: bytes, semitones: float) -> bytes:
    """Change the pitch (a different-sounding man) and keep the length: resample, then restore the length with the pitch-preserving stretch."""
    if abs(semitones) < 0.05:
        return pcm
    np = _np(); f = 2 ** (semitones / 12); x = _f(pcm)
    y = np.interp(np.arange(0, len(x) - 1, f), np.arange(len(x)), x)
    return stretch(_pcm(y), 1.0 / f)


BIDDER_PITCH = (-1.5, -3.0, -2.0, -4.0)               # every bidder is pitched DOWN (older, heavier men), each by a different amount, plus a small wobble per shout


def syl(text: str) -> int:
    """A rough syllable count of Tamil text (independent vowels + consonants that carry a vowel). Good enough to compare speaking rates, not exact."""
    t = re.sub(r"<[a-z ]+>", " ", text); n = 0
    for i, ch in enumerate(t):
        o = ord(ch)
        if 0x0B85 <= o <= 0x0B94: n += 1
        elif 0x0B95 <= o <= 0x0BB9 and not (i + 1 < len(t) and t[i + 1] == "\u0BCD"): n += 1
    return max(n, 1)


def pace_target(rng, median: float = 5.4, sigma: float = 0.30) -> float:
    """How fast this call is spoken, in syllables per second: around the pace measured in a real auction video (median about 5, p90 about 7, some bursts above 9)."""
    return float(min(max(rng.lognormal(math.log(median), sigma), 4.2), 9.5))


def fit_speed(pcm: bytes, text: str, target: float, lo: float = 0.9, hi: float = 1.6) -> float:
    """The speed factor that takes a phrase from the pace Timbre gave it to `target` syllables per second (pitch is kept by the stretch)."""
    native = syl(text) / max(len(pcm) / 2 / RATE, 0.05)
    return float(min(max(target / native, lo), hi))


def rough(pcm: bytes, rng, depth: float = 0.3) -> bytes:
    """Hoarse, strained shouting: a 55-90 Hz flutter in the loudness, a dull top, a little saturation."""
    np = _np(); x = _f(pcm); t = np.arange(len(x)) / RATE
    x = x * (1 - depth * 0.5 * (1 + np.sin(2 * np.pi * float(rng.uniform(55, 90)) * t + rng.uniform(0, 6.28))))
    x = _bandpass(x, 120, 3800)
    return _pcm(np.tanh(x * 1.8 / 20000) * 20000)


def distant(pcm: bytes, rng, semis: float = 0.0) -> bytes:
    """A bidder standing further away than the auctioneer: quieter, no deep or bright end, one short early reflection off the crates/wall,
    and a slightly faster, more hurried delivery."""
    x = _bandpass(_f(pcm), 260, 3000); d = int(0.045 * RATE); y = x.copy(); y[d:] += 0.22 * x[:-d]
    sp = float(rng.uniform(1.0, 1.1)); out = drag_unit(pitch(_pcm(y), semis), sp, 1.0, 0.0, 1.0) if sp != 1.0 else pitch(_pcm(y), semis)
    return _pcm(_f(out) * float(rng.uniform(0.78, 0.95)))          # clearly audible over the background (it is 12 dB under the auctioneer), but not as close as the auctioneer


def burst_gaps(n: int, rng, within: list = None) -> list:
    """The breath before each burst. Between price levels: 40% short (0.4-0.7 s), 35% medium (0.7-1.2 s), 25% a real pause (1.3-2.4 s). Inside one price level
    (the next 1-3 calls of the same price) mostly short. Never under 0.4 s: the recogniser needs that to close an utterance."""
    out = []
    for i in range(n):
        r = rng.random(); w = bool(within[i]) if within else False
        if w:
            out.append(float(rng.uniform(0.4, 0.7)) if r < 0.7 else float(rng.uniform(0.7, 1.2)) if r < 0.95 else float(rng.uniform(1.3, 2.4)))
        else:
            out.append(float(rng.uniform(0.4, 0.7)) if r < 0.40 else float(rng.uniform(0.7, 1.2)) if r < 0.75 else float(rng.uniform(1.3, 2.4)))
    return out


def lay(segs: list, gap_s, shouts: dict, overlap_s: float, rng, cues: list = None) -> bytes:
    """The auctioneer's bursts one after another (a breath of gap_s between them), with bidders' shouts placed BEFORE the burst whose index is their key.
    Usually the bidder shouts after the breath and the auctioneer takes the price up at once (overlap_s of cross-talk, never more). Now and then
    (about one time in three) the bidder cuts in over the end of the previous burst instead. rng=None = no overlap at all (the clean test version)."""
    np = _np(); gl = [gap_s] * len(segs) if not isinstance(gap_s, list) else gap_s; g = int(gl[0] * RATE); ev, t = [], 0
    for i, sg in enumerate(segs):
        g = int(gl[max(i - 1, 0)] * RATE)                                  # the breath that came before this burst
        if i in shouts:
            b = _f(shouts[i])
            bs = t; t = bs + len(b) + int(0.24 * RATE)                              # the bidder finishes, a short beat, then the auctioneer confirms: two clean utterances, no cross-talk
            ev.append((bs, b))
            if cues is not None:
                cues.append((bs / RATE, "shout", i))
        x = _f(sg); ev.append((t, x)); t += len(x) + g
        if cues is not None:
            cues.append((ev[-1][0] / RATE, "seg", i))
    for key_ in sorted(k for k in shouts if k >= len(segs)):          # the winning bidder's answer: 0.3-0.6 s after the auctioneer's question, nothing after it
        b = _f(shouts[key_]); bs = max(t - g + int((rng.uniform(0.3, 0.6) if rng is not None else 0.45) * RATE), 0); ev.append((bs, b)); t = bs + len(b)
        if cues is not None:
            cues.append((bs / RATE, "shout", key_))
    total = max(st + len(x) for st, x in ev); out = np.zeros(total)
    for st, x in ev:
        out[st: st + len(x)] += x
    return _pcm(out)


STEADY_SPS = 7.4          # --steady on: the auctioneer's opening, every call and the question all run at this pace, in the same <shouting> tone


def t_open(t: str) -> str: return f"<shouting> {t}" if (_cfg["simple"] or _cfg["steady"]) else f"<excited> {t}"
def t_call(t: str) -> str: return f"<shouting> {t}"
def t_held(t: str) -> str: return f"<shouting> {t}" if _cfg["simple"] else f"<slow> {t}"               # <slow> = drawn-out delivery. A tag lasts until the next tag, so it replaces <shouting>, it does not add to it
def t_close(t: str) -> str:
    head, sep, tail = t.partition(" பேரு ")
    return (f"<shouting> {head} <slow> பேரு {tail}" if not _cfg["simple"] else f"<shouting> {t}") if sep else f"<shouting> {t}"                          # the buyer's name is drawn out


def chant_plan(lot: dict, forms: str, no_buyer: bool) -> dict:
    """The lot as separate calls: an opening, then each price level as ONE unit repeated n times, then the close and the buyer.
    With bidders (raise mode): the auctioneer says the FULL price at the start and at the end; in between, both he and the bidders say only the hundreds (3550 -> 550)."""
    levels, calls, i = [], lot["calls"], 0
    while i < len(calls):
        j = i
        while j < len(calls) and calls[j] == calls[i]:
            j += 1
        levels.append((calls[i], j - i)); i = j
    raise_mode = _cfg["shout"] == "raise" and _cfg["ask"]
    last = len(levels) - 1; units, bid = [], []
    for k, (v, c) in enumerate(levels):
        full = say(v, lot["style"], forms)
        short = say(v % 1000, lot["style"], forms) if (v >= 1000 and v % 1000 and _cfg["mid"] == "hundreds") else full           # only the thousands are dropped; 800, 850 ... are already hundreds
        n = min(c, _cfg["cap"]) if _cfg["cap"] else c
        if raise_mode and k >= 1:
            n = 1                                                                                   # the bidder has just said this price: the auctioneer confirms it ONCE
            units.append(((full if k == last else short) + " வேற?", n))                             # full price again only at the very end
        else:
            units.append((full, n))
        bid.append(short)
    return {"open": f"{lot['species']} ஸ்டார்ட் ஆகுது", "bursts": units, "bid": bid, "close": lot["closing"] if no_buyer else (f"{lot['closing']} பேரு?" if _cfg["ask"] else f"{lot['closing']} பேரு {lot['buyer']}")}


SHORT_CALLS = ["போடு", "எடு", "எனக்கு", "இங்க", "சரி"]


LAB = {500: ["ஐநூறு", "அஞ்சூறு", "ஐந்நூறு"], 600: ["அறுநூறு", "அறநூறு"], 700: ["எழுநூறு", "எழநூறு"], 800: ["எண்ணூறு", "எட்டுநூறு"], 300: ["முன்னூறு", "முந்நூறு"],
       550: ["ஐநூத்தம்பது", "ஐநூற்று ஐம்பது"], 750: ["எழுநூத்தம்பது", "எழநூத்தம்பது", "ஏழரை"], 850: ["எண்ணூத்தம்பது", "எட்டுநூத்தம்பது", "எட்டரை"],
       1000: ["ஆயிரம்"], 2000: ["ரெண்டாயிரம்", "இரண்டாயிரம்"], 1500: ["ஆயிரத்தி ஐநூறு", "ஆயிரத்து ஐநூறு"], 3500: ["மூணாயிரத்து ஐநூறு", "மூன்றாயிரத்து ஐநூறு"]}


def number_lab(key: str, voice: str, speed: float, out: pathlib.Path) -> None:
    """Every doubtful spelling spoken three times in a row, as in a chant. Spellings cannot be judged on paper: listen, and pick the one that sounds like a person."""
    d = out / "number_lab"; d.mkdir(parents=True, exist_ok=True); (out / ".cache").mkdir(parents=True, exist_ok=True); lines = []
    for n, vs in LAB.items():
        for i, v in enumerate(vs):
            pcm = trim(to_pcm16k(speak(t_call(" ".join([v] * 3)), voice, speed, key, out / ".cache")))
            name = f"{n}_{chr(97 + i)}.wav"
            with wave.open(str(d / name), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
            lines.append(f"{name}   {v}")
    (d / "labels.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} clips to {d}.  Listen to each pair/trio and tell me, for every number, which letter (a, b, c) sounds right. labels.txt says which spelling each file is.")


def shout_here(lid: str, k: int, last: int) -> bool:
    """Not every raised price gets a bidder's shout (about 60% do; the last one, where the lot is claimed, always does). Deterministic, so the cost preview and the cache agree."""
    if _cfg["shout"] == "raise":
        return True                                                   # every raise is made by a bidder, and heard
    return k == last or (k + sum(map(ord, lid))) % 5 >= 2


def limit_dur(pcm: bytes, text: str, sps_min: float = 6.5, max_stretch: float = 2.2) -> bytes:
    """A shout may not drag: if it is slower than sps_min syllables per second, squeeze it (pitch is kept)."""
    dur = len(pcm) / 2 / RATE; allowed = syl(text) / sps_min
    return stretch(pcm, min(dur / allowed, max_stretch)) if dur > allowed else pcm


AUDITION_TEXT = "<shouting> ஆயிரத்தி ஐநூறு ஆயிரத்தி ஐநூத்தம்பது ஆயிரத்தி அறுநூறு எண்ணூறு ஏழரை போச்சு"


def audition(key: str, speed: float, out: pathlib.Path) -> None:
    """The same chant in every Timbre v3.0 male voice: listen, and pick the auctioneer (and the bidders) by ear."""
    d = out / "audition"; d.mkdir(parents=True, exist_ok=True); (out / ".cache").mkdir(parents=True, exist_ok=True)
    for v in ("Avinash", "Prakash", "Harshad", "Yashraj", "Shubham", "Devansh"):
        pcm = trim(to_pcm16k(speak(AUDITION_TEXT, v, speed, key, out / ".cache")))
        with wave.open(str(d / f"{v}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
    print(f"Wrote 6 clips to {d}. Listen, choose the auctioneer, and run with  --voice <name>  (and  --bidders  with three others).")


def natural_far(pcm: bytes, rng) -> bytes:
    """A bidder a few metres away, still a natural voice: just a band-pass (no pitch shift, no flutter, no echo) and a little less level. The earlier chain (pitch shift + 55-90 Hz flutter + echo) sounded like a robot."""
    return _pcm(_bandpass(_f(pcm), 170, 4800) * float(rng.uniform(0.85, 0.97)))


# --space on: each speaker gets his own "place": distance (level and tone), a room tail and a short reflection that differ from speaker to speaker.
# (index 0 = auctioneer, close but outdoors; 1 and 2 = the two bidders, further away and in different spots). A plain wet/dry reverb, no pitch or flutter effects.
PLACES = [dict(rt=0.22, wet=0.14, lp=6500, pre=0.008, gain=1.00),
          dict(rt=0.30, wet=0.20, lp=4800, pre=0.018, gain=0.95),
          dict(rt=0.40, wet=0.26, lp=4400, pre=0.030, gain=0.92)]


def place(pcm: bytes, which: int, on: bool = True) -> bytes:
    if not on:
        return pcm
    np = _np(); P = PLACES[which % len(PLACES)]; x = _f(pcm); r = np.random.default_rng(100 + which)
    n = int(P["rt"] * RATE); t = np.arange(n) / RATE
    ir = r.normal(size=n) * np.exp(-6.9 * t / P["rt"]); ir = _bandpass(ir, 150, P["lp"]); ir /= np.sqrt((ir ** 2).sum()) + 1e-9      # -60 dB after rt
    pre = int(P["pre"] * RATE); wet = np.convolve(x, ir)[: len(x)]; wet = np.concatenate([np.zeros(pre), wet])[: len(x)]
    y = _bandpass((1 - P["wet"]) * x + P["wet"] * wet * (np.sqrt((x ** 2).mean()) / (np.sqrt((wet ** 2).mean()) + 1e-9)), 150, P["lp"] + 1500)
    y = y * (np.sqrt((x ** 2).mean()) / (np.sqrt((y ** 2).mean()) + 1e-9)) * P["gain"]
    return _pcm(y)


def question_rise(pcm: bytes, semis: float = 3.0, tail: float = 0.4) -> bytes:
    """The last part of a word is lifted by `semis` semitones (pitch only, same length): 'பேரு?' ends like a question."""
    np = _np(); x = _f(pcm); cut = int(len(x) * (1 - tail)); f = int(0.025 * RATE)
    if cut < f or len(x) - cut < 4 * f:
        return pcm
    up = _f(pitch(_pcm(x[cut - f:]), semis)); m = min(len(up), len(x) - cut + f)
    y = np.concatenate([x[:cut - f], np.zeros(m)]); w = np.linspace(0, 1, f)
    y[cut - f:cut] = x[cut - f:cut] * (1 - w) + up[:f] * w; y[cut:cut - f + m] = up[f:m]
    return _pcm(y)


def ask_name_clip(closing: str, unit, steady: bool) -> bytes:
    """'எடுத்துட்டாங்க' and 'பேரு?' are two separate words with a short breath between them, and the second ends with a rising, questioning lift."""
    a_ = unit(t_call(closing)); b_ = unit(t_call("பேரு?"))
    if steady:
        a_ = drag_unit(a_, fit_speed(a_, closing, STEADY_SPS), 1.0, 0.0, 1.0); b_ = drag_unit(b_, fit_speed(b_, "பேரு", STEADY_SPS), 1.0, 0.0, 1.0)
    return a_ + bytes(int(0.14 * RATE) * 2) + question_rise(b_, 2.0, 0.35)


def voiced_rms(pcm: bytes) -> float:
    np = _np(); x = _f(pcm); v = x[np.abs(x) > 0.05 * np.abs(x).max()]
    return float(np.sqrt(np.mean(v ** 2))) + 1e-9 if v.size else 1e-9


def match_level(pcm: bytes, ref_rms: float, offset_db: float = -4.0) -> bytes:
    """A bidder is 4 dB under the auctioneer at the source (distance and the background then take him further down)."""
    np = _np(); x = _f(pcm); y = x * (ref_rms * 10 ** (offset_db / 20) / voiced_rms(pcm)); m = float(np.abs(y).max())
    return _pcm(y * (30000.0 / m) if m > 30000.0 else y)


def shout_clip(text: str, voice: str, speed: float, key: str, cache) -> bytes:
    """A bidder's short word, at least max(0.25 s, 0.09 s per syllable) long. Too short (Timbre sometimes returns a click): the same word without the tag; still too short: EmptyAudio, and that shout is left out."""
    need = max(0.25, 0.09 * syl(text))
    for variant in (text, re.sub(r"<[a-z ]+>\s*", "", text).strip()):
        try:
            x = trim(to_pcm16k(speak(variant, voice, speed, key, cache)))
        except EmptyAudio:
            continue
        if len(x) / 2 / RATE >= need:
            return x
    raise EmptyAudio(f"the clip for {text!r} (voice {voice}) stays shorter than {need:.2f} s")


def winner_of(lid: str, plan: dict, bidders: list) -> str:
    """The bidder who shouted the last (highest) level wins the lot and says his name when the auctioneer asks."""
    return bidders[((len(plan["bursts"]) - 1) + sum(map(ord, lid))) % len(bidders)]


def shout_text(lot: dict, forms: str, no_buyer: bool, k: int) -> str:
    """What a bidder shouts when the price goes up to level k (k >= 1): the new price, once. At the last level of a lot that is sold, he also claims it."""
    plan_ = chant_plan(lot, forms, no_buyer); units = [(plan_["bid"][k] if _cfg["shout"] == "raise" else u.removesuffix(" வேற?"), c) for k, (u, c) in enumerate(plan_["bursts"])]       # the bidder says the price only (hundreds only in raise mode); "வேற?" is the auctioneer's
    if _cfg["shout"] == "short":                                                  # a word, not a number: the bidder only claims the lot (have a coastal speaker confirm the words)
        return t_call(SHORT_CALLS[(k + sum(map(ord, lot["id"]))) % len(SHORT_CALLS)])
    return t_call(units[k][0] + ("" if _cfg["shout"] == "raise" else (" எனக்கு போடுங்க" if (k == len(units) - 1 and not no_buyer) else "")))


def add_noise(pcm: bytes, snr_db: float) -> bytes:
    """Synthetic harbour-like noise (rumble + hiss + slow swell) mixed at the requested speech-to-noise ratio. Needs numpy."""
    import numpy as np
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64); rng = np.random.default_rng(7)
    brown = np.cumsum(rng.normal(size=x.size)); brown -= np.convolve(brown, np.ones(4000) / 4000, mode="same")      # low rumble
    n = brown / (np.std(brown) + 1e-9) * 0.8 + rng.normal(size=x.size) * 0.5                                           # + hiss
    n *= 0.75 + 0.25 * np.sin(np.arange(x.size) / RATE * 2 * np.pi * 0.35)                                             # slow swell
    voiced = x[np.abs(x) > 0.05 * np.abs(x).max()]
    n *= (np.sqrt(np.mean(voiced ** 2)) / (10 ** (snr_db / 20))) / (np.std(n) + 1e-9)
    return np.clip(x + n, -32768, 32767).astype("<i2").tobytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lots", nargs="+", default=DEFAULT_LOTS); ap.add_argument("--script", default=str(HERE.parent / "auction_script_val2.json"))
    ap.add_argument("--model", choices=["timbre-v3.0", "timbre-v2.5"], default="timbre-v3.0", help="timbre-v3.0 (default) understands <shouting>/<slow>/<excited> tags and has 6 male voices that speak Tamil; timbre-v2.5 ignores tags")
    ap.add_argument("--voice", default=None, help="v3.0: Shubham (energetic, default) or Devansh (young, conversational) suit an auctioneer; Avinash/Prakash/Harshad are 'professional'. v2.5 Tamil: Noopur, Trisha (friendly), Brinda/Vedika/Asmita (professional = newsreader)")
    ap.add_argument("--tags", choices=["auto", "off"], default="auto", help="auto: with timbre-v3.0 put <shouting> on calls, <slow> on the held call, <excited> on the opening")
    ap.add_argument("--speed", type=float, default=None, help="Timbre speed. Its limit is 0.85-1.15 (Timbre v2.5). Default 1.15 for --style fast, 1.0 for plain")
    ap.add_argument("--style", choices=["chant", "fast", "plain"], default="chant", help="chant (default): each repeat of a price has its own timing, words dragged and clipped; fast: even bursts; plain: the sheet read in one go"); ap.add_argument("--forms", choices=["spoken", "spoken-old", "slang", "standard"], default="spoken", help="spoken (default): numbers as people SAY them (அஞ்சூறு, எட்டுநூறு) | slang: written colloquial forms | standard: written Tamil")
    ap.add_argument("--gap", type=float, default=0.55, help="breath between bursts, in seconds (the speech service needs about 0.4 s to end an utterance)")
    ap.add_argument("--list", action="store_true", help="print what would be spoken and stop")
    ap.add_argument("--tight", action="store_true", help="shorten the breaths INSIDE a burst (between repeated calls) to ~0.08 s, like a chanter")
    ap.add_argument("--stretch", type=float, default=None, help="extra speed-up WITHOUT raising the pitch, on top of Timbre's own (e.g. 1.25). Needs numpy")
    ap.add_argument("--noise-db", type=float, default=None, help="add a background at this speech-to-noise ratio (12 = busy, 6 = very loud). Needs numpy")
    ap.add_argument("--ambience-dir", default=str(HERE / "ambience"), help="folder with real recordings: a file with 'tejo' or 'harbour' in its name (base), 'vismarkt' or 'market' (crowd), 'horn' (ship's horn)")
    ap.add_argument("--crowd-gain", type=float, default=1.0, help="how loud the fish-market recording is in the background (1.5 = clearer, 0.7 = less)")
    ap.add_argument("--base-gain", type=float, default=0.6, help="how loud the harbour rumble recording is under it (0.45 = more rumble)")
    ap.add_argument("--bed-test", action="store_true", help="only write bed_test_calm.wav and bed_test_busy.wav (the background alone, 20 s each) and stop: listen to them first")
    ap.add_argument("--horn", default="", help="lots that get ONE ship's horn in a breath between calls, e.g. lot52 (default: none; it sits in the voice's frequency range)")
    ap.add_argument("--ambience", default="auto", help="'auto' (the real recordings in --ambience-dir when they are there, else the built-in synthetic bed), 'real', 'harbour' (built-in synthetic fish-hub bed), 'plain' (simple hiss) or the path of a REAL recording (wav/mp3/mp4, needs ffmpeg for non-wav)")
    ap.add_argument("--drag", type=float, default=0.75, help="how loose the chant rhythm is, 0 (even) to 1 (very uneven). Words held at the end, clipped repeats, uneven breaths. Needs numpy")
    ap.add_argument("--seed", type=int, default=1, help="another seed = the same chant performed differently")
    ap.add_argument("--bidders", default="Avinash,Harshad,Yashraj,Prakash", help="Timbre v3.0 voices of the other bidders, comma-separated; they shout each raised price before the auctioneer repeats it, from further away. 'none' = the auctioneer alone")
    ap.add_argument("--overlap", type=float, default=0.12, help="seconds a bidder may talk over the start of the auctioneer's next burst (0 = never). Keep it small: heavy overlap is hard for any speech recogniser")
    ap.add_argument("--rhythm", choices=["varied", "fixed"], default="varied", help="varied: short and long breaths between price levels (like a real auction); fixed: always --gap")
    ap.add_argument("--bed", choices=["target", "old"], default="target", help="target: the synthetic harbour background re-balanced to a measured real one; old: the first version")
    ap.add_argument("--pace", choices=["fit", "free"], default="fit", help="fit: every call is sped up or slowed to a pace drawn around a real auction's (median ~5.4 syllables/s, some bursts above 9); free: only the random speed variation")
    ap.add_argument("--calls-per-price", type=int, default=0, help="0 = as the script has it (a price may be called several times); 1 = every price is said once")
    ap.add_argument("--bidder-shouts", choices=["raise", "price", "short"], default="raise", help="raise (default): each raised price is said ONCE, clearly, by a bidder; the auctioneer then confirms it once (nobody repeats a price after that). short: only a short word (போடு, எடு...). price: old behaviour. short (older text): a bidder only shouts a short word (போடு, எடு, எனக்கு...): never a price, never a name. Only the auctioneer says prices and the buyer's name. price: old behaviour")
    ap.add_argument("--simple-tags", action="store_true", help="only <shouting> on everything: no <excited> opening, no <slow> held call or buyer name")
    ap.add_argument("--number-lab", action="store_true", help="speak the doubtful number spellings three ways each into number_lab\\ and stop: listen, and tell me which sound right")
    ap.add_argument("--audition", action="store_true", help="speak one chant in each male v3.0 voice into audition\\ and stop: choose the auctioneer by ear")
    ap.add_argument("--auctioneer-semis", type=float, default=0.0, help="shift the auctioneer's pitch (negative = deeper, older; try -2.0). Formants move with it, so go gently")
    ap.add_argument("--mid-prices", choices=["full", "hundreds"], default="full", help="full (default): every raise and every confirmation says the whole price once (3550). hundreds: only the hundreds in between (550): natural, but Prisma misheard them in a test (650, 'ஐ நோ நோ') and the ledger flags the lot")
    ap.add_argument("--steady", choices=["on", "off"], default="on", help="on (default): the auctioneer keeps the SAME tone (<shouting> from the first word) and the SAME fast pace from the opening to the question; off: the earlier varied pace and held calls")
    ap.add_argument("--space", choices=["on", "off"], default="on", help="on (default): every speaker sounds like he stands in a different place (own distance, room tail and tone) instead of talking into one microphone")
    ap.add_argument("--split", choices=["on", "off"], default="on", help="on: each price is called in short bursts of 1-3 calls with breaths between; off: one run per price")
    ap.add_argument("--polish", choices=["on", "off"], default="on", help="gentle EQ + compression of the voices before the background is added (chant style only)")
    ap.add_argument("--hub", action="store_true", help="preset: --tight, --stretch 1.25 and a busy harbour background at 14 dB")
    ap.add_argument("--out", default=str(HERE / "synth_demo"))
    a = ap.parse_args()
    if a.hub:                                                  # the chant style already has its own rhythm: --hub then adds only the background
        if a.style != "chant":
            a.tight = True; a.stretch = a.stretch or 1.25
        a.noise_db = 14.0 if a.noise_db is None else a.noise_db
    if a.style == "chant":
        _np()                                                  # fail early, with the pip hint, if numpy is missing
    _cfg["model"] = a.model
    a.voice = a.voice or ("Shubham" if a.model == "timbre-v3.0" else "Noopur")
    tags_on = a.model == "timbre-v3.0" and a.tags == "auto" and a.style == "chant"
    if a.model == "timbre-v3.0" and a.voice not in V3_VOICES:
        sys.exit(f"{a.voice} is not a Timbre v3.0 voice. Its voices: {', '.join(V3_VOICES)}   (male: Avinash, Shubham, Prakash, Devansh, Yashraj, Harshad)")
    bidders = [] if a.bidders.strip().lower() in ("none", "off", "") or not tags_on else [v.strip() for v in a.bidders.split(",") if v.strip()]
    if a.voice in bidders:                                            # the auctioneer is never also a bidder
        bidders = [v for v in bidders if v != a.voice]
        for v in ("Harshad", "Yashraj", "Avinash", "Prakash", "Devansh", "Shubham"):       # keep at least 3 bidder voices, all different from the auctioneer
            if len(bidders) >= 3: break
            if v != a.voice and v not in bidders: bidders.append(v)
    for v in bidders:
        if v not in V3_VOICES:
            sys.exit(f"--bidders: {v} is not a Timbre v3.0 voice. Its voices: {', '.join(V3_VOICES)}")
    if a.bidder_shouts == "raise":
        bidders = bidders[:2]                                         # two rival bidders, so the raising is easy to follow
    _cfg["ask"] = bool(bidders); _cfg["steady"] = a.steady == "on"; _cfg["mid"] = a.mid_prices                                   # with bidders: the auctioneer asks "பேரு?" and the winning bidder says his own name
    os.environ["BED_SHAPE"] = a.bed
    amb = {}
    for d in dict.fromkeys([a.ambience_dir, str(HERE), str(HERE / "synth_demo"), str(pathlib.Path(a.out))]):         # the folder asked for, then where the recordings often end up
        amb = find_ambience(d)
        if amb.get("base") or amb.get("crowd"):
            a.ambience_dir = d; break
    mode = a.ambience
    if a.bed_test:
        if not (amb.get("base") or amb.get("crowd")):
            sys.exit("--bed-test needs the recordings in the ambience folder")
        for name, busy in (("calm", False), ("busy", True)):
            bed = make_bed(amb, 20 * RATE, _np().random.default_rng(3), busy, a.crowd_gain, a.base_gain)
            with wave.open(f"bed_test_{name}.wav", "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(_pcm(bed * 4000))
        sys.exit("Wrote bed_test_calm.wav and bed_test_busy.wav. The market should be clearly audible; if not --crowd-gain 1.5, if it is too much --crowd-gain 0.7 (and --base-gain 0.45 for more rumble).")
    if mode == "auto":
        mode = "real" if (amb.get("base") or amb.get("crowd")) else "harbour"
    if mode == "real" and not (amb.get("base") or amb.get("crowd")):
        sys.exit(f"--ambience real: no recording in {a.ambience_dir} (a file with 'tejo'/'harbour' or 'vismarkt'/'market' in its name)")
    if a.noise_db is not None and mode == "real":
        print("  background: REAL recordings from " + a.ambience_dir + ": " + ", ".join(f"{k} = {os.path.basename(v)}" for k, v in amb.items() if v) + "\n  (Freesound files are often Creative Commons: check each file's page and credit the authors in your demo notes.)")
    elif a.noise_db is not None:
        print("  background: the built-in synthetic bed (put the three Freesound files in " + a.ambience_dir + " for the real one)")
    _cfg["cap"], _cfg["shout"], _cfg["simple"] = a.calls_per_price, a.bidder_shouts, a.simple_tags
    print(f"  make_synth_chants {SCRIPT_VERSION}")
    stretch_f = a.stretch or 1.0
    speed = a.speed if a.speed is not None else (1.15 if a.style in ("fast", "chant") else 1.0)
    key = os.environ.get("GNANI_API_KEY", "")
    if not key and not a.list:
        sys.exit("Set your key first:  $env:GNANI_API_KEY = \"<your key>\"   (never paste it into a chat or a file)")
    if a.audition:
        out_aud = pathlib.Path(a.out); audition(key, _speed["use"] or speed, out_aud); sys.exit(0)
    if a.number_lab:
        out_lab = pathlib.Path(a.out); out_lab.mkdir(parents=True, exist_ok=True); number_lab(key, a.voice or "Shubham", _speed["use"] or speed, out_lab); sys.exit(0)
    lots = {l["id"]: l for l in json.loads(pathlib.Path(a.script).read_text(encoding="utf-8"))["lots"]}
    out = pathlib.Path(a.out); (out / ".cache").mkdir(parents=True, exist_ok=True); (out / "_text").mkdir(exist_ok=True)
    for lid in a.lots:
        if lid not in lots:
            sys.exit(f"{lid} is not in {a.script}")
    if a.style == "chant":                                       # what will this cost? Every different word/price is spoken ONCE and re-used for each repeat
        texts = set()
        for lid in a.lots:
            pl = chant_plan(lots[lid], a.forms, lid in NO_BUYER)
            if tags_on:
                texts |= ({t_call(lots[lid]["closing"]), t_call("பேரு?")} if pl["close"].endswith(" பேரு?") else {t_close(pl["close"])}) | {t_open(pl["open"])} | {t_call(u) for u, _ in pl["bursts"]} | {t_held(u) for u, _ in pl["bursts"]}     # the held variant is only requested if a call is held
            else:
                texts |= {pl["open"], pl["close"]} | {u for u, _ in pl["bursts"]}
        memo = out / ".cache" / (f"speed_{a.voice}_{speed}.json" if a.model == "timbre-v2.5" else f"speed_v3_{a.voice}_{speed}.json")
        use = json.loads(memo.read_text(encoding="utf-8"))["use"] if memo.exists() else speed
        new = [t for t in texts if not _cache_file(out / ".cache", t, a.voice, use).exists()]
        bt = {(bidders[(k + sum(map(ord, lid))) % len(bidders)], shout_text(lots[lid], a.forms, lid in NO_BUYER, k)) for lid in a.lots for k in range(1, len(chant_plan(lots[lid], a.forms, lid in NO_BUYER)["bursts"])) if shout_here(lid, k, len(chant_plan(lots[lid], a.forms, lid in NO_BUYER)["bursts"]) - 1)} if bidders else set()
        if bidders:
            bt |= {(winner_of(lid, chant_plan(lots[lid], a.forms, False), bidders), t_call(lots[lid]["buyer"])) for lid in a.lots if lid not in NO_BUYER}
        n_all = len(texts) + len(bt); n_new = len(new) + sum(1 for v, t in bt if not _cache_file(out / ".cache", t, v, use).exists())
        print(f"  {a.model} · voice {a.voice}" + (" · tags on (<excited> opening, <shouting> calls, <slow> held call and buyer name)" if tags_on else " · no tags") + f"\n  {n_all} different words/prices to speak" + (f" (incl. {len(bt)} bidder shouts, voices {', '.join(bidders)})" if bt else "") + f": up to {n_new} new Timbre requests (very roughly {n_new * 0.1:.1f} credits), {n_all - n_new} already cached\n")
    rows, failed = [], []
    for lid in a.lots:
        if lid not in lots:
            sys.exit(f"{lid} is not in {a.script}")
        l = lots[lid]; plan = None; gap_times = []; no_buyer = lid in NO_BUYER
        if a.style == "chant":
            plan = chant_plan(l, a.forms, no_buyer)
            phrases = [plan["open"]] + [" ".join([u] * c) for u, c in plan["bursts"]] + [plan["close"]]
        elif a.style == "fast":
            phrases = bursts(l, a.forms, no_buyer)
        else:
            phrases = [l["text"].split("பேரு?")[0].strip() if no_buyer else l["text"]]
        if a.list:
            print(f"  {lid}: " + "  |  ".join(phrases)); continue
        try:
            gap = bytes(int(a.gap * RATE) * 2)
            if a.style == "chant":
                rng = _np().random.default_rng(sum(map(ord, lid)) * 7 + a.seed); cache = out / ".cache"
                unit = (lambda t: pitch(trim(to_pcm16k(speak(t, a.voice, speed, key, cache))), a.auctioneer_semis)) if a.auctioneer_semis else (lambda t: trim(to_pcm16k(speak(t, a.voice, speed, key, cache))))
                post = (lambda x: stretch(x, stretch_f)) if stretch_f != 1.0 else (lambda x: x)
                apost = lambda x: place(post(x), 0, a.space == "on")                   # the auctioneer's place
                segs, plain_segs = [], []; shouts_far, shouts_raw, shout_who = {}, {}, {}
                if tags_on:                                                          # Timbre v3.0 does the shouting and the drawn-out words itself; the rhythm engine only varies speed, breaths and stress
                    o = unit(t_open(plan["open"]))
                    if _cfg["steady"]:
                        o = drag_unit(o, fit_speed(o, plan["open"], STEADY_SPS), 1.0, 0.0, 1.0)
                    segs.append(apost(o)); plain_segs.append(o)
                    first_seg, seg_names, cont = {}, [plan["open"]], set()
                    for k, (u_text, count) in enumerate(plan["bursts"]):
                        u = unit(t_call(u_text)); u_slow = None; calls, even = [], []
                        for q in rhythm(rng, count, a.drag):
                            if _cfg["steady"]:                                          # same pace, same level for every call
                                calls.append(drag_unit(u, fit_speed(u, u_text, STEADY_SPS), 1.0, 0.0, 1.0))
                            elif q["drag"] > 1.25:                                      # this call is the held one
                                u_slow = u_slow or unit(t_held(u_text))
                                calls.append(drag_unit(u_slow, q["speed"], 1.0, q["bend"], q["gain"]))
                            else:
                                fs = fit_speed(u, u_text, pace_target(rng, 7.4 if (k >= 1 and u_text.endswith(" வேற?")) else 5.4)) * q["speed"] ** 0.5 if a.pace == "fit" else q["speed"]       # the confirmation after a raise is quick: "...ஐநூறு வேற"
                                calls.append(drag_unit(u, fs, 1.0, 0.0, q["gain"]))
                            calls[-1] += bytes(int(q["gap"] * RATE) * 2); even.append(u + bytes(int(0.05 * RATE) * 2))
                        first_seg[k] = len(segs); i = 0
                        while i < count:                                             # a price is called in short bursts of 1-3 calls with breaths between, not in one long run
                            m = count if (a.split == "off" or a.rhythm == "fixed") else min(int(rng.choice([1, 2, 3], p=[0.45, 0.35, 0.2])), count - i)
                            if i > 0:
                                cont.add(len(segs))
                            segs.append(apost(b"".join(calls[i:i + m]))); plain_segs.append(b"".join(even[i:i + m])); seg_names.append(" ".join([u_text] * m)); i += m
                    if _cfg["ask"] and not no_buyer:
                        c = ask_name_clip(l["closing"], unit, _cfg["steady"]); segs.append(apost(c)); plain_segs.append(c)
                    else:
                        c = unit(t_close(plan["close"])); segs.append(apost(drag_unit(c, fit_speed(c, plan["close"], STEADY_SPS) if _cfg["steady"] else 1.0, 1.0, 0.0, 1.05))); plain_segs.append(c)
                    if bidders and not no_buyer:
                        nm_who = winner_of(lid, plan, bidders); nm = shout_clip(t_call(l["buyer"]), nm_who, speed, key, cache)
                        shouts_raw[len(segs)] = nm; shout_who[len(segs)] = (nm_who, l["buyer"])
                        nm = match_level(limit_dur(nm, l["buyer"], 7.0, 2.2), voiced_rms(o), 0.0)
                        shouts_far[len(segs)] = post(natural_far(nm, rng) if a.bidder_shouts == "raise" else distant(rough(nm, rng, 0.2), rng, BIDDER_PITCH[bidders.index(nm_who) % len(BIDDER_PITCH)]))
                    for k in range(1, len(plan["bursts"])) if bidders else []:                       # a raised price is often first shouted by a bidder, then the auctioneer takes it up
                        if not shout_here(lid, k, len(plan["bursts"]) - 1):
                            continue
                        who = bidders[(k + sum(map(ord, lid))) % len(bidders)]
                        try:
                            bu = shout_clip(shout_text(l, a.forms, no_buyer, k), who, speed, key, cache)
                        except EmptyAudio as e:                                       # a bidder's word came back empty: that shout is left out, the lot is still made
                            print(f"  (skipped one bidder shout: {e})"); continue
                        shouts_raw[first_seg[k]] = bu; shout_who[first_seg[k]] = (who, shout_text(l, a.forms, no_buyer, k))
                        bu = match_level(limit_dur(bu, shout_text(l, a.forms, no_buyer, k), 7.0 if a.bidder_shouts == "raise" else 6.5, 2.2), voiced_rms(o), -1.5 if a.bidder_shouts == "raise" else -4.0)
                        bu = bu if a.pace != "fit" else drag_unit(bu, min(fit_speed(bu, shout_text(l, a.forms, no_buyer, k), pace_target(rng, 6.5)) if a.bidder_shouts != "raise" else fit_speed(bu, shout_text(l, a.forms, no_buyer, k), STEADY_SPS), 1.6), 1.0, 0.0, 1.0)
                        shouts_far[first_seg[k]] = post(place(natural_far(bu, rng), 1 + bidders.index(who), a.space == "on") if a.bidder_shouts == "raise" else distant(rough(bu, rng, float(rng.uniform(0.2, 0.45))), rng, BIDDER_PITCH[bidders.index(who) % len(BIDDER_PITCH)] + float(rng.normal(0, 0.6))))
                else:
                    o = unit(plan["open"]); segs.append(apost(drag_unit(o, 1.0, 1.0 + 0.7 * a.drag, 0.0, 1.0))); plain_segs.append(o)      # "...ஆகுதூ": the opening is held a little
                    for u_text, count in plan["bursts"]:
                        u = unit(u_text); calls, even = [], []
                        for q in rhythm(rng, count, a.drag):
                            calls.append(drag_unit(u, q["speed"], q["drag"], q["bend"], q["gain"]) + bytes(int(q["gap"] * RATE) * 2)); even.append(u + bytes(int(0.05 * RATE) * 2))
                        segs.append(apost(b"".join(calls))); plain_segs.append(b"".join(even))
                    c = unit(plan["close"]); segs.append(apost(drag_unit(c, 1.0, 1.0 + 0.9 * a.drag, 0.0, 1.05))); plain_segs.append(c)    # the buyer's name is held: "...பேரு கோபீ"
                if shouts_far:
                    cues = []
                    pcm, plain_pcm = lay(segs, (burst_gaps(len(segs), rng, [(i + 1) in cont for i in range(len(segs))]) if a.rhythm == "varied" else a.gap), shouts_far, a.overlap, rng, cues), lay(plain_segs, a.gap, shouts_raw, 0.0, None)
                    starts = {i: t for t, kind, i in cues if kind == "seg"}
                    gap_times = [starts[i] + len(segs[i]) / 2 / RATE + 0.05 + LEAD_S for i in range(len(segs) - 1) if i in starts]
                    names = seg_names + [phrases[-1]]
                    sheet = [f"{t + LEAD_S:6.1f}s  " + (f"bidder {shout_who[i][0]:<8}: {re.sub('<[a-z ]+>', '', shout_who[i][1]).strip()}" if kind == "shout" else f"AUCTIONEER {a.voice:<8}: {names[i]}") for t, kind, i in sorted(cues)]
                    (out / "_text" / f"{lid}.cues.txt").write_text("\n".join(sheet) + "\n", encoding="utf-8")
                else:
                    pcm, plain_pcm = gap.join(segs), gap.join(plain_segs)
            else:
                parts = [to_pcm16k(speak(t, a.voice, speed, key, out / ".cache")) for t in phrases]
                plain_pcm = gap.join(trim(x) for x in parts) if a.style == "fast" else parts[0]          # exactly what Timbre said, nothing added
                proc = []
                for x in (parts if a.style == "fast" else parts[:1]):
                    x = trim(x) if a.style == "fast" else x
                    if a.tight:
                        x = tighten(x)
                    if stretch_f != 1.0:
                        x = stretch(x, stretch_f)                       # per burst, so the breath BETWEEN bursts stays exactly --gap long
                    proc.append(x)
                pcm = gap.join(proc) if a.style == "fast" else proc[0]
        except Exception as e:
            failed.append((lid, str(e))); print(f"  !! {lid} FAILED: {e}\n     (skipped; the other lots go on. Run the same command again to retry only this one: the words already spoken are cached)", file=sys.stderr); continue
        text = " | ".join(phrases)
        pad = lambda b: bytes(int(LEAD_S * RATE) * 2) + b + bytes(int(TAIL_S * RATE) * 2)
        pcm, plain_pcm = pad(pcm), pad(plain_pcm)
        if a.style == "chant" and a.polish == "on":
            pcm = polish(pcm)
        if a.noise_db is not None:                                  # the background runs under the WHOLE clip, including the breaths and the lead-in
            n = len(pcm) // 2; r_amb = _np().random.default_rng(sum(map(ord, lid)) * 13 + a.seed)
            if mode == "real":
                busy = a.style == "chant" and plan is not None and len(plan["bursts"]) >= 4
                bed = make_bed(amb, n, r_amb, busy, a.crowd_gain, a.base_gain)
                if lid in [x.strip() for x in a.horn.split(",") if x.strip()] and amb.get("horn"):
                    bed = add_horn(bed, amb["horn"], r_amb, gap_times)
                pcm = mix(pcm, bed, a.noise_db if busy else a.noise_db + 3)       # calm lots: 3 dB quieter background
            elif a.ambience == "plain":
                pcm = add_noise(pcm, a.noise_db)
            else:
                bed = harbour_ambience(n, seed=sum(map(ord, lid))) if mode == "harbour" else load_ambience(a.ambience, n, seed=sum(map(ord, lid)))
                pcm = mix(pcm, bed, a.noise_db)
        if pcm != plain_pcm:
            (out / "plain").mkdir(exist_ok=True)
            with wave.open(str(out / "plain" / f"{lid}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(plain_pcm)
        with wave.open(str(out / f"{lid}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
        (out / "_text" / f"{lid}.txt").write_text(text + "\n", encoding="utf-8")
        (out / "_text" / f"{lid}.phrases.json").write_text(json.dumps(phrases, ensure_ascii=False, indent=1), encoding="utf-8")
        exp = "needs review (no buyer spoken)" if lid in NO_BUYER else f"{l['species']} · ₹{l['final_price']} · {l['buyer']}"
        rows.append((lid, len(pcm) / 2 / RATE, exp))
        faster = f"   (was {len(plain_pcm) / 2 / RATE:.1f}s)" if len(plain_pcm) != len(pcm) else ""
        print(f"  {lid}.wav  {len(pcm) / 2 / RATE:5.1f}s{faster}   expect: {exp}")
    if a.list:
        return
    (out / "README.txt").write_text(
        "SYNTHETIC AUDIO. Gnani %s (voice: %s, speed %s, style %s, forms %s) reading the chant sheets of the demo lots%s.\n"
        "It is not a recording of a real auction. Say so wherever you show it.\n" % (a.model.replace("timbre-", "Timbre "), a.voice, _speed["use"] or speed, a.style, a.forms, (f", then {('tightened pauses, ' if a.tight else '') + (f'sped up x{stretch_f} without changing pitch, ' if stretch_f != 1.0 else '')}".rstrip(", ") if (a.tight or stretch_f != 1.0) else "") + (f", with a {'synthetic harbour' if a.ambience == 'harbour' else a.ambience} background at {a.noise_db} dB" if a.noise_db is not None else "")), encoding="utf-8")
    print(f"\nTimbre speed used for every voice: {_speed['use'] or speed}  (1.0 would mean it refused every faster setting)")
    print(f"\nDone: {len(rows)} files in {out}\nNext: in the app press 'Use an audio file instead' and pick one of them.")
    if failed:
        print(f"\nNOT MADE ({len(failed)}): " + ", ".join(l for l, _ in failed) + "   -> run the same command again; only these are requested.", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
