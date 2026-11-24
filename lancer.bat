@echo off
REM Lance l'interface CloudPilot sous Windows (après : pip install -r requirements.txt)
chcp 65001 >nul
if exist tools\opa.exe set OPA_BIN=%~dp0tools\opa.exe
python -m streamlit run app.py
