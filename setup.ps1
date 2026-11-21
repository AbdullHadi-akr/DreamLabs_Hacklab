# One-time setup for team members (Windows PowerShell), run from the dream-tool\ folder:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Creates: ..\dreamlabs (repo clone), ..\.venv (Python 3.12) with the Dream library + dashboard deps + pytest.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\dreamlabs")) {
    git clone --depth 1 https://github.com/dreamlabs-co/dreamlabs.git "$root\dreamlabs"
}
if (-not (Test-Path "$root\.venv")) {
    py -3.12 -m venv "$root\.venv"
}
& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install "$root\dreamlabs\dream_library\dream_client" "$root\dreamlabs\dream_library"
& "$root\.venv\Scripts\python.exe" -m pip install -r "$PSScriptRoot\requirements.txt"
& "$root\.venv\Scripts\python.exe" "$PSScriptRoot\check_setup.py"
