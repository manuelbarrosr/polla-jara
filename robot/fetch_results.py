#!/usr/bin/env python3
"""
Robot de la Polla Mundial 2026
-------------------------------
Baja los partidos de PLAYOFFS del Mundial desde football-data.org
y los sube/actualiza en la tabla 'matches' de Supabase.

Corre solo (GitHub Actions) cada 15 minutos.
NO guarda nada sensible en el código: todo viene de variables de entorno.
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------
# 1) Credenciales (vienen de los "secrets" de GitHub, nunca van en el código)
# ---------------------------------------------------------------------
FD_TOKEN     = os.environ.get("FOOTBALL_DATA_TOKEN")
SB_URL       = os.environ.get("SUPABASE_URL")          # https://xxxx.supabase.co
SB_KEY       = os.environ.get("SUPABASE_SERVICE_KEY")  # clave service_role (secreta)

missing = [k for k, v in {
    "FOOTBALL_DATA_TOKEN": FD_TOKEN,
    "SUPABASE_URL": SB_URL,
    "SUPABASE_SERVICE_KEY": SB_KEY,
}.items() if not v]
if missing:
    sys.exit(f"❌ Faltan secretos: {', '.join(missing)}")

# ---------------------------------------------------------------------
# 2) Qué partidos nos interesan
#    Tomamos TODO lo que NO sea fase de grupos = los playoffs.
#    (Así no dependemos del nombre exacto que use la API para 16avos.)
# ---------------------------------------------------------------------
EXCLUIR = {"GROUP_STAGE", "LEAGUE_STAGE"}

# ---------------------------------------------------------------------
# 2b) MODO TEST (temporal)
#     Mientras probamos el sistema antes de los playoffs, además de los
#     playoffs traemos partidos de FASE DE GRUPOS recientes/próximos
#     (los marcamos con round='GROUP_STAGE' -> pestaña "Testeo" en la web).
#     Para volver a producción: poner TEST_GROUPS = False (o borrar este bloque).
# ---------------------------------------------------------------------
TEST_GROUPS = True
# Solo grupos cuyo kickoff sea de hace <= 2 días en adelante (evita traer los 72)
GROUP_CUTOFF = datetime.now(timezone.utc) - timedelta(days=2)

def kickoff_dt(iso: str):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None

def mapear_estado(api_status: str) -> str:
    if api_status in ("FINISHED", "AWARDED"):
        return "FINISHED"
    if api_status in ("IN_PLAY", "PAUSED", "SUSPENDED"):
        return "IN_PLAY"
    return "SCHEDULED"  # SCHEDULED, TIMED, POSTPONED, CANCELLED, etc.

# ---------------------------------------------------------------------
# 3) Bajar los partidos del Mundial (competición "WC")
# ---------------------------------------------------------------------
print("⬇️  Bajando partidos del Mundial desde football-data.org...")
resp = requests.get(
    "https://api.football-data.org/v4/competitions/WC/matches",
    headers={"X-Auth-Token": FD_TOKEN},
    timeout=30,
)
if resp.status_code != 200:
    sys.exit(f"❌ football-data devolvió {resp.status_code}: {resp.text[:300]}")

partidos = resp.json().get("matches", [])
print(f"   {len(partidos)} partidos en total en el torneo.")

# ---------------------------------------------------------------------
# 4) Armar las filas para Supabase (solo playoffs)
#    OJO: usamos score.fullTime = marcador a los 120 min, SIN penales.
#    Los penales van aparte en la API, así que un 1-1 que se define por
#    penales se guarda como 1-1 (empate), tal como querés.
# ---------------------------------------------------------------------
filas = []
for m in partidos:
    stage = m.get("stage")
    is_group = stage == "GROUP_STAGE"

    # Regla normal: excluir fase de grupos / liga.
    # Excepción (modo test): incluir grupos recientes/próximos.
    if stage in EXCLUIR:
        if not (TEST_GROUPS and is_group):
            continue
        ko = kickoff_dt(m.get("utcDate", ""))
        if ko is None or ko < GROUP_CUTOFF:
            continue

    score_ft = (m.get("score") or {}).get("fullTime") or {}

    filas.append({
        "external_id": m["id"],
        "round":       stage,
        "home_team":   (m.get("homeTeam") or {}).get("name"),
        "away_team":   (m.get("awayTeam") or {}).get("name"),
        "kickoff":     m["utcDate"],
        "home_score":  score_ft.get("home"),
        "away_score":  score_ft.get("away"),
        "status":      mapear_estado(m.get("status", "SCHEDULED")),
    })

grupos_test = sum(1 for f in filas if f["round"] == "GROUP_STAGE")
print(f"   {len(filas)} partidos para guardar"
      + (f" (incluye {grupos_test} de grupos en modo test)." if grupos_test else "."))
if not filas:
    print("ℹ️  Todavía no hay partidos para sincronizar. Nada que hacer.")
    sys.exit(0)

# ---------------------------------------------------------------------
# 5) Subir a Supabase (UPSERT por external_id: inserta o actualiza)
# ---------------------------------------------------------------------
print("⬆️  Subiendo a Supabase...")
up = requests.post(
    f"{SB_URL}/rest/v1/matches?on_conflict=external_id",
    headers={
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    },
    json=filas,
    timeout=30,
)
if up.status_code >= 300:
    sys.exit(f"❌ Supabase devolvió {up.status_code}: {up.text[:300]}")

terminados = sum(1 for f in filas if f["status"] == "FINISHED")
print(f"✅ Listo. {len(filas)} partidos sincronizados ({terminados} terminados).")
