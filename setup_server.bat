@echo off
chcp 65001 >nul
title إعداد وتثبيت منظومة المعهد على السيرفر
cd /d "%~dp0"

echo ================================================================
echo       بدء معالج التثبيت الذاتي لمنظومة المعهد على السيرفر        
echo ================================================================
echo.

:: التحقق من صلاحيات المدير (Administrator Elevation)
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] تم تشغيل المعالج بصلاحيات مسؤول كاملة.
) else (
    echo [INFO] جاري طلب صلاحيات المسؤول لفتح المنفذ في جدار الحماية...
    powershell -Command "Start-Process '%~0' -Verb RunAs"
    exit /b
)

:: تشغيل سكربت باورشيل للتثبيت الآلي مع تجاوز قيود السياسة
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_server.ps1"

echo.
echo اضغط على أي مفتاح لبدء تشغيل السيرفر مباشرة...
pause >nul

start "" "%~dp0start_production_server.bat"
exit /b
