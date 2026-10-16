@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 "%~dp0avvia_sorgenti.py"
if errorlevel 1 pause
exit /b
:python_fallback
where python >nul 2>nul
if errorlevel 1 goto missing
python "%~dp0avvia_sorgenti.py"
if errorlevel 1 pause
exit /b
:missing
echo Installa Python 3.12, 3.13 o 3.14 a 64 bit con Tcl/Tk.
echo Vedi LEGGIMI_PRIMA.md per le istruzioni.
pause
