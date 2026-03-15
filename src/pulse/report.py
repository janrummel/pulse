"""Generate a static HTML report from Pulse data."""

import json
import sqlite3
import webbrowser
from datetime import datetime
from pathlib import Path


def generate_report(db_path: str, output_path: str | None = None, open_browser: bool = True) -> Path:
    """Generate HTML report from Pulse SQLite database.

    Args:
        db_path: Path to the Pulse SQLite database.
        output_path: Where to write the HTML file. Defaults to ~/.pulse/report.html.
        open_browser: Whether to open the report in the default browser.

    Returns:
        Path to the generated HTML file.
    """
    if output_path is None:
        out = Path.home() / ".pulse" / "report.html"
    else:
        out = Path(output_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Query 1: Tool mix (top 5 + "Other")
    tool_mix_all = conn.execute("""
        SELECT tool_name, COUNT(*) as count
        FROM events
        WHERE tool_name IS NOT NULL AND event_type = 'PreToolUse'
        GROUP BY tool_name
        ORDER BY count DESC
    """).fetchall()
    tool_mix_top = tool_mix_all[:5]
    tool_mix_other = sum(r["count"] for r in tool_mix_all[5:])
    tool_mix_total = sum(r["count"] for r in tool_mix_all)

    # Query 2: Events per day
    daily_events = conn.execute("""
        SELECT date(timestamp) as day, COUNT(*) as count
        FROM events
        GROUP BY day
        ORDER BY day
    """).fetchall()

    # Query 3: Session sizes
    sessions = conn.execute("""
        SELECT session_id, COUNT(*) as events,
               MIN(timestamp) as start_time, MAX(timestamp) as end_time
        FROM events
        GROUP BY session_id
        HAVING events > 5
        ORDER BY events DESC
        LIMIT 15
    """).fetchall()

    # Query 4: Error rate per tool
    error_rates = conn.execute("""
        SELECT tool_name,
               SUM(CASE WHEN tool_output_success = 0 THEN 1 ELSE 0 END) as failures,
               COUNT(*) as total,
               ROUND(100.0 * SUM(CASE WHEN tool_output_success = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as fail_pct
        FROM events
        WHERE event_type = 'PostToolUse' AND tool_name IS NOT NULL
        GROUP BY tool_name
        HAVING total > 10 AND fail_pct > 0
        ORDER BY fail_pct DESC
    """).fetchall()

    # Query 5: Prompts per hour
    prompts_per_hour = conn.execute("""
        SELECT CAST(strftime('%H', timestamp) AS INTEGER) as hour, COUNT(*) as count
        FROM events
        WHERE event_type = 'UserPromptSubmit'
        GROUP BY hour
        ORDER BY hour
    """).fetchall()

    # Query 6: Summary stats
    total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    total_sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM events").fetchone()[0]
    total_prompts = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'UserPromptSubmit'"
    ).fetchone()[0]
    date_range_row = conn.execute(
        "SELECT MIN(date(timestamp)), MAX(date(timestamp)) FROM events"
    ).fetchone()
    first_day = date_range_row[0] or "—"
    last_day = date_range_row[1] or "—"

    conn.close()

    def _short_name(name: str) -> str:
        return name.split("__")[-1] if "__" in name else name

    # Tool mix: top 5 + Other
    tool_labels = [_short_name(r["tool_name"]) for r in tool_mix_top]
    tool_data = [r["count"] for r in tool_mix_top]
    if tool_mix_other > 0:
        tool_labels.append("Other")
        tool_data.append(tool_mix_other)

    # Top tool for insight
    top_tool = _short_name(tool_mix_top[0]["tool_name"]) if tool_mix_top else "—"
    top_tool_pct = round(100 * tool_mix_top[0]["count"] / tool_mix_total, 0) if tool_mix_top and tool_mix_total else 0

    # Peak hour for insight
    peak_hour_row = max(prompts_per_hour, key=lambda r: r["count"]) if prompts_per_hour else None
    peak_hour = f"{peak_hour_row['hour']:02d}:00" if peak_hour_row else "—"
    peak_hour_count = peak_hour_row["count"] if peak_hour_row else 0

    # Top error tool for insight
    top_error_tool = _short_name(error_rates[0]["tool_name"]) if error_rates else None
    top_error_pct = error_rates[0]["fail_pct"] if error_rates else 0

    # Build insights
    insights = []
    if top_error_tool and top_error_pct > 5:
        insights.append(f"{top_error_tool} has a {top_error_pct}% failure rate — your biggest cost driver.")
    insights.append(f"{top_tool} dominates your tool mix at {top_tool_pct:.0f}%.")
    if peak_hour_row:
        insights.append(f"Peak activity: {peak_hour} ({peak_hour_count} prompts).")
    if sessions:
        insights.append(f"Largest session: {sessions[0]['events']:,} events ({sessions[0]['start_time'][:10]}).")

    # Prepare JSON data for Chart.js
    chart_data = {
        "toolMix": {
            "labels": tool_labels,
            "data": tool_data,
        },
        "dailyEvents": {
            "labels": [r["day"] for r in daily_events],
            "data": [r["count"] for r in daily_events],
        },
        "sessions": {
            "labels": [r["start_time"][:16].replace("T", " ") for r in sessions],
            "data": [r["events"] for r in sessions],
        },
        "errorRates": {
            "labels": [_short_name(r["tool_name"]) for r in error_rates],
            "data": [r["fail_pct"] for r in error_rates],
            "totals": [r["total"] for r in error_rates],
        },
        "promptsPerHour": {
            "labels": [f"{r['hour']:02d}:00" for r in prompts_per_hour],
            "data": [r["count"] for r in prompts_per_hour],
        },
    }

    html = _build_html(chart_data, total_events, total_sessions, total_prompts, first_day, last_day, insights)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    if open_browser:
        webbrowser.open(f"file://{out.resolve()}")

    return out


def _build_html(
    data: dict,
    total_events: int,
    total_sessions: int,
    total_prompts: int,
    first_day: str,
    last_day: str,
    insights: list[str] | None = None,
) -> str:
    """Build the complete self-contained HTML string with Chart.js visualizations."""
    insights_html = ""
    if insights:
        items = "".join(f'<li>{i}</li>' for i in insights)
        insights_html = f"""
    <div class="insights">
        <h2>Key Insights</h2>
        <ul>{items}</ul>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pulse Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        :root {{
            --bg: #0d1117;
            --card: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-dim: #848d97;
            --text-heading: #e6edf3;
            --accent: #58a6ff;
            --green: #3fb950;
            --yellow: #d29922;
            --red: #f85149;
            --font-sans: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            --font-mono: 'SF Mono', 'Fira Code', monospace;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: var(--font-sans);
            line-height: 1.6;
            padding: 40px 24px;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{
            font-size: 28px;
            color: var(--text-heading);
            margin-bottom: 4px;
            letter-spacing: -0.5px;
        }}
        .subtitle {{
            color: var(--text-dim);
            font-size: 14px;
            margin-bottom: 32px;
        }}
        .kpi-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 32px;
        }}
        .kpi {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .kpi-value {{
            font-size: 32px;
            font-weight: 700;
            color: var(--accent);
            font-family: var(--font-mono);
        }}
        .kpi-label {{
            font-size: 12px;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 4px;
        }}
        .charts {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        @media (max-width: 700px) {{
            .charts {{ grid-template-columns: 1fr; }}
        }}
        .chart-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }}
        .chart-card h3 {{
            font-size: 14px;
            color: var(--text-heading);
            margin-bottom: 16px;
            font-weight: 600;
        }}
        .chart-card.wide {{
            grid-column: 1 / -1;
        }}
        canvas {{ max-height: 300px; }}
        .insights {{
            background: var(--card);
            border: 1px solid var(--border);
            border-left: 3px solid var(--accent);
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 32px;
        }}
        .insights h2 {{
            font-size: 16px;
            color: var(--text-heading);
            margin-bottom: 10px;
            font-weight: 600;
        }}
        .insights ul {{
            list-style: none;
            padding: 0;
        }}
        .insights li {{
            font-size: 14px;
            color: var(--text);
            padding: 4px 0;
        }}
        .insights li::before {{
            content: "→ ";
            color: var(--accent);
        }}
        .chart-desc {{
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 8px;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            font-size: 12px;
            color: var(--text-dim);
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>Pulse Report</h1>
    <p class="subtitle">Generated {datetime.now().strftime("%Y-%m-%d %H:%M")} &middot; Data from {first_day} to {last_day}</p>

    <div class="kpi-row">
        <div class="kpi">
            <div class="kpi-value">{total_events:,}</div>
            <div class="kpi-label">Total Events</div>
        </div>
        <div class="kpi">
            <div class="kpi-value">{total_sessions}</div>
            <div class="kpi-label">Sessions</div>
        </div>
        <div class="kpi">
            <div class="kpi-value">{total_prompts}</div>
            <div class="kpi-label">Prompts</div>
        </div>
    </div>
{insights_html}
    <div class="charts">
        <div class="chart-card">
            <h3>Tool Mix</h3>
            <canvas id="toolMix" aria-label="Donut chart showing distribution of tool usage"></canvas>
            <p class="chart-desc">Top 5 tools by usage count. Remaining tools grouped as Other.</p>
        </div>
        <div class="chart-card">
            <h3>Error Rate by Tool</h3>
            <canvas id="errorRates" aria-label="Bar chart showing failure percentage per tool"></canvas>
            <p class="chart-desc">Only tools with failures shown. Red &gt;20%, yellow &gt;5%, green &lt;5%.</p>
        </div>
        <div class="chart-card wide">
            <h3>Events per Day</h3>
            <canvas id="dailyEvents" aria-label="Bar chart showing event count per day"></canvas>
            <p class="chart-desc">All hook events (tool calls, prompts, sessions) per day.</p>
        </div>
        <div class="chart-card">
            <h3>Prompts per Hour</h3>
            <canvas id="promptsPerHour" aria-label="Bar chart showing prompt count per hour of day"></canvas>
            <p class="chart-desc">When you send prompts. Gaps mean no activity in that hour.</p>
        </div>
        <div class="chart-card">
            <h3>Session Sizes</h3>
            <canvas id="sessions" aria-label="Bar chart showing event count per session"></canvas>
            <p class="chart-desc">Sessions sorted by size. Larger sessions indicate longer or more complex work.</p>
        </div>
    </div>

    <p class="footer">Pulse &mdash; The heartbeat of your Claude Code projects</p>
</div>

<script>
const DATA = {json.dumps(data)};

Chart.defaults.color = '#848d97';
Chart.defaults.borderColor = '#30363d';
Chart.defaults.font.family = "'Segoe UI', sans-serif";
if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {{
    Chart.defaults.animation = false;
}}

const COLORS = ['#58a6ff', '#3fb950', '#e3b341', '#f85149', '#a78bfa', '#79c0ff'];

// Tool Mix (Donut)
new Chart(document.getElementById('toolMix'), {{
    type: 'doughnut',
    data: {{
        labels: DATA.toolMix.labels,
        datasets: [{{ data: DATA.toolMix.data, backgroundColor: COLORS, borderWidth: 0 }}]
    }},
    options: {{
        plugins: {{
            legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 8, font: {{ size: 11 }} }} }}
        }}
    }}
}});

// Error Rates (Bar)
new Chart(document.getElementById('errorRates'), {{
    type: 'bar',
    data: {{
        labels: DATA.errorRates.labels,
        datasets: [{{
            label: 'Fail %',
            data: DATA.errorRates.data,
            backgroundColor: DATA.errorRates.data.map(v => v > 20 ? '#f85149' : v > 5 ? '#d29922' : '#3fb950'),
            borderRadius: 4
        }}]
    }},
    options: {{
        indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ max: Math.max(...DATA.errorRates.data, 30), ticks: {{ callback: v => v + '%' }} }} }}
    }}
}});

// Daily Events (Bar)
new Chart(document.getElementById('dailyEvents'), {{
    type: 'bar',
    data: {{
        labels: DATA.dailyEvents.labels,
        datasets: [{{
            label: 'Events',
            data: DATA.dailyEvents.data,
            backgroundColor: '#58a6ff',
            borderRadius: 4
        }}]
    }},
    options: {{
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ y: {{ beginAtZero: true }} }}
    }}
}});

// Prompts per Hour (Bar — honest about gaps)
new Chart(document.getElementById('promptsPerHour'), {{
    type: 'bar',
    data: {{
        labels: DATA.promptsPerHour.labels,
        datasets: [{{
            label: 'Prompts',
            data: DATA.promptsPerHour.data,
            backgroundColor: '#58a6ff',
            borderRadius: 4
        }}]
    }},
    options: {{
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ y: {{ beginAtZero: true }} }}
    }}
}});

// Session Sizes (Horizontal Bar)
new Chart(document.getElementById('sessions'), {{
    type: 'bar',
    data: {{
        labels: DATA.sessions.labels,
        datasets: [{{
            label: 'Events',
            data: DATA.sessions.data,
            backgroundColor: '#3fb950',
            borderRadius: 4
        }}]
    }},
    options: {{
        indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }}
    }}
}});
</script>
</body>
</html>"""
