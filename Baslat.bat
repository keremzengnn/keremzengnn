@echo off
REM PCS 7 Upgrade Analyzer - pencereyi acar. Python 3.11+ gerekir (ek paket gerekmez).
REM Ekip ayarlari: bu klasordeki pcs7_analyzer_ayarlar.json (varsa) once okunur.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" && (start "" pyw -3 -m pcs7_analyzer & exit /b))
where pythonw >nul 2>nul && (python -c "import sys; sys.exit(sys.version_info < (3, 11))" && (start "" pythonw -m pcs7_analyzer & exit /b))
echo Python 3.11+ bulunamadi. https://www.python.org adresinden Python 3.11+ kurun
echo (kurulumda "tcl/tk and IDLE" secili olsun) veya PCS7Analyzer.exe kullanin.
pause
