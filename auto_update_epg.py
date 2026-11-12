import gzip
import json
import lzma
import os
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

EPGSHARE_BASE = "https://epgshare01.online/epgshare01/epg_ripper_{}.xml.gz"
EPGSHARE_CODES = ["UK1", "IE1", "US2", "CA2", "AU1", "NZ1", "ZA1", "ALJAZEERA1"]
RYTEC_MIRRORS = [
    "http://www.xmltvepg.nl/{}.xz",
    "http://epg.vuplus-community.net/{}.xz",
    "http://rytecepg.wanwizard.eu/{}.xz",
]
RYTEC_FILES = ["rytecUK_SportMovies", "rytecUK_SkyLive", "rytecUK_Basic"]

OUT = "epg_xtream.xml"
OUT_GZ = "epg_xtream.xml.gz"


def fetch(url, timeout=60, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "epg-builder/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def fetch_xz_from_any_mirror(filename):
    last_err = None
    for base in RYTEC_MIRRORS:
        url = base.format(filename)
        try:
            print("Downloading", url)
            raw = fetch(url, timeout=30, retries=1)
            return lzma.decompress(raw)
        except Exception as e:
            print(f"  mirror failed ({e}), trying next...")
            last_err = e
    raise RuntimeError(f"All mirrors failed for {filename}: {last_err}")


def download_all(tmpdir):
    paths = {}
    for code in EPGSHARE_CODES:
        url = EPGSHARE_BASE.format(code)
        print("Downloading", url)
        data = gzip.decompress(fetch(url))
        p = os.path.join(tmpdir, code + ".xml")
        with open(p, "wb") as f:
            f.write(data)
        paths[code] = p
    for name in RYTEC_FILES:
        data = fetch_xz_from_any_mirror(name)
        p = os.path.join(tmpdir, name + ".xml")
        with open(p, "wb") as f:
            f.write(data)
        paths[name] = p
    return paths


def process_file(path, wanted, out_f):
    """wanted: {source_epg_id: [original_tvg_ids]}"""
    written_ids = set()
    prog_count = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        it = iter(ET.iterparse(f, events=("start", "end")))
        _, root = next(it)
        for event, elem in it:
            if event != "end":
                continue
            if elem.tag == "channel":
                cid = elem.attrib.get("id", "")
                for alias in wanted.get(cid, []):
                    if alias in written_ids:
                        continue
                    written_ids.add(alias)
                    dn = elem.find("display-name")
                    dn_text = dn.text if dn is not None and dn.text else alias
                    out_f.write(f'  <channel id="{escape(alias)}">\n')
                    out_f.write(f'    <display-name lang="en">{escape(dn_text)}</display-name>\n')
                    out_f.write("  </channel>\n")
                elem.clear()
                root.clear()
            elif elem.tag == "programme":
                cid = elem.attrib.get("channel", "")
                aliases = wanted.get(cid)
                if aliases:
                    start = elem.attrib.get("start", "")
                    stop = elem.attrib.get("stop", "")
                    title_el = elem.find("title")
                    desc_el = elem.find("desc")
                    title = escape(title_el.text) if title_el is not None and title_el.text else ""
                    title_lang = title_el.attrib.get("lang", "en") if title_el is not None else "en"
                    desc = escape(desc_el.text) if desc_el is not None and desc_el.text else ""
                    desc_lang = desc_el.attrib.get("lang", "en") if desc_el is not None else "en"
                    for alias in aliases:
                        out_f.write(f'  <programme start="{start}" stop="{stop}" channel="{escape(alias)}">\n')
                        out_f.write(f'    <title lang="{title_lang}">{title}</title>\n')
                        if desc:
                            out_f.write(f'    <desc lang="{desc_lang}">{desc}</desc>\n')
                        out_f.write("  </programme>\n")
                        prog_count += 1
                elem.clear()
                root.clear()
    return written_ids, prog_count


def main():
    with open("mapping.json", encoding="utf-8") as f:
        mapping = json.load(f)

    tvgid_to_match = {}
    for m in mapping:
        if m["match_epg_id"] and m["tvg_id"] not in tvgid_to_match:
            tvgid_to_match[m["tvg_id"]] = (m["match_file"], m["match_epg_id"])

    targets_by_file = {}
    for tvg_id, (fname, epg_id) in tvgid_to_match.items():
        targets_by_file.setdefault(fname, {}).setdefault(epg_id, []).append(tvg_id)

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = download_all(tmpdir)

        tmp_out = os.path.join(tmpdir, OUT)
        total_channels = 0
        total_programmes = 0
        with open(tmp_out, "w", encoding="utf-8") as out_f:
            out_f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            out_f.write('<tv generator-info-name="epg-builder">\n')
            for fname, wanted in targets_by_file.items():
                written, prog_count = process_file(paths[fname], wanted, out_f)
                total_channels += len(written)
                total_programmes += prog_count
                print(f"  {fname}: wrote {len(written)} aliased channels, {prog_count} programmes")
            out_f.write("</tv>\n")

        if total_channels == 0:
            raise RuntimeError("No channels written - aborting without touching committed output")

        with open(tmp_out, "rb") as f_in, gzip.open(OUT_GZ, "wb") as f_out:
            f_out.writelines(f_in)

    print(f"\nTotal: {total_channels} channel ids, {total_programmes} programmes -> {OUT_GZ}")


if __name__ == "__main__":
    main()
