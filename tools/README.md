Placez ici le binaire OPA (il est ignoré par Git) :

Windows :  curl -L -o tools\opa.exe https://openpolicyagent.org/downloads/v0.68.0/opa_windows_amd64.exe
Linux   :  curl -L -o tools/opa https://openpolicyagent.org/downloads/v0.68.0/opa_linux_amd64_static && chmod +x tools/opa

CloudPilot le détecte tout seul. Sans OPA, un moteur de secours applique les mêmes règles
et l'interface affiche « règles de secours (OPA absent) ».
