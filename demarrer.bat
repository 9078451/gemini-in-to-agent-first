@echo off
cd /d "%~dp0"
start "Agent First" .venv\Scripts\python.exe -m agent_first
