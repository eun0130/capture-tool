# Publish the 회사용 installer (built by release.yml) as a release of eun0130/capture_work - the
# repository company PCs download from. Needed when WORK_REPO_TOKEN is not set in the main
# repository's secrets. Usage: tools\publish_work.ps1 -Version 0.8.27 [-RunId <workflow run id>]
param([Parameter(Mandatory = $true)][string]$Version, [string]$RunId = "", [string]$Repo = "eun0130/capture_work")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$tag = "v$Version"
$dir = Join-Path $env:TEMP "capture_work_$Version"
New-Item -ItemType Directory -Force $dir | Out-Null
if (-not $RunId) {
    $RunId = (gh run list --workflow=release.yml --branch $tag --limit 1 --json databaseId --jq ".[0].databaseId")
    if (-not $RunId) { throw "no release.yml run for $tag" }
}
gh run download $RunId -n CaptureTool-Setup -D $dir
$exe = Get-ChildItem $dir -Filter "CaptureTool-Work-Setup-$Version.exe" | Select-Object -First 1
if (-not $exe) { throw "CaptureTool-Work-Setup-$Version.exe not in the artifact of run $RunId" }
$notes = "docs/release-notes/$tag.md"
gh release view $tag --repo $Repo 2>$null
if ($LASTEXITCODE -eq 0) {
    gh release upload $tag $exe.FullName --repo $Repo --clobber
} elseif (Test-Path $notes) {
    gh release create $tag $exe.FullName --repo $Repo --title "캡처 도구 (회사용) $tag" --notes-file $notes
} else {
    gh release create $tag $exe.FullName --repo $Repo --title "캡처 도구 (회사용) $tag" --notes "회사용 설치 파일 (카카오톡 기능 없음)"
}
Write-Host "published $($exe.Name) to https://github.com/$Repo/releases/tag/$tag"
