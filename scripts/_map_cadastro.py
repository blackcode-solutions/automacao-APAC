"""Smoke: login emanuelle -> /consultorio -> Cadastro de Pacientes -> busca 1 nome."""
from __future__ import annotations

import shutil
from pathlib import Path

from apac_bot.config import load_config
from apac_bot.connectors.biodata import BiodataConnector
from apac_bot.sheet import load_lancamentos

cfg = load_config("config.json")
# perfil limpo para este usuário
profile = Path("browser_profile_emanuelle")
if profile.exists():
    shutil.rmtree(profile)
cfg.raw["biodata"]["user_data_dir"] = str(profile)

sheet = load_lancamentos(cfg)
assert sheet.ok and sheet.lancamentos, "planilha sem lançamentos"
nome = sheet.lancamentos[0].paciente_nome
print("usuario=emanuelle")
print("busca_nome_prefixo=", nome[:12], "...")

conn = BiodataConnector(cfg)
try:
    resultados = conn.buscar_por_nome(nome)
    print("url_final=", getattr(conn, "_page", None).url if conn._page else "?")
    print("resultados=", len(resultados))
    if resultados:
        p = resultados[0]
        print("campos=", sorted(p.campos_preenchidos().keys()))
        print("tem_cpf=", bool(p.cpf))
        print("tem_id=", bool(p.id_paciente))
finally:
    conn.close()
print("OK")
