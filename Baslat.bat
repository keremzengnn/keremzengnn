@echo off
REM PCS 7 Upgrade Analyzer - pencereyi acar. Python 3.11+ gerekir (ek paket gerekmez).
cd /d "%~dp0"
where py >nul 2>nul && (start "" pyw -3 -m pcs7_analyzer & exit /b)
where pythonw >nul 2>nul && (start "" pythonw -m pcs7_analyzer & exit /b)
echo Python bulunamadi. https://www.python.org adresinden Python 3.11+ kurun veya PCS7Analyzer.exe kullanin.
pause
