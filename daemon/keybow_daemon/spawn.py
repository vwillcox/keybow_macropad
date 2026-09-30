"""Starts long-lived programs (apps, browsers, shell commands) so they don't
belong to the daemon's own systemd service.

The daemon runs as keybow-daemon.service, which udev stops whenever the pad
is unplugged or re-enumerates. A plain Popen child lives in the service's
cgroup, so stopping the service kills it too — e.g. the whole browser the
configurator (or a URL key) was opened in. Wrapping the command in
`systemd-run --user --scope` moves it into its own transient scope unit
under app.slice, so it outlives the daemon like any normally launched app.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger("keybow.spawn")

_SYSTEMD_RUN = shutil.which("systemd-run")


def spawn_detached(args: list[str]) -> None:
    if _SYSTEMD_RUN is not None:
        args = [
            _SYSTEMD_RUN, "--user", "--scope", "--slice=app.slice",
            "--collect", "--quiet", "--", *args,
        ]
    else:
        logger.warning("systemd-run not found; %s will be tied to the daemon's lifetime", args[0])
    subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
