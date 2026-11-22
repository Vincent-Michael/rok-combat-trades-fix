#!/usr/bin/env python3
"""Infantry-style Markdown reports and trade-ranking SVGs for Combat Lab.

Only verified 7d/Open Field snapshots supplied by each monitor are rendered.
This module never requests data, modifies the historical comparison baseline,
or relabels an unchanged site snapshot as newly generated.
"""
from html import escape

from combat_source import is_fresh, report_status_summary, status_label


def rank_pairs(pairs, results):
    def sort_key(pair):
        snapshot = results[f"{pair[1]}-{pair[2]}"]["snapshot"]
        trade = snapshot.get("tradePercent") if snapshot else None
        return trade is None, -(trade if trade is not None else 0)
    return sorted(pairs, key=sort_key)


def build_trade_svg(troop, pairs, results):
    """Match REPORT_INF.md's dark SVG chart, including 100% break-even line."""
    label = troop.capitalize()
    ranked = rank_pairs(pairs, results)
    trades = [
        result["snapshot"]["tradePercent"]
        for result in results.values()
        if result["snapshot"] and result["snapshot"].get("tradePercent") is not None
    ]
    limit = 200  # Fixed 0–200% axis for all Combat Lab trade charts
    x0, width, y0, step = 328, 660, 90, 52
    yaxis = y0 + len(ranked) * step
    height = yaxis + 77
    break_even = x0 + width * 100 / limit

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {height}" role="img" aria-label="{label} trade efficiency ranking">',
        f'<rect x="1" y="1" width="1198" height="{height-2}" rx="16" fill="#172234" stroke="#344258" stroke-width="2"/>',
        '<circle cx="26" cy="31" r="7" fill="#22c55e"/><text x="43" y="37" fill="#22c55e" font-family="Arial,sans-serif" font-size="18" font-weight="600">Positive (&gt;100%)</text>',
        '<circle cx="280" cy="31" r="7" fill="#ef4444"/><text x="297" y="37" fill="#ef4444" font-family="Arial,sans-serif" font-size="18" font-weight="600">Negative (&lt;100%)</text>',
    ]
    for index, (name, primary, secondary) in enumerate(ranked):
        y = y0 + index * step
        snapshot = results[f"{primary}-{secondary}"]["snapshot"]
        trade = snapshot.get("tradePercent") if snapshot else None
        color = "#22c55e" if trade is not None and trade > 100 else "#ef4444" if trade is not None and trade < 100 else "#94a3b8"
        svg.append(f'<rect x="{x0}" y="{y-25}" width="{width}" height="32" rx="5" fill="#28374d"/>')
        if trade is not None:
            svg.append(
                f'<rect x="{x0}" y="{y-25}" width="{max(0,min(width,width*trade/limit)):.2f}" height="32" rx="5" fill="{color}"/>'
            )
        trade_text = f"{trade:.2f}%" if trade is not None else "N/A"
        svg.extend([
            f'<text x="20" y="{y-2}" fill="#9baec9" font-family="Arial,sans-serif" font-size="18">{index+1}</text>',
            f'<text x="53" y="{y-2}" fill="#f1f5f9" font-family="Arial,sans-serif" font-size="19">{escape(name)}</text>',
            f'<text x="1172" y="{y-2}" text-anchor="end" fill="{color}" font-family="Arial,sans-serif" font-weight="bold" font-size="22">{trade_text}</text>',
        ])
    svg.append(
        f'<line x1="{break_even:.2f}" y1="53" x2="{break_even:.2f}" y2="{yaxis-29}" stroke="#e2e8f0" stroke-width="2" stroke-dasharray="6 7"/>'
    )
    svg.extend([
        f'<line x1="{x0}" y1="{yaxis-31}" x2="{x0+width}" y2="{yaxis-31}" stroke="#51617a"/>',
        f'<text x="{x0}" y="{yaxis-7}" text-anchor="middle" fill="#b4c3d8" font-family="Arial" font-size="18">0%</text>',
        f'<text x="{break_even:.2f}" y="{yaxis-7}" text-anchor="middle" fill="#f1f5f9" font-family="Arial" font-size="18">100%</text>',
        f'<text x="{x0+width}" y="{yaxis-7}" text-anchor="middle" fill="#b4c3d8" font-family="Arial" font-size="18">{limit}%</text>',
        f'<text x="600" y="{yaxis+37}" text-anchor="middle" fill="#cbd5e1" font-family="Arial" font-size="16">Dashed line = 100% break-even · Latest verified site snapshot</text>',
        '</svg>',
    ])
    return "\n".join(svg) + "\n"


def build_trade_report(troop, pairs, results, now):
    """Use the structure and units of REPORT_INF.md for other troop types."""
    label = troop.capitalize()
    ranked = rank_pairs(pairs, results)
    verified = sum(bool(r["ok"]) for r in results.values())
    fresh = sum(bool(r["ok"] and is_fresh(r["snapshot"])) for r in results.values())
    stale = sum(bool(r["snapshot"] and not is_fresh(r["snapshot"])) for r in results.values())
    stamps = sorted({r["snapshot"]["generatedAtUTC"] for r in results.values() if r["snapshot"]})
    site_stamp = ", ".join(stamps) if stamps else "N/A"
    report_name = "REPORT_" + ("CAV" if troop == "cavalry" else "ARCHER") + ".md"
    data_name = "trades_" + ("cav" if troop == "cavalry" else "archer") + ".json"

    lines = [
        f"# RoK Combat Lab — {label} Trade Report",
        "",
        f"**Workflow checked UTC:** {now}  ",
        f"**API site-generated UTC:** {site_stamp}  ",
        f"**Successful monitor checks:** {verified}/{len(pairs)}  ",
        f"**Source verification:** {report_status_summary(results)}  ",
        f"**Fresh site snapshots (age <= 8h):** {fresh}/{len(pairs)}  ",
        f"**Stale site snapshots:** {stale}/{len(pairs)}  ",
        "**Scenario:** 7 Days / Open Field ([3,1]); rolling seven days, independent of eight-hour monitoring.",
        "",
        "**Data age:** Successful API retrieval does NOT imply newly generated statistics. Snapshots older than 8 hours are marked STALE. Cache bypass cannot force an upstream refresh.",
        "",
        "## Trade Efficiency Ranking",
        "",
        f"![Trade efficiency ranking](charts/{troop}.svg)",
        "",
        "## Trade Ranking & Battle Reports",
        "",
        "| Rank | Commander Pairing | Trade % | Δ pp | Reports | Site-generated UTC | Source status |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    for index, (name, primary, secondary) in enumerate(ranked, start=1):
        result = results[f"{primary}-{secondary}"]
        snapshot, prior = result["snapshot"], result.get("previous")
        trade = snapshot.get("tradePercent") if snapshot else None
        old = prior.get("tradePercent") if prior else None
        delta = f"{trade-old:+.2f}" if trade is not None and old is not None else "N/A"
        value = f"{trade:.2f}%" if trade is not None else "N/A"
        reports = f'{snapshot["battles"]:,}' if snapshot else "N/A"
        timestamp = snapshot.get("generatedAtUTC", "N/A") if snapshot else "N/A"
        link = f"https://rokbattles.com/combat-lab?primary={primary}&secondary={secondary}"
        lines.append(
            f"| {index} | [{name}]({link}) | {value} | {delta} | {reports} | {timestamp} | {status_label(result['status'], snapshot)} |"
        )

    unavailable = [name for name, primary, secondary in ranked if not results[f"{primary}-{secondary}"]["snapshot"]]
    retained = [
        name for name, primary, secondary in ranked
        if results[f"{primary}-{secondary}"]["snapshot"] and not results[f"{primary}-{secondary}"]["ok"]
    ]
    lines.extend([
        "",
        f"Site-generated: {site_stamp} · Retrieved: {verified}/{len(pairs)} · Fresh site snapshots: {fresh}/{len(pairs)} · Stale site snapshots: {stale}/{len(pairs)} · Retained after errors: {len(retained)} · Unavailable: {len(unavailable)}.",
        "",
        "## Detailed Combat Statistics",
        "",
        "KP Gained and KP Lost are in millions (M). DPS, SPS and TPS are per-second rates.",
        "",
        "| Commander Pairing | KP Gained | KP Lost | DPS | SPS | TPS |",
        "|---|---:|---:|---:|---:|---:|",
    ])

    for name, primary, secondary in ranked:
        snapshot = results[f"{primary}-{secondary}"]["snapshot"]
        metrics = []
        for field in ("killPointsGained", "killPointsLost", "dps", "sps", "tps"):
            value = snapshot.get(field) if snapshot else None
            metrics.append(
                "N/A" if value is None else f"{value/1_000_000:,.3f}M"
                if field in ("killPointsGained", "killPointsLost") else f"{value:.3f}"
            )
        lines.append(f"| {name} | " + " | ".join(metrics) + " |")

    valid = [
        (name, primary, secondary, results[f"{primary}-{secondary}"]["snapshot"])
        for name, primary, secondary in ranked
        if results[f"{primary}-{secondary}"]["snapshot"]
        and results[f"{primary}-{secondary}"]["snapshot"].get("tradePercent") is not None
    ]
    lines.extend(["", "## Key Findings", ""])
    if valid:
        best, worst = valid[0], valid[-1]
        largest = max(valid, key=lambda row: row[3].get("battles", 0))
        smallest = min(valid, key=lambda row: row[3].get("battles", 0))
        lines.append(
            f'**Best trade:** {best[0]} at {best[3]["tradePercent"]:.2f}%. '
            f'**Worst trade:** {worst[0]} at {worst[3]["tradePercent"]:.2f}%.'
        )
        lines.append(
            f'**Largest dataset:** {largest[0]} ({largest[3]["battles"]:,} reports). '
            f'**Smallest dataset:** {smallest[0]} ({smallest[3]["battles"]:,} reports; interpret cautiously).'
        )
    else:
        lines.append("No verified 7-day/Open Field trade values are currently available.")

    changes = []
    for name, primary, secondary, snapshot in valid:
        prior = results[f"{primary}-{secondary}"].get("previous")
        if prior and prior.get("tradePercent") is not None:
            changes.append(f'{name} {snapshot["tradePercent"]-prior["tradePercent"]:+.2f} pp')
    lines.append(
        "**Distinct-snapshot changes:** " + ("; ".join(changes) + "." if changes else
        "N/A (no preceding distinct valid 7-day/Open Field snapshot).")
    )
    if retained:
        lines.append("**Old verified snapshots retained after failed requests:** " + ", ".join(retained) + ".")
    if stale:
        lines.append(
            f"**Source age warning:** {stale}/{len(pairs)} site-generated snapshots exceed 8 hours. "
            "These are historical 7-day rolling windows, NOT current live statistics."
        )
    if unavailable:
        lines.append("**Unverified / N/A:** " + ", ".join(unavailable) + ".")

    errors = [
        f'{name}: {results[f"{primary}-{secondary}"]["error"]}'
        for name, primary, secondary in ranked
        if results[f"{primary}-{secondary}"]["error"]
    ]
    if errors:
        lines.append("**Retrieval failures:** " + "; ".join(errors) + ".")
    lines.extend([
        "",
        f"**Source / monitor status:** [{data_name}](data/{data_name}) · [{report_name}]({report_name}) · "
        f"Workflow checked: {now} · API generated: {site_stamp} · "
        f"Retrievals: {verified}/{len(pairs)} · Fresh site data: {fresh}/{len(pairs)} · "
        f"Stale source: {stale}/{len(pairs)} · Historical data preserved; no 1-year baselines.",
        "",
    ])
    return "\n".join(lines)
