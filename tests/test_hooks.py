"""Tests for pulse.hooks — Installation of Claude Code hook configuration."""

import json

import pytest

from pulse.hooks import generate_hook_config, install_hooks, uninstall_hooks


class TestGenerateHookConfig:
    def test_returns_dict(self):
        config = generate_hook_config()
        assert isinstance(config, dict)

    def test_contains_all_p1_events(self):
        config = generate_hook_config()
        expected = ["SessionStart", "SessionEnd", "PreToolUse", "PostToolUse",
                     "UserPromptSubmit", "Stop"]
        for event in expected:
            assert event in config, f"Missing event: {event}"

    def test_each_event_has_command(self):
        config = generate_hook_config()
        for event_name, event_hooks in config.items():
            assert len(event_hooks) >= 1
            hook_entry = event_hooks[0]
            assert "hooks" in hook_entry
            commands = hook_entry["hooks"]
            assert len(commands) >= 1
            assert commands[0]["type"] == "command"
            assert "pulse collect" in commands[0]["command"]

    def test_commands_reference_correct_event(self):
        config = generate_hook_config()
        for event_name, event_hooks in config.items():
            cmd = event_hooks[0]["hooks"][0]["command"]
            assert f"--event {event_name}" in cmd

    def test_tool_use_events_have_empty_matcher(self):
        config = generate_hook_config()
        for event in ["PreToolUse", "PostToolUse"]:
            entry = config[event][0]
            assert "matcher" in entry
            assert entry["matcher"] == ""

    def test_non_tool_events_have_no_matcher(self):
        config = generate_hook_config()
        for event in ["SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"]:
            entry = config[event][0]
            assert "matcher" not in entry or entry.get("matcher") is None


class TestInstallHooks:
    def test_install_creates_settings_file(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hooks(str(settings_path))
        assert settings_path.exists()

    def test_install_writes_valid_json(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hooks(str(settings_path))
        data = json.loads(settings_path.read_text())
        assert "hooks" in data

    def test_install_preserves_existing_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {"permissions": {"allow": ["Read"]}, "other_key": True}
        settings_path.write_text(json.dumps(existing))
        install_hooks(str(settings_path))
        data = json.loads(settings_path.read_text())
        assert data["permissions"] == {"allow": ["Read"]}
        assert data["other_key"] is True
        assert "hooks" in data

    def test_install_preserves_existing_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "bash-firewall.sh"}]
                }]
            }
        }
        settings_path.write_text(json.dumps(existing))
        install_hooks(str(settings_path))
        data = json.loads(settings_path.read_text())
        pre_tool = data["hooks"]["PreToolUse"]
        # Should have the existing hook PLUS the new pulse hook
        assert len(pre_tool) >= 2
        commands = [h["hooks"][0]["command"] for h in pre_tool]
        assert "bash-firewall.sh" in commands
        assert any("pulse collect" in c for c in commands)

    def test_install_idempotent(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hooks(str(settings_path))
        install_hooks(str(settings_path))
        data = json.loads(settings_path.read_text())
        # Should not duplicate pulse hooks
        for event_name, hooks_list in data["hooks"].items():
            pulse_hooks = [h for h in hooks_list
                          if any("pulse collect" in hh["command"] for hh in h["hooks"])]
            assert len(pulse_hooks) == 1, f"Duplicate pulse hook in {event_name}"


class TestUninstallHooks:
    def test_uninstall_removes_pulse_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hooks(str(settings_path))
        uninstall_hooks(str(settings_path))
        data = json.loads(settings_path.read_text())
        for event_name, hooks_list in data["hooks"].items():
            for h in hooks_list:
                for hh in h["hooks"]:
                    assert "pulse collect" not in hh.get("command", "")

    def test_uninstall_preserves_other_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "bash-firewall.sh"}]
                }]
            }
        }
        settings_path.write_text(json.dumps(existing))
        install_hooks(str(settings_path))
        uninstall_hooks(str(settings_path))
        data = json.loads(settings_path.read_text())
        pre_tool = data["hooks"]["PreToolUse"]
        assert len(pre_tool) == 1
        assert pre_tool[0]["hooks"][0]["command"] == "bash-firewall.sh"

    def test_uninstall_on_no_settings_is_noop(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        # Should not raise
        uninstall_hooks(str(settings_path))
