# Middletown Chatbot launcher
# Starts standalone Ollama + chatbot backend, then opens the browser.
# Safe to run when already running - skips steps that don't need doing.

$ErrorActionPreference = 'SilentlyContinue'

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OllamaExe  = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$PythonExe  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Url        = "http://localhost:8000"

function Wait-Url($uri, $timeoutSec = 30) {
    for ($i = 0; $i -lt $timeoutSec; $i++) {
        try { Invoke-RestMethod -Uri $uri -TimeoutSec 1 | Out-Null; return $true } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

# 1. Make sure AI Marketing Studio's IPEX-LLM Ollama isn't squatting on the port.
Get-Process -Name "ollama-lib","ollama app" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

# 2. Start standalone Ollama if its server isn't already responding with the right version.
$needsOllama = $true
try {
    $v = Invoke-RestMethod -Uri 'http://localhost:11434/api/version' -TimeoutSec 1
    if ($v.version -and $v.version -notmatch 'ipexllm') { $needsOllama = $false }
} catch {}
if ($needsOllama) {
    if (-not (Test-Path $OllamaExe)) {
        [System.Windows.Forms.MessageBox]::Show(
            "Standalone Ollama not found at:`n$OllamaExe`n`nInstall from https://ollama.com/download.",
            "Middletown Chatbot", "OK", "Error") | Out-Null
        exit 1
    }
    Start-Process -FilePath $OllamaExe -ArgumentList 'serve' -WindowStyle Hidden
    if (-not (Wait-Url 'http://localhost:11434/api/version')) {
        Write-Warning "Ollama didn't come up within 30s."
    }
}

# 3. Start the chatbot backend if not already serving on :8000.
$needsBackend = $true
try { Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 1 | Out-Null; $needsBackend = $false } catch {}
if ($needsBackend) {
    if (-not (Test-Path $PythonExe)) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "Python venv not found at:`n$PythonExe`n`nRun setup first:`n  python -m venv .venv`n  .\.venv\Scripts\Activate.ps1`n  pip install -r requirements.txt",
            "Middletown Chatbot", "OK", "Error") | Out-Null
        exit 1
    }
    Start-Process -FilePath $PythonExe `
        -ArgumentList @('-m','uvicorn','backend.server:app','--host','127.0.0.1','--port','8000','--log-level','warning') `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden
    if (-not (Wait-Url "$Url/api/health")) {
        Write-Warning "Backend didn't come up within 30s."
    }
}

# 4. Open the browser.
Start-Process $Url
