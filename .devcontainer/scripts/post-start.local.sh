#!/bin/bash
# Local-only setup — this file is gitignored.

# Start Tailscale (userspace networking, no TUN device needed)
if ! pgrep -x tailscaled > /dev/null; then
    sudo tailscaled \
        --state=/var/lib/tailscale/tailscaled.state \
        --socket=/var/run/tailscale/tailscaled.sock \
        --tun=userspace-networking &
    sleep 2
    sudo tailscale up --hostname=bsgateway-dev
    echo "[OK] Tailscale started"
else
    echo "[OK] Tailscale already running"
fi
