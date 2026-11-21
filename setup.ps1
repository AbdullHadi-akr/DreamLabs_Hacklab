# Einmaliges Setup fuer Teammitglieder (Windows PowerShell), aus dem Ordner dream-tool\ heraus:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Legt an: ..\dreamlabs (Repo-Klon), ..\.venv (Python 3.12) mit dem Dream-Library + pytest.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\dreamlabs")) {
    git clone --depth 1 https://github.com/dreamlabs-co/dreamlabs.git "$root\dreamlabs"
}
if (-not (Test-Path "$root\.venv")) {
    py -3.12 -m venv "$root\.venv"
}
& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install "$root\dreamlabs\dream_library\dream_client" "$root\dreamlabs\dream_library" pytest
& "$root\.venv\Scripts\python.exe" "$PSScriptRoot\check_setup.py"
