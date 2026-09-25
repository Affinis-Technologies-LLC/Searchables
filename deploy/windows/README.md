# Running Searchables as a Windows service

The scripts in this folder install Searchables as a Windows service that starts with the machine,
restarts itself if it crashes, and writes rotating logs. They use [WinSW](https://github.com/winsw/winsw),
a small open-source service wrapper, to run Streamlit.

## Just want to try it?

`run.ps1` starts the app in a PowerShell window without installing a service (Ctrl+C stops it). It sets
up `.venv` on first use and keeps the library in the project's `data` folder:

```powershell
cd C:\Apps\Searchables\deploy\windows
Set-ExecutionPolicy -Scope Process Bypass
.\run.ps1                # http://127.0.0.1:8501
.\run.ps1 -Port 8600
```

The rest of this page covers the Windows service, which starts with the machine. Note that the
service keeps its library in `C:\ProgramData\Searchables`, separate from the one `run.ps1` uses.

## Before you start

- **Windows 10/11 or Windows Server 2019+**, and an account with administrator rights.
- **Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/)**, installed with
  **"Install for all users"** and the **py launcher**. A per-user install lives in your profile, which
  the service account can't read; the install script detects this and stops.
- **Tesseract (optional, for scanned pages)**: install the
  [UB Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki) to its default location. The install
  script finds it automatically.
- **The project outside your user profile**, e.g. `C:\Apps\Searchables`. Folders under
  `C:\Users\<you>` aren't readable by the service account.

## Install

Open **PowerShell as administrator**, then:

```powershell
cd C:\Apps\Searchables\deploy\windows
Set-ExecutionPolicy -Scope Process Bypass   # Allows these unsigned scripts for this window only
.\install-service.ps1
```

The script:

1. creates `.venv` and installs `requirements.txt` (several minutes the first time);
2. creates the data folder `C:\ProgramData\Searchables` and lets the service account write to it;
3. finds Tesseract's language data;
4. downloads WinSW (a pinned release from GitHub) and writes the service configuration;
5. installs and starts the service, then checks that the app answers.

When it finishes, open **http://127.0.0.1:8501**.

### Options

| Parameter | Default | Purpose |
|---|---|---|
| `-Port` | `8501` | Port the app listens on |
| `-Address` | `127.0.0.1` | `127.0.0.1` = this machine only; `0.0.0.0` = every network interface |
| `-OpenFirewall` | off | Adds an inbound rule for the port (Domain and Private networks) |
| `-DataDir` | `C:\ProgramData\Searchables` | Library: PDFs, search index, collections, logs |
| `-ServiceAccount` | `LocalService` | `LocalService` (least privilege), `NetworkService` or `LocalSystem` |
| `-ServiceName` | `Searchables` | Service name; use different names to run more than one copy |
| `-Python` | `py -3` | A specific `python.exe` for creating `.venv` |
| `-WinSWPath` | download | Use a `WinSW-x64.exe` you downloaded yourself (e.g. on a machine without internet access) |
| `-TessdataDir` | auto-detect | Tesseract's `tessdata` folder, if it's installed somewhere unusual |

Re-running the script is safe: it replaces the service and keeps the library.

## Security

**The app has no login.** Anyone who can open it can read every stored standard, and can add, rename
and delete documents. The default (`-Address 127.0.0.1`) keeps it on this machine. Before using
`-Address 0.0.0.0 -OpenFirewall`, make sure only people covered by your standards licences can reach
the machine, or put it behind a reverse proxy that requires sign-in (e.g. IIS with Windows
authentication).

The data folder holds your licensed PDFs. Back it up, and don't copy it anywhere your licence
doesn't allow.

## Day to day

```powershell
Get-Service Searchables          # Status
Restart-Service Searchables      # After changing settings or updating
Stop-Service Searchables
Start-Service Searchables
```

Logs are in `C:\ProgramData\Searchables\logs` (`Searchables.out.log`, `Searchables.err.log`,
`Searchables.wrapper.log`), rotated at 10 MB with 8 files kept.

## Updating the app

```powershell
cd C:\Apps\Searchables
git pull
.\deploy\windows\install-service.ps1   # Picks up new requirements and restarts the service
```

For a change that doesn't touch `requirements.txt`, `Restart-Service Searchables` is enough.

## Moving an existing library

The library is portable. To bring one from another machine, stop the service and copy that machine's
`data` folder contents (`library.db` and the `pdfs` folder) into `C:\ProgramData\Searchables`, then
start the service again. Re-run `install-service.ps1` afterwards so the copied files get the service
account's permissions.

## Uninstall

```powershell
.\uninstall-service.ps1               # Removes the service; keeps the library
.\uninstall-service.ps1 -RemoveData   # Also deletes the library (asks first)
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Install stops at "Python is installed for your user only" | Reinstall Python with "Install for all users", delete `.venv`, run the script again |
| Service starts, then stops | `Searchables.err.log` in the logs folder. Most often a missing package: re-run the install script |
| "Access is denied" in the logs | The project or data folder isn't readable by the service account: re-run the install script, which re-applies permissions |
| Scanned pages aren't searchable | Install Tesseract, re-run the install script, then **Re-index** the affected documents in the Library tab |
| Page doesn't load from another machine | The default address is `127.0.0.1`; re-run with `-Address 0.0.0.0 -OpenFirewall` |
| Port already in use | Re-run with a different `-Port` |
