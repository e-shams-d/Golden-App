$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,

        [Parameter(Mandatory = $true)]
        [string] $InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required. $InstallHint"
    }
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Command,

        [Parameter(Mandatory = $true)]
        [string[]] $Arguments,

        [Parameter(Mandatory = $true)]
        [string] $FailureMessage
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Get-ExternalVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Command,

        [Parameter(Mandatory = $true)]
        [string[]] $Arguments,

        [Parameter(Mandatory = $true)]
        [string] $FailureMessage
    )

    $output = & $Command @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }

    return (($output | Out-String).Trim())
}

function Assert-ExactVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Label,

        [Parameter(Mandatory = $true)]
        [string] $Actual,

        [Parameter(Mandatory = $true)]
        [string] $Expected
    )

    if ($Actual -ne $Expected) {
        throw "$Label version mismatch. Expected '$Expected', found '$Actual'."
    }

    Write-Host "$Label version: $Actual"
}

$repositoryRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $repositoryRoot
try {
    Assert-Command -Name "node" -InstallHint "Install the version pinned in .nvmrc."
    Assert-Command -Name "uv" -InstallHint "Install the repository-pinned uv version."
    Assert-Command -Name "pnpm" -InstallHint "Enable the repository-pinned pnpm version through Corepack."

    Write-Host "Verifying the exact repository toolchain..."
    Assert-ExactVersion `
        -Label "Node.js" `
        -Actual (Get-ExternalVersion -Command "node" -Arguments @("--version") -FailureMessage "Unable to read the Node.js version") `
        -Expected "v24.18.0"
    Assert-ExactVersion `
        -Label "pnpm" `
        -Actual (Get-ExternalVersion -Command "pnpm" -Arguments @("--version") -FailureMessage "Unable to read the pnpm version") `
        -Expected "11.15.1"
    $uvVersion = Get-ExternalVersion `
        -Command "uv" `
        -Arguments @("--version") `
        -FailureMessage "Unable to read the uv version"
    if ($uvVersion -notmatch "^uv 0\.8\.22(?:\s|$)") {
        throw "uv version mismatch. Expected 'uv 0.8.22', found '$uvVersion'."
    }
    Write-Host "uv version: $uvVersion"

    Write-Host "Synchronizing the frozen backend environment..."
    Invoke-External -Command "uv" `
        -Arguments @("sync", "--project", "services/backend", "--frozen", "--group", "dev") `
        -FailureMessage "Frozen backend dependency synchronization failed"

    Assert-ExactVersion `
        -Label "Python" `
        -Actual (Get-ExternalVersion `
            -Command "uv" `
            -Arguments @(
                "run",
                "--project",
                "services/backend",
                "--frozen",
                "python",
                "--version"
            ) `
            -FailureMessage "Unable to read the project Python version") `
        -Expected "Python 3.12.13"

    Write-Host "Running provider-neutral repository checks..."
    Invoke-External -Command "uv" `
        -Arguments @(
            "run",
            "--project",
            "services/backend",
            "--frozen",
            "python",
            "infra/scripts/validate_repository.py"
        ) `
        -FailureMessage "Static repository validation failed"

    $secretScanner = "infra/scripts/scan_secrets.py"
    if (Test-Path -LiteralPath $secretScanner -PathType Leaf) {
        Write-Host "Running the repository secret scanner..."
        Invoke-External -Command "uv" `
            -Arguments @(
                "run",
                "--project",
                "services/backend",
                "--frozen",
                "python",
                $secretScanner
            ) `
            -FailureMessage "Repository secret scan failed"
    }
    else {
        Write-Host "No repository-local secret scanner is present; the CI provider must supply this gate."
    }

    Write-Host "Running backend lint, type, and test gates..."
    Invoke-External -Command "uv" `
        -Arguments @(
            "run",
            "--project",
            "services/backend",
            "--frozen",
            "ruff",
            "check",
            "--config",
            "services/backend/pyproject.toml",
            "services/backend/app",
            "services/backend/alembic",
            "services/backend/scripts",
            "tests/backend",
            "infra/scripts/validate_repository.py",
            "infra/scripts/scan_secrets.py"
        ) `
        -FailureMessage "Backend lint failed"
    Invoke-External -Command "uv" `
        -Arguments @(
            "run",
            "--project",
            "services/backend",
            "--frozen",
            "mypy",
            "--config-file",
            "services/backend/pyproject.toml",
            "services/backend/app"
        ) `
        -FailureMessage "Backend typecheck failed"
    Invoke-External -Command "uv" `
        -Arguments @(
            "run",
            "--project",
            "services/backend",
            "--frozen",
            "pytest",
            "-c",
            "services/backend/pyproject.toml",
            "tests/backend"
        ) `
        -FailureMessage "Backend tests failed"

    Write-Host "Installing the frozen frontend dependency graph..."
    Invoke-External -Command "pnpm" `
        -Arguments @("install", "--frozen-lockfile") `
        -FailureMessage "Frozen frontend dependency installation failed"

    Write-Host "Checking the committed OpenAPI contract..."
    Invoke-External -Command "pnpm" `
        -Arguments @("openapi:check") `
        -FailureMessage "OpenAPI contract verification failed"

    Write-Host "Running frontend safety, lint, type, test, build, and accessibility gates..."
    Invoke-External -Command "pnpm" `
        -Arguments @("validate:static") `
        -FailureMessage "Frontend static validation failed"
    Invoke-External -Command "pnpm" `
        -Arguments @("check:public-env") `
        -FailureMessage "Public environment safety scan failed"
    Invoke-External -Command "pnpm" `
        -Arguments @("lint") `
        -FailureMessage "Frontend lint failed"
    Invoke-External -Command "pnpm" `
        -Arguments @("typecheck") `
        -FailureMessage "Frontend typecheck failed"
    Invoke-External -Command "pnpm" `
        -Arguments @("test") `
        -FailureMessage "Frontend tests failed"
    Invoke-External -Command "pnpm" `
        -Arguments @("build") `
        -FailureMessage "Frontend build failed"
    Invoke-External -Command "pnpm" `
        -Arguments @("test:a11y") `
        -FailureMessage "Frontend accessibility tests failed"

    Write-Host "Native M1 verification passed."
}
finally {
    Pop-Location
}
