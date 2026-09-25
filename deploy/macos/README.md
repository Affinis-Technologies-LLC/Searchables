# Running Searchables on macOS

Two ways to run it:

| | Script | Starts | Good for |
|---|---|---|---|
| **In a terminal** | `run.sh` | when you run it; stops with Ctrl+C or when the window closes | trying it out, occasional use |
| **As a background service** | `install-service.sh` | at login, restarts after a crash | everyday use |

Both keep the library in the project's `data` folder by default, so they share the same documents,
collections and search history. Run only one at a time on the same port.

## Before you start

- **Python 3.10 or newer.** The `python3` that comes with macOS is 3.9, which is too old. Install a newer
  one with [Homebrew](https://brew.sh) (`brew install python@3.12`) or from [python.org](https://www.python.org/downloads/macos/).
  The scripts pick the newest suitable one automatically, or use `--python /path/to/python3`.
- **Tesseract (optional, for scanned pages):** `brew install tesseract`. The scripts find it automatically.
- **The project outside Documents, Desktop, Downloads and iCloud Drive.** macOS privacy controls can
  stop background services reading those folders. `~/GitHub/Searchables` or `~/Apps/Searchables` is fine.

## In a terminal

```bash
cd ~/GitHub/Searchables
deploy/macos/run.sh                 # http://127.0.0.1:8501
deploy/macos/run.sh --port 8600     # Other options are passed on to Streamlit
```

The first run creates `.venv` and installs the Python packages (several minutes). Later runs start
straight away, reinstalling only when `requirements.txt` changes.

## As a background service

```bash
deploy/macos/install-service.sh
```

Then open **http://127.0.0.1:8501**. The service is a launchd *LaunchAgent*: it runs as you, starts
when you log in, and restarts if it crashes. Re-running the script is safe (it replaces the service,
e.g. after updating the app), and never touches the library.

**Allow it in the background.** macOS 13 and later show a *"Background Items Added"* notification for
a new service and can hold its automatic starts until it's allowed. If it doesn't start at login or
after a crash, open **System Settings → General → Login Items & Extensions** and make sure it's allowed
under *Allow in the Background* (it may be listed as *python* or *Python*).

### Options

| Option | Default | Purpose |
|---|---|---|
| `--port N` | `8501` | Port the app listens on |
| `--address ADDR` | `127.0.0.1` | `127.0.0.1` = this Mac only; `0.0.0.0` = other machines on the network |
| `--data-dir DIR` | project's `data` folder | Library: PDFs, search index, collections |
| `--label NAME` | `com.searchables.app` | Service name; use another to run a second copy |
| `--python PATH` | newest Python 3.10+ | Python used to create `.venv` |

### Day to day

```bash
launchctl print gui/$(id -u)/com.searchables.app | grep -E "state|pid"   # Status
launchctl kickstart -k gui/$(id -u)/com.searchables.app                  # Restart (e.g. after changing settings)
tail -f data/logs/searchables.err.log                                     # Logs
```

Logs are in the library's `logs` folder (`searchables.out.log`, `searchables.err.log`). macOS doesn't
rotate them; they stay small in normal use, and can be deleted while the service is stopped.

### Updating the app

```bash
git pull
deploy/macos/install-service.sh    # Installs any new requirements and restarts the service
```

### Uninstall

```bash
deploy/macos/uninstall-service.sh  # Stops and removes the service; keeps the library
```

## Security

**The app has no login.** Anyone who can open it can read every stored document and add, rename or
delete documents. The default address `127.0.0.1` keeps it on this Mac. With `--address 0.0.0.0`,
anyone on your network who can reach the port can use it, and macOS will ask whether Python may accept
incoming connections. Only do that on a network where everyone is covered by your document licences.

## Troubleshooting

| Symptom | Check |
|---|---|
| "Python 3.10 or newer not found" | Install Python (see *Before you start*) or pass `--python` |
| "The existing .venv uses Python older than 3.10" | Delete the `.venv` folder and run the script again |
| Service installed but doesn't start at login | Allow it under *Login Items & Extensions* (see above) |
| "didn't answer within 60 seconds" | `data/logs/searchables.err.log`; also check nothing else uses the port (`lsof -i :8501`) |
| "Operation not permitted" in the logs | The project or library is in a privacy-protected folder: move it (see *Before you start*) |
| Scanned pages aren't searchable | `brew install tesseract`, re-run the script, then **Re-index** those documents in the Library tab |
