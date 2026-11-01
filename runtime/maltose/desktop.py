"""Native App entry point, retaining the existing CLI/runtime initialization."""
from __future__ import annotations
import os
import atexit
import signal
import sys
from pathlib import Path


def main() -> None:
    # Keep the original stream alive while fd 1 becomes diagnostics. This also
    # catches C/C++ libraries' printf, which assigning sys.stdout cannot redirect.
    original_stdout = sys.stdout
    protocol = os.fdopen(os.dup(1), 'w', encoding='utf-8', buffering=1)
    os.dup2(2, 1)
    sys.__stdout__ = protocol
    sys.stdout = sys.stderr
    if os.getpgrp() != os.getpid():
        os.setsid()

    def terminate(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    from maltose.runtime.lifetime import NativeRuntimeLifetime
    from maltose.agent.cli import main as run_agent
    if '--native-stdio' not in sys.argv:
        sys.argv.append('--native-stdio')
    from maltose.paths import default_config_path
    from maltose.runtime.ownership import RuntimeLease
    # Match argparse's --config/--config= handling without initializing any model.
    import argparse
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument('--config', type=Path, default=default_config_path())
    config, _ = probe.parse_known_args()
    # Keep ownership through ThreadPoolExecutor's interpreter shutdown. Releasing
    # the lexical main() scope earlier would admit another writer while an old
    # background task is still draining.
    lease = RuntimeLease(config.config.expanduser().absolute().parent)
    atexit.register(lease.close)
    lifetime = NativeRuntimeLifetime(config.config.expanduser().absolute().parent, lease_fd=lease.stream.fileno())
    try:
        from maltose.runtime.environment import load_private_environment
        load_private_environment(config.config.expanduser().absolute().parent / '.env')
        run_agent(native_owner_lost=lifetime.owner_disconnected, native_control_ready=lifetime.attach_control)
    except KeyboardInterrupt:
        # SIGTERM during model initialization is a managed cancellation too.
        pass
    if lifetime.failed:
        raise SystemExit(70)


if __name__ == '__main__':
    main()
