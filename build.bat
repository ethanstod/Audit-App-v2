@echo off
echo ============================================
echo  WH-347 Audit Engine -- Windows Build
echo ============================================
echo.

:: Install / upgrade build tools
pip install --upgrade pyinstaller waitress pystray pillow

echo.
echo Building exe...
pyinstaller wh347_audit.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo BUILD FAILED. Check the output above for missing imports.
    pause
    exit /b 1
)

echo.
echo Zipping output...
powershell -Command "Compress-Archive -Force -Path 'dist\WH347 Audit Engine\*' -DestinationPath 'dist\WH347-Audit-Engine-Windows.zip'"

echo.
echo ============================================
echo  Done!
echo  Installer zip: dist\WH347-Audit-Engine-Windows.zip
echo  Run directly:  dist\WH347 Audit Engine\WH347 Audit Engine.exe
echo ============================================
pause
