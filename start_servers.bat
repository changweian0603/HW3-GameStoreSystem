@echo off
echo Starting HW3 Servers...

start "DB Server" cmd /k python server/db_server.py
timeout /t 1
start "Lobby Server" cmd /k python server/lobby_server.py
start "Dev Server" cmd /k python server/dev_server.py

echo Servers Started.
echo Press any key to stop all python processes (Optional cleanup)...
pause
taskkill /IM python.exe /F
