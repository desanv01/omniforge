# Partial offline receiver-client seam

This is partial offline preparation, not a working native SDK receiver.
The default `construct_receiver` raises UnsupportedReceiver before any SDK import
or configuration/client/channel/process construction. No worker-start interface is
exposed. Native implementation and runtime remain separate gates.

ReceiverConfig requires explicit UUID tenant/workflow/version, already normalized
lowercase namespace ending in underscore, unprefixed workflow/worker names, and
literal development endpoints127.0.0.1:7077/http://127.0.0.1:8888. Names are composed
exactly once. The token is a separate explicit argument, excluded from policy repr.
No environment, file, endpoint default or JWT address fallback is consulted. No
database configuration is accepted by this module.

The immutable ReceiverPolicy specifies explicit-only settings sources, one attempt,
gRPC retry/proxy disable, no REST proxy/environment/middleware/connection retry,
disabled health/debug/log capture/embedded mode and no forced sync-thread kill.
These are requirements for a future trusted adapter. Passing them to a fake does
not demonstrate that native SDK transports implement them. The telemetry policy
is an adapter requirement; it is not presented as an existing SDK enabled switch.

An explicitly injected async constructor receives policy and ReceiverOwnership.
It registers exact owned or borrowed child/client/channel objects as they are
created (maximum16). This seam creates none itself. Close callbacks run once;
borrowed objects are never closed. Partial construction/cancellation cleans the
registered resources. Cleanup failure/timeout is explicit and sanitized. A
noncooperative close task remains visible in ownership.unresolved until actual
settlement; no hard thread/process kill or false cleanup success is claimed.
Trusted adapters must register ownership immediately and use exact resource
handles, never guessed process names/PIDs. A hidden resource created then lost
before registration cannot be recovered by this contract.

Pinned SDK1.41.1 prevents a supported default using top-level injection alone:

- Worker.__init__ creates Client unconditionally; its constructor has no client
  injection argument. Hatchet(client=...) does not propagate that client there.
- WorkerActionListenerProcess creates a new Client in its spawned child and may
  recreate DispatcherClient. A parent-only adapter cannot cover that path.
- Client supports selected dispatcher/admin injection but unconditionally creates
  other listener/feature clients; new_conn has fixed channel options without a
  caller retry/proxy option hook.
- SDK config uses BaseSettings nested sources and defines TenacityConfig() at
  class definition, so even importing that configuration module can consult
  ambient settings. Supplying `_env_file=None` alone does not solve this.

The smallest follow-up is a reviewed pinned adaptation or upstream injection
surface spanning worker, spawned listener, recreated client and transport settings,
with a process-local explicit child environment and exact lifecycle ownership.
This module applies no global monkeypatch, copies no SDK worker implementation,
and never silently falls back to native constructors.

Ten new fake-only tests passed in one run. They block native SDK, gRPC, aiohttp,
process/subprocess imports; every executed construction uses injected fakes.
Coverage includes policy/name propagation, unsupported default, strict input,
exact once/borrowed ownership, partial initialization, cancellation, safe failures,
noncooperative cleanup, hostile ambient values and inert import. No native session,
channel, worker, child process, network service, database, credential/config file,
package installation or image operation occurred. Real receiver behavior remains
unsupported and unexecuted. Independent review and intended-head CI are required.
