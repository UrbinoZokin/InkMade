try:
    from .agent import run
except ImportError as exc:
    # The setup crypto needs spake2 and cryptography, which only
    # scripts/install_provisioning.sh installs. Exit cleanly rather than have
    # systemd restart into the same failure every few seconds.
    print(f"[agent] setup mode can't start: {exc}. Run scripts/install_provisioning.sh to install what it needs.")
    raise SystemExit(0)

if __name__ == "__main__":
    raise SystemExit(run())
