import subprocess
from types import SimpleNamespace

from contracts import credentials


def test_keychain_project_key_takes_precedence_over_stale_shell_key(monkeypatch):
    monkeypatch.setattr(credentials.sys, 'platform', 'darwin')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-stale-test-value')
    calls = []
    def lookup(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='sk-ant-stored-test-value\n')
    monkeypatch.setattr(credentials.subprocess, 'run', lookup)
    assert credentials.load_api_key() == 'sk-ant-stored-test-value'
    assert calls[0][0][-1] == '-w'
    assert calls[0][1]['capture_output'] is True


def test_keychain_unavailable_falls_back_to_environment(monkeypatch):
    monkeypatch.setattr(credentials.sys, 'platform', 'darwin')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-environment-test-value')
    monkeypatch.setattr(credentials.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=44, stdout=''))
    assert credentials.load_api_key() == 'sk-ant-environment-test-value'
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('security', 10)
    monkeypatch.setattr(credentials.subprocess, 'run', timeout)
    assert credentials.load_api_key() == 'sk-ant-environment-test-value'


def test_non_mac_uses_environment_and_rejects_malformed_values(monkeypatch):
    monkeypatch.setattr(credentials.sys, 'platform', 'linux')
    def reject(*args, **kwargs):
        raise AssertionError('No Keychain access on this platform')
    monkeypatch.setattr(credentials.subprocess, 'run', reject)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-test\nnot-a-key')
    assert credentials.load_api_key() is None
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-environment-test-value')
    assert credentials.load_api_key() == 'sk-ant-environment-test-value'
