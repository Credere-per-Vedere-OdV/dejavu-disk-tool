@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 "%~dp0build_windows.py"
pause
exit /b
:python_fallback
python "%~dp0build_windows.py"
pause
