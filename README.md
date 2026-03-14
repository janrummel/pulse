# Pulse

**The heartbeat of your Claude Code projects.**

Pulse observes your Claude Code sessions via hooks, collects metrics, and gives you a live picture of what's happening across all your projects.

## What it does

- **Collects** hook events from Claude Code sessions (tool calls, prompts, errors) into SQLite
- **Analyzes** velocity, debug cycles, think-time, tool mix
- **Forecasts** deadlines based on historical data
- **Tracks** task completion automatically (commit mentions, test patterns, prompt transitions)
- **Shows** everything in an interactive terminal UI

## Quick Start

```bash
# Install
pipx install -e .          # or: pip install -e .

# Set up hooks (adds Pulse to Claude Code's hook system)
pulse install

# Register your projects
pulse add myproject ~/Projects/myproject --tasks 10
pulse add infra ~/Projects/infra --category system --type continuous

# Launch the app
pulse
```

## The App

`pulse` opens an interactive TUI with four views:

| Key | View | What it shows |
|-----|------|---------------|
| `1` | **Launcher** | Select a project → starts Claude with context |
| `2` | **Dashboard** | Live metrics: tasks done today, tool mix, activity |
| `3` | **Recap** | Daily summary with prompt rounds |
| `4` | **Portfolio** | All projects grouped by category |
| `q` | Quit | |

## CLI Commands

All views are also available as standalone commands:

```bash
pulse                  # Interactive app (default)
pulse dashboard        # Live TUI dashboard
pulse recap            # Daily recap
pulse recap --week     # Weekly recap with trends
pulse portfolio        # All projects by category
pulse metrics          # Dashboard snapshot
pulse priority         # Priority ranking
pulse track            # Detect task completions
pulse track --apply    # Auto-mark detected tasks as done
pulse feedback "text"  # Save feedback
pulse feedback --list  # Show all feedback
pulse status           # Simple project list
pulse project <name>   # Project details
pulse add <name> <path> [--tasks N] [--deadline DATE] [--category CAT] [--type TYPE]
pulse task add <project> <task>
pulse task done <project> <task>
pulse install          # Install Claude Code hooks
pulse uninstall        # Remove hooks
```

## Architecture

```
Claude Code Sessions
    │
    └── Hooks (SessionStart, PreToolUse, PostToolUse, UserPromptSubmit, Stop, SessionEnd)
            │
            ▼
    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
    │  Collector   │───▶│   Analyzer    │───▶│   Planner    │
    │  (hook→db)   │    │  (metrics)   │    │ (forecasts)  │
    └─────────────┘    └──────────────┘    └──────────────┘
            │                │                    │
            ▼                ▼                    ▼
    ┌────────────────────────────────────────────────────┐
    │                    SQLite DB                        │
    │  events · sessions · projects · tasks · feedback   │
    └────────────────────────────────────────────────────┘
            │
            ▼
    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
    │  Dashboard   │    │   Launcher    │    │   Tracker    │
    │  (Rich TUI)  │    │  (Textual)   │    │ (auto-tasks) │
    └─────────────┘    └──────────────┘    └──────────────┘
```

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

The orchestrator integration is optional. Without it, the launcher starts Claude in the project directory without loading next-step context.

## Project Categories

```bash
pulse add tool1 ~/Projects/tool1 --category tools
pulse add course ~/Projects/course --category learning --type one-time
pulse add infra ~/Projects/infra --category system --type continuous
```

Categories: `tools`, `learning`, `system`, `research`, `content`, `career`
Types: `one-time` (has an end), `continuous` (ongoing)

## Design Principles

Inspired by [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/):

- **Clarity** — every element earns its place
- **Hierarchy** — outcomes first, activity second
- **Color = meaning** — green/yellow/red/dim, never decorative
- **Consistency** — same markers and patterns everywhere (● ○ ✓ !)

## Requirements

- Python 3.12+
- Claude Code (for hook integration)
- Dependencies: `rich`, `textual`, `pyyaml`

## License

MIT
