# Windows local-source startup

Double-click `start_determinflow.bat`. It selects Python 3.11 or newer, creates
`.venv` if absent, and runs `scripts/start_local.py` using that interpreter.
Project paths containing spaces are supported. Startup failures return a
nonzero status and remain visible in the batch window.

Startup uses the current files in this checkout and in the sibling
`DeterminFlow-Plugins/plugins` directory, including uncommitted changes. It does
not fetch, pull, reset, or commit either repository. Override the plugin source
directory with `DETERMINFLOW_LOCAL_PLUGINS_DIR` when the repositories are elsewhere.

Python dependencies are installed when their requirements or interpreter
fingerprint changes. Frontend dependencies use a separate package/lock-file
fingerprint. Frontend source, local `extensions/*/frontend` modules, public assets, build configuration and generated
output are checked by content; changed or missing output triggers a build.
Installation, build and plugin validation failures stop startup. The initial
fingerprinted launch installs dependencies once, so package registries may be
needed then or after dependency changes.

Local plugin files are copied into staging and validated before the PluginStore
publishes an immutable checkout and updates `plugins.lock.json`. Existing
checkouts remain available in revision history. The existing source identity,
resource prefix, enabled state and plugin settings are preserved. First install
creates `extensions.json` with the required plugin enabled only when that file
does not exist and no extensions environment override is set. An existing empty
enabled list stays empty. Missing local source is accepted only if an installed
checkout passes integrity verification. Pending plugin removal stays pending.

`WEB_HOST` and `WEB_PORT` come from the environment or `.env`; the default port
is 8020. Repeated launches identify the existing service by its exact project,
data/configuration profile, process ID and private startup token. An idle service
is gracefully stopped before dependencies, frontend output or plugin snapshots
are updated, and the new service loads the current source. The launcher waits
for the old process to finish shutdown as well as release its port.

Active chat/model invocations, workflows, adoption jobs and background work block
restart. The second window explains the reason and preserves the running service.
An idle chat window or an unstarted workflow draft does not count as active work.
A temporary admission fence checks for races before shutdown; it does not change
saved workflow controls, novel data or configuration. Simultaneous double-clicks
are serialized by a per-profile startup lock.

An unrelated listener, an unverifiable service, or an older service started before
this restart protocol was installed is preserved. Close that old startup window
with Ctrl+C once, then launch again. Future launches can restart idle services
automatically. Expected busy/identity notices pause startup without a Python
traceback; the launcher never force-kills a port owner.

The browser opens only after the new server answers with that launch's unique
readiness token. An old server cannot satisfy this check. Ctrl+C and failed
readiness shut down only the child started by this launcher.
Worker initialization updates shared state in sequence. Its bounded waiting
budget scales with the configured worker count, and the launcher's readiness
budget includes that queue, so a normal four-worker Windows start can exceed
one minute without being mistaken for a failed boot.

Preparation and server output are recorded in `logs/startup_<time>_<pid>.log`.
Existing `.env`, model settings, novels and plugin settings are not replaced.
Examples are copied only when their destination configuration is absent.

From PowerShell, optional switches are:

```powershell
.\start_determinflow_v2.ps1 -NoBrowser
.\start_determinflow_v2.ps1 -PrepareOnly
```

`-PrepareOnly` installs/builds/snapshots local code and then exits without starting
the app. It never stops a live service; close the existing startup window first
when preparation is needed. With no live service, it updates the plugin lock and
generated build/dependency files.
For an isolated validation, set `DETERMINFLOW_DATA_DIR` and
`DETERMINFLOW_CONFIG_DIR` to test directories before running it.
