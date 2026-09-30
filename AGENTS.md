# Local de trabalho

Este diretório, `D:\Codex\APP-ACI`, é a única fonte ativa do aplicativo.
Todas as futuras alterações devem ser feitas aqui. A antiga pasta
`sandbox-app` não deve receber alterações nem ser usada para iniciar a aplicação.

Preserve `.env` e credenciais locais. `run_sandbox.py` inicia testes no sandbox
Cisco; produção deve usar `app.py` pelo serviço existente.

Validação local: `.venv\Scripts\python.exe -B -m unittest discover -s tests -q`.
