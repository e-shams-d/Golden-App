$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

& (Join-Path $PSScriptRoot "verify-native.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Native verification failed (exit code $LASTEXITCODE)."
}

& (Join-Path $PSScriptRoot "verify-docker.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Docker verification failed (exit code $LASTEXITCODE)."
}
