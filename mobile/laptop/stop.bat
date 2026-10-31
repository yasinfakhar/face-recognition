@echo off
set ADB=adb
where adb >nul 2>nul || set ADB=C:\platform-tools\adb.exe
%ADB% shell am force-stop com.termux
%ADB% shell am force-stop com.pas.webcam.pro
echo Stopped the recognition script and the camera server.
pause
