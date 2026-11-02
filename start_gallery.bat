@echo off
rem Reference Gallery standalone server (no ComfyUI needed).
rem Keep this file pure ASCII: cmd breaks non-ASCII batch files.
cd /d %~dp0
where python >nul 2>nul
if %errorlevel%==0 (
  python server.py %*
  goto :end
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py %*
  goto :end
)
echo [!] Python not found in PATH.
echo     Install Python 3.10+, or run ComfyUI's bundled python directly:
echo     "..\..\python.exe" server.py
pause
:end
