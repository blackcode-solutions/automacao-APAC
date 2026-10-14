# Automação APAC (local Windows)

Script em Python para apoiar o lançamento de APACs: lê a planilha, consulta a origem (mock ou BIODATA) e prepara o preenchimento do **APAC Magnético** via teclado.

**Sem interface web, servidor, Docker ou nuvem.** Execução pelo terminal.

> Esta versão está pronta para **simulação (dry-run)** e testes locais.  
> A automação **não está operacional** no BIODATA/APAC reais até o mapeamento das telas ser concluído e testado no Windows da clínica.

## Requisitos

- Windows 10/11
- Python 3.10+
- APAC Magnético (quando for testar `--live`)
- Acesso ao BIODATA web (quando `sistema_origem` for `biodata`)

## 1. Instalação (PowerShell)

```powershell
cd "C:\Users\diego\OneDrive\Documentos\Projetos\Automação DG\automacao-APAC"

# Se `python` não estiver no PATH, use o launcher do Windows:
py -3 -m venv .venv

# Se a ativação do venv for restrita na política de execução, use o Python do venv diretamente:
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .

# Navegador do Playwright (só necessário para BIODATA real)
.\.venv\Scripts\python.exe -m playwright install chromium
```

Opcional — ativar o ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 2. Configuração

```powershell
Copy-Item config.example.json config.json
.\.venv\Scripts\python.exe -m apac_bot make-example
```

A planilha real fica na pasta `data/` (ou em outro caminho do PC). No `config.json`, informe esse caminho em `planilha.caminho`. Não é preciso “anexar” arquivo: a automação lê o `.xlsx` do disco. Se o cabeçalho não estiver na linha 1, use `planilha.linha_cabecalho`.

Com `planilha.apenas_ativos: true` (padrão), o bot processa **só as linhas visíveis** no Excel — ou seja, as que o filtro da planilha deixa ativas. Linhas ocultas pelo AutoFilter são ignoradas. Para ler a planilha inteira, use `"apenas_ativos": false`.

**Não coloque senha no `config.json`.** Credenciais ficam em `secrets.local.json` (arquivo local, fora do Git):

```powershell
Copy-Item secrets.example.json secrets.local.json
# edite usuario e senha nesse arquivo
```

Com `secrets.local.json` preenchido, o login no BIODATA é **automático** (`open-biodata`, `fetch`, `run`). Sem o arquivo, o login continua manual.

Edite `config.json`:

| Campo | Uso |
|--------|-----|
| `clinica_id` | Identificador da clínica no progresso |
| `sistema_origem` | `mock` (padrão) ou `biodata` |
| `planilha.*` | Caminho, aba, `linha_cabecalho`, `apenas_ativos` e mapeamento de colunas |
| `normalizacao` | Hífen→barra na numeração; zeros no código (só se configurado) |
| `dados_fixos` | Fixos por clínica: `cnes_*`, `tipo_apac` (`1` ou `3`; UI futura) |
| `biodata.locators` | Seletores Playwright — `null` bloqueia consulta real |
| `apac.usar_navegacao_inicial` | Menu → 2 Enter até a lista (uma vez por sessão) |
| `apac.usar_conhost` | `true` (padrão) = abre o APAC no console clássico para ler o buffer da tela |
| `apac.reiniciar_se_ja_aberto` | `true` (padrão) = no `open-apac`/`dump-apac-screen`, encerra APAC já aberto e reabre limpo no MENU |
| `apac.confirmar_navegacao_inicial` | `false` = passos mapeados no `open-apac` rodam sem `s`; `true` = pede `s` em cada um. Passos **novos** sempre pedem `s` |
| `apac.velocidade` | `seguro` (padrão no código) ou `rapido` — pausas menores; o gate por rótulo continua. Se falhar timing, volte para `seguro` |
| `apac.intervalo_enter_navegacao_s` | Pausa entre Enters do menu; se omitido, usa 2.0 (`seguro`) ou 0.8 (`rapido`) |
| `apac.paciente_inicio` | Nome do 1º paciente no `open-apac` (NUMERO) |
| `apac.passos` | Teclas por paciente — vazia bloqueia `--live` |
| `apac.caminho_exe` | Caminho do `APAC.exe` (padrão `C:\APAC\APAC.exe`) |
| `apac.timeout_abrir_s` | Segundos para aguardar a janela após iniciar o exe |
| `apac.permitir_salvar` | Deve permanecer `false` até o save estar mapeado |

A automação lê o **buffer do console** (não só clipboard) para saber a tela (MENU, LISTA, IDENTIFICACAO, PROCEDIMENTOS) e o **rótulo do campo** na linha do cursor. Se a tela ou o campo não for o esperado, o bot **para** — não digita nem dá Tab no campo errado. Se falhar o rótulo, rode `dump-apac-screen` nesse campo e ajuste os marcadores em `console_screen.py`.

Não coloque senhas no JSON. O login no BIODATA é manual, em perfil de navegador dedicado (`browser_profile/`).

## 3. Comandos

```powershell
# Validar configuração + planilha
.\.venv\Scripts\python.exe -m apac_bot validate --config config.json

# Abrir BIODATA no Chromium (login manual; ainda sem buscar paciente)
.\.venv\Scripts\python.exe -m apac_bot open-biodata --config config.json

# Abrir o APAC Magnético (inicia C:\APAC\APAC.exe no conhost se necessário)
.\.venv\Scripts\python.exe -m apac_bot open-apac --config config.json

# Ler o buffer da tela do APAC (imprime + salva em capturas/)
.\.venv\Scripts\python.exe -m apac_bot dump-apac-screen --config config.json

# Consultar origem e registrar progresso (exige locators se sistema_origem=biodata)
.\.venv\Scripts\python.exe -m apac_bot fetch --config config.json --limit 5

# Simulação completa (padrão: não digita no APAC)
.\.venv\Scripts\python.exe -m apac_bot run --config config.json --dry-run --limit 1

# Tentativa real (bloqueada até mapear passos/locators)
.\.venv\Scripts\python.exe -m apac_bot run --config config.json --live --limit 1

# Status do progresso
.\.venv\Scripts\python.exe -m apac_bot status --config config.json

# Testes
.\.venv\Scripts\python.exe -m pytest -q
```

Flags úteis: `--config`, `--planilha`, `--limit`, `--dry-run` (padrão em `run`), `--live`.

## 4. Fluxo recomendado

1. Estrutura e instalação  
2. Config + planilha fictícia + `validate`  
3. `sistema_origem=mock` + `run --dry-run`  
4. Progresso / retomada / falhas (já coberto pelos testes)  
5. Mapear BIODATA → preencher locators → `fetch` real  
6. Testar teclas no APAC **sem salvar** (`permitir_salvar=false`)  
7. Um lançamento supervisionado  
8. Lote pequeno  

## 5. Fluxo BIODATA mapeado (Oftalmocentro)

Após o login automático (a rota pós-login depende do usuário: `/home`, `/consultorio/...`, etc.) o bot **não força** `/home`: usa o menu lateral na rota em que caiu.

1. Clica no módulo **Atendimento** do menu lateral  
2. Em **Pesquisar tela...**, digita `cadastro de paciente`  
3. Clica em **Cadastro de Pacientes**  
4. Se aparecer modal **Autenticação**, preenche a senha de `secrets.local.json`  
5. Clica em **Pesquisar** → diálogo **Pesquisar Cliente** → campo **Nome** → **Confirmar**

Credenciais ficam só em `secrets.local.json`. O sistema aceita retorno em `/home*` ou `/consultorio/**`.

Teste supervisionado (abre o navegador):

```powershell
.\.venv\Scripts\python.exe -m apac_bot open-biodata --config config.json
.\.venv\Scripts\python.exe -m apac_bot fetch --config config.json --limit 1
```

Feche outras abas do BIODATA antes de rodar (evita conflito de sessão).

## 5b. Mapear o BIODATA (Playwright) — outras clínicas

Enquanto `biodata.locators` tiver valores `null`, a consulta real é **bloqueada**.

1. Com o venv instalado:

```powershell
.\.venv\Scripts\python.exe -m playwright codegen "URL_DO_BIODATA"
```

2. Faça login manualmente no navegador aberto pelo codegen.  
3. Navegue até a busca de paciente e copie seletores estáveis (role, label, id, etc.).  
4. Preencha em `config.json` as chaves:

- `campo_busca_id`, `campo_busca_nome`, `botao_buscar`
- `lista_resultados`, `resultado_item`
- `campo_cpf`, `campo_cns`, `campo_nome`, `campo_nome_mae`
- `campo_nascimento`, `campo_endereco`, `campo_id_paciente`

5. Alternativa: abra o DevTools (F12) → inspetor → copie seletores CSS/XPath confiáveis.  
6. Use perfil dedicado (`browser_profile/`). Não copie sessão do Chrome pessoal nem salve senhas no projeto.

## 6. Mapear o APAC

No `run --live` / `open-apac`, se o APAC não estiver aberto, o bot inicia `apac.caminho_exe` (padrão `C:\APAC\APAC.exe`) via `start` (Windows Terminal), espera até `timeout_abrir_s` e foca a janela `titulo_janela` (padrão `APAC MAGNETICO`). A detecção exige o processo `APAC.exe`.

**Navegação + formulário (teste `open-apac`)** — passos **já mapeados** rodam **sem `s`** (`confirmar_navegacao_inicial=false`). O bot recupera o foco sozinho. Paciente: `apac.paciente_inicio`. Passos **novos** (ainda não estabilizados) continuam pedindo `s`.

Fluxo automático até o CPF:

1. Enter 1 (A.P.A.C.) → Enter 2 (CADASTRO) → Insert  
2. NUMERO + Enter → CNES sol/exec → validade (mês anterior) → TIPO → Enter nacionalidade  
3. Enter prontuário → `n` em SEM CPF → busca BIODATA (só este paciente) → cola CPF (sem Enter)

Teste:

```powershell
.\.venv\Scripts\python.exe -m apac_bot open-apac --config config.json
```

Requer BIODATA logável. Para rever cada tecla com `s`, use `"confirmar_navegacao_inicial": true`.

**Por paciente** — referência do que vem depois (novos passos pedem `s`):

1. Enter após CPF / demais campos do usuário  
2. Procedimento, auditor, competência, save

Cada passo no JSON pode ter: `id`, `acao`, `teclas`/`tecla`/`texto`/`campo`, `tela_esperada`, `confirmar_operador`, `e_salvamento`.

Exemplo ilustrativo (não use em produção sem testar a máscara real):

```json
"passos": [
  {"id": "foco_janela", "acao": "foco_janela"},
  {"id": "inserir", "acao": "press", "tecla": "insert", "confirmar_operador": true},
  {"id": "numero_apac", "acao": "type", "campo": "numeracao", "tela_esperada": "Identificacao Unidade/APAC"},
  {"id": "cpf", "acao": "type", "campo": "cpf"},
  {"id": "enter_apos_cpf", "acao": "press", "tecla": "enter", "confirmar_operador": true}
]
```

Antes de cada passo o script confere a janela; se a tela não puder ser confirmada automaticamente, pede `s/n` no terminal.  
**Fail-safe do PyAutoGUI:** mova o mouse para o canto superior esquerdo para abortar.

Na v1 o fluxo **para antes do salvamento** (`permitir_salvar=false`).  
Se houver interrupção durante um passo de salvamento, o estado fica `salvamento_incerto` e a retomada **não** reenvia — reconcilie no APAC.

## 7. Teste supervisionado (um paciente)

1. `config.json` com passos mínimos e `permitir_salvar=false` (o bot abre o APAC sozinho se preciso).  
2. BIODATA mapeado **ou** `sistema_origem=mock` com ID conhecido.  
3. Opcional: `open-apac` para validar só a abertura.  
4. Execute:

```powershell
.\.venv\Scripts\python.exe -m apac_bot run --config config.json --live --limit 1
```

5. Confirme cada tela pedida no terminal.  
6. Revise no APAC o que foi digitado; salve manualmente se estiver correto.  
7. Só então evolua o mapeamento e um lote pequeno.  


## 8. Privacidade e Git

Não versionados (ver `.gitignore`): `config.json`, planilhas reais, `progress.db`, `browser_profile/`, capturas, logs.

Logs usam identidade interna (hash curto), sem CPF/CNS/nome completo.  
Capturas de tela só se `diagnostico.capturar_tela=true` (desligado por padrão; a v1 não grava automaticamente).

## 9. Mapeamentos ainda pendentes

- Localizadores HTML do BIODATA  
- Sequência completa de teclas do APAC após o CPF (auditor, procedimento, competência, save)  
- Confirmação da máscara: numeração `-` vs `/`; código com zero à esquerda  
- Significado da coluna `QUANT.`  
- Quais `dados_fixos` (CNES, validade, etc.) são realmente fixos por clínica  

## 10. Estrutura

```
src/apac_bot/          # CLI e módulos
  connectors/          # mock + biodata
data/planilha_exemplo.xlsx
config.example.json
tests/
```
