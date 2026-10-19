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

São **duas planilhas** no disco (a UI permite escolher os caminhos):

1. **Lançamentos** — `planilha.caminho` (PACIENTE, COD, NUMERAÇÃO, etc.)
2. **Prontuários** — `planilha_prontuarios.caminho` (Cliente → Prontuário; obrigatória com `sistema_origem=biodata` para buscar o paciente)

Não é preciso “anexar” arquivo no sentido de upload: a automação lê os `.xlsx` do caminho informado. Se o cabeçalho da planilha de lançamentos não estiver na linha 1, use `planilha.linha_cabecalho`. Aba/colunas da planilha de prontuários ficam no `config.json` (padrão: aba `APAC `, cabeçalho na linha 3).

Com `planilha.apenas_ativos: true` (padrão), o bot processa **só as linhas visíveis** no Excel — ou seja, as que o filtro da planilha deixa ativas. Linhas ocultas pelo AutoFilter são ignoradas. Para ler a planilha inteira, use `"apenas_ativos": false`.

**Não coloque senha no `config.json`.** Credenciais ficam em `secrets.local.json` (arquivo local, fora do Git):

```powershell
Copy-Item secrets.example.json secrets.local.json
# edite usuario e senha nesse arquivo
```

Com `secrets.local.json` preenchido, a consulta BIODATA no **modo API** autentica sozinha (`fetch`, `run`). No **modo browser**, o mesmo arquivo automatiza o login no Chromium (`open-biodata`); sem o arquivo, o login web continua manual.

Edite `config.json`:

| Campo | Uso |
|--------|-----|
| `clinica_id` | Identificador da clínica no progresso |
| `sistema_origem` | `mock` (padrão) ou `biodata` |
| `planilha.*` | Caminho, aba, `linha_cabecalho`, `apenas_ativos` e mapeamento de colunas (lançamentos) |
| `planilha_prontuarios.*` | Caminho da planilha Cliente/Prontuário (obrigatório com BIODATA); aba/colunas no JSON |
| `normalizacao` | Hífen→barra na numeração; zeros no código (só se configurado) |
| `dados_fixos` | Por clínica / stub da UI: `cnes_*`, `tipo_apac`; procedimentos: `codigo_procedimento` e `cns_executante` (**dinâmicos** na UI futura), `cbo` (fixo), `quantidade_procedimento` (sempre `1`) |
| `biodata.modo` | `api` (HTTP, sem Chromium) ou `browser` (Playwright). Se omitido: `api` quando houver `biodata.api.base_url`, senão `browser` |
| `biodata.api.base_url` | Base REST (ex.: `https://apis.biodataweb.net/oftalmocentro91/biodata`) |
| `biodata.api.id_sac` | `idSAC` da clínica na API |
| `biodata.api.param_nome` | Query de busca por nome (padrão `strCliente`) |
| `biodata.api.paginacao_nome` | Paginação da busca por nome (padrão `0,20`) |
| `biodata.api.authorization_prefix` | Prefixo do header `Authorization` (padrão `Bearer`; vazio = token puro) |
| `biodata.locators` | Seletores Playwright — só obrigatórios no modo `browser` |
| `apac.usar_navegacao_inicial` | Menu → 2 Enter até a lista (uma vez por sessão) |
| `apac.usar_conhost` | `true` (padrão) = abre o APAC no console clássico para ler o buffer da tela |
| `apac.reiniciar_se_ja_aberto` | `true` (padrão) = no `open-apac`/`dump-apac-screen`, encerra APAC já aberto e reabre limpo no MENU |
| `apac.confirmar_navegacao_inicial` | `false` = passos mapeados no `open-apac` rodam sem `s`; `true` = pede `s` em cada um. Passos **novos** sempre pedem `s` |
| `apac.velocidade` | `seguro` (padrão no código) ou `rapido` (agressivo: pausas curtas + digitação rápida). Se o Magnético engolir teclas ou pular campos, volte para `seguro` |
| `apac.intervalo_enter_navegacao_s` | Pausa entre Enters do menu; se omitido, usa 2.0 (`seguro`) ou 0.8 (`rapido`) |
| `apac.paciente_inicio` | Nome do 1º paciente no `open-apac` (NUMERO) |
| `apac.passos` | Teclas por paciente — vazia bloqueia `--live` |
| `apac.caminho_exe` | Caminho do `APAC.exe` (padrão `C:\APAC\APAC.exe`) |
| `apac.timeout_abrir_s` | Segundos para aguardar a janela após iniciar o exe |
| `apac.permitir_salvar` | Deve permanecer `false` até o save estar mapeado |

A automação lê o **buffer do console** (não só clipboard) para saber a tela (MENU, LISTA, IDENTIFICACAO, PROCEDIMENTOS) e o **rótulo do campo** na linha do cursor. Se a tela ou o campo não for o esperado, o bot **para** — não digita nem dá Tab no campo errado. Se falhar o rótulo, rode `dump-apac-screen` nesse campo e ajuste os marcadores em `console_screen.py`.

Na tela **PROCEDIMENTOS**, o `open-apac` preenche até Classificação e para antes do CID: código/CNS vêm de `dados_fixos` (dinâmicos na UI futura; se `codigo_procedimento` estiver vazio, usa o COD da planilha); CBO e quantidade são fixos; Equipe fica vazia (Tab); Serviço/Classif. só Tab sem sobrescrever.

Não coloque senhas no JSON. Credenciais ficam em `secrets.local.json`. No modo `api`, a senha é convertida para maiúsculas e enviada como SHA-512 na autenticação; o token (~4h) vai no header `Authorization`. O comando `open-biodata` continua abrindo o Chromium (útil para mapeamento / modo `browser`).

## 3. Comandos

```powershell
# Interface desktop SIS DG (tela inicial → config da clínica + lote)
.\.venv\Scripts\python.exe -m apac_bot ui --config config.json
# ou:
.\.venv\Scripts\python.exe -m apac_bot.ui --config config.json

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
5. Configurar `biodata.modo=api` + `biodata.api.*` + `secrets.local.json` → `fetch` real (sem abrir navegador)  
6. (Opcional) Modo `browser` / locators Playwright se precisar do Chromium  
7. Testar teclas no APAC **sem salvar** (`permitir_salvar=false`)  
8. Um lançamento supervisionado  
9. Lote pequeno  

## 5. Fluxo BIODATA via API (recomendado)

1. Em `config.json`: `sistema_origem=biodata`, `biodata.modo=api`, `biodata.api.base_url` e `biodata.api.id_sac`  
2. Preencher `secrets.local.json` (`usuario` / `senha` em texto — o bot faz `SHA-512(senha.upper())`)  
3. Rodar `fetch` ou `run` — consulta `autenticar` + `clientes/listar` por prontuário (`clienteId`) ou nome  

```powershell
.\.venv\Scripts\python.exe -m apac_bot fetch --config config.json --limit 1
```

## 5a. Fluxo BIODATA mapeado no browser (Oftalmocentro)

Com `biodata.modo=browser`, após o login automático (a rota pós-login depende do usuário: `/home`, `/consultorio/...`, etc.) o bot **não força** `/home`: usa o menu lateral na rota em que caiu.

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
  ui/                  # Interface desktop (CustomTkinter)
  connectors/          # mock + biodata
data/planilha_exemplo.xlsx
config.example.json
tests/
```

A UI grava os campos dinâmicos, as duas planilhas (`planilha.caminho` e `planilha_prontuarios.caminho`) e `paciente_inicio` no `config.json` (merge seguro: não apaga `biodata`, timeouts etc.) ao clicar em **Iniciar**. Ações na tela: iniciar, cancelar e exportar o `.SET`. Validar/status ficam no CLI. Credenciais continuam em `secrets.local.json`.
