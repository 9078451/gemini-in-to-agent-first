@echo off
cd /d "%~dp0"
start "Agent First" .venv\Scripts\python.exe -m agent_first
start "" .venv\Scripts\pythonw.exe -m gui
