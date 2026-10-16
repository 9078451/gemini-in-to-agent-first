@echo off
cd /d "%~dp0"
start "Agent First" /min .venv\Scripts\python.exe -m agent_first --ouvrir
