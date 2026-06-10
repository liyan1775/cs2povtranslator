param(
  [Parameter(Mandatory=$false)] [string]$Demo = "",
  [Parameter(Mandatory=$false)] [string]$Output = "output_acceptance",
  [Parameter(Mandatory=$false)] [string]$WhisperModel = "tiny",
  [Parameter(Mandatory=$false)] [int]$Team = 2,
  [Parameter(Mandatory=$false)] [int]$MaxRounds = 3
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==============================================================="
Write-Host "CS2 POV Translator acceptance smoke"
Write-Host "==============================================================="
Write-Host "This script validates the ordinary-user path without real LLM cost."
Write-Host "It runs: setup-check -> run dry-run -> inspect-job -> export -> feedback"
Write-Host ""

if (-not $Demo) {
  $Demo = Read-Host "Drag a .dem or .dem.zst file here, then press Enter"
  $Demo = $Demo.Trim('"')
}

if (-not (Test-Path $Demo)) {
  throw "Demo file not found: $Demo"
}

Write-Host "[1/5] setup-check"
cs2pov setup-check

Write-Host "[2/5] run dry-run pipeline"
cs2pov run $Demo --output $Output --whisper-model $WhisperModel --team $Team --dry-run-translation --max-rounds $MaxRounds

Write-Host "[3/5] inspect latest job"
cs2pov inspect-job $Output

Write-Host "[4/5] export all subtitles"
cs2pov export $Output --format all

Write-Host "[5/5] create feedback pack"
cs2pov feedback $Output

Write-Host ""
Write-Host "Acceptance smoke finished."
Write-Host "Check the final/ folder in the latest job under: $Output"
