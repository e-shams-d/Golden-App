$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-DockerCompose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments,

        [Parameter(Mandatory = $true)]
        [string] $FailureMessage
    )

    & docker @script:composeArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string] $EnvironmentText,

        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    $escapedName = [Regex]::Escape($Name)
    $matches = [Regex]::Matches(
        $EnvironmentText,
        "(?m)^[ \t]*$escapedName[ \t]*=[ \t]*(?<value>[^\r\n]*?)[ \t]*$"
    )
    if ($matches.Count -ne 1) {
        throw "$Name must have exactly one assignment in the private .env file."
    }

    return $matches[0].Groups["value"].Value
}

function Assert-UrlSafeCredential {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,

        [Parameter(Mandatory = $true)]
        [string] $Value,

        [Parameter(Mandatory = $true)]
        [int] $MinimumLength
    )

    if (
        $Value.StartsWith("change-me", [StringComparison]::OrdinalIgnoreCase) -or
        $Value.Length -lt $MinimumLength -or
        $Value -notmatch "^[A-Za-z0-9._~-]+$"
    ) {
        throw (
            "$Name must be at least $MinimumLength characters and use only " +
            "URL-safe characters: A-Z, a-z, 0-9, dot, underscore, tilde, or hyphen."
        )
    }
}

function Get-ServiceContainerId {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Service,

        [switch] $IncludeStopped
    )

    $arguments = @("ps")
    if ($IncludeStopped) {
        $arguments += "--all"
    }
    $arguments += @("-q", $Service)
    $containerIdOutput = & docker @script:composeArguments @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Could not resolve the $Service container."
    }

    $containerId = @($containerIdOutput | Where-Object { $_ })[0]
    if (-not $containerId) {
        throw "The $Service service did not create a container."
    }
    return $containerId
}

function Assert-OneShotSucceeded {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Service
    )

    $containerId = Get-ServiceContainerId -Service $Service -IncludeStopped

    $exitCodeOutput = & docker inspect --format "{{.State.ExitCode}}" $containerId
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the $Service one-shot service exit code."
    }

    $exitCode = @($exitCodeOutput | Where-Object { $_ })[0]
    if ($exitCode -ne "0") {
        throw "The $Service one-shot service did not complete successfully."
    }
}

function Assert-LongRunningServices {
    $expectedServices = @(
        "nginx",
        "trader-pwa",
        "admin-web",
        "backend",
        "worker",
        "scheduler",
        "postgres",
        "redis"
    )
    $runningOutput = & docker @script:composeArguments ps --services --status running
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect running Docker Compose services."
    }

    $runningServices = @($runningOutput | Where-Object { $_ })
    $missingServices = @(
        $expectedServices | Where-Object { $_ -notin $runningServices }
    )
    if ($missingServices.Count -gt 0) {
        throw "Expected services are not running: $($missingServices -join ', ')."
    }
}

function Assert-ApplicationIsolation {
    $nonRootServices = @(
        "nginx",
        "trader-pwa",
        "admin-web",
        "backend",
        "worker",
        "scheduler",
        "migrate"
    )
    foreach ($service in $nonRootServices) {
        $containerId = Get-ServiceContainerId -Service $service -IncludeStopped
        $configuredUser = (& docker inspect --format "{{.Config.User}}" $containerId |
            Select-Object -First 1)
        if (
            $LASTEXITCODE -ne 0 -or
            -not $configuredUser -or
            $configuredUser -in @("0", "0:0", "root")
        ) {
            throw "$service must use an explicit non-root runtime user."
        }
    }

    $privateServices = @(
        "trader-pwa",
        "admin-web",
        "backend",
        "worker",
        "scheduler",
        "postgres",
        "redis"
    )
    foreach ($service in $privateServices) {
        $containerId = Get-ServiceContainerId -Service $service
        $bindings = (& docker inspect --format "{{json .HostConfig.PortBindings}}" $containerId |
            Select-Object -First 1)
        if ($LASTEXITCODE -ne 0 -or $bindings -notin @("null", "{}")) {
            throw "$service must not publish a host port."
        }
    }
}

function Assert-ContainerHealthChecks {
    $containerIds = @(
        & docker @script:composeArguments ps --all -q | Where-Object { $_ }
    )
    if ($LASTEXITCODE -ne 0 -or $containerIds.Count -eq 0) {
        throw "Could not inspect Docker Compose container health."
    }

    $checkedServices = @()
    foreach ($containerId in $containerIds) {
        $hasHealthCheck = (& docker inspect `
            --format "{{if .Config.Healthcheck}}configured{{else}}none{{end}}" `
            $containerId | Select-Object -First 1)
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect a container health-check configuration."
        }
        if ($hasHealthCheck -ne "configured") {
            continue
        }

        $service = (& docker inspect `
            --format "{{index .Config.Labels `"com.docker.compose.service`"}}" `
            $containerId | Select-Object -First 1)
        $healthStatus = (& docker inspect --format "{{.State.Health.Status}}" $containerId |
            Select-Object -First 1)
        if ($LASTEXITCODE -ne 0 -or $healthStatus -ne "healthy") {
            throw "Container health check is not healthy for service $service."
        }
        $checkedServices += $service
    }

    $requiredHealthChecks = @(
        "nginx",
        "trader-pwa",
        "admin-web",
        "backend",
        "postgres",
        "redis"
    )
    $missingHealthChecks = @(
        $requiredHealthChecks | Where-Object { $_ -notin $checkedServices }
    )
    if ($missingHealthChecks.Count -gt 0) {
        throw "Required container health checks were not inspected: $($missingHealthChecks -join ', ')."
    }
}

function Wait-ForContainerHealthChecks {
    param(
        [Parameter(Mandatory = $true)]
        [int] $TimeoutSeconds
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = "No container health result was available."
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            Assert-ContainerHealthChecks
            return
        }
        catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Seconds 2
        }
    }
    throw "Timed out waiting for container health checks. Last result: $lastError"
}

function Assert-StorageInitSecurity {
    $containerId = Get-ServiceContainerId -Service "storage-init" -IncludeStopped
    $configuredUser = (& docker inspect --format "{{.Config.User}}" $containerId |
        Select-Object -First 1)
    $readOnlyRoot = (& docker inspect --format "{{.HostConfig.ReadonlyRootfs}}" $containerId |
        Select-Object -First 1)
    $capAddJson = (& docker inspect --format "{{json .HostConfig.CapAdd}}" $containerId |
        Select-Object -First 1)
    $capDropJson = (& docker inspect --format "{{json .HostConfig.CapDrop}}" $containerId |
        Select-Object -First 1)
    $securityOptionsJson = (& docker inspect `
        --format "{{json .HostConfig.SecurityOpt}}" `
        $containerId | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect storage-init runtime security."
    }

    if ($configuredUser -notin @("0", "0:0", "root")) {
        throw "storage-init is the only root exception and must explicitly use root."
    }
    if ($readOnlyRoot -ne "true") {
        throw "storage-init must use a read-only root filesystem."
    }

    # Docker 25+/Compose v2 may report capabilities in CAP_-prefixed form.
    $capAdd = @($capAddJson | ConvertFrom-Json) |
        ForEach-Object { "$_".ToUpperInvariant() -replace '^CAP_', '' }
    $capDrop = @($capDropJson | ConvertFrom-Json) |
        ForEach-Object { "$_".ToUpperInvariant() -replace '^CAP_', '' }
    $securityOptions = @($securityOptionsJson | ConvertFrom-Json)
    $expectedCapabilities = @("CHOWN", "DAC_OVERRIDE", "FOWNER")
    $missingCapabilities = @(
        $expectedCapabilities | Where-Object { $_ -notin $capAdd }
    )
    $unexpectedCapabilities = @(
        $capAdd | Where-Object { $_ -notin $expectedCapabilities }
    )
    if (
        $missingCapabilities.Count -gt 0 -or
        $unexpectedCapabilities.Count -gt 0 -or
        "ALL" -notin $capDrop
    ) {
        throw "storage-init capabilities differ from the reviewed least-privilege exception."
    }
    if ("no-new-privileges:true" -notin $securityOptions) {
        throw "storage-init must enable no-new-privileges."
    }
}

function Get-IngressPort {
    $portOutput = & docker @script:composeArguments port nginx 8080
    if ($LASTEXITCODE -ne 0) {
        throw "Could not resolve the Nginx host port."
    }

    $binding = @($portOutput | Where-Object { $_ })[0]
    if (-not $binding -or $binding -notmatch ":(\d+)\s*$") {
        throw "The Nginx host port mapping is missing or invalid."
    }

    return [int] $Matches[1]
}

function Test-HttpTarget {
    param(
        [Parameter(Mandatory = $true)]
        [int] $Port,

        [Parameter(Mandatory = $true)]
        [hashtable] $Target
    )

    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:$Port$($Target.Path)" `
            -Headers @{ Host = $Target.Host } `
            -TimeoutSec 5 `
            -UseBasicParsing `
            -ErrorAction Stop
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Wait-ForHttpTargets {
    param(
        [Parameter(Mandatory = $true)]
        [int] $Port,

        [Parameter(Mandatory = $true)]
        [int] $TimeoutSeconds
    )

    $targets = @(
        @{ Name = "Nginx"; Host = "trader.localhost"; Path = "/nginx-health" },
        @{ Name = "backend liveness"; Host = "trader.localhost"; Path = "/api/v1/health/live" },
        @{ Name = "backend readiness"; Host = "trader.localhost"; Path = "/api/v1/health/ready" },
        @{ Name = "trader app"; Host = "trader.localhost"; Path = "/" },
        @{ Name = "admin app"; Host = "admin.localhost"; Path = "/" }
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)

    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $pending = @(
            $targets | Where-Object {
                -not (Test-HttpTarget -Port $Port -Target $_)
            }
        )
        if ($pending.Count -eq 0) {
            return
        }
        Start-Sleep -Seconds 2
    }

    $pendingNames = ($pending | ForEach-Object { $_.Name }) -join ", "
    throw "Timed out waiting for HTTP checks: $pendingNames."
}

function Test-RestrictedHealthTarget {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    $probe = @'
import os
import sys
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8000" + sys.argv[1],
    headers={"X-Operations-Token": os.environ["OPERATIONS_HEALTH_TOKEN"]},
)
with urllib.request.urlopen(request, timeout=5) as response:
    if response.status != 200:
        raise SystemExit(1)
'@
    & docker @script:composeArguments exec -T backend python -c $probe $Path 2>$null
    return $LASTEXITCODE -eq 0
}

function Wait-ForRestrictedHealthTargets {
    param(
        [Parameter(Mandatory = $true)]
        [int] $TimeoutSeconds
    )

    $paths = @(
        "/api/v1/health/dependencies",
        "/api/v1/health/workers"
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $pending = @($paths | Where-Object { -not (Test-RestrictedHealthTarget -Path $_) })
        if ($pending.Count -eq 0) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for restricted dependency/worker health checks."
}

function Assert-ReleaseMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [int] $Port,

        [Parameter(Mandatory = $true)]
        [string] $ExpectedCommit
    )

    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:$Port/api/v1/meta/release" `
            -Headers @{ Host = "trader.localhost" } `
            -TimeoutSec 5 `
            -UseBasicParsing `
            -ErrorAction Stop
        $metadata = $response.Content | ConvertFrom-Json
    }
    catch {
        throw "Could not read release metadata through Nginx."
    }

    if ($metadata.commit -cne $ExpectedCommit) {
        throw "Release metadata commit does not match the clean-clone Git SHA."
    }
}

function Assert-AuthenticationCompletes {
    <#
        The check every earlier smoke check was missing, and the reason a broken login
        survived five merged slices: they all probed with a *wrong* credential.

        A wrong password returns 401 whether the stack is healthy or not, because it
        never reaches the code that mints a CSRF token. With AUTH_CSRF_KEY_SECRET
        absent from the container, the success path raised on an empty HMAC key and
        every correct password returned 500 - while every wrong one kept returning the
        same 401 it always had.

        The integration suite could not see it either: each of its settings factories
        passes the secret in directly, so it tests a configuration the deployment does
        not have.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [int] $Port
    )

    # A fresh identity per run. The verifier keeps its data volumes across runs, so a
    # fixed number would find a trader already registered under an earlier run's
    # password and fail for a reason that has nothing to do with the stack.
    $phone = "09" + -join (1..9 | ForEach-Object { Get-Random -Minimum 0 -Maximum 10 })
    $password = "Verify-" + [System.Guid]::NewGuid().ToString("N")
    $headers = @{ Host = "trader.localhost" }

    try {
        Invoke-WebRequest `
            -Uri "http://127.0.0.1:$Port/api/v1/traders/register" `
            -Method Post `
            -Headers $headers `
            -ContentType "application/json" `
            -Body (@{
                display_name      = "Docker Verification"
                primary_phone     = $phone
                contact_full_name = "Verification Contact"
                password          = $password
            } | ConvertTo-Json -Compress) `
            -TimeoutSec 15 `
            -UseBasicParsing `
            -ErrorAction Stop | Out-Null
    }
    catch {
        throw "Public trader registration failed against the running stack."
    }

    $loginUri = "http://127.0.0.1:$Port/api/v1/auth/trader/login"

    # -SkipHttpErrorCheck so a 401 is data rather than an exception: this stage has to
    # distinguish three outcomes, and two of them are not successes.
    $refused = Invoke-WebRequest `
        -Uri $loginUri `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body (@{ identifier = $phone; password = "wrong-$password" } | ConvertTo-Json -Compress) `
        -TimeoutSec 15 `
        -UseBasicParsing `
        -SkipHttpErrorCheck
    if ($refused.StatusCode -ne 401) {
        throw "A wrong password returned $($refused.StatusCode) rather than 401."
    }

    $accepted = Invoke-WebRequest `
        -Uri $loginUri `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body (@{ identifier = $phone; password = $password } | ConvertTo-Json -Compress) `
        -TimeoutSec 15 `
        -UseBasicParsing `
        -SkipHttpErrorCheck
    if ($accepted.StatusCode -ne 200) {
        throw (
            "A correct password did not complete authentication against the stack " +
            "(HTTP $($accepted.StatusCode)). This is the shape of the defect this " +
            "stage was written for: check that the backend container receives " +
            "AUTH_CSRF_KEY_SECRET."
        )
    }

    # The cookie, not just the status. A 200 with no session cookie is a login that
    # tells the browser nothing, and the prefix carries the audience isolation the
    # deployment depends on: `__Host-` is refused by the browser unless the cookie is
    # Secure, has no Domain, and is Path=/, which is what keeps a trader credential
    # off the admin host.
    $cookies = @($accepted.Headers["Set-Cookie"])
    $session = $cookies | Where-Object { $_ -like "*__Host-gp_trader_session=*" }
    if (-not $session) {
        throw "Authentication returned 200 without setting __Host-gp_trader_session."
    }
    if ($session -notmatch "(?i)secure") {
        throw (
            "The session cookie is not marked Secure, so a browser will refuse to " +
            "store it under the __Host- prefix and every request will be anonymous."
        )
    }
}

function Invoke-PostgresSql {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Sql,

        [Parameter(Mandatory = $true)]
        [string] $FailureMessage
    )

    $command = 'psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --command "$1"'
    & docker @script:composeArguments exec -T postgres sh -eu -c $command "_" $Sql
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Write-PersistenceSentinels {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Sentinel
    )

    $script:persistenceSentinel = $Sentinel
    $sql = @"
CREATE SCHEMA IF NOT EXISTS m1_verification;
CREATE TABLE IF NOT EXISTS m1_verification.persistence_probe (
    probe_key text PRIMARY KEY,
    probe_value text NOT NULL
);
INSERT INTO m1_verification.persistence_probe (probe_key, probe_value)
VALUES ('$Sentinel', 'present')
ON CONFLICT (probe_key) DO UPDATE SET probe_value = EXCLUDED.probe_value;
"@
    Invoke-PostgresSql -Sql $sql -FailureMessage "Could not write the PostgreSQL persistence sentinel."
    $script:databaseSentinelCreated = $true

    $storageWriter = @'
from pathlib import Path
import sys

path = Path("/app/storage") / f".m1-persistence-{sys.argv[1]}"
path.write_text("present\n", encoding="ascii")
'@
    & docker @script:composeArguments exec -T backend python -c $storageWriter $Sentinel
    if ($LASTEXITCODE -ne 0) {
        throw "Could not write the storage persistence sentinel."
    }
    $script:storageSentinelCreated = $true
}

function Assert-PersistenceSentinels {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Sentinel
    )

    $query = @"
SELECT probe_value
FROM m1_verification.persistence_probe
WHERE probe_key = '$Sentinel';
"@
    $command = 'psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --command "$1"'
    $databaseOutput = & docker @script:composeArguments exec -T postgres `
        sh -eu -c $command "_" $query
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the PostgreSQL persistence sentinel after restart."
    }
    $databaseValue = (@($databaseOutput | Where-Object { $_ })[-1]).Trim()
    if ($databaseValue -cne "present") {
        throw "The PostgreSQL persistence sentinel did not survive container recreation."
    }

    $storageReader = @'
from pathlib import Path
import sys

path = Path("/app/storage") / f".m1-persistence-{sys.argv[1]}"
if path.read_text(encoding="ascii").strip() != "present":
    raise SystemExit(1)
'@
    & docker @script:composeArguments exec -T backend python -c $storageReader $Sentinel
    if ($LASTEXITCODE -ne 0) {
        throw "The storage persistence sentinel did not survive container recreation."
    }
}

function Remove-PersistenceSentinels {
    if (-not $script:persistenceSentinel) {
        return
    }
    $sentinel = $script:persistenceSentinel

    if ($script:storageSentinelCreated) {
        $storageCleanup = @'
from pathlib import Path
import sys

path = Path("/app/storage") / f".m1-persistence-{sys.argv[1]}"
path.unlink(missing_ok=True)
'@
        & docker @script:composeArguments exec -T backend `
            python -c $storageCleanup $sentinel
        if ($LASTEXITCODE -ne 0) {
            throw "Could not remove the storage persistence sentinel."
        }
        $script:storageSentinelCreated = $false
    }

    if ($script:databaseSentinelCreated) {
        Invoke-PostgresSql `
            -Sql (
                "DELETE FROM m1_verification.persistence_probe " +
                "WHERE probe_key = '$sentinel';"
            ) `
            -FailureMessage "Could not remove the PostgreSQL persistence sentinel."
        $script:databaseSentinelCreated = $false
    }
    $script:persistenceSentinel = $null
}

function Write-ImageEvidence {
    $services = @(
        "nginx",
        "trader-pwa",
        "admin-web",
        "backend",
        "worker",
        "scheduler",
        "migrate",
        "storage-init",
        "postgres",
        "redis"
    )
    Write-Host "Container image evidence (IDs and available immutable digests):"
    foreach ($service in $services) {
        $containerId = Get-ServiceContainerId -Service $service -IncludeStopped
        $imageId = (& docker inspect --format "{{.Image}}" $containerId |
            Select-Object -First 1)
        $repoDigestsJson = (& docker image inspect `
            --format "{{json .RepoDigests}}" `
            $imageId | Select-Object -First 1)
        if ($LASTEXITCODE -ne 0 -or -not $imageId) {
            throw "Could not inspect image evidence for $service."
        }
        $repoDigests = @($repoDigestsJson | ConvertFrom-Json)
        $digestEvidence = if ($repoDigests.Count -gt 0) {
            $repoDigests -join ","
        }
        else {
            "<none-for-local-build>"
        }
        Write-Host "$service image_id=$imageId repo_digests=$digestEvidence"
    }
}

$repositoryRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$stackStarted = $false
$verificationSucceeded = $false
$script:databaseSentinelCreated = $false
$script:storageSentinelCreated = $false
$script:persistenceSentinel = $null
$previousLocalDataRoot = [Environment]::GetEnvironmentVariable(
    "LOCAL_DATA_ROOT",
    [EnvironmentVariableTarget]::Process
)
$previousHttpPort = [Environment]::GetEnvironmentVariable(
    "HTTP_PORT",
    [EnvironmentVariableTarget]::Process
)
$verificationProjectName = [Environment]::GetEnvironmentVariable(
    "M1_VERIFY_PROJECT_NAME",
    [EnvironmentVariableTarget]::Process
)
if ([string]::IsNullOrWhiteSpace($verificationProjectName)) {
    $verificationProjectName = "gold-platform-m1-verify"
}
if ($verificationProjectName -notmatch "^[a-z0-9][a-z0-9_-]*$") {
    throw "M1_VERIFY_PROJECT_NAME must contain only lowercase letters, digits, underscore, or hyphen."
}

$verificationPortText = [Environment]::GetEnvironmentVariable(
    "M1_VERIFY_HTTP_PORT",
    [EnvironmentVariableTarget]::Process
)
if ([string]::IsNullOrWhiteSpace($verificationPortText)) {
    $verificationPortText = "18080"
}
$verificationPort = 0
if (
    -not [int]::TryParse($verificationPortText, [ref] $verificationPort) -or
    $verificationPort -lt 1 -or
    $verificationPort -gt 65535
) {
    throw "M1_VERIFY_HTTP_PORT must be an integer between 1 and 65535."
}

$env:LOCAL_DATA_ROOT = "../../.local/m1-verify/$verificationProjectName"
$env:HTTP_PORT = "$verificationPort"
$script:composeArguments = @(
    "compose",
    "--project-name",
    $verificationProjectName,
    "--env-file",
    ".env",
    "-f",
    "infra/compose/compose.local.yml"
)

Push-Location $repositoryRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Engine with Compose v2 is required."
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is required to bind release metadata to the clean-clone commit."
    }
    if (-not (Test-Path -LiteralPath ".env" -PathType Leaf)) {
        throw "Create a private .env from .env.example before Docker verification."
    }

    $environmentText = Get-Content -LiteralPath ".env" -Raw
    $controlledEnvironmentNames = @(
        "POSTGRES_PASSWORD",
        "APP_DB_PASSWORD",
        "MIGRATION_DB_PASSWORD",
        "REDIS_PASSWORD",
        "OPERATIONS_HEALTH_TOKEN",
        "RELEASE_COMMIT"
    )
    foreach ($environmentName in $controlledEnvironmentNames) {
        $inheritedValue = [Environment]::GetEnvironmentVariable(
            $environmentName,
            [EnvironmentVariableTarget]::Process
        )
        if ($null -ne $inheritedValue) {
            throw (
                "$environmentName is inherited from the process and would override .env. " +
                "Remove that process variable before verification."
            )
        }
    }
    foreach ($credentialName in @(
        "POSTGRES_PASSWORD",
        "APP_DB_PASSWORD",
        "MIGRATION_DB_PASSWORD",
        "REDIS_PASSWORD"
    )) {
        Assert-UrlSafeCredential `
            -Name $credentialName `
            -Value (Get-DotEnvValue -EnvironmentText $environmentText -Name $credentialName) `
            -MinimumLength 16
    }
    Assert-UrlSafeCredential `
        -Name "OPERATIONS_HEALTH_TOKEN" `
        -Value (Get-DotEnvValue `
            -EnvironmentText $environmentText `
            -Name "OPERATIONS_HEALTH_TOKEN") `
        -MinimumLength 32

    $expectedCommit = (& git rev-parse HEAD | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or $expectedCommit -notmatch "^[0-9a-f]{40}$") {
        throw "Could not resolve the clean-clone Git commit."
    }
    $configuredCommit = Get-DotEnvValue `
        -EnvironmentText $environmentText `
        -Name "RELEASE_COMMIT"
    if ($configuredCommit -cne $expectedCommit) {
        throw "RELEASE_COMMIT in .env must exactly equal the clean-clone Git SHA."
    }

    & docker compose version
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is unavailable."
    }

    $existingContainers = @(
        & docker @script:composeArguments ps --all -q | Where-Object { $_ }
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Could not check for an existing verification stack."
    }
    if ($existingContainers.Count -gt 0) {
        throw (
            "The isolated verification project '$verificationProjectName' already has containers. " +
            "Inspect it and stop it explicitly before retrying; this verifier will not take it over."
        )
    }

    Write-Host "Validating the Docker Compose model..."
    Invoke-DockerCompose -Arguments @("config", "--quiet") `
        -FailureMessage "Docker Compose rendering failed"

    Write-Host "Building the application images..."
    Invoke-DockerCompose -Arguments @("build") `
        -FailureMessage "Container image build failed"

    Write-Host "Starting the local stack..."
    $stackStarted = $true
    Invoke-DockerCompose -Arguments @("up", "-d", "--no-build") `
        -FailureMessage "Docker Compose startup failed"

    Assert-OneShotSucceeded -Service "migrate"
    Assert-OneShotSucceeded -Service "storage-init"
    Assert-LongRunningServices
    Assert-ApplicationIsolation
    Assert-StorageInitSecurity

    $ingressPort = Get-IngressPort
    Wait-ForHttpTargets -Port $ingressPort -TimeoutSeconds 180
    Wait-ForRestrictedHealthTargets -TimeoutSeconds 180
    Wait-ForContainerHealthChecks -TimeoutSeconds 180
    Assert-ReleaseMetadata -Port $ingressPort -ExpectedCommit $expectedCommit

    $persistenceSentinel = [Guid]::NewGuid().ToString("N")
    Write-Host "Writing non-financial PostgreSQL and storage persistence sentinels..."
    Write-PersistenceSentinels -Sentinel $persistenceSentinel

    Write-Host "Recreating the verification stack without deleting persistent data..."
    Invoke-DockerCompose -Arguments @("down") `
        -FailureMessage "Could not stop the stack for persistence verification"
    $stackStarted = $false
    $stackStarted = $true
    Invoke-DockerCompose -Arguments @("up", "-d", "--no-build") `
        -FailureMessage "Could not recreate the stack for persistence verification"

    Assert-OneShotSucceeded -Service "migrate"
    Assert-OneShotSucceeded -Service "storage-init"
    Assert-LongRunningServices
    Assert-ApplicationIsolation
    Assert-StorageInitSecurity
    $ingressPort = Get-IngressPort
    Wait-ForHttpTargets -Port $ingressPort -TimeoutSeconds 180
    Wait-ForRestrictedHealthTargets -TimeoutSeconds 180
    Wait-ForContainerHealthChecks -TimeoutSeconds 180
    Assert-ReleaseMetadata -Port $ingressPort -ExpectedCommit $expectedCommit

    # After the recreate rather than before it, so the identity this registers is
    # written to a volume that has already survived one `compose down` -
    # authentication proved against persisted data is worth more than against a first
    # boot.
    Write-Host "Completing an end-to-end authentication against the running stack..."
    Assert-AuthenticationCompletes -Port $ingressPort

    Assert-PersistenceSentinels -Sentinel $persistenceSentinel
    Remove-PersistenceSentinels
    Write-ImageEvidence

    Write-Host "Docker Compose service status:"
    Invoke-DockerCompose -Arguments @("ps") `
        -FailureMessage "Could not read Docker Compose service status"

    $verificationSucceeded = $true
    Write-Host (
        "automated Docker gates passed. Maintained security scans, SBOMs, " +
        "CI evidence, and owner acceptance are still separate required gates."
    )
}
finally {
    $finalizationError = $null
    if (
        $stackStarted -and
        ($script:databaseSentinelCreated -or $script:storageSentinelCreated)
    ) {
        try {
            Write-Host "Removing non-financial persistence sentinels..."
            Remove-PersistenceSentinels
        }
        catch {
            $finalizationError = "Persistence-sentinel cleanup failed: $($_.Exception.Message)"
            if (-not $verificationSucceeded) {
                Write-Warning $finalizationError
            }
        }
    }
    if ($stackStarted) {
        Write-Host "Stopping the verification stack without deleting data volumes..."
        & docker @script:composeArguments down
        $cleanupExitCode = $LASTEXITCODE
        if ($cleanupExitCode -ne 0) {
            $cleanupMessage = (
                "Verification stack cleanup failed (exit code $cleanupExitCode). " +
                "No volume deletion was attempted."
            )
            if ($verificationSucceeded -and -not $finalizationError) {
                $finalizationError = $cleanupMessage
            }
            else {
                Write-Warning $cleanupMessage
            }
        }
    }

    if ($null -eq $previousLocalDataRoot) {
        Remove-Item Env:LOCAL_DATA_ROOT -ErrorAction SilentlyContinue
    }
    else {
        $env:LOCAL_DATA_ROOT = $previousLocalDataRoot
    }
    if ($null -eq $previousHttpPort) {
        Remove-Item Env:HTTP_PORT -ErrorAction SilentlyContinue
    }
    else {
        $env:HTTP_PORT = $previousHttpPort
    }
    Pop-Location
    if ($verificationSucceeded -and $finalizationError) {
        throw $finalizationError
    }
}
