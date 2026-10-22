param([Parameter(Mandatory=$true)][string]$CoreDirectory)
$ErrorActionPreference = 'Stop'
$contextProject = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$contextCore = (Resolve-Path -LiteralPath $CoreDirectory).Path
if (-not (Test-Path -LiteralPath (Join-Path $contextCore 'modules/CMakeLists.txt'))) {
    throw 'Target must contain the optional TrinityCore modules build convention.'
}
$contextTarget = [IO.Path]::GetFullPath((Join-Path $contextCore 'modules/mod-context-api'))
if (-not $contextTarget.StartsWith($contextCore.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Module target escaped the selected core checkout.'
}
if (Test-Path -LiteralPath $contextTarget) {
    throw 'Module target already exists. Review it before replacing or merging anything.'
}
# Copy the canonical module as one new directory; do not change core hooks/config.
Copy-Item -LiteralPath (Join-Path $contextProject 'server-module') -Destination $contextTarget -Recurse
Write-Host "Installed source module at $contextTarget"
Write-Host 'Apply/review the paired hooks, build, then configure read-only capture for the development realm.'
