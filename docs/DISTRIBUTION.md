# Distribution (Tier 2 E2–E6)

How a MARK-42 build leaves this machine. Credentials are never part of any
artefact below: `agent.build.stage_config()` copies only `*.example.json`, the
credential files are gitignored, and `agent.build.verify()` fails the build if
one reaches the bundle.

## E2 — Installer and first-run wizard

1. Build the frozen app (see `docs/REPRODUCIBLE.md`):
   `python -m agent.build stage && pyinstaller MarkJarvis.spec`
2. Compile the installer with Inno Setup 6:
   `ISCC.exe packaging\installer.iss` → `dist\installer\MARK-42-<ver>-setup.exe`
3. On first launch the app runs `agent/first_run.py`: it asks for the Gemini
   key (written to `config/api_keys.json`, gitignored) and lets the user pick a
   microphone by number or name, with a live 3-second level meter. Nothing is
   saved for a dead device. The completion marker is
   `config/first_run.json`.

The installer never writes a key and never copies `dist/JARVIS/config/*.json`
credentials, so an unattended install cannot leak one.

## E3 — Auto-update from a signed manifest

The update source is a JSON manifest (see `agent/updater.py` for the schema).
It must be fetched over HTTPS and carry an Ed25519 `signature` plus the
artefact `sha256`. The public key lives at `config/update_key.pem` (or
`JARVIS_UPDATE_KEY` for a CI-built key). Checks run in this order, all fail
closed:

```
python -m agent.updater check https://example.com/manifest.json
python -m agent.updater stage https://example.com/manifest.json
python -m agent.updater pending
```

`stage` verifies the digest before writing anything. The archive is applied
only after the UI exits (`updater.apply_on_exit()` is called after
`ui.root.mainloop()` returns), and only for a frozen build — a source checkout
refuses so it can never edit the repo behind your back. A missing key,
signature, digest or `https://` means no update.

To sign a manifest during a release, generate a key pair once:

```
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; \
from cryptography.hazmat.primitives import serialization as s; \
k=Ed25519PrivateKey.generate(); \
open('config/update_key.pem','wb').write(k.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo)); \
open('update_signing_key.pem','wb').write(k.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()))"
```

Keep `update_signing_key.pem` offline/in CI secrets; commit only the public
half. `config/update_key.pem` ships with the app.

## E4 — Code signing

`packaging/sign_windows.ps1` signs `dist\JARVIS\JARVIS.exe` and every
installer in `dist\installer\` with `signtool`, then verifies each signature.
It needs a real certificate:

```
$env:JARVIS_CERT_SHA1 = "<thumbprint>"
powershell -ExecutionPolicy Bypass -File packaging\sign_windows.ps1
```

Without `JARVIS_CERT_SHA1` the script exits non-zero rather than pretending the
build is signed. SmartScreen will warn until a certificate exists; that warning
is honest and is not worked around.

## E5 — Docker for cloud_jarvis

```
docker build -t mark-jarvis-cloud .
docker run -d --name jarvis-cloud --restart unless-stopped \
  -v "$PWD/config:/app/config:ro" -v "$PWD/memory:/app/memory" \
  mark-jarvis-cloud
```

`requirements-cloud.txt` is pinned with `==`. The image contains no config and
starts in manual mode when `config/alert_config.json` is absent. Run
unprivileged (uid 10001).

## E6 — Offline install

On a machine with internet:

```
python packaging\offline_install.py download      # -> vendor/wheels
```

Copy the repo *including* `vendor/wheels` to the offline machine, then:

```
python packaging\offline_install.py install
```

Both steps use the same pinned `requirements.txt`; only the pip flags differ.
The wheelhouse must match the offline machine's Python version and OS family.
