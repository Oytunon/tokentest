@echo off
cd /d "%~dp0"

set "PY=C:\Users\alper\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python bulunamadi. https://www.python.org/downloads/ adresinden kurun.
        pause
        exit /b 1
    )
    set "PY=python"
)

echo Bagimliliklar kuruluyor...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r requirements.txt pyinstaller --quiet
if errorlevel 1 (
    echo Bagimlilik kurulumu basarisiz.
    pause
    exit /b 1
)

echo CrmYetkiKontrolu.exe olusturuluyor...
"%PY%" -m PyInstaller --onefile --windowed --noconfirm --name CrmYetkiKontrolu crm_yetki_kontrolu.py
if errorlevel 1 goto :buildfail

echo.
echo Exe kopyalaniyor ve gecici dosyalar temizleniyor...
copy /y "dist\CrmYetkiKontrolu.exe" "CrmYetkiKontrolu.exe" >nul
rmdir /s /q dist
rmdir /s /q build
rmdir /s /q __pycache__ 2>nul
del /q CrmYetkiKontrolu.spec 2>nul

echo.
echo Bitti. CrmYetkiKontrolu.exe hazir.
pause
exit /b 0

:buildfail
echo.
echo Build basarisiz oldu, yukaridaki hatayi kontrol edin.
pause
exit /b 1
