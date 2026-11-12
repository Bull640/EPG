import json
import re
import difflib
import xml.etree.ElementTree as ET
import gzip
import shutil

RYTEC_UK = ["rytecUK_SportMovies", "rytecUK_SkyLive", "rytecUK_Basic"]
GROUP_TO_FILES = {
    "UK": ["UK1"] + RYTEC_UK,
    "US": ["US2", "US_LOCALS1", "US_SPORTS1"],
    "CA": ["CA2"],
    "AFR": ["ZA1"],
    "AU": ["AU1"],
    "NZ": ["NZ1"],
    "IR": ["IE1"] + RYTEC_UK,
}
GROUP_TO_FILES["UK"] = GROUP_TO_FILES["UK"] + ["ALJAZEERA1"]
GROUP_TO_FILES["US"] = GROUP_TO_FILES["US"] + ["ALJAZEERA1"]
ALL_FILES = ["UK1", "US2", "US_LOCALS1", "US_SPORTS1", "CA2", "ZA1", "AU1", "NZ1", "IE1", "ALJAZEERA1"] + RYTEC_UK

QUALITY_WORDS = re.compile(
    r"\b(hd|fhd|uhd|hevc|sd|4k|backup|hi|plus1|plus2)\b", re.IGNORECASE
)
FILLER_WORDS = {"channel", "network", "station", "service", "television", "tv", "canada", "canadian"}
NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
LETTER_THEN_DIGIT = re.compile(r"(?<=[a-z])(?=[0-9])")
DIGIT_THEN_LETTER = re.compile(r"(?<=[0-9])(?=[a-z])")
NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
LCN_PREFIX = re.compile(r"^\s*\d+\s*-\s*")
SKYSP_SUFFIX = {
    "mainev": ["main", "event"],
    "fball": ["football"],
    "pl": ["premier", "league"],
    "theopen": ["the", "open"],
}


def expand_skysp(tokens):
    out = []
    for t in tokens:
        if t == "skysp" or t == "skysport" or t == "skysports":
            out.extend(["sky", "sports"])
        elif t.startswith("skysp") and len(t) > 5:
            suf = t[5:]
            out.extend(["sky", "sports"] + SKYSP_SUFFIX.get(suf, [suf]))
        elif t == "pl":
            out.extend(["premier", "league"])
        elif t == "fball":
            out.append("football")
        elif t == "en":
            out.append("english")
        else:
            out.append(t)
    return out


def tokenize(name: str):
    if "|" in name:
        name = name.split("|", 1)[1]
    name = LCN_PREFIX.sub("", name)
    name = name.lower().replace("&", "and")
    name = NON_ALNUM.sub(" ", name)
    name = QUALITY_WORDS.sub(" ", name)
    name = LETTER_THEN_DIGIT.sub(" ", name)
    name = DIGIT_THEN_LETTER.sub(" ", name)
    tokens = [NUM_WORDS.get(t, t) for t in name.split()]
    tokens = expand_skysp(tokens)
    # drop generic filler words, but never down to the point where a brand
    # name becomes a single bare word that could match almost anything
    # (e.g. "Cartoon Network" must not collapse to just "cartoon")
    without_filler = [t for t in tokens if t not in FILLER_WORDS]
    if len(without_filler) >= 2:
        tokens = without_filler
    # "BBC 3 / CBBC" and "BBC 4 / CBEEBIES" are how listings label the
    # timeshare with kids' programming - the schedule that actually airs is
    # CBBC/CBeebies, not a generic "BBC 3"/"BBC 4", so match on that instead.
    if "cbbc" in tokens:
        return ["cbbc"]
    if "cbeebies" in tokens:
        return ["cbeebies"]
    # "Alibi" was rebranded "U & Alibi" - guides disagree on which name to use,
    # so match on the distinctive word alone rather than the filler around it.
    if "alibi" in tokens:
        return ["alibi"] + (["1"] if "1" in tokens else [])
    return tokens


def normalize(name: str) -> str:
    # kept for compatibility: compact form used as a cache key
    return "".join(tokenize(name))


def score_names(a_tokens, b_tokens) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    compact_a, compact_b = "".join(a_tokens), "".join(b_tokens)
    if compact_a == compact_b:
        return 1.0
    num_a = {t for t in a_tokens if t.isdigit()}
    num_b = {t for t in b_tokens if t.isdigit()}
    if num_a != num_b:
        # a channel number ("Sports 1" vs "Sports 2", "Sports" vs "Sports 5")
        # almost always means a genuinely different channel.
        return 0.0
    if len(a_tokens) == len(b_tokens):
        # same number of words, so a length mismatch between the compact
        # forms can only be an abbreviation of one of those words (e.g.
        # "Wal"/"Wales"), never a wholly missing/extra word.
        shorter, longer = sorted((compact_a, compact_b), key=len)
        if len(shorter) >= 4 and len(shorter) / len(longer) >= 0.65 and shorter in longer:
            return 0.95
    wa, wb = set(a_tokens), set(b_tokens)
    inter = wa & wb
    if min(len(wa), len(wb)) == 1:
        # a single-word name is too ambiguous to fuzzy-match against a
        # multi-word candidate (e.g. "Discovery" could be "Discovery Channel"
        # or "Investigation Discovery") - require exact compact equality only.
        return 0.0
    if len(wa) != len(wb):
        # different token counts almost always means a regional/variant
        # qualifier (e.g. "Fox Sports Wisconsin" vs "Fox Sports") rather than
        # the same channel - too risky to treat as a match via word overlap.
        return 0.0
    jaccard = len(inter) / len(wa | wb)
    if jaccard >= 0.65:
        ratio = difflib.SequenceMatcher(None, compact_a, compact_b).ratio()
        return max(jaccard, 0.5 * jaccard + 0.5 * ratio)
    return 0.0


def load_channel_names(fname):
    """Stop reading as soon as the first <programme> is hit (channels always come first)."""
    path = f"{fname}.xml"
    result = []  # list of (id, display_name)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        context = ET.iterparse(f, events=("end",))
        for event, elem in context:
            if elem.tag == "channel":
                cid = elem.attrib.get("id", "")
                for dn in elem.findall("display-name"):
                    if dn.text:
                        result.append((cid, dn.text))
                elem.clear()
            elif elem.tag == "programme":
                break
    return result


print("Loading channel name lists from each source file...")
source_channels = {}  # fname -> list of (id, tokens, raw_name)
for fname in ALL_FILES:
    raw = load_channel_names(fname)
    tok_list = [(cid, tokenize(name), name) for cid, name in raw]
    source_channels[fname] = tok_list
    print(f"  {fname}: {len(raw)} display-name entries")

with open("channels.json", encoding="utf-8") as f:
    entries = json.load(f)

match_cache = {}
mapping = []  # per-entry result

for e in entries:
    group_prefix = e["group"].split("|")[0].strip() if "|" in e["group"] else e["group"].strip()
    files = GROUP_TO_FILES.get(group_prefix, ALL_FILES)
    q_tokens = tokenize(e["name"])
    cache_key = (tuple(files), tuple(q_tokens))

    if cache_key in match_cache:
        best = match_cache[cache_key]
    else:
        best = (None, None, 0.0, None)  # file, epg_id, score, matched_raw_name
        second_score = 0.0
        best_compact = None
        for fname in files:
            for cid, cand_tokens, cand_raw in source_channels[fname]:
                if not cand_tokens:
                    continue
                score = score_names(q_tokens, cand_tokens)
                if score <= 0.0:
                    continue
                compact = "".join(cand_tokens)
                if score > best[2]:
                    if best_compact is not None and compact != best_compact:
                        second_score = best[2]
                    best = (fname, cid, score, cand_raw)
                    best_compact = compact
                elif compact != best_compact and score > second_score:
                    second_score = score
        # ambiguous: a meaningfully different candidate scored almost as well
        if best[2] < 1.0 and second_score >= best[2] - 0.03:
            best = (None, None, 0.0, None)
        match_cache[cache_key] = best

    mapping.append({
        "tvg_id": e["tvg_id"],
        "name": e["name"],
        "group": e["group"],
        "match_file": best[0],
        "match_epg_id": best[1],
        "match_score": round(best[2], 3),
        "match_name": best[3],
    })

THRESHOLD = 0.65
matched = [m for m in mapping if m["match_score"] >= THRESHOLD]
unmatched = [m for m in mapping if m["match_score"] < THRESHOLD]

print()
print(f"Matched {len(matched)} / {len(mapping)} entries (threshold {THRESHOLD})")

by_group = {}
for m in mapping:
    g = m["group"].split("|")[0].strip() if "|" in m["group"] else m["group"]
    by_group.setdefault(g, [0, 0])
    by_group[g][1] += 1
    if m["match_score"] >= THRESHOLD:
        by_group[g][0] += 1
print("By group (matched/total):")
for g, (ok, tot) in sorted(by_group.items(), key=lambda x: -x[1][1]):
    print(f"  {g}: {ok}/{tot}")

with open("mapping.json", "w", encoding="utf-8") as f:
    json.dump(mapping, f, indent=1)
with open("unmatched.txt", "w", encoding="utf-8") as f:
    for m in sorted(unmatched, key=lambda x: x["group"]):
        f.write(f"[{m['group']}] {m['name']}  (best guess: {m['match_name']!r} score={m['match_score']})\n")

print("\nSaved mapping.json (full mapping) and unmatched.txt (entries with no good match)")
