@echo off
REM AI Engineering Laboratory — start the backend on Windows.
REM Before first run, set the Turso variables once (see docs/TUNNEL_SETUP.md step 3):
REM   setx TURSO_DATABASE_URL "libsql://aielab-qogtrix.aws-us-west-2.turso.io"
REM   setx TURSO_AUTH_TOKEN "paste-your-token-here"
REM Then open a NEW terminal and double-click this file.
if "%TURSO_AUTH_TOKEN%"=="" (
  echo Turso token is not set. See docs/TUNNEL_SETUP.md step 3, then open a NEW terminal.
  pause
  exit /b 1
)
if "%TURSO_DATABASE_URL%"=="" set TURSO_DATABASE_URL=libsql://aielab-qogtrix.aws-us-west-2.turso.io
cd /d %~dp0backend
python app.py
pause
