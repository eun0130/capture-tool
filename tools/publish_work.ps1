# Publish an installer built by release.yml as a release of the repository people download from:
#   -Edition work  -> CaptureTool-Work-Setup-<v>.exe to eun0130/capture_work (회사용; the default)
#   -Edition home  -> CaptureTool-Setup-<v>.exe      to eun0130/capture_dist (개인용; public, installers only)
# Needed when WORK_REPO_TOKEN / DIST_REPO_TOKEN are not set in the main repository's secrets.
# Usage: tools\publish_work.ps1 -Version 0.8.31 [-Edition home|work] [-RunId <workflow run id>]
param([Parameter(Mandatory = $true)][string]$Version, [string]$RunId = "", [string]$Repo = "",
      [ValidateSet("work", "home")][string]$Edition = "work")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$tag = "v$Version"
$name = if ($Edition -eq "work") { "CaptureTool-Work-Setup-$Version.exe" } else { "CaptureTool-Setup-$Version.exe" }
if (-not $Repo) { $Repo = if ($Edition -eq "work") { "eun0130/capture_work" } else { "eun0130/capture_dist" } }
$title = if ($Edition -eq "work") { "캡처 도구 (회사용) $tag" } else { "캡처 도구 $tag" }
$fallback = if ($Edition -eq "work") { "회사용 설치 파일 (카카오톡·메일 기능 없음)" } else { "개인용 설치 파일" }
$dir = Join-Path $env:TEMP "capture_${Edition}_$Version"
New-Item -ItemType Directory -Force $dir | Out-Null
if (-not $RunId) {
    $RunId = (gh run list --workflow=release.yml --branch $tag --limit 1 --json databaseId --jq ".[0].databaseId")
    if (-not $RunId) { throw "no release.yml run for $tag" }
}
gh run download $RunId -n CaptureTool-Setup -D $dir
$exe = Get-ChildItem $dir -Filter $name | Select-Object -First 1
if (-not $exe) { throw "$name not in the artifact of run $RunId" }
$sha = "$($exe.FullName).sha256"                       # the in-app updater checks the download against it
if (-not (Test-Path $sha)) {
    $h = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLower()
    [IO.File]::WriteAllText($sha, "$h *$($exe.Name)`n")
}
$notes = "docs/release-notes/$tag.md"
$existing = @(gh release list --repo $Repo --json tagName --jq ".[].tagName")   # no stderr: PS 5.1 would stop on it
if ($existing -contains $tag) {
    gh release upload $tag $exe.FullName $sha --repo $Repo --clobber
} elseif (Test-Path $notes) {
    gh release create $tag $exe.FullName $sha --repo $Repo --title $title --notes-file $notes
} else {
    gh release create $tag $exe.FullName $sha --repo $Repo --title $title --notes $fallback
}
Write-Host "published $($exe.Name) to https://github.com/$Repo/releases/tag/$tag"
