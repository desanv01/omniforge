# Fresh local credential setup

Status: seven mock-only tests passed; independent review and hosted CI pending.

The explicit `python -m adapters.secrets.setup` command accepts no arguments and
requires interactive input/error streams. It requests hidden input using getpass,
raises on echo-fallback warnings, accepts only nonempty UTF-8 values within the
existing 2560-byte store limit, and generates its own fresh v1 UUID reference.
Only that new target is passed to put. No get, enumeration, existing reference
argument, delete, environment/file key input or provider request is implemented.
Importing the module does not construct a store or prompt.

Only the opaque reference is printed after a successful put. Invalid input,
interruption and exceptions use fixed errors. A failure after attempting put,
including lost output, is reported as uncertain with no automatic retry or cleanup.
The owned SecretValue buffer is cleared on success and failure; immutable Python
strings and other copies cannot be guaranteed erased. UUID generation reduces
collision risk but the underlying store has no atomic create-if-absent operation.

Tests inject all terminal input and a fake store; they never construct an OS store,
read actual terminal input or access a real credential. The intended command is:

```text
python -B -m unittest discover -s tests/contracts/secrets -p test_setup.py -v
```

Executed once: seven tests passed in 0.003 seconds, exit zero. They cover fresh
reference output and clearing, argument/nonterminal rejection, prevention of the
getpass echo fallback, invalid UTF-8/oversized input, interruption, storage failure
and lost output after put. All input and store behavior was injected synthetically.

This standalone helper does not bind a credential to a principal, case or profile.
Reference possession does not confer authority. Application enrollment still
requires the separately reviewed reservation, fresh pre-put authority check and
post-put attachment protocol. No actual enrollment, live-provider capability,
cross-user isolation or complete setup flow is claimed here.
