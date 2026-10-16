# Build CaptureTool: tests -> icon -> PyInstaller (dist\CaptureTool) -> Inno Setup (installer\Output)
# -Edition work builds 회사용 (no KakaoTalk): capture_tool\edition.txt says "work" inside that build only,
# the installer is CaptureTool-Work-Setup-<version>.exe (published from its own repository).
param([switch]$SkipTests, [ValidateSet("home", "work")][string]$Edition = "home")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }  # CI has no venv

if (-not $SkipTests) {
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
}
& $py tools\fetch_models.py
if ($LASTEXITCODE -ne 0) { throw "OCR models missing" }
& $py tools\make_icon.py
$marker = Join-Path $PSScriptRoot "capture_tool\edition.txt"
if ($Edition -eq "work") { [IO.File]::WriteAllText($marker, "work") }
try {
    & $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\capture_tool.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally {
    if (Test-Path $marker) { [IO.File]::Delete($marker) }   # never left in the source tree
}

$version = (& $py -c "import capture_tool; print(capture_tool.__version__)").Trim()
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (https://jrsoftware.org/isdl.php)" }
& $iscc "/DAppVersion=$version" "/DEdition=$Edition" installer\CaptureTool.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem installer\Output\*.exe | Select-Object Name, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } }
