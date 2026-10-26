# License Server (SIS DG)

API + painel web para ativar/suspender clínicas. Ativação **manual** (Pix → você marca no admin).

## Subir local

```powershell
cd license-server
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# edite LICENSE_ADMIN_PASSWORD e LICENSE_SIGNING_SECRET

# Carregar .env (PowerShell simples) ou exporte as variáveis:
$env:LICENSE_ADMIN_PASSWORD = "troque-esta-senha"
$env:LICENSE_SIGNING_SECRET = "mesmo-valor-do-LICENSE_VERIFY_KEY-no-app"
$env:LICENSE_PUBLIC_URL = "http://127.0.0.1:8090"

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

- Painel: http://127.0.0.1:8090/admin (usuário `admin` + senha do env)
- Health: http://127.0.0.1:8090/health
- Check (app): `POST /v1/license/check`
- `LICENSE_PUBLIC_URL`: aparece no admin com botão Copiar → vai em `licenca.server_url` do config da clínica

## Produção

1. Hospede com HTTPS (VPS, Railway, Fly, etc.).
2. Defina `LICENSE_ADMIN_PASSWORD` forte.
3. Defina `LICENSE_SIGNING_SECRET` **igual** à constante `LICENSE_VERIFY_KEY` em `src/apac_bot/license.py` (ou gere um e atualize o app na próxima release).
4. Defina `LICENSE_PUBLIC_URL` com a URL HTTPS pública do servidor.
5. Persistência: volume em `data/licenses.db` (ou `LICENSE_DB_PATH`).

## Fluxo

1. Clínica paga Pix.
2. Em `/admin` → Nova clínica → copie a `license_key`.
3. Envie a URL (`LICENSE_PUBLIC_URL` → `licenca.server_url` no config) + a chave (tela **Ativar licença** do app).
4. Inadimplência → status `suspended` → o app bloqueia no próximo check (ou ao fim do grace offline).
