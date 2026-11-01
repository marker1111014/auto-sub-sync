@echo off
cd /d "%~dp0"

set "PY_EXE=C:\Users\Mark\miniconda3\pythonw.exe"
if not exist "%PY_EXE%" set "PY_EXE=pythonw.exe"

start "" "%PY_EXE%" "%~dp0gui_app.py" %*
exit
