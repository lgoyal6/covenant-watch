"""Load the project key without printing it or storing it in the repository."""

import os
import re
import subprocess
import sys

SERVICE = 'covenant-watch.anthropic'
ACCOUNT = 'covenant-watch'


def valid_key(value):
    return bool(re.fullmatch(r'sk-ant-[A-Za-z0-9_-]+', value))


def load_api_key():
    # The user explicitly saved the working project key in macOS Keychain. It
    # takes precedence over the stale key inherited by this app's shell sessions.
    if sys.platform == 'darwin':
        try:
            result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-a', ACCOUNT,
                                     '-s', SERVICE, '-w'], capture_output=True, text=True, timeout=10)
            key = result.stdout.strip() if result.returncode == 0 else ''
            if valid_key(key):
                return key
        except (OSError, subprocess.TimeoutExpired):
            pass
    key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    return key if valid_key(key) else None
