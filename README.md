# fcc-sync

One-command export/import of [free-claude-code](https://pypi.org/project/free-claude-code/) (fcc) configuration between devices. **Linux, macOS, and Windows.** One plain Python file, zero dependencies — any Python ≥ 3.10 runs it.

`fcc` keeps all its configuration — API keys for **every provider it supports** (any of the 40+ in its catalog: Gemini, OpenAI/ChatGPT, Groq, OpenRouter, Mistral, Cerebras, Kimi, DeepSeek, Cloudflare, Bedrock, ...), OAuth login tokens, base URLs, proxies, and model routing — in `~/.fcc/`. fcc-sync bundles exactly that into a single small tarball and restores it anywhere, installing fcc itself if the target machine doesn't have it.

Nothing is provider-specific: whatever providers you've configured (or add in future fcc versions) travel along automatically, because the whole config file and the whole token directory are what gets exported.

## Install

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/zamirszn/fcc-sync/main/fcc-sync.py -o ~/.local/bin/fcc-sync
chmod +x ~/.local/bin/fcc-sync
```

Windows (PowerShell):

```powershell
$bin = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force $bin | Out-Null
Invoke-RestMethod https://raw.githubusercontent.com/zamirszn/fcc-sync/main/fcc-sync.py -OutFile (Join-Path $bin "fcc-sync.py")
@'
@echo off
where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0fcc-sync.py" %*
) else (
  py "%~dp0fcc-sync.py" %*
)
exit /b %errorlevel%
'@ | Set-Content -Encoding ASCII (Join-Path $bin "fcc-sync.cmd")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ([string]::IsNullOrWhiteSpace($userPath)) {
  [Environment]::SetEnvironmentVariable("Path", $bin, "User")
  $env:Path += ";$bin"
} elseif (($userPath -split ";") -notcontains $bin) {
  [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";$bin"), "User")
  $env:Path += ";$bin"
}
```

The Windows installer creates `fcc-sync.cmd`, so PowerShell can run `fcc-sync` as a bare command. If an already-open terminal still cannot find it, open a new PowerShell window so it picks up the updated PATH.

Or just grab `fcc-sync.py` and run it anywhere with `python fcc-sync.py <command>`.

## Usage

```
fcc-sync export [file]    bundle ~/.fcc/.env + all OAuth tokens (default ~/fcc-backup-<date>.tar.gz)
fcc-sync import <file>    restore a bundle: backs up existing config, installs fcc if missing,
                          restarts the server, verifies providers via the admin API
fcc-sync status           server state, active model, configured providers
```

## What's in a bundle

| File | Why |
|---|---|
| `.env` | Every configured setting: all provider API keys, base URLs, proxies, `MODEL` / `MODEL_FALLBACKS` routing, messaging tokens |
| `auth/*.json` | All OAuth login tokens (ChatGPT, GitHub Copilot, and any future connected accounts) |
| `manifest.json` | fcc version, export date, hostname, provider count |

Deliberately excluded: session database, logs, and model-catalog caches — they're device-specific and regenerate on startup.

## Moving to a new device

```bash
# on the old machine
fcc-sync export
scp ~/fcc-backup-*.tar.gz user@newhost:   # or a USB stick, or a private repo

# on the new machine (uv installs fcc too if it's missing)
fcc-sync import ~/fcc-backup-*.tar.gz
```

If the new machine has neither fcc nor `uv`, import installs both. One command, full setup.

## Notes

- Bundles are **plain unencrypted tarballs containing your API keys** — move them over a trusted channel, and don't commit them to anything public.
- OAuth tokens occasionally turn out to be machine-bound; if a provider shows disconnected after import, re-do its login in the [fcc admin UI](http://127.0.0.1:8082/admin).
- Import never destroys data silently: existing config is copied to `~/.fcc/.env.bak-<timestamp>` first.
- Windows uses `taskkill`/PowerShell for the same lifecycle steps the Unix path does with `pkill`; everything else is plain Python stdlib, so the same file works everywhere.
- If a target machine has no fcc, import tries to install it. fcc needs Python ≥ 3.14, so import falls back to [uv](https://docs.astral.sh/uv/) (installing uv if needed) purely for that step — fcc-sync itself never requires uv to run.

## License

MIT
