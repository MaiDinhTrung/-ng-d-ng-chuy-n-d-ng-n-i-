# Chạy Local AI Voice Studio: build frontend (nếu cần) rồi mở backend tại http://127.0.0.1:8000
$root = $PSScriptRoot
$env:PYTHONUTF8 = "1"
if (-not (Test-Path "$root\frontend\dist\index.html")) {
    Push-Location "$root\frontend"; npm install; npm run build; Pop-Location
}
if (-not (Test-Path "$root\backend\.venv")) {
    python -m venv "$root\backend\.venv"
    & "$root\backend\.venv\Scripts\python" -m pip install -r "$root\backend\requirements.txt"
}
Start-Process "http://127.0.0.1:8000"
Set-Location "$root\backend"
& "$root\backend\.venv\Scripts\python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
