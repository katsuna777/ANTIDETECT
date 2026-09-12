# Stage 3 — Final Report

Status: **implemented and green**. Full test suite: **284 passed** (zero runtime dependencies, Python 3.13, macOS verified).

## What Stage 3 delivers
Profiles, browser configurations ("fingerprints") and proxies are now one coherent system exposed through a single CLI. A configuration is generated coherently, attached to a profile, launched through Chromium with real fingerprint flags and an optional proxy, started/stopped/restarted with durable state, and cookies can be exported/imported per profile.

## Architecture
Clean layering, `src/app/{domain,infrastructure,application,config,cli}`:

- **Story → service chain**: `cli/commands/*` → `cli/cli.main` routing vs `_COMMAND_HANDLERS`/`_SERVICE_ATTR` → application services (`ProfileService`, `ConfigurationService`, `CookieService`, `ProxyService`) → ports (abstract repositories / `BrowserManager`) → SQLite repositories + `ChromiumManager`.
- **Persistence**: SQLite in WAL mode, migrations `0001_initial` → `0002_proxies` → `0003_profiles_and_configurations` (registered + idempotent + downgradable).
- **`Database`**: single connection wrapper, `PRAGMA foreign_keys = ON`, explicit transactions.
- **Composition root**: `app/di.py` wires services; `AppConfig.from_env` redirects via `ANTIDETECT_DATA_DIR`, `ANTIDETECT_CHROMIUM_PATH`, `ANTIDETECT_LOGS_DIR`, `ANTIDETECT_PROXY_SOURCES`.

### Data model
- `profiles(id, name, profile_path, configuration_id, proxy_id, status, …, pid)` — `configuration_id`/`proxy_id` are **nullable** with `ON DELETE SET NULL` (deleting a config or proxy detaches it from profiles, never orphan-crashes).
- `browser_configurations` extended with `platform`, `locale`, `screen_width`, `screen_height`, `device_pixel_ratio`, `color_depth`, `webgl_settings` (JSON), `hardware_settings` (JSON). `language_tag` prefers the full `locale` over `language` so `navigator.language` reports realistically.
- `proxies` + `proxy_checks` (latest check resolved per proxy; pid-reuse-safe liveness).
- DELETE flows: profile delete removes its data dir automatically.

## What was implemented
1. **ConfigurationGenerator + ConfigurationService** — coherent (never independent random) fingerprint generation: platform → browser/UA → language/locale → timezone → screen → hardware/webgl. Templates: `windows-chrome`, `windows-firefox`, `macos-chrome`, `linux-chrome`. `validate_draft` catches incoherent hand-edits. Unique-name uniquifier appends `-2`.
2. **ProfileService extension** — `create/update` accept `--proxy-id`; `assign_configuration/remove_configuration/assign_proxy/remove_proxy`; `ProfileDetails(profile, proxy_check, configuration)` for `profile show`; start guard chain: missing configuration → `ProfileConfigurationMissingError`, dead proxy → `ProxyNotUsableError`, invalid draft → validation error; `duplicate_profile` copies config + proxy refs and browser state; `_reconcile` resyncs stale RUNNING rows.
3. **CookieService** — export = sqlite3 **online backup** (zero data-copy, works while browser runs) from `Default/Cookies` or `Cookies`; default target `{cookie-backups}/profile_{id:03d}/cookies_{stamp}.db`; import validates source is a real SQLite cookies db, requires profile **stopped**, and replaces the live cookie store. Cookie payloads are never logged (CLI prints only paths/ids).
4. **ChromiumManager** — per-profile `--user-data-dir` (isolation), fingerprint flags `--user-agent`, `--lang`/`--accept-lang`, `--timezone-id`, `--window-size`, `--force-device-scale-factor`; optional `--proxy-server=scheme://user:pass@host:port` with percent-encoded credentials; process-group signal + fallback kill; pid-reuse guard via command-line inspection; waits for `SingletonLock` release before restart (no start racing).
5. **CLI** — new `config` group, `cookies` group, `profile proxy --set|--remove`, `--proxy-id` on create/update, enriched `profile list` (ID/NAME/PROXY/IP/COUNTRY/PING/STATUS) and `profile show` (PROFILE/PROXY/CONFIGURATION sections). `_HANDLERS` alias kept for legacy tests.

## Tests (284 passed)
Runs: `cd "/Users/katsuna/q/antidetect browser" && "./venv/bin/python" -m pytest -q`

| Area | File(s) | What it covers |
|---|---|---|
| Config generator | `test_configuration_generator.py` (15) | coherence invariants, determinism, templates, `validate_draft` |
| Configuration service | `test_configuration_service.py` (16) | CRUD, JSON settings, naming, delete-detach semantics |
| Profile↔config↔proxy | `test_profile_proxy.py` (13) | assignments/removals, `ProfileDetails`, launch guards, duplicate |
| Cookies | `test_cookie_service.py` (10) | export backup, import restore, running/stopped guards, no-payload logs |
| CLI Stage 3 | `test_cli_stage3.py` (10) | `config generate/show/list/edit/duplicate/delete`, `cookies export/import`, `profile proxy`, full **end-to-end** flow through `main()` |
| Chromium launch | `test_chromium_manager.py` (23) | fingerprint flags, proxy flag/URI encoding, stop/restart, lock waits |
| Migrations | `test_migrations.py` (11) | 0003 columns, FKs, `ON DELETE SET NULL`, degradation |
| Integration | `test_stage3_integration.py` (4) | acceptance scenario, storage isolation (A ≠ B), duplicate independence, restart persistence |
| Regression | all others | lifecycle, CLI legacy, proxy checks/concurrency, config, errors |

Notable: the once-flaky `test_check_all_runs_concurrently` was rewritten to assert **structural** peak concurrency (≥ 2 workers) instead of wall-clock — deterministic.

## CLI reference (verified interactively)
```
app config generate --name Demo --from-template windows-chrome   # coherent fingerprint
app profile create "Demo Profile" --configuration-id 2
app proxy refresh && app proxy check-all                          # populate+check proxies
app profile proxy 1 --set <id>                                    # attach working proxy
app profile start 1 / stop 1 / restart 1
app profile list                                                  # ID/NAME/PROXY/IP/COUNTRY/PING/STATUS
app profile show 1                                                # PROFILE/PROXY/CONFIGURATION detail
app cookies export 1                                              # online SQLite backup
app cookies import 1 --from backup.db                             # restore into stopped profile
```

## e2e / RAM / leak verification (macOS)
- Acceptance flow through the real CLI: config → profile → start → stop → restart syncs status in the DB; state persists across a fresh DB connection.
- RAM over start/stop cycles (fake long-running Chromium): 174–198 MB RSS, **stable** across 5 cycles (no growth), and **old PIDs fully gone** after every stop (no zombie/process-group leaks).
- Launcher self-heals: immediate-exit detection + confirmation poll; SIGTERM→SIGKILL escalation.

## Cross-platform notes
- Windows: `_signal_group` falls back to force-kill (no POSIX groups); pid-arg guard uses `wmic`; all paths via `pathlib` (no hardcoded slashes); `_KNOWN_COMMANDS` PATH discovery for Linux. Verified logic by unit tests; physical Windows/Linux runs pending hardware.
- Chrome discovery: `ANTIDETECT_CHROMIUM_PATH`/`CHROME_PATH` → well-known install paths per OS → PATH.

## Known limitations (V1)
- Fingerprint fields that **cannot** be forged via launch flags (WebGL vendor/renderer, hardware concurrency, RAM, color depth) are stored in `webgl_settings`/`hardware_settings` JSON and **not injected into the renderer yet** — they are displayed in `config show` and ready for the V2 CDP layer.
- `profile list` shows proxy IP/country/ping supplied via `proxy_checks` at check time; unproxied rows render `-`.
- Import target resolution assumes the standard Chromium cookie layout (`Default/Cookies`), mirroring `--user-data-dir` structure.

## V2 GUI plan (not implemented, per scope)
- Tkinter/PySide or web-based dashboard over the same service layer + `di.py`; real-time `proxy check` progress; cookie manager UI.
- CDP (Chrome DevTools Protocol) injection for WebGL/hardware overrides using the stored JSON — the only fingerprint dimensions V1 leaves to the renderer.
- Status streaming (PROFILE/PROXY) via a small event bus instead of CLI polling.