#!/usr/bin/env python3
"""
Robot de la Polla Mundial 2026
-------------------------------
1) Baja los partidos de PLAYOFFS y los guarda en 'matches'.
2) Baja los 48 equipos del torneo y los guarda en 'teams'
   (para los dropdowns de campeón/subcampeón/3º).

Corre solo (GitHub Actions) cada 15 minutos.
"""

import os
import sys
import requests

FD_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN")
SB_URL   = os.environ.get("SUPABASE_URL")
SB_KEY   = os.environ.get("SUPABASE_SERVICE_KEY")

missing = [k for k, v in {
    "FOOTBALL_DATA_TOKEN": FD_TOKEN,
    "SUPABASE_URL": SB_URL,
    "SUPABASE_SERVICE_KEY": SB_KEY,
}.items() if not v]
if missing:
    sys.exit(f"\u274c Faltan secretos: {', '.join(missing)}")

FD_HEADERS = {"X-Auth-Token": FD_TOKEN}
SB_HEADERS = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}
EXCLUIR = {"GROUP_STAGE", "LEAGUE_STAGE"}


def mapear_estado(api_status: str) -> str:
    if api_status in ("FINISHED", "AWARDED"):
        return "FINISHED"
    if api_status in ("IN_PLAY", "PAUSED", "SUSPENDED"):
        return "IN_PLAY"
    return "SCHEDULED"


def upsert(tabla, filas, conflict):
    if not filas:
        return
    r = requests.post(
        f"{SB_URL}/rest/v1/{tabla}?on_conflict={conflict}",
        headers=SB_HEADERS, json=filas, timeout=30,
    )
    if r.status_code >= 300:
        sys.exit(f"\u274c Supabase ({tabla}) devolvio {r.status_code}: {r.text[:300]}")


# ---------------------------------------------------------------------
#  1) PARTIDOS DE PLAYOFFS
# ---------------------------------------------------------------------
print("\u2b07\ufe0f  Bajando partidos...")
resp = requests.get("https://api.football-data.org/v4/competitions/WC/matches",
                    headers=FD_HEADERS, timeout=30)
if resp.status_code != 200:
    sys.exit(f"\u274c football-data (matches) {resp.status_code}: {resp.text[:300]}")

filas = []
for m in resp.json().get("matches", []):
    stage = m.get("stage")
    if stage in EXCLUIR:
        continue
    ft = (m.get("score") or {}).get("fullTime") or {}
    filas.append({
        "external_id": m["id"],
        "round": stage,
        "home_team": (m.get("homeTeam") or {}).get("name"),
        "away_team": (m.get("awayTeam") or {}).get("name"),
        "kickoff": m["utcDate"],
        "home_score": ft.get("home"),
        "away_score": ft.get("away"),
        "status": mapear_estado(m.get("status", "SCHEDULED")),
    })

upsert("matches", filas, "external_id")
print(f"   {len(filas)} partidos de playoffs sincronizados.")

# ---------------------------------------------------------------------
#  2) EQUIPOS DEL TORNEO
# ---------------------------------------------------------------------
print("\u2b07\ufe0f  Bajando equipos...")
tresp = requests.get("https://api.football-data.org/v4/competitions/WC/teams",
                     headers=FD_HEADERS, timeout=30)
if tresp.status_code == 200:
    trows = [{
        "id": t["id"],
        "name": t["name"],
        "tla": t.get("tla"),
        "crest": t.get("crest"),
    } for t in tresp.json().get("teams", [])]
    upsert("teams", trows, "id")
    print(f"   {len(trows)} equipos sincronizados.")
else:
    print(f"   \u26a0\ufe0f No se pudieron bajar equipos ({tresp.status_code}). Sigo igual.")

print("\u2705 Listo.")
