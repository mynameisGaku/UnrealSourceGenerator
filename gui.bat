@echo off
setlocal DisableDelayedExpansion
set "PYTHONIOENCODING=utf-8"
py -3 "%~dp0internal\launch.py" >nul 2>nul
if not errorlevel 1 exit /b 0
python "%~dp0internal\launch.py" >nul 2>nul
if not errorlevel 1 exit /b 0
python3 "%~dp0internal\launch.py" >nul 2>nul
if not errorlevel 1 exit /b 0
powershell -NoProfile -NonInteractive -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python 3.10+ with tkinter is required. Install Python with tcl/tk and IDLE, then open gui.bat again.', 'UnrealSourceGenerator')" >nul 2>nul
exit /b 1
