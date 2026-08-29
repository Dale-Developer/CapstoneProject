# ESSCAN - Ollama Windows setup
# Installs the Ollama application and stores its models on D:\Ollama\models.
# Official Ollama installer supports OLLAMA_INSTALL_DIR and OLLAMA_MODELS.

$ErrorActionPreference = 'Stop'

$InstallDir = 'D:\Ollama'
$ModelsDir = 'D:\Ollama\models'

Write-Host '=== ESSCAN Ollama Windows Setup ===' -ForegroundColor Cyan
Write-Host "Install directory: $InstallDir"
Write-Host "Model directory:   $ModelsDir"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

# Persist model location for the current Windows user.
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $ModelsDir, 'User')
$env:OLLAMA_MODELS = $ModelsDir

# Download/run the official installer script with a custom installation directory.
Write-Host ''
Write-Host 'Installing/updating Ollama from the official installer...' -ForegroundColor Yellow
$env:OLLAMA_INSTALL_DIR = $InstallDir
irm https://ollama.com/install.ps1 | iex

Write-Host ''
Write-Host 'Ollama setup completed.' -ForegroundColor Green
Write-Host 'IMPORTANT: close this PowerShell window and open a new one.' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Then run:'
Write-Host '  ollama --version'
Write-Host '  ollama list'
Write-Host '  ollama pull qwen2.5vl:3b'
Write-Host '  ollama list'
Write-Host ''
Write-Host "Models will be stored under $ModelsDir"
