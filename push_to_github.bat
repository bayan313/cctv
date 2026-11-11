@echo off
cd /d "%~dp0"
echo ========================================================
echo   PUSH CODE TO GITHUB (https://github.com/bayan313/cctv)
echo ========================================================
echo.
git add .
git commit -m "Update lab study monitor"
echo Pushing to main branch...
git push -u origin main --force
echo.
pause
