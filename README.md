# IATI Bangladesh Donor Atlas

A donor-landscape dashboard built from IATI Datastore exports for Bangladesh.
No build step, no server, no dependencies beyond Python's standard library.
Designed to live on GitHub Pages.

**Live site:** https://anzeeh.github.io/Bangladesh-Donor-Atlas/

## What's in this repo

```
.
├── index.html          ← the dashboard itself — this is what GitHub Pages serves
├── template.html        ← the HTML/React shell, with a placeholder where data gets injected
├── refresh.py            ← the pipeline: raw CSV in, index.html + data/latest.json out
├── data/
│   └── latest.json       ← processed data, also kept here for inspection/diffing
└── README.md             ← this file
```

`index.html` is fully self-contained: it uses plain vanilla JavaScript with
no external libraries at all — no React, no charting library, no CDN calls.
Charts are drawn as inline SVG. The processed data is embedded directly in
the page as a JSON script tag. There is genuinely nothing to load or install:
double-click `index.html` and it opens offline, and GitHub Pages serves it
as-is. This is deliberate — an earlier version depended on CDN-hosted React
and Babel, which meant a blank page whenever a CDN was slow, blocked, or the
in-browser compile choked. The vanilla build removes every one of those
failure points.

## How to refresh the data

1. **Get a fresh export from the IATI Datastore.**
   Go to https://www.iatistandard.org/en/about-iati/iati-tools-and-systems/
   or use the Datastore Activity Search directly, filter to
   `recipient_country_code: BD`, and export as CSV. Save it locally —
   filename doesn't matter.

2. **Run the refresh script**, pointing it at that file:

   ```bash
   python refresh.py path/to/your-export.csv
   ```

   This regenerates `data/latest.json` and `index.html` in place.

3. **Check the output locally** by opening `index.html` in a browser before
   pushing — confirm the numbers look sane, the date in the header updated,
   and nothing broke.

4. **Commit and push:**

   ```bash
   git add index.html data/latest.json
   git commit -m "Refresh data — $(date +%Y-%m-%d)"
   git push
   ```

   GitHub Pages picks up the change automatically within a minute or two.

No other setup is needed — `refresh.py` only uses Python's standard library
(`csv`, `json`, `collections`, `urllib`), so there's no `pip install` step
and no `requirements.txt` to worry about going stale.

## How the data is structured

The script reads the raw IATI CSV (which has ~280 columns, mostly
comma-packed multi-value fields like transactions, sectors, and policy
markers within a single cell) and produces:

- **Org-level rollups** — total committed/disbursed, activity counts, top
  sectors, theme participation, for every reporting organisation.
- **Sector-level rollups** — DAC sector codes grouped into ~19 readable
  families, with multi-sector activities split proportionally.
- **Theme tagging** — every activity is matched against 16 curated themes
  (climate, governance, RMG/trade, etc.) using keyword search on
  title/description, sector codes, and OECD-DAC policy markers. See the
  `THEMES` dict near the top of `refresh.py` to edit or add themes.
- **Pre-baked positioning summaries** — one paragraph per theme, generated
  deterministically from the computed stats (leading donors, results
  coverage) plus a hand-written one-sentence "why this matters for Sida"
  angle from the `POSITIONING_NOTES` dict. These update automatically
  with the numbers; the analytical framing only changes when you edit
  the dict.
- **Result indicators** — wherever an activity publishes baseline/target/
  actual values for an indicator, these are extracted and shown in the
  activity drill-down. Coverage is roughly 18% of activities and skews
  toward better-resourced reporters — treated honestly as a transparency
  floor, not a performance verdict, in both the UI and the Caveats tab.
- **Source links** — every activity links out to
  [d-portal.org](https://d-portal.org), a public independent viewer for
  IATI data, using its IATI identifier. This is the place to verify any
  figure against the original publisher record.

## Editing themes or positioning notes

Both live in `refresh.py`:

- `THEMES` — the dict of theme ID → keywords/sectors/policy markers used
  for matching. Add a new theme by adding a new key; it'll appear in the
  Topics tab automatically on next refresh.
- `POSITIONING_NOTES` — one sentence per theme ID, your own analytical
  read on where Sida sits relative to other donors in that space. This is
  the one piece of genuine judgment in an otherwise mechanical pipeline —
  worth revisiting each refresh cycle rather than treating as fixed.

## Known limitations

See the **Caveats** tab in the live dashboard for the full list — currency
conversion is indicative, SDC's activity count is inflated by reporting
granularity rather than scale, major donors like the World Bank/IDA, ADB,
JICA, and KfW are underrepresented in IATI's own data, and theme tagging
is keyword-based rather than authoritative. The dashboard surfaces all of
this directly rather than hiding it.


