@echo off
setlocal

set PYTHON=venv\Scripts\python
set APP_NAME=ApexDatabase

echo.
echo ============================================
echo   %APP_NAME% - Build Media Pack
echo ============================================
echo.
echo This may take several minutes for large media libraries.
echo.

%PYTHON% build_media_pack.py
if errorlevel 1 (
    echo [ERROR] Media pack build failed!
    exit /b 1
)

echo.
echo [DONE] Media pack ready in dist\
exit /b 0
