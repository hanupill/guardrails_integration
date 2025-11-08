param(
    [string]$PythonVersion = "3.13",
    [int]$Port = 8000,
    [string]$Host = "0.0.0.0",
    [switch]$NoStart,
    [switch]$SkipValidators
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Warning $msg }
function Write-Err($msg) { Write-Error $msg }

function Ensure-Venv {
    $venvPy = ".\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Info "Creating Python $PythonVersion virtual environment at '.\.venv'..."
        & py -$PythonVersion -m venv .venv
        Write-Ok "Virtual environment created."
    } else {
        Write-Ok "Virtual environment already exists."
    }
}

function Use-VenvPython {
    $venvPy = ".\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Err "Virtual environment Python not found at '$venvPy'."
        throw "Venv Python missing."
    }
    return $venvPy
}

function Install-Dependencies {
    $venvPy = Use-VenvPython
    $pip = ".\.venv\Scripts\pip.exe"
    Write-Info "Upgrading pip..."
    & $pip install --upgrade pip
    if (Test-Path ".\pyproject.toml") {
        Write-Info "Installing project dependencies via pyproject.toml (editable mode)..."
        & $pip install -e .
    } elseif (Test-Path ".\requirements.txt") {
        Write-Info "Installing dependencies via requirements.txt..."
        & $pip install -r .\requirements.txt
    } else {
        Write-Err "No dependency file found (pyproject.toml or requirements.txt)."
        throw "Dependency file missing."
    }
    Write-Ok "Dependencies installed."
}

function Get-ManifestValidators {
    $manifestPath = ".\hub_validators.txt"
    if (Test-Path $manifestPath) {
        $lines = Get-Content -Path $manifestPath | ForEach-Object { $_.Trim() } | Where-Object { $_ -and (-not $_.StartsWith("#")) }
        if ($lines.Count -gt 0) {
            return $lines
        }
    }
    # Fallback built-in list
    return @(
        "hub://groundedai/grounded_ai_hallucination",
        "hub://guardrails/valid_json",
        "hub://guardrails/unusual_prompt",
        "hub://guardrails/regex_match",
        "hub://guardrails/detect_pii",
        "hub://guardrails/toxic_language",
        "hub://guardrails/valid_url",
        "hub://guardrails/detect_jailbreak",
        "hub://tryolabs/restricttotopic",
        "hub://guardrails/guardrails_pii",
        "hub://guardrails/sensitive_topics"
    )
}

function Install-HubValidators {
    if ($SkipValidators) {
        Write-Warn "Skipping Hub validators installation as requested."
        return
    }

    $validators = Get-ManifestValidators
    $venvPy = Use-VenvPython
    $guardrailsExe = ".\.venv\Scripts\guardrails.exe"

    Write-Info "Installing Guardrails Hub validators..."
    foreach ($v in $validators) {
        Write-Host "  -> $v"
        # Prefer venv Python module invocation
        & $venvPy -m guardrails hub install $v
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Failed via 'python -m guardrails'. Trying 'guardrails.exe'..."
            if (Test-Path $guardrailsExe) {
                & $guardrailsExe hub install $v
                if ($LASTEXITCODE -ne 0) {
                    Write-Err "Installation failed for $v"
                }
            } else {
                Write-Err "guardrails.exe not found in venv; installation failed for $v"
            }
        }
    }
    Write-Ok "Hub validators installation complete."
}

function Start-ApiServer {
    if ($NoStart) {
        Write-Warn "Skipping server start as requested."
        return
    }
    $uvicorn = ".\.venv\Scripts\uvicorn.exe"
    if (-not (Test-Path $uvicorn)) {
        Write-Err "uvicorn.exe not found in venv. Ensure dependencies are installed."
        throw "Uvicorn missing."
    }
    Write-Info "Starting API server at http://$Host:$Port ..."
    & $uvicorn "main:app" --host $Host --port $Port
}

# --- Run all steps ---
Write-Info "Guardrails Integration full setup starting..."
Ensure-Venv
Install-Dependencies
Install-HubValidators
Start-ApiServer
Write-Ok "Setup finished."