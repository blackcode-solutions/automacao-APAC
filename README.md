# SIS DG — Geração de arquivo SET/OUT (Windows)

Aplicação local para apoiar o faturamento APAC: lê planilhas Excel, consulta a origem (**mock**, **BIODATA** ou **Eyecare**) e gera arquivos **`.SET` / `.OUT`** no layout INTERNO para importação no fluxo da clínica.

**Sem servidor web obrigatório.** Interface desktop (SIS DG) + CLI no Windows.

## Requisitos

- Windows 10/11
- Python 3.10+ (desenvolvimento) ou instalador `SIS-DG-APAC-Setup.exe`
- Acesso ao BIODATA web ou API (quando `sistema_origem=biodata`)
- Planilha de cadastro de pacientes + Eyecare BI (quando `sistema_origem=eyecare`, clínica `IMO`)

## 1. Instalação (PowerShell)

```powershell
cd "C:\Users\diego\OneDrive\Documentos\Projetos\Automação DG\automacao-APAC"

py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .

# Navegador do Playwright (só necessário para BIODATA modo browser)
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 2. Configuração

```powershell
Copy-Item config.example.json config.json
.\.venv\Scripts\python.exe -m apac_bot make-example
```

São **duas planilhas** (a UI permite escolher os caminhos):

1. **Lançamentos** — `planilha.caminho`
2. **Prontuários** — `planilha_prontuarios.caminho` (obrigatória com `sistema_origem=biodata` na modalidade padrão; **não usada** no Eyecare/IMO)
3. **Pacientes Eyecare** — `planilha_pacientes.caminho` (obrigatória com `sistema_origem=eyecare`; na UI, anexo logo após o ID da clínica `IMO`)

Com **Eyecare/IMO**, inclua na planilha de pacientes uma coluna **nome da mãe** (mapeável em `planilha_pacientes.colunas.NOME_MAE`). Não há login no portal Eyecare.

Credenciais BIODATA em `secrets.local.json` (não versionar):

```powershell
Copy-Item secrets.example.json secrets.local.json
```

| Campo | Uso |
|--------|-----|
| `clinica_id` | Identificador da clínica no progresso |
| `sistema_origem` | `mock`, `biodata` ou `eyecare` (alias legado `icare`) |
| `planilha_pacientes.*` | Cadastro local de pacientes (só Eyecare / clínica IMO), incl. nome da mãe |
| `biodata.modo` | `api` (recomendado) ou `browser` |
| `apac.modalidade` | `padrao` ou `glaucoma` (validade/CID/regras do SET) |
| `apac.paciente_inicio` | Nome do 1º paciente do lote (vazio = todos) |
| `export_set.*` | Pasta staging, órgão, limite de pacientes |
| `dados_fixos.*` | CNES, médicos, classificação padrão, etc. |

Chaves legadas no JSON (`apac.passos`, `caminho_exe`, …) são **ignoradas**.

## 3. Comandos

```powershell
# Interface desktop
.\.venv\Scripts\python.exe -m apac_bot ui --config config.json

# Validar configuração + planilha
.\.venv\Scripts\python.exe -m apac_bot validate --config config.json

# Gerar lote (staging data/export_set/lote_atual.SET)
.\.venv\Scripts\python.exe -m apac_bot gerar-set --config config.json --limit 5

# Reprocessar só erros / revisão
.\.venv\Scripts\python.exe -m apac_bot gerar-set --config config.json --somente-falhas

# Abrir BIODATA no Chromium (mapeamento / modo browser)
.\.venv\Scripts\python.exe -m apac_bot open-biodata --config config.json

# Testes
.\.venv\Scripts\python.exe -m pytest -q
```

## 4. Fluxo na UI (produção)

1. **Iniciar** — `gerar-set`: BIODATA + montagem do SET parcial (`lote_atual.SET`).
2. Corrija falhas no BIODATA ou planilha.
3. **Enviar pacientes pendentes** — `--somente-falhas`, mescla no mesmo SET.
4. **Exportar arquivo** — cópia final com nome por competência (`APOFTA10.OUT`, etc.).
5. **Relatório do lote** — PDF operacional.

Competência do lote: **mês civil anterior** à data de geração.

Ao abrir a UI ou trocar a planilha, o painel pode **resetar** progresso local da sessão; para continuar sem fechar o app, use **Enviar pacientes pendentes**.

## 5. BIODATA via API (recomendado)

1. `sistema_origem=biodata`, `biodata.modo=api`, `biodata.api.base_url` e `id_sac`
2. `secrets.local.json` com usuário e senha (SHA-512 na autenticação)
3. `gerar-set` ou **Iniciar** na UI

## 5.1 ICARE (clínica IMO)

1. Na UI, escolha **Sistema: ICARE** ou **ID da clínica: IMO** (os dois ficam sincronizados).
2. Anexe a **planilha lista APAC IMO** (`planilha.caminho`) com colunas ORD, PRONT, DATA, PACIENTES, CNS, PROCEDIMENTO, TIPO, MÉDICO, CÓDIGO, NUMERAÇÃO DE APACS (obrigatórios: PRONT, PACIENTES, CÓDIGO, NUMERAÇÃO DE APACS).
3. Anexe a **planilha de pacientes** (`planilha_pacientes`) com prontuários, paciente, cpf, data nascimento, genero, cep, endereço, etc. O cruzamento é **sempre pelo PRONT**; se o prontuário não existir no cadastro ou o nome divergir, o paciente não entra no SET e o motivo aparece no painel.
4. Campos obrigatórios para o SET (CPF ou CNS, nome da mãe, nascimento, sexo) seguem as mesmas regras: faltas aparecem no painel do lote (`faltam: …`). Se **genero/sexo** vier vazio na planilha de pacientes, o sistema tenta inferir **M/F** pelo primeiro nome (heurística); nomes ambíguos continuam pendentes até preencher a coluna.

## 6. Licença

Ver [`license-server/README.md`](license-server/README.md) e bloco `licenca` no `config.json`.

## 7. Build Windows

```powershell
.\scripts\build_exe.ps1
```

Saída: `dist\SIS-DG-APAC-Setup.exe` e pasta `dist\SIS-DG-APAC\`.

O Chromium do Playwright **não** entra no pacote — instale uma vez no PC (`playwright install chromium`).

## 8. Estrutura

```
src/apac_bot/
  set_pipeline.py, set_layout.py, set_parse.py
  pipeline.py          # resolver paciente, validação planilha
  ui/                  # SIS DG (CustomTkinter)
  connectors/          # mock + biodata API/browser
license-server/
packaging/
tests/
```

## 9. Privacidade e Git

Não versionar: `config.json`, planilhas reais, `progress.db`, `secrets.local.json`, `license_cache.json`, `browser_profile/`.

Logs usam identidade interna (hash curto), sem CPF/CNS/nome completo.
