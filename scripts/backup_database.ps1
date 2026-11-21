# =====================================================================
# سكربت النسخ الاحتياطي اليومي الآلي لقاعدة بيانات المنظومة
# =====================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$ProjectDir\manage.py")) {
    $ProjectDir = (Get-Location).Path
}

$BackupDir = "$ProjectDir\backups"
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

$LogsDir = "$ProjectDir\logs"
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir | Out-Null
}

$LogFile = "$LogsDir\backup.log"
$DateStr = Get-Date -Format "yyyy-MM-dd_HH-mm"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# قراءة إعدادات قاعدة البيانات من .env
$EnvPath = "$ProjectDir\.env"
$DbName = "academy_db"
$DbUser = "postgres"
$DbPass = "Game3d"
$DbHost = "localhost"
$DbPort = "5432"

if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $parts = $line.Split('=', 2)
            $key = $parts[0].Trim()
            $val = $parts[1].Trim()
            if ($key -eq 'DB_NAME') { $DbName = $val }
            if ($key -eq 'DB_USER') { $DbUser = $val }
            if ($key -eq 'DB_PASSWORD') { $DbPass = $val }
            if ($key -eq 'DB_HOST') { $DbHost = $val }
            if ($key -eq 'DB_PORT') { $DbPort = $val }
        }
    }
}

$BackupFile = "$BackupDir\${DbName}_${DateStr}.dump"
$JsonBackupFile = "$BackupDir\${DbName}_${DateStr}.json"

$env:PGPASSWORD = $DbPass

# محاولة النسخ الاحتياطي عبر pg_dump
$PgDumpPath = "pg_dump"
$PgDumpSuccess = $false

if (Get-Command pg_dump -ErrorAction SilentlyContinue) {
    & pg_dump -h $DbHost -p $DbPort -U $DbUser -F c -b -v -f "$BackupFile" $DbName 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $BackupFile)) {
        $PgDumpSuccess = $true
        "[$Timestamp] [SUCCESS] تم إنشاء نسخة احتياطية بنجاح عبر pg_dump: $BackupFile" | Out-File -Append -FilePath $LogFile -Encoding UTF8
    }
}

# إذا لم تكن أداة pg_dump في PATH، استخدام dumpdata كبديل آمن وموثوق
if (-not $PgDumpSuccess) {
    $VenvPython = "$ProjectDir\venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        & $VenvPython "$ProjectDir\manage.py" dumpdata --exclude auth.permission --exclude contenttypes --indent 2 -o "$JsonBackupFile" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0 -and (Test-Path $JsonBackupFile)) {
            "[$Timestamp] [SUCCESS] تم إنشاء نسخة احتياطية بنجاح عبر dumpdata: $JsonBackupFile" | Out-File -Append -FilePath $LogFile -Encoding UTF8
        } else {
            "[$Timestamp] [ERROR] فشل إنشاء النسخة الاحتياطية." | Out-File -Append -FilePath $LogFile -Encoding UTF8
        }
    }
}

# حذف النسخ الاحتياطية الأقدم من 30 يوماً لتوفير مساحة التخزين
$RetentionDays = 30
Get-ChildItem -Path $BackupDir -File | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } | ForEach-Object {
    Remove-Item $_.FullName -Force
    "[$Timestamp] [CLEANUP] تم حذف النسخة القديمة لتجاوزها 30 يوماً: $($_.Name)" | Out-File -Append -FilePath $LogFile -Encoding UTF8
}
