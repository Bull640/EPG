# Custom EPG for Trex playlist

Auto-generated XMLTV guide for the live TV channels in this Xtream/Trex IPTV panel, merged from:

- [epgshare01](https://epgshare01.online/epgshare01/) (UK/IE/US/CA/AU/NZ/ZA)
- [Rytec](https://forums.openpli.org/) UK/Ireland Sky Sports & Movies feeds

`epg_xtream.xml.gz` is keyed by the **original `tvg-id` values** your Xtream panel already supplies, so it can be added as an extra EPG source in TiviMate without changing your playlist or channel source at all.

## EPG URL for TiviMate

```
https://raw.githubusercontent.com/<your-username>/<your-repo>/main/epg_xtream.xml.gz
```

In TiviMate: Settings → Playlists → your playlist → EPG → Add source → paste the URL above.

## Auto-update

`.github/workflows/update-epg.yml` re-runs `auto_update_epg.py` daily (05:00 UTC) via GitHub Actions, re-downloading fresh programme data and committing the updated `epg_xtream.xml.gz`. No manual steps needed as long as the workflow keeps running.

## Re-matching channels

`mapping.json` maps each `tvg-id` to a specific guide-source channel. It was built once from a snapshot of the M3U and does **not** auto-update if Trex renames or adds channels. To refresh it, re-run the matching pipeline against a fresh M3U export.
