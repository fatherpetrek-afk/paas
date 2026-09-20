# Team PaaS

Personal / small-team compute platform. A Control plane accepts jobs; Workers pull and run them. Results stay on the User UI.

## Roles

| Role | Where | Notes |
|------|--------|--------|
| User | `:8080` | Submit jobs, view Terminal / Display / App, Shared files |
| Worker | `:9090` (localhost only) | Accept jobs, occupancy, queue, shared-folder ops |
| Admin | `:8080` | Approve accounts / workers, occupancy control. Cannot submit jobs |

Accounts use an 8-digit username and a 16-digit password. Admin credentials are **not** stored in source; set them via environment or `data/admin.json` (gitignored).

## Quick start (Windows)

1. Install Python 3.10+.
2. From the repo root:

```bat
start_platform.bat
```

This creates `.venv` if needed, installs `requirements.txt`, and opens Control (`0.0.0.0:8080`) plus Worker (`127.0.0.1:9090`) in two visible consoles.

Stop:

```bat
stop_platform.bat
```

Or:

```bat
.venv\Scripts\python.exe open_platform.py
.venv\Scripts\python.exe stop_platform.py
```

LAN users open `http://<this-pc-lan-ip>:8080`. Do not Funnel port 8080.

## Admin credentials

Pick one:

**Environment**

```bat
set PAAS_ADMIN_USERNAME=########
set PAAS_ADMIN_PASSWORD=################
```

**Local file** (recommended on a private PC; already gitignored under `data/`)

```json
{
  "username": "########",
  "password": "################"
}
```

Save as `data/admin.json`. Without either, Admin login will fail.

Optional: `PAAS_SESSION_SECRET` for cookie signing.

## How it works

- Control does not execute user code. Workers pull leases and run native / conda / toolchain jobs on the host.
- Job states: `queued` → `running` → `succeeded` / `failed` / `cancelled`.
- Submit placement: **System** (default) picks an online accepting Worker whose environment matches (idle, shorter queue, load, sticky last Worker, GPU when needed). **Manual** lets you pick Worker + environment. Shared-folder dispatch stays Manual.
- Interactive jobs: Terminal (logs / stdin) and Display (images under `output/_display`). Streamlit / Gradio / Flask / HTML bind `127.0.0.1` only; Users open them through Control at `/jobs/{id}/ui` (Display becomes App).
- Shared folders: Open and Granted per Worker. Bytes live on that Worker; Control keeps a serving copy.

## Examples

Under `examples/`:

- `draw_py.py`, `draw.cpp`, `draw.js` — graphics + Terminal stdin (`wave` / `bars` / `spiral`)
- `draw.html` — canvas App in Jobs
- `interactive_demo.py`, `canvas_demo.py`, `flask_demo.py`, `streamlit_demo.py`

## Layout

```
control/     FastAPI control plane + User UI
worker/      Worker agent + localhost console
shared/      Protocols and helpers
examples/    Sample jobs
tests/       Unit tests
```

## Tests

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -q
```

## Notes

- This PC is the cloud: if it is off, the platform is off.
- Installs lock is a static scan, not a jail. Isolation later can use optional Docker.
- Worker session token is reused from `data/worker-session.json` after restarts; log in again on `:9090` if the token is rejected.
