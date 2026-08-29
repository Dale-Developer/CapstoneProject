# ESSCAN backup script.
#
# Backs up the MySQL database (via mysqldump) and the uploads folder
# (scanned answer sheets) to timestamped files under .\backups\, and
# deletes anything older than $RetentionDays so this can run unattended
# via Task Scheduler without filling up the disk.
#
# Usage (from the backend folder, in an activated venv is not required):
#   .\backup_database.ps1
#
# First-time setup: edit $MysqlExe and $DbPassword below to match your
# environment, or pass them as parameters:
#   .\backup_database.ps1 -MysqlExe "C:\xampp\mysql\bin\mysql.exe" -DbPassword "yourpassword"

param(
    [string]$MysqlExe = "C:\xampp\mysql\bin\mysql.exe",
    [string]$DbUser = "root",
    [string]$DbPassword = "",
    [string]$DbName = "automate_assessment_application",
    [string]$BackupRoot = ".\backups",
    [int]$RetentionDays = 14
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$dbBackupDir = Join-Path $BackupRoot "database"
$uploadsBackupDir = Join-Path $BackupRoot "uploads"

New-Item -ItemType Directory -Force -Path $dbBackupDir | Out-Null
New-Item -ItemType Directory -Force -Path $uploadsBackupDir | Out-Null

# mysqldump.exe lives next to mysql.exe.
$mysqldumpExe = Join-Path (Split-Path $MysqlExe) "mysqldump.exe"
if (-not (Test-Path $mysqldumpExe)) {
    Write-Error "mysqldump.exe not found at $mysqldumpExe. Check -MysqlExe points at your MySQL bin folder."
    exit 1
}

# ---- Database dump ----
$dbBackupFile = Join-Path $dbBackupDir "esscan_db_$timestamp.sql"
Write-Host "Backing up database '$DbName' to $dbBackupFile ..."

if ($DbPassword -eq "") {
    & $mysqldumpExe -u $DbUser $DbName | Out-File -Encoding utf8 $dbBackupFile
} else {
    & $mysqldumpExe -u $DbUser "-p$DbPassword" $DbName | Out-File -Encoding utf8 $dbBackupFile
}

if ($LASTEXITCODE -ne 0 -or (Get-Item $dbBackupFile).Length -eq 0) {
    Write-Error "Database backup failed or produced an empty file. Check credentials and that MySQL is running."
    exit 1
}
Write-Host "Database backup OK ($([math]::Round((Get-Item $dbBackupFile).Length / 1MB, 2)) MB)."

# Compress it — SQL dumps compress very well (usually 5-10x smaller).
Compress-Archive -Path $dbBackupFile -DestinationPath "$dbBackupFile.zip" -Force
Remove-Item $dbBackupFile
Write-Host "Compressed to $dbBackupFile.zip"

# ---- Uploads folder (scanned answer sheets) ----
$uploadsSource = ".\uploads\student_submissions"
if (Test-Path $uploadsSource) {
    $uploadsBackupFile = Join-Path $uploadsBackupDir "esscan_uploads_$timestamp.zip"
    Write-Host "Backing up uploads folder to $uploadsBackupFile ..."
    Compress-Archive -Path $uploadsSource -DestinationPath $uploadsBackupFile -Force
    Write-Host "Uploads backup OK ($([math]::Round((Get-Item $uploadsBackupFile).Length / 1MB, 2)) MB)."
} else {
    Write-Warning "No uploads folder found at $uploadsSource — skipping (nothing to back up yet)."
}

# ---- Retention: delete backups older than $RetentionDays ----
$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -Path $dbBackupDir, $uploadsBackupDir -Filter "*.zip" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        Write-Host "Deleting old backup: $($_.Name)"
        Remove-Item $_.FullName -Force
    }

Write-Host "`nBackup complete. $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
