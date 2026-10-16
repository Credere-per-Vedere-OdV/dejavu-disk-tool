@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 "%~dp0avvia_sorgenti.py" --diagnostics
if errorlevel 1 pause
exit /b
:python_fallback
python "%~dp0avvia_sorgenti.py" --diagnostics
if errorlevel 1 pause
