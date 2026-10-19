"""Shell-command classification (A3)."""

import pytest

from agent import command_policy as cp


@pytest.mark.parametrize("cmd", ["dir", "ls -la", "git status", "git diff HEAD",
                                 "whoami", "ping 1.1.1.1", "netstat -an"])
def test_read_only_commands_are_allowed(cmd):
    assert cp.classify(cmd)[0] == cp.CATEGORY_ALLOW


@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf ~/Documents",
    "format c:",
    "diskpart",
    "reg delete HKLM\\Software\\X /f",
    "net user hacker /add",
    "shutdown /s /t 0",
    "bcdedit /set {default} safeboot minimal",
    "mkfs.ext4 /dev/sda1",
    "vssadmin delete shadows /all",
    "cat a | rm -rf /tmp/x",
])
def test_destructive_commands_are_blocked(cmd):
    assert cp.classify(cmd)[0] == cp.CATEGORY_BLOCK


@pytest.mark.parametrize("cmd", ["dir && del important.txt", "echo hi > file.txt",
                                 "cat a | sort", "whoami; echo done"])
def test_chained_or_redirected_commands_need_confirmation(cmd):
    assert cp.classify(cmd)[0] == cp.CATEGORY_CONFIRM


@pytest.mark.parametrize("cmd", ["pip install requests", "mkdir newdir", "git push",
                                 "python run.py", "curl http://x"])
def test_state_changing_commands_need_confirmation(cmd):
    assert cp.classify(cmd)[0] == cp.CATEGORY_CONFIRM


def test_empty_command_needs_confirmation():
    assert cp.classify("")[0] == cp.CATEGORY_CONFIRM
    assert cp.classify(None)[0] == cp.CATEGORY_CONFIRM


def test_classify_returns_a_reason():
    category, why = cp.classify("dir")
    assert category == cp.CATEGORY_ALLOW and why
