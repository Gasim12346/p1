@echo off
chcp 65001 >nul
title تشغيل خادم منظومة المعهد للشبكة المحلية (Waitress WSGI Production)
cd /d "%~dp0"

echo ================================================================
echo       خادم منظومة المعهد قيد التشغيل المستمر (Waitress)          
echo ================================================================
echo.

if not exist "venv\Scripts\waitress-serve.exe" (
    echo [ERROR] لم يتم العثور على حزم خادم الإنتاج!
    echo يرجى تشغيل ملف setup_server.bat أولاً لتثبيت المتطلبات.
    pause
    exit /b
)

echo المنظومة متاحة الآن لجميع أجهزة الشبكة على المنفذ 8000
echo لا تغلق هذه النافذة طالما أن المنظومة قيد الاستخدام.
echo للوصول من المتصفح: http://localhost:8000
echo.
echo ================================================================

venv\Scripts\waitress-serve.exe --listen=0.0.0.0:8000 --threads=8 config.wsgi:application
pause
