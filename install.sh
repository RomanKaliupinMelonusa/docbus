#!/bin/sh
# docbus installer for macOS and Linux
# Usage: curl -sSfL https://raw.githubusercontent.com/RomanKaliupinMelonusa/docbus/main/install.sh | sh
#
# This script:
#   1. Checks for uv (installs it if missing)
#   2. Finds the latest docbus GitHub release and its wheel asset
#   3. Installs docbus via `uv tool install <wheel-url>`
#
# docbus still needs pandoc and mmdc (mermaid-cli) on PATH at runtime.
# This installer does not vendor them -- see the README for install links.

set -eu

REPO="RomanKaliupinMelonusa/docbus"
GITHUB_API="https://api.github.com/repos/${REPO}/releases/latest"

info()    { printf '  \033[1;34m->\033[0m %s\n' "$1"; }
success() { printf '  \033[1;32m OK\033[0m %s\n' "$1"; }
warn()    { printf '  \033[1;33m !\033[0m %s\n' "$1" >&2; }
error()   { printf '  \033[1;31m X\033[0m %s\n' "$1" >&2; exit 1; }

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

download_stdout() {
    url="$1"
    if need_cmd curl; then
        curl -sSfL "$url"
    elif need_cmd wget; then
        wget -qO- "$url"
    else
        error "Neither curl nor wget found. Please install one and retry."
    fi
}

main() {
    printf '\n\033[1mdocbus installer\033[0m\n\n'

    # --- uv ---
    if ! need_cmd uv; then
        info "uv not found -- installing..."
        curl -sSfL https://astral.sh/uv/install.sh | sh
        if [ -f "$HOME/.local/bin/env" ]; then
            . "$HOME/.local/bin/env"
        fi
        export PATH="$HOME/.local/bin:$PATH"
        if ! need_cmd uv; then
            error "uv installation succeeded but 'uv' is not on PATH. Please add ~/.local/bin to your PATH and retry."
        fi
        success "uv installed"
    else
        success "uv found at $(command -v uv)"
    fi

    # --- Find the latest release and its wheel asset ---
    info "Fetching latest release..."
    release_json=$(download_stdout "$GITHUB_API")
    tag_name=$(printf '%s' "$release_json" | grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -z "$tag_name" ]; then
        error "Could not determine latest release tag from GitHub API."
    fi
    wheel_url=$(printf '%s' "$release_json" | grep -o '"browser_download_url"[[:space:]]*:[[:space:]]*"[^"]*\.whl"' | head -1 | cut -d'"' -f4)
    if [ -z "$wheel_url" ]; then
        error "Could not find a .whl asset on release ${tag_name}."
    fi
    success "Latest release: ${tag_name}"

    # --- Install ---
    info "Installing docbus ${tag_name}..."
    log_file=$(mktemp)
    trap 'rm -f "$log_file"' EXIT
    if uv tool install --force "$wheel_url" >"$log_file" 2>&1; then
        cat "$log_file"
    else
        cat "$log_file" >&2
        error "uv tool install failed. See output above."
    fi

    # --- Ensure PATH is updated for new shells ---
    uv tool update-shell >/dev/null 2>&1 || warn "Could not update shell PATH automatically. Run 'uv tool update-shell' manually."

    # --- Verify ---
    if need_cmd docbus; then
        success "Verified: $(docbus --version 2>/dev/null || echo docbus) responds correctly"
    else
        warn "Could not find 'docbus' on PATH in this shell (a fresh shell may be needed)."
    fi

    printf '\n  docbus also needs pandoc and mmdc (mermaid-cli) on PATH:\n'
    printf '    pandoc: https://pandoc.org/installing.html\n'
    printf '    mmdc:   npm install -g @mermaid-js/mermaid-cli\n\n'
    printf '  Run \033[1mdocbus --help\033[0m to get started.\n\n'
}

main
