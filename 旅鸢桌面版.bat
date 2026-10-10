@echo off
setlocal
set "APP=%~dp0frontend"
set "EXE=%APP%\node_modules\electron\dist\electron.exe"
if exist "%EXE%" goto run
echo [TripCraft] Electron not found. Installing frontend dependencies...
pushd "%APP%"
call npm install --registry=https://registry.npmmirror.com
call node node_modules\electron\install.js
popd
if not exist "%EXE%" goto fail
:run
start "" "%EXE%" "%APP%"
exit /b 0
:fail
echo [TripCraft] Electron binary still missing.
echo Please run:  cd frontend  ^&^&  npx electron .
pause
exit /b 1
