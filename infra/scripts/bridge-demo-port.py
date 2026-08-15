#!/usr/bin/env python3
"""Make the demonstration reachable from a Windows browser when Docker's ports are not.

WHY THIS EXISTS. On WSL2 with `networkingMode=mirrored`, a plain listener started inside
WSL is reachable from Windows at both `127.0.0.1` and `*.localhost` — but a port *published
by Docker* is not. That was measured rather than assumed: a `python -m http.server` on 8098
answered 200 from Windows, while the same request to Docker's published 8080 was refused,
and binding the container to `0.0.0.0` instead of `127.0.0.1` changed nothing. The bind
address is not the problem; Docker's port publishing is what does not cross the boundary.

So this forwards a plain WSL socket to the container's port. It is a workaround for a
host-networking quirk, not a fix to the deployment — `infra/compose/compose.local.yml`
still publishes on loopback only, which is the property that keeps a demonstration stack
off the office network.

The durable fix is to take WSL out of mirrored networking (`networkingMode=NAT` in
`%USERPROFILE%\\.wslconfig`, then `wsl --shutdown`), after which Docker's ports reach
Windows directly and this script is unnecessary.

**The Host header passes through untouched**, which is what makes it usable at all: nginx
routes `admin.localhost` and `trader.localhost` to different applications by that header,
so a forwarder that rewrote it would collapse the two audiences onto one.

Usage:  python3 infra/scripts/bridge-demo-port.py [listen_port] [target_port]
"""

from __future__ import annotations

import socket
import socketserver
import sys
import threading

LISTEN_DEFAULT = 8081
TARGET_DEFAULT = 8080
CHUNK = 65536


def _pump(source: socket.socket, destination: socket.socket) -> None:
    """Copy one direction until it closes, then half-close the far side.

    Half-closing rather than tearing both down: an HTTP client that has finished sending
    its request still expects to read the response, and closing both directions on the
    first EOF truncates every reply.
    """

    try:
        while True:
            chunk = source.recv(CHUNK)
            if not chunk:
                break
            destination.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class _Handler(socketserver.BaseRequestHandler):
    target_port = TARGET_DEFAULT

    def handle(self) -> None:
        try:
            upstream = socket.create_connection(("127.0.0.1", self.target_port), timeout=10)
        except OSError as error:
            print(f"  cannot reach the stack on {self.target_port}: {error}", file=sys.stderr)
            return

        with upstream:
            outbound = threading.Thread(target=_pump, args=(self.request, upstream), daemon=True)
            outbound.start()
            _pump(upstream, self.request)
            outbound.join(timeout=5)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    listen_port = int(arguments[0]) if arguments else LISTEN_DEFAULT
    target_port = int(arguments[1]) if len(arguments) > 1 else TARGET_DEFAULT

    _Handler.target_port = target_port

    # 0.0.0.0 rather than 127.0.0.1: the whole point is to be reachable from outside this
    # WSL instance. That is a deliberate widening and the reason this is a separate,
    # explicitly-run script rather than something the compose file does.
    with _Server(("0.0.0.0", listen_port), _Handler) as server:
        print(f"forwarding *:{listen_port} -> 127.0.0.1:{target_port}")
        print(f"  open http://admin.localhost:{listen_port}")
        print(f"  open http://trader.localhost:{listen_port}")
        print("  stop with Ctrl-C")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
