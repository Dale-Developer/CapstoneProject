# ESSCAN - Verify Ollama on Windows
$ErrorActionPreference = 'Continue'
Write-Host '=== ESSCAN Ollama Verification ===' -ForegroundColor Cyan

Write-Host "`n1. ollama command"
$cmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($cmd) { Write-Host "OK: $($cmd.Source)" -ForegroundColor Green; ollama --version } else { Write-Host 'ERROR: ollama is not on PATH.' -ForegroundColor Red }

Write-Host "`n2. OLLAMA_MODELS"
Write-Host "OLLAMA_MODELS=$env:OLLAMA_MODELS"
if ($env:OLLAMA_MODELS) { Write-Host "Exists: $(Test-Path $env:OLLAMA_MODELS)" }

Write-Host "`n3. Ollama API"
try {
  $r = Invoke-WebRequest -UseBasicParsing http://localhost:11434/api/tags -TimeoutSec 5
  Write-Host "OK: HTTP $($r.StatusCode)" -ForegroundColor Green
  $json = $r.Content | ConvertFrom-Json
  $json.models | Select-Object name,size | Format-Table
} catch { Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red }

Write-Host "`n4. ESSCAN recommendation"
Write-Host 'If qwen2.5vl:3b is missing, run: ollama pull qwen2.5vl:3b'
