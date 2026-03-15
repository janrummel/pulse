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

    # Query 1: Tool mix (top 10)
    tool_mix = conn.execute("""
        SELECT tool_name, COUNT(*) as count
        FROM events
        WHERE tool_name IS NOT NULL AND event_type = 'PreToolUse'
        GROUP BY tool_name
        ORDER BY count DESC
        LIMIT 10
    """).fetchall()

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
        HAVING total > 10
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

    # Prepare JSON data for Chart.js
    chart_data = {
        "toolMix": {
            "labels": [r["tool_name"] for r in tool_mix],
            "data": [r["count"] for r in tool_mix],
        },
        "dailyEvents": {
            "labels": [r["day"] for r in daily_events],
            "data": [r["count"] for r in daily_events],
        },
        "sessions": {
            "labels": [r["session_id"][:8] + "..." for r in sessions],
            "data": [r["events"] for r in sessions],
            "times": [r["start_time"][:16] for r in sessions],
        },
        "errorRates": {
            "labels": [r["tool_name"] for r in error_rates],
            "data": [r["fail_pct"] for r in error_rates],
            "totals": [r["total"] for r in error_rates],
        },
        "promptsPerHour": {
            "labels": [f"{r['hour']:02d}:00" for r in prompts_per_hour],
            "data": [r["count"] for r in prompts_per_hour],
        },
    }

    html = _build_html(chart_data, total_events, total_sessions, total_prompts, first_day, last_day)

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
) -> str:
    """Build the complete self-contained HTML string with Chart.js visualizations."""
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

    <div class="charts">
        <div class="chart-card">
            <h3>Tool Mix</h3>
            <canvas id="toolMix"></canvas>
        </div>
        <div class="chart-card">
            <h3>Error Rate by Tool</h3>
            <canvas id="errorRates"></canvas>
        </div>
        <div class="chart-card wide">
            <h3>Events per Day</h3>
            <canvas id="dailyEvents"></canvas>
        </div>
        <div class="chart-card">
            <h3>Prompts per Hour</h3>
            <canvas id="promptsPerHour"></canvas>
        </div>
        <div class="chart-card">
            <h3>Session Sizes</h3>
            <canvas id="sessions"></canvas>
        </div>
    </div>

    <p class="footer">Pulse &mdash; The heartbeat of your Claude Code projects</p>
</div>

<script>
const DATA = {json.dumps(data)};

Chart.defaults.color = '#848d97';
Chart.defaults.borderColor = '#30363d';
Chart.defaults.font.family = "'Segoe UI', sans-serif";

const COLORS = ['#58a6ff', '#3fb950', '#d29922', '#f85149', '#a78bfa', '#79c0ff', '#56d4dd', '#db61a2', '#f0883e', '#7ee787'];

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

// Prompts per Hour (Line)
new Chart(document.getElementById('promptsPerHour'), {{
    type: 'line',
    data: {{
        labels: DATA.promptsPerHour.labels,
        datasets: [{{
            label: 'Prompts',
            data: DATA.promptsPerHour.data,
            borderColor: '#58a6ff',
            backgroundColor: 'rgba(88, 166, 255, 0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 3
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
