[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$SkipInstall,
    [switch]$SkipModels,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $projectRoot "frontend"
$venvRoot = Join-Path $projectRoot ".venv"
$pythonExe = Join-Path $venvRoot "Scripts\python.exe"
$requirementsFile = Join-Path $projectRoot "requirements.txt"
$packageLockFile = Join-Path $frontendRoot "package-lock.json"
$runtimeRoot = Join-Path $projectRoot ".runtime"
$logRoot = Join-Path $runtimeRoot "logs"
$backendOutLog = Join-Path $logRoot "backend.stdout.log"
$backendErrorLog = Join-Path $logRoot "backend.stderr.log"
$frontendOutLog = Join-Path $logRoot "frontend.stdout.log"
$frontendErrorLog = Join-Path $logRoot "frontend.stderr.log"
$pythonMarker = Join-Path $venvRoot ".requirements.sha256"
$nodeMarker = Join-Path $frontendRoot "node_modules\.package-lock.sha256"
$startedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$backend = $null
$frontend = $null
$reusedBackend = $false

function Write-Step([string]$Message) {
    Write-Host "`n> $Message" -ForegroundColor Cyan
}

function Stop-StartedProcesses {
    foreach ($process in $startedProcesses) {
        if ($null -ne $process -and -not $process.HasExited) {
            try {
                & taskkill.exe /PID $process.Id /T /F *> $null
            }
            catch {
                try { $process.Kill() } catch { }
            }
        }
    }
}

function Get-ListeningProcess([int]$Port) {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Assert-PortAvailable([int]$Port, [string]$ServiceName) {
    $listener = Get-ListeningProcess $Port
    if ($null -ne $listener) {
        $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        $ownerName = if ($null -ne $owner) { $owner.ProcessName } else { "PID $($listener.OwningProcess)" }
        throw "$ServiceName cannot start because port $Port is already used by $ownerName. Close that process or run tools\launch.ps1 with a different port."
    }
}

function Find-Python312 {
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        try {
            $version = & $pyLauncher.Source -3.12 -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version -eq "3.12") {
                return @($pyLauncher.Source, "-3.12")
            }
        }
        catch { }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        try {
            $version = & $python.Source -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version -eq "3.12") {
                return @($python.Source)
            }
        }
        catch { }
    }

    throw "Python 3.12 was not found. Install Python 3.12, then double-click the launcher again."
}

function Wait-ForUrl(
    [string]$Url,
    [System.Diagnostics.Process]$Process,
    [string]$ServiceName,
    [string]$ErrorLog,
    [int]$TimeoutSeconds = 90
) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $nextProgress = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            $details = if (Test-Path $ErrorLog) { (Get-Content $ErrorLog -Tail 12) -join "`n" } else { "No error log was written." }
            throw "$ServiceName exited during startup.`n$details"
        }

        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $response
            }
        }
        catch { }

        if ((Get-Date) -ge $nextProgress) {
            Write-Host "." -NoNewline
            $nextProgress = (Get-Date).AddSeconds(10)
        }
        Start-Sleep -Milliseconds 500
    }

    throw "$ServiceName did not become ready within $TimeoutSeconds seconds. Check $ErrorLog"
}

try {
    Write-Host "VERIFai one-click launcher" -ForegroundColor Green
    Write-Host "Project: $projectRoot"

    if (-not (Test-Path $runtimeRoot)) { New-Item -ItemType Directory -Path $runtimeRoot | Out-Null }
    if (-not (Test-Path $logRoot)) { New-Item -ItemType Directory -Path $logRoot | Out-Null }

    if (-not (Test-Path $pythonExe)) {
        Write-Step "Creating the Python 3.12 environment"
        $pythonCommand = Find-Python312
        $pythonProgram = $pythonCommand[0]
        $pythonArguments = @()
        if ($pythonCommand.Count -gt 1) { $pythonArguments += $pythonCommand[1..($pythonCommand.Count - 1)] }
        $pythonArguments += @("-m", "venv", $venvRoot)
        & $pythonProgram @pythonArguments
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
    }

    if (-not $SkipInstall) {
        $requirementsHash = (Get-FileHash $requirementsFile -Algorithm SHA256).Hash
        $installedHash = if (Test-Path $pythonMarker) { (Get-Content $pythonMarker -Raw).Trim() } else { "" }
        if ($requirementsHash -ne $installedHash) {
            Write-Step "Installing Python packages (the first run can take several minutes)"
            & $pythonExe -m pip install --disable-pip-version-check -r $requirementsFile
            if ($LASTEXITCODE -ne 0) { throw "Python package installation failed." }
            Set-Content -Path $pythonMarker -Value $requirementsHash -NoNewline
        }
        else {
            Write-Host "Python packages are up to date."
        }
    }

    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npm) {
        throw "Node.js/npm was not found. Install Node.js 22 or newer, then double-click the launcher again."
    }

    $nodeVersion = (& node.exe -p "process.versions.node").Trim()
    $nodeMajor = [int]($nodeVersion.Split('.')[0])
    $nodeMinor = [int]($nodeVersion.Split('.')[1])
    $supportedNode = ($nodeMajor -eq 20 -and $nodeMinor -ge 19) -or $nodeMajor -ge 22
    if (-not $supportedNode) {
        throw "Node.js $nodeVersion is not supported by this frontend. Install Node.js 22 or newer."
    }

    if (-not $SkipInstall) {
        $packageLockHash = (Get-FileHash $packageLockFile -Algorithm SHA256).Hash
        $installedNodeHash = if (Test-Path $nodeMarker) { (Get-Content $nodeMarker -Raw).Trim() } else { "" }
        if ($packageLockHash -ne $installedNodeHash) {
            Write-Step "Installing frontend packages"
            Push-Location $frontendRoot
            try { & $npm.Source ci }
            finally { Pop-Location }
            if ($LASTEXITCODE -ne 0) { throw "Frontend package installation failed." }
            Set-Content -Path $nodeMarker -Value $packageLockHash -NoNewline
        }
        else {
            Write-Host "Frontend packages are up to date."
        }
    }

    if (-not (Test-Path (Join-Path $frontendRoot "node_modules\vite\bin\vite.js"))) {
        throw "Frontend packages are missing. Run the launcher without -SkipInstall."
    }

    # Face match, age gap, and liveness need ~800 MB of pretrained model files
    # that are not in git. Fetch them now, outside any request, so the first
    # selfie does not stall on a download. An offline machine still gets the
    # document checks; the face endpoints then say what to run.
    if (-not $SkipModels) {
        Write-Step "Checking face-pipeline model files"
        & $pythonExe (Join-Path $projectRoot "tools\fetch_models.py")
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Face-pipeline model files are incomplete. Face match, age gap, and liveness stay unavailable until 'python tools\fetch_models.py' succeeds; document checks still work."
        }
    }

    $tesseract = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    $standardTesseract = "C:\Program Files\Tesseract-OCR\tesseract.exe"
    if ($null -eq $tesseract -and (Test-Path $standardTesseract)) {
        $env:PATH = "$(Split-Path $standardTesseract);$env:PATH"
        $tesseract = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    }
    if ($null -eq $tesseract) {
        Write-Warning "Tesseract OCR is not installed. Passport, PAN, and marksheet text extraction may fail; the rest of the app can still start."
    }

    Assert-PortAvailable -Port $FrontendPort -ServiceName "Frontend"

    $backendListener = Get-ListeningProcess $BackendPort
    if ($null -ne $backendListener) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 5
            if ($health.status -ne "ok" -or $null -eq $health.consent_enforcement) {
                throw "The health response does not identify VERIFai."
            }
            $reusedBackend = $true
            Write-Host "Using the VERIFai API already running on port $BackendPort."
        }
        catch {
            $owner = Get-Process -Id $backendListener.OwningProcess -ErrorAction SilentlyContinue
            $ownerName = if ($null -ne $owner) { $owner.ProcessName } else { "PID $($backendListener.OwningProcess)" }
            throw "Backend cannot start because port $BackendPort is already used by $ownerName, and it is not a responsive VERIFai API."
        }
    }
    else {
        Write-Step "Starting the API on http://localhost:$BackendPort"
        $backend = Start-Process -FilePath $pythonExe `
            -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", $BackendPort) `
            -WorkingDirectory $projectRoot -PassThru -NoNewWindow `
            -RedirectStandardOutput $backendOutLog -RedirectStandardError $backendErrorLog
        $startedProcesses.Add($backend)
        $healthResponse = Wait-ForUrl -Url "http://127.0.0.1:$BackendPort/health" -Process $backend -ServiceName "Backend" -ErrorLog $backendErrorLog -TimeoutSeconds 300
        Write-Host ""
        $health = $healthResponse.Content | ConvertFrom-Json
    }

    Write-Step "Starting the web app on http://localhost:$FrontendPort"
    $env:VITE_API_BASE_URL = "http://localhost:$BackendPort"
    $frontend = Start-Process -FilePath $npm.Source `
        -ArgumentList @("run", "dev", "--", "--host", "localhost", "--port", $FrontendPort, "--strictPort") `
        -WorkingDirectory $frontendRoot -PassThru -NoNewWindow `
        -RedirectStandardOutput $frontendOutLog -RedirectStandardError $frontendErrorLog
    $startedProcesses.Add($frontend)
    Wait-ForUrl -Url "http://localhost:$FrontendPort/" -Process $frontend -ServiceName "Frontend" -ErrorLog $frontendErrorLog | Out-Null

    Write-Host "`nVERIFai is ready: http://localhost:$FrontendPort" -ForegroundColor Green
    if ($health.face_models_ready -eq $false) {
        Write-Warning "Face-pipeline model files are missing: $($health.face_models_missing -join ', '). Run 'python tools\fetch_models.py'."
    }
    if (-not $health.uidai_certificate_loaded) {
        Write-Warning "No UIDAI certificate is loaded. Aadhaar authenticity checks will remain inconclusive."
    }
    elseif (-not $health.uidai_certificate_pinned) {
        Write-Warning "The UIDAI certificate is loaded but its fingerprint is not pinned."
    }

    if (-not $NoBrowser) {
        Start-Process "http://localhost:$FrontendPort" | Out-Null
    }

    Write-Host "Logs: $logRoot"
    $shutdownMessage = if ($reusedBackend) {
        "Press Ctrl+C or close this window to stop the frontend. The API that was already running will remain open."
    }
    else {
        "Press Ctrl+C or close this window to stop both servers."
    }
    Write-Host $shutdownMessage -ForegroundColor Yellow

    while (($reusedBackend -or -not $backend.HasExited) -and -not $frontend.HasExited) {
        Start-Sleep -Seconds 1
    }

    if (-not $reusedBackend -and $backend.HasExited) { throw "The backend stopped unexpectedly. Check $backendErrorLog" }
    if ($frontend.HasExited) { throw "The frontend stopped unexpectedly. Check $frontendErrorLog" }
}
catch {
    Write-Host "`nLauncher error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Stop-StartedProcesses
}
