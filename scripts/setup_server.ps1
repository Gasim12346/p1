# =====================================================================
# سكربت الإعداد والتثبيت الآلي الشامل لمنظومة المعهد على السيرفر
# =====================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "إعداد وتثبيت منظومة المعهد على السيرفر"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "       بدء الإعداد والتثبيت الذاتي لمنظومة المعهد على السيرفر   " -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Cyan

# 1. التحقق من مسار المشروع
$ProjectDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$ProjectDir\manage.py")) {
    $ProjectDir = (Get-Location).Path
}
Set-Location $ProjectDir
Write-Host "[1/7] مسار المنظومة: $ProjectDir" -ForegroundColor Green

# 2. التحقق من تثبيت بايثون (Python)
Write-Host "[2/7] التحقق من بيئة بايثون (Python)..." -ForegroundColor Yellow
$PythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = "py"
}

if (-not $PythonCmd) {
    Write-Host "خطأ فادح: لم يتم العثور على بايثون (Python) مثبت في مسار النظام!" -ForegroundColor Red
    Write-Host "يرجى تثبيت بايثون من موقع python.org وتفعيل خيار 'Add Python to PATH'." -ForegroundColor Yellow
    Pause
    exit 1
}

$PyVer = & $PythonCmd --version
Write-Host "تم العثور على بايثون: $PyVer" -ForegroundColor Green

# 3. إعداد البيئة الافتراضية venv
Write-Host "[3/7] تجهيز البيئة الافتراضية (venv)..." -ForegroundColor Yellow
if (-not (Test-Path "$ProjectDir\venv\Scripts\python.exe")) {
    Write-Host "إنشاء بيئة افتراضية جديدة..." -ForegroundColor Cyan
    & $PythonCmd -m venv "$ProjectDir\venv"
}

$VenvPython = "$ProjectDir\venv\Scripts\python.exe"
$VenvPip = "$ProjectDir\venv\Scripts\pip.exe"

Write-Host "تحديث الحزم وتثبيت متطلبات النظام..." -ForegroundColor Cyan
& $VenvPip install --upgrade pip --quiet
& $VenvPip install -r "$ProjectDir\requirements.txt" --quiet
Write-Host "تم تثبيت كافة المكتبات البرمجية وخادم الإنتاج بنجاح." -ForegroundColor Green

# 4. إعداد ملف البيئة .env وقاعدة البيانات PostgreSQL
Write-Host "[4/7] التحقق من ملف الإعدادات وقاعدة البيانات..." -ForegroundColor Yellow
$EnvPath = "$ProjectDir\.env"

if (-not (Test-Path $EnvPath)) {
    Write-Host "إنشاء ملف الإعدادات .env تلقائياً..." -ForegroundColor Cyan
    $DefaultEnv = @"
# إعدادات قاعدة البيانات PostgreSQL
DB_TYPE=postgresql
DB_NAME=academy_db
DB_USER=postgres
DB_PASSWORD=Game3d
DB_HOST=localhost
DB_PORT=5432

# السماح بالوصول من كافة أجهزة الشبكة
ALLOWED_HOSTS=*
DEBUG=True
"@
    Set-Content -Path $EnvPath -Value $DefaultEnv -Encoding UTF8
    Write-Host "تم إنشاء ملف .env بإعدادات PostgreSQL الافتراضية." -ForegroundColor Green
}

# التحقق من إنشاء قاعدة البيانات في PostgreSQL
& $VenvPython "$ProjectDir\scripts\init_db.py"

# 5. ترحيل جداول النظام وتجميع الملفات الثابتة
Write-Host "[5/7] بناء جداول وقواعد المنظومة (Migrations)..." -ForegroundColor Yellow
& $VenvPython "$ProjectDir\manage.py" migrate --noinput
& $VenvPython "$ProjectDir\manage.py" collectstatic --noinput

# التحقق من وجود حساب مدير، وإنشاء حساب افتراضي إن لم يوجد
& $VenvPython "$ProjectDir\scripts\init_admin.py"

# 6. فتح منفذ المنظومة في جدار الحماية (Firewall)
Write-Host "[6/7] إعداد جدار حماية ويندوز للمنفذ 8000..." -ForegroundColor Yellow
try {
    $RuleExists = Get-NetFirewallRule -DisplayName "Academy Management System Port 8000" -ErrorAction SilentlyContinue
    if (-not $RuleExists) {
        New-NetFirewallRule -DisplayName "Academy Management System Port 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow | Out-Null
        Write-Host "تم فتح المنفذ 8000 في جدار الحماية بنجاح." -ForegroundColor Green
    } else {
        Write-Host "قاعدة جدار الحماية للمنفذ 8000 مفعلة مسبقاً." -ForegroundColor Green
    }
} catch {
    Write-Host "تنبيه: لم نتمكن من تعديل جدار الحماية تلقائياً (قد يتطلب تشغيل كمسؤول)." -ForegroundColor Yellow
}

# 7. استخراج عنوان IP السيرفر وعرض رابط الوصول
Write-Host "[7/7] جاري استخراج عناوين الشبكة المحلية للسيرفر..." -ForegroundColor Yellow
$LocalIps = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback|vEthernet' -and $_.IPAddress -notlike '169.254*' }).IPAddress

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "           تم اكتمال تثبيت وتجهيز المنظومة بنجاح!               " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "بيانات الدخول الافتراضية لمدير المنظومة:" -ForegroundColor Yellow
Write-Host "اسم المستخدم: admin" -ForegroundColor White
Write-Host "كلمة المرور : Admin@123456" -ForegroundColor White
Write-Host "----------------------------------------------------------------" -ForegroundColor Gray
Write-Host "يمكن للموظفين الدخول للمنظومة من أي جهاز عبر الروابط التالية:" -ForegroundColor Yellow
foreach ($ip in $LocalIps) {
    Write-Host "  -> http://${ip}:8000" -ForegroundColor Cyan
}
Write-Host "  -> http://localhost:8000 (من هذا السيرفر محلياً)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# إنشاء اختصار تشغيل سريع على سطح المكتب إن رغب المستخدم
Write-Host "لبدء تشغيل السيرفر الآن، يمكنك تشغيل الملف: start_production_server.bat" -ForegroundColor Green
Write-Host ""
