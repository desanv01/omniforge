"""Explicit terminal-only fresh credential enrollment; importing has no effects."""

import getpass
import sys
import warnings

from .store import CredentialRef, SecretValue


def _error(stream, message):
    try:
        stream.write(message + "\n")
        stream.flush()
    except Exception:
        pass


def run(argv=None, *, stdin=None, stdout=None, stderr=None, prompt=None, store_factory=None):
    """Inject dependencies for offline checks; ordinary CLI accepts no arguments.

    This creates an unbound reference, not a profile or authorization grant.
    No existing credential is read, enumerated, replaced intentionally or deleted.
    """
    argv = sys.argv[1:] if argv is None else argv
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    if argv:
        _error(stderr, "Credential setup accepts no arguments.")
        return 2
    value = None
    raw = None
    attempted_write = False
    try:
        if not stdin.isatty() or not stderr.isatty():
            _error(stderr, "Credential setup requires an interactive terminal.")
            return 1
        # Detect an already broken output before requesting input or writing a key.
        stdout.write("")
        stdout.flush()
        reader = getpass.getpass if prompt is None else prompt
        with warnings.catch_warnings():
            # getpass warns before its echoing fallback: raise before any input.
            warnings.simplefilter("error", getpass.GetPassWarning)
            raw = reader("Credential (hidden): ", stream=stderr)
        if not isinstance(raw, str) or not raw or raw.isspace() or len(raw) > 2560:
            raise ValueError("invalid input")
        value = SecretValue(raw.encode("utf-8"))
        raw = None
        reference = CredentialRef.new()
        if store_factory is None:
            from .windows import WindowsSecretStore
            store_factory = WindowsSecretStore
        store = store_factory()
        attempted_write = True
        store.put(reference, value)
        stdout.write(reference.value + "\n")
        stdout.flush()
        return 0
    except (Exception, KeyboardInterrupt):
        if attempted_write:
            _error(stderr, "Credential setup outcome is uncertain; do not retry automatically.")
        else:
            _error(stderr, "Credential setup did not complete.")
        return 1
    finally:
        raw = None
        if value is not None:
            value.clear()


if __name__ == "__main__":
    raise SystemExit(run())
