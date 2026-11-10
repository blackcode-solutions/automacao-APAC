SIS DG — Automação APAC (build Windows)
========================================

Instalação recomendada
----------------------
Use SIS-DG-APAC-Setup.exe (gerado pelo build com Inno Setup).
Ele instala em Program Files, cria atalho no Menu Iniciar
(e opcionalmente na área de trabalho) e registra desinstalador.

Instalação manual (sem Setup)
-----------------------------
1. Copie a pasta inteira SIS-DG-APAC para o PC da clínica (não só o .exe).

Configuração (após instalar)
----------------------------
- Copie config.example.json para config.json (na mesma pasta do .exe).
  Com Setup: tipicamente em
  C:\Program Files\SIS DG APAC\config.json
- Ajuste planilha, clínica, licença, etc.
- Em reinstalação, não sobrescreva um config.json já ajustado.

Chromium (BIODATA / Playwright)
-------------------------------
O navegador NÃO vem no pacote. No PC com Python/Playwright instalado
(ou após um build com venv), rode uma vez:

  playwright install chromium

Em builds empacotados, o Playwright usa os browsers do perfil do usuário.
Se a automação BIODATA falhar ao abrir o browser, defina a variável de
ambiente PLAYWRIGHT_BROWSERS_PATH para a pasta onde o Chromium foi
instalado (saída típica de `playwright install chromium`).

APAC Magnético
--------------
Instale o APAC.exe e aponte apac.caminho_exe no config.json.

Executar
--------
Menu Iniciar / atalho / SIS-DG-APAC.exe (abre a UI).
O ícone do executável e do Setup é a marca DG
(packaging/sis-dg-apac.ico no build).

Na UI:
  Iniciar — continua o lote no mesmo arquivo SET (pula concluídos).
  Completar erros — só pacientes em Erro ou Em revisão, após ajuste no BIODATA.
  Exportar arquivo — copia o lote_atual.SET gerado no servidor/pasta local.
