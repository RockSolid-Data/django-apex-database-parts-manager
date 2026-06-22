@echo off
setlocal

REM Build the Apex Database media pack (dist\ApexDatabase_Media.zip).
REM
REM Default: walks media\ as-is and zips it.
REM
REM Optional pre-conversion (for the Qt / ChoreBoy edition that can't
REM render JPEGs): pass --preconvert siblings (safe; Option A, keeps the
REM .jpg/.jpeg next to a new .png) or --preconvert replace (Option B;
REM smaller zip but requires a Django consumer audit -- see
REM .cursor\rules\media-pack.mdc). Any extra args are forwarded to
REM build_media_pack.py, which also honours the MEDIA_PRECONVERT env var.
REM
REM Examples:
REM   build_media_pack.bat
REM   build_media_pack.bat --preconvert siblings
REM   set MEDIA_PRECONVERT=siblings & build_media_pack.bat

set PYTHON=venv\Scripts\python
set APP_NAME=ApexDatabase

echo.
echo ============================================
echo   %APP_NAME% - Build Media Pack
echo ============================================
echo.
echo This may take several minutes for large media libraries.
echo.

%PYTHON% build_media_pack.py %*
if errorlevel 1 (
    echo [ERROR] Media pack build failed!
    exit /b 1
)

echo.
echo [DONE] Media pack ready in dist\
exit /b 0
