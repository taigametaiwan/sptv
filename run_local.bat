@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || exit /b 1
)
call ".venv\Scripts\activate.bat" || exit /b 1
python -m pip install -r requirements.txt || exit /b 1
python -m unittest discover -s tests -v || exit /b 1
python sptv_api.py --output sptv.m3u --debug debug\sptv_debug.json || exit /b 1
python audit_m3u.py sptv.m3u --strict || exit /b 1
echo.
echo HOAN TAT: %CD%\sptv.m3u
pause
