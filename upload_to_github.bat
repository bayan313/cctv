@echo off
title Push Lab Monitor to GitHub
cd /d "%~dp0"
echo ========================================================
echo   PUSHING TO GITHUB (https://github.com/bayan313/cctv)
echo ========================================================
echo.
git add .
git commit -m "Update CCTV Lab Study Monitor with Vercel support"
echo.
echo Now pushing to main branch...
echo (If a browser window opens, please click Authorize to login to GitHub)
echo.
git push -u origin main --force
echo.
echo ========================================================
echo   Finished! Check: https://github.com/bayan313/cctv
echo ========================================================
pause
