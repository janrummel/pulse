<p align="center">
  <img src="https://em-content.zobj.net/source/apple/391/anatomical-heart_1fac0.png" width="80" alt="Pulse">
</p>

<h1 align="center">Pulse</h1>

<p align="center">
  <strong>The heartbeat of your Claude Code projects.</strong><br>
  Measure what matters. See where you stand. Know what to do next.
</p>

<p align="center">
  <a href="https://janrummel.github.io/pulse/">Website</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#the-app">The App</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#faq">FAQ</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-114%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Status">
</p>

---

## The Problem

Claude Code creates plans as if a human writes the code. A typical plan says:

```
vault.py + tests:     2 hours
scanner.py + patterns: 3 hours
proxy.py:              3 hours
```

What actually happens:

```
vault.py + tests:     8 minutes (Claude writes it in 45s, review + test-fix: 7 min)
scanner.py + patterns: 12 minutes (+ 1 debug cycle)
proxy.py:              47 minutes (6 debug cycles — TLS integration)
```

The real bottlenecks are not lines of code. They are:

- **Debug cycles** — how often does Claude have to correct its own output?
- **Think-Time** — how long do you spend deciding what to do next?
- **Integration blockers** — external systems that don't cooperate
- **Context loss** — when the context window fills up and information gets compacted

**Nobody measures these.** Claude Squad, Agent Teams, Craft — they manage sessions, but they don't measure what happens *inside* them. Pulse does.

---

## What Pulse Does

| | |
|---|---|
| **Collects** | Hook events from every Claude Code session into SQLite — tool calls, prompts, errors, timing |
| **Analyzes** | Velocity, debug ratio, think-time, tool mix, grouped by session and project |
| **Forecasts** | Deadline feasibility based on historical data and debug overhead |
| **Tracks** | Task completion automatically from git commits, passing tests, and prompt transitions |
| **Shows** | Everything in an interactive terminal UI with four switchable views |
| **Launches** | Claude in any project directory with context from the last session |

---

## Quick Start

```bash
# Install
pipx install git+https://github.com/janrummel/pulse.git

# Set up hooks (adds Pulse to Claude Code's hook system)
pulse install

# Register your projects
pulse add backend ~/Projects/backend --tasks 12
pulse add infra ~/Projects/infra --category system --type continuous

# Launch
pulse
```

Three commands, then Pulse is collecting data from every Claude Code session.

---

## The App

Type `pulse` to open the interactive TUI. Switch views with number keys:

| Key | View | What it shows |
|-----|------|---------------|
| `1` | **Launcher** | Select a project, see its next step, press Enter to start Claude |
| `2` | **Dashboard** | Hero KPI (tasks done today), session metrics, tool mix |
| `3` | **Recap** | Daily summary with prompt rounds and think-time |
| `4` | **Portfolio** | All projects grouped by category with progress bars |
| `q` | Quit | |

**Launcher** is the home screen. Pick a project and Claude starts in that directory with context from your orchestrator state. When Claude exits, you're back in the launcher.

**Dashboard** shows outcomes first — not tool call counts. "3 Tasks erledigt" is the hero metric. Session details, debug cycles, and tool mix are secondary context.

**Recap** answers "What did I accomplish today?" with a structured summary including prompt rounds and think-time analysis.

**Portfolio** shows every project at a glance — grouped by category (tools, learning, system, research, content, career), with progress bars and continuous/one-time markers.

---

## CLI Commands

All views are also available as standalone commands:

```bash
# Main entry points
pulse                  # Interactive TUI (default)
pulse dashboard        # Live dashboard with auto-refresh
pulse recap            # Daily recap
pulse recap --week     # Weekly recap with trend comparison
pulse portfolio        # Full project portfolio
pulse metrics          # Dashboard snapshot (non-interactive)
pulse priority         # Priority ranking across projects

# Task tracking
pulse track            # Detect task completions from events
pulse track --apply    # Auto-mark high-confidence detections as done
pulse task add <project> <task>
pulse task done <project> <task>

# Project management
pulse add <name> <path> [--tasks N] [--deadline DATE] [--category CAT] [--type TYPE]
pulse project <name>   # Project details with tasks and sessions
pulse status           # Simple project list

# System
pulse install          # Install Claude Code hooks
pulse uninstall        # Remove hooks
pulse feedback "text"  # Save feedback for later review
pulse feedback --list  # Show all feedback
```

---

## Architecture

```
Claude Code Sessions
  |
  +-- Hooks
  |   SessionStart, PreToolUse, PostToolUse
  |   UserPromptSubmit, Stop, SessionEnd
  |
  v
+-----------+    +-----------+    +-----------+
| Collector |--->| Analyzer  |--->| Planner   |
| hook > db |    | metrics   |    | forecasts |
+-----------+    +-----------+    +-----------+
  |                 |                 |
  v                 v                 v
+----------------------------------------------+
|                 SQLite DB                     |
|  events · sessions · projects · tasks         |
+----------------------------------------------+
  |
  v
+-----------+    +-----------+    +-----------+
| Dashboard |    | Launcher  |    | Tracker   |
| Rich TUI  |    | Textual   |    | auto-task |
+-----------+    +-----------+    +-----------+
```

**Collector** reads hook events from stdin (JSON), extracts metadata (no secrets), writes to SQLite. Must complete in <100ms — no blocking of Claude Code.

**Analyzer** computes metrics from raw events: tool mix, debug ratio (error→fix pattern detection), think-time (Stop→UserPrompt gaps), session summaries, project health.

**Planner** forecasts deadlines using historical velocity and debug overhead. Generates priority rankings across projects.

**Tracker** detects task completions from three signal types:
- `commit_mention` (0.9 confidence) — git commit message mentions task name
- `write_test_success` (0.7) — write to file + tests pass
- `prompt_transition` (0.5) — user moves to new topic

**Dashboard** renders Rich panels with hero KPIs, tool mix bars, and grouped activity feeds.

**Launcher** is a Textual app that shows all projects, their next steps, and launches Claude with context.

---

## Key Metrics

| Metric | What it measures | Why it matters |
|--------|-----------------|----------------|
| **Tasks done today** | Completed tasks (auto-detected + manual) | Outcome, not activity |
| **Debug ratio** | Fraction of tool calls that are error→fix cycles | Shows code quality and complexity |
| **Think-Time** | Time between agent completion and next prompt | Where human decisions happen |
| **Tool mix** | Distribution of Write/Edit/Bash/Read/Search | Reveals session phase (building vs debugging) |
| **Velocity** | Tasks per hour over time | Trend analysis for forecasting |

---

## Configuration

Copy `config.example.yaml` to `~/.pulse/config.yaml`:

```yaml
db_path: ~/.pulse/pulse.db
claude_settings_path: ~/.claude/settings.json
orchestrator_dir: ~/.claude/orchestrator/projects  # optional
language: de
dashboard:
  refresh_interval: 3.0
```

All paths are configurable. The orchestrator integration is optional — without it, the launcher starts Claude in the project directory without loading next-step context.

### Project Categories

```bash
pulse add tool1 ~/Projects/tool1 --category tools
pulse add course ~/Projects/course --category learning --type one-time
pulse add infra ~/Projects/infra --category system --type continuous
```

Categories: `tools`, `learning`, `system`, `research`, `content`, `career`

Types: `one-time` (has a defined end) vs `continuous` (ongoing, never "done")

---

## Design Principles

Inspired by [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/).

| Principle | Application |
|-----------|------------|
| **Clarity** | Every element earns its place. No decorative noise. |
| **Hierarchy** | Outcomes first (tasks done), activity second (tool calls). |
| **Color = Meaning** | `●` green = good · `○` yellow = attention · `!` red = problem · `·` dim = secondary |
| **Consistency** | Same markers, colors, spacing everywhere. One design system (`theme.py`). |
| **Breathing** | Generous whitespace. Sections separated, not crammed. |
| **Progressive Disclosure** | Summary first, detail on demand. Tabs, not walls of data. |

---

## FAQ

**How does Pulse collect data?**
Through [Claude Code hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) — shell commands that run on every session event. `pulse install` adds these hooks to your Claude Code settings. Each hook reads JSON from stdin and writes one row to SQLite. Takes <100ms, no blocking.

**Does Pulse see my code or prompts?**
Pulse logs tool names and file paths, never file contents. Prompts are truncated to 500 characters. The `_summarize_input` function explicitly strips content — only structural metadata (command names, file paths, patterns) is stored.

**Does it work with multiple Claude Code sessions?**
Yes. Every session gets a unique `session_id` from Claude Code. Pulse tracks them independently. SQLite runs in WAL mode for concurrent writes.

**Can I use it without the orchestrator?**
Yes. The orchestrator integration (loading next steps from project files) is optional. Without it, `pulse` still works as a launcher, dashboard, and metrics tool — the "next step" line in the launcher will just be empty.

**What about token costs?**
Claude Code hooks don't expose token/cost data (yet). Pulse tracks everything else — when cost data becomes available in hooks, it can be added without schema changes.

**Is it open source?**
Yes, MIT licensed. Contributions welcome.

---

## Requirements

- Python 3.12+
- [Claude Code](https://www.anthropic.com/products/claude-code) (for hook integration)
- Dependencies: `rich`, `textual`, `pyyaml` (installed automatically)

## License

MIT
