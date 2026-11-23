import json
import urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json"

# On lit les éruptions des 7 derniers jours
with urllib.request.urlopen(URL, timeout=30) as reponse:
    eruptions = json.load(reponse)

limite = datetime.now(timezone.utc) - timedelta(hours=24)
recentes = []

for e in eruptions:
    classe = e.get("max_class") or ""
    heure = e.get("max_time") or e.get("begin_time")
    if not heure:
        continue
    moment = datetime.fromisoformat(heure.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    # On ne garde que les éruptions fortes (M ou X) des dernières 24 h
    if moment >= limite and classe[:1] in ("M", "X"):
        recentes.append({"classe": classe, "heure_utc": heure})

resultat = {
    "alerte": len(recentes) > 0,
    "eruptions": recentes,
    "mis_a_jour": datetime.now(timezone.utc).isoformat(),
}

with open("alerte.json", "w") as f:
    json.dump(resultat, f, indent=2)
