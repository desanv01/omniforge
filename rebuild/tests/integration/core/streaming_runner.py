"""Portable explicit SSE proof runner. No database/bootstrap/resource creation.

Run after the existing isolated database setup:
python -B -m tests.integration.core.streaming_runner
Requires OMNIFORGE_CONFIG supplied by the caller. Listener conflicts fail closed.
"""
import json
import faulthandler
import socket
import threading
import time
import unittest


def main():
    import uvicorn
    from services.api.app import create_app
    from services.api.settings import Settings
    from services.api.streams import StreamPolicy
    from tests.integration.scheduler.core_streaming import CoreStreamingProof

    settings = Settings.from_env()
    if settings is None:
        raise RuntimeError("Explicit isolated configuration is required")
    faulthandler.dump_traceback_later(120, exit=True)
    app = create_app(settings)
    if app.state.event_streams.policy != StreamPolicy():
        raise RuntimeError("Default stream policy is required")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    server = thread = result = None
    bound = False
    expected_tests = 0
    stopped = closed = False
    try:
        listener.bind(("127.0.0.1", 64111))
        bound = True
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=64111,
            access_log=False, log_level="warning", log_config=None, timeout_keep_alive=1,
            timeout_graceful_shutdown=2))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        deadline = time.monotonic()+8
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.025)
        if not server.started or not thread.is_alive():
            raise RuntimeError("Owned loopback listener failed to start")
        CoreStreamingProof.runtime_url = "http://127.0.0.1:64111"
        CoreStreamingProof.runtime_app = app
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CoreStreamingProof)
        expected_tests = suite.countTestCases()
        if expected_tests < 20:
            raise RuntimeError("The complete streaming and physical-read fixture is required")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(2)
            stopped = not thread.is_alive()
        else:
            stopped = True
        listener.close()
        if bound:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.settimeout(.3)
                closed = probe.connect_ex(("127.0.0.1", 64111)) != 0
            finally:
                probe.close()
        # Dispose only this runner's engine, after its owned listener has stopped.
        leases = app.state.event_streams.limiter.snapshot()["total"]
        checked_out = app.state.engine.pool.checkedout()
        stream_resources = app.state.event_streams.resource_snapshot()
        reads_closed = app.state.event_streams.close()
        if stopped:
            app.state.engine.dispose()
        print(json.dumps({"tests": result.testsRun if result else 0,
                          "skipped": len(result.skipped) if result else 0,
                          "listener_stopped": stopped, "port_closed": closed,
                          "stream_reservations": leases, "db_checked_out": checked_out,
                          "stream_resources": stream_resources, "stream_reads_closed": reads_closed}))
        faulthandler.cancel_dump_traceback_later()
    return 0 if (result and result.testsRun == expected_tests and result.wasSuccessful() and not result.skipped
                 and stopped and closed and leases == 0 and checked_out == 0 and reads_closed
                 and stream_resources["pending_reads"] == 0 and stream_resources["global_admitted_reads"] == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
