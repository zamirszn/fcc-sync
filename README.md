# fcc-sync

One-command export/import of [free-claude-code](https://pypi.org/project/free-claude-code/) (fcc) configuration between devices.

`fcc` keeps all its provider configuration — API keys for 15+ providers, OAuth login tokens, and model routing — in `~/.fcc/`. fcc-sync bundles exactly what matters into a single small tarball and restores it anywhere, installing fcc itself if the target machine doesn't have it.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/zamirszn/fcc-sync/main/fcc-sync -o ~/.local/bin/fcc-sync
chmod +x ~/.local/bin/fcc-sync
```

(Requires `~/.local/bin` on your PATH.)

## Usage

```bash
fcc-sync export [file]    # bundle ~/.fcc/.env + OAuth tokens (default ~/fcc-backup-<date>.tar.gz)
fcc-sync import <file>    # restore a bundle: backs up existing config, installs fcc if missing,
                          # restarts the server, verifies providers via the admin API
fcc-sync status           # server state, active model, configured providers
```

## What's in a bundle

| File | Why |
|---|---|
| `.env` | All provider API keys + `MODEL` / `MODEL_FALLBACKS` routing |
| `auth/*.json` | OAuth login tokens (ChatGPT, GitHub Copilot) |
| `manifest.json` | fcc version, export date, hostname, provider count |

Deliberately excluded: session database, logs, and model-catalog caches — they're device-specific and regenerate on startup.

## Moving to a new device

```bash
# on the old machine
fcc-sync export
scp ~/fcc-backup-*.tar.gz user@newhost:

# on the new machine
fcc-sync import ~/fcc-backup-*.tar.gz
```

If the new machine has neither fcc nor `uv`, import installs both. One command, full setup.

## Notes

- Bundles are **plain unencrypted tarballs containing your API keys** — move them over a trusted channel, and don't commit them to anything public.
- OAuth tokens occasionally turn out to be machine-bound; if a provider shows disconnected after import, re-do its login in the [fcc admin UI](http://127.0.0.1:8082/admin).
- Import never destroys data silently: existing config is copied to `~/.fcc/.env.bak-<timestamp>` first.

## License

MIT
