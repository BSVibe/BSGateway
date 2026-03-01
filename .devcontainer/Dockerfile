FROM python:3.11-slim

ARG CLAUDE_CODE_VERSION=latest

# Install basic development tools (without nodejs/npm from apt)
# Retry logic for transient network failures
RUN apt-get update && \
    for i in 1 2 3; do \
    apt-get install -y --no-install-recommends \
    build-essential git procps sudo curl zsh gh \
    iptables ipset iproute2 dnsutils vim locales nodejs npm \
    && break || { echo "Retry $i..."; sleep 5; apt-get update; }; \
    done && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Generate locale
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen en_US.UTF-8

ARG USERNAME=vscode
ARG GROUPNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000

RUN groupadd -g $USER_GID $USERNAME \
    && useradd -m -u $USER_UID -g $USER_GID -d /home/$USERNAME -s /bin/bash $USERNAME

# Persist bash history
RUN SNIPPET="export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
    && mkdir /commandhistory \
    && touch /commandhistory/.bash_history \
    && chown -R $USER_UID:$USER_GID /commandhistory \
    && echo $SNIPPET >> /home/$USERNAME/.bashrc

# Set up npm global directory
RUN mkdir -p /usr/local/share/npm-global && \
    chown -R $USER_UID:$USER_GID /usr/local/share
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin

# Create workspace and config directories
RUN mkdir -p /workspace /home/$USERNAME/.claude && \
    chown -R $USER_UID:$USER_GID /workspace /home/$USERNAME/.claude

# Set up non-root user
USER $USERNAME

# Install Claude Code
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Install homebrew (for dotfiles)
RUN mkdir -p $HOME/.linuxbrew \
    && git clone https://github.com/Homebrew/brew $HOME/.linuxbrew/Homebrew \
    && mkdir -p $HOME/.linuxbrew/bin \
    && ln -s $HOME/.linuxbrew/Homebrew/bin/brew $HOME/.linuxbrew/bin/brew \
    && eval "$($HOME/.linuxbrew/bin/brew shellenv)"

ENV PATH=/home/$USERNAME/.linuxbrew/bin:/home/$USERNAME/.linuxbrew/sbin:$PATH

RUN brew install openssl@3 --force-bottle
RUN brew install git-delta --force-bottle

# Install uv (fast Python package installer)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Add uv to PATH
ENV PATH=/home/$USERNAME/.local/bin:$PATH

# Copy and set up firewall script (for Claude Code)
COPY scripts/init-firewall.sh /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.sh && \
    echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME && \
    chmod 0440 /etc/sudoers.d/$USERNAME

USER $USERNAME
