@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m pylibstudy.launcher %*
) else (
  py -3 -m pylibstudy.launcher %*
)
set "taskExit=%errorlevel%"
if not "%taskExit%"=="0" (
  echo.
  echo PyLiBStudy could not start. See the error above.
  echo Check Python, port 8765, and README.md.
  pause
)
exit /b %taskExit%
