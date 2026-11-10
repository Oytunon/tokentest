@echo off
cd /d "%~dp0"
set "PYW=C:\Users\alper\AppData\Local\Programs\Python\Python312\pythonw.exe"
if exist "%PYW%" (
    start "" "%PYW%" "crm_yetki_kontrolu.py"
) else (
    start "" pythonw "crm_yetki_kontrolu.py"
)
