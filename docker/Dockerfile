# Isaac Sim + browser-accessible GUI for TCP-only GPU clouds (RunPod, Vast.ai).
#
# Why this exists: Isaac Sim's built-in WebRTC livestream needs UDP 47998, and
# RunPod's proxy only forwards TCP. Instead of streaming, we render Isaac to a
# virtual X display and serve it over ONE HTTP port via noVNC.
#
# Why we BUILD instead of installing into a running container: Isaac Sim 5.x/6.x
# run as an unprivileged user with read-only /usr, so you cannot apt-get install
# a desktop at runtime. At build time we are root, so this is fine.

ARG ISAAC_VERSION=6.0.1
FROM nvcr.io/nvidia/isaac-sim:${ISAAC_VERSION}

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        openbox \
        novnc \
        websockify \
        x11-utils \
        xterm \
        net-tools \
        procps \
    && rm -rf /var/lib/apt/lists/*

# noVNC ships its landing page as vnc.html; make "/" load the client directly.
RUN ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

COPY start-gui.sh /usr/local/bin/start-gui.sh
RUN chmod +x /usr/local/bin/start-gui.sh

ENV DISPLAY_NUM=99 \
    SCREEN_RES=1920x1080x24 \
    NOVNC_PORT=8080 \
    ACCEPT_EULA=Y \
    PRIVACY_CONSENT=Y

EXPOSE 8080

CMD ["/usr/local/bin/start-gui.sh"]
