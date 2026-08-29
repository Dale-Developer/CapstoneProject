# ESSCAN V7.9.6 Database and Upload Backup Script

param(
    [string]$MysqlExe = "C:\xampp\mysql\bin\mysql.exe",
    [string]$DbUser = "root",
    [string]$DbPassword = "",
    [string]$DbName = "automate_assessment_application",
    [string]$BackupRoot = ".\backups",
    [int]$RetentionDays = 14
)

$ErrorActionPreference = "Stop"

# --------------------------------------------------
# Configuration
# --------------------------------------------------

$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

$dbBackupDir = Join-Path $BackupRoot "database"
$uploadsBackupDir = Join-Path $BackupRoot "uploads"

# Create backup directories
New-Item -ItemType Directory -Force -Path $dbBackupDir | Out-Null
New-Item -ItemType Directory -Force -Path $uploadsBackupDir | Out-Null

# --------------------------------------------------
# Check MySQL / mysqldump
# --------------------------------------------------

if (-not (Test-Path $MysqlExe)) {
    Write-Error "mysql.exe not found at: $MysqlExe"
    exit 1
}

$mysqlBinDir = Split-Path $MysqlExe
$mysqldumpExe = Join-Path $mysqlBinDir "mysqldump.exe"

if (-not (Test-Path $mysqldumpExe)) {
    Write-Error "mysqldump.exe not found at: $mysqldumpExe"
    exit 1
}

Write-Host ""
Write-Host "========================================"
Write-Host " ESSCAN DATABASE BACKUP"
Write-Host "========================================"
Write-Host "Database: $DbName"
Write-Host "Timestamp: $timestamp"
Write-Host ""

# --------------------------------------------------
# Database Backup
# --------------------------------------------------

$dbBackupFile = Join-Path $dbBackupDir "esscan_db_$timestamp.sql"

Write-Host "Backing up database..."

if ([string]::IsNullOrWhiteSpace($DbPassword)) {
    & $mysqldumpExe -u $DbUser $DbName |
        Out-File -Encoding utf8 $dbBackupFile
}
else {
    & $mysqldumpExe -u $DbUser "-p$DbPassword" $DbName |
        Out-File -Encoding utf8 $dbBackupFile
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Database backup failed. Check that MySQL is running and credentials are correct."
    exit 1
}

if (-not (Test-Path $dbBackupFile)) {
    Write-Error "Database backup file was not created."
    exit 1
}

$dbSize = (Get-Item $dbBackupFile).Length

if ($dbSize -eq 0) {
    Write-Error "Database backup produced an empty file."
    exit 1
}

$dbSizeMB = [math]::Round($dbSize / 1MB, 2)

Write-Host "Database backup OK: $dbSizeMB MB"

# --------------------------------------------------
# Compress Database Backup
# --------------------------------------------------

$dbZipFile = "$dbBackupFile.zip"

Write-Host "Compressing database backup..."

Compress-Archive `
    -Path $dbBackupFile `
    -DestinationPath $dbZipFile `
    -Force

Remove-Item $dbBackupFile -Force

Write-Host "Database archive created: $dbZipFile"

# --------------------------------------------------
# Uploads Backup
# --------------------------------------------------

$uploadsSource = ".\uploads\student_submissions"

if (Test-Path $uploadsSource) {

    $uploadsBackupFile = Join-Path `
        $uploadsBackupDir `
        "esscan_uploads_$timestamp.zip"

    Write-Host ""
    Write-Host "Backing up student submissions..."

    Compress-Archive `
        -Path $uploadsSource `
        -DestinationPath $uploadsBackupFile `
        -Force

    $uploadsSize = (Get-Item $uploadsBackupFile).Length
    $uploadsSizeMB = [math]::Round($uploadsSize / 1MB, 2)

    Write-Host "Uploads backup OK: $uploadsSizeMB MB"
    Write-Host "Uploads archive: $uploadsBackupFile"
}
else {
    Write-Warning "No uploads folder found at $uploadsSource"
    Write-Warning "Skipping uploads backup."
}

# --------------------------------------------------
# Retention
# --------------------------------------------------

Write-Host ""
Write-Host "Cleaning backups older than $RetentionDays days..."

$cutoff = (Get-Date).AddDays(-$RetentionDays)

$backupFiles = Get-ChildItem `
    -Path $dbBackupDir, $uploadsBackupDir `
    -Filter "*.zip" `
    -ErrorAction SilentlyContinue

foreach ($backupFile in $backupFiles) {

    if ($backupFile.LastWriteTime -lt $cutoff) {

        Write-Host "Deleting old backup: $($backupFile.Name)"

        Remove-Item `
            $backupFile.FullName `
            -Force
    }
}

# --------------------------------------------------
# Complete
# --------------------------------------------------

Write-Host ""
Write-Host "========================================"
Write-Host " BACKUP COMPLETE"
Write-Host "========================================"
Write-Host "Completed: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")"
Write-Host ""