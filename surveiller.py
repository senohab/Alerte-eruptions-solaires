import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone

# --- Réglages (vous pouvez les modifier) ---
SEUIL = 1         # 1 = on garde toutes les éruptions
HEURES_LISTE = 48  # durée pendant laquelle une éruption reste dans la liste
HEURES_ALERTE = 24 # "alerte" est vraie si une éruption date de moins de ces heures
JOURS_HISTO_FAIBLES = 30  # les éruptions faibles (C) restent 30 jours dans l'historique
                         # les fortes (M et X) restent sans limite

URL_NOAA = "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json"
URL_DONKI = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/FLR?startDate={debut}&endDate={fin}"

MAINTENANT = datetime.now(timezone.utc)


def lire(url):
    requete = urllib.request.Request(url, headers={"User-Agent": "alerte-eruptions-solaires"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.load(reponse)


def en_date(texte):
    """Transforme un texte de date en date UTC, ou None s'il est vide ou illisible."""
    if not texte:
        return None
    texte = str(texte).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(texte)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def en_texte(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def force(classe):
    """Force d'une éruption : C1 = 1, M1 = 10, M5 = 50, X1 = 100..."""
    m = re.match(r"^([A-Z])(\d+(?:\.\d+)?)", classe or "")
    if not m:
        return 0
    return {"A": 0.01, "B": 0.1, "C": 1, "M": 10, "X": 100}.get(m.group(1), 0) * float(m.group(2))


def vers_la_terre(position):
    """Estimation d'après la position sur le Soleil, par exemple N12W20.
    Près du centre du disque (moins de 45 degrés) : probable. Sur le bord ou derrière : non."""
    m = re.match(r"^[NS]\d+([EW])(\d+)", position or "")
    if not m:
        return "inconnu"
    longitude = int(m.group(2))
    if longitude <= 45:
        return "probable"
    if longitude <= 75:
        return "inconnu"
    return "non"


# 1) Les éruptions détectées par les satellites GOES (très rapide)
noaa = lire(URL_NOAA)

# 2) La position de l'éruption, donnée par la NASA (peut arriver plus tard, ce n'est pas bloquant)
try:
    debut = (MAINTENANT - timedelta(days=4)).strftime("%Y-%m-%d")
    fin = (MAINTENANT + timedelta(days=1)).strftime("%Y-%m-%d")
    donki = lire(URL_DONKI.format(debut=debut, fin=fin)) or []
except Exception as erreur:
    print("NASA indisponible, on continue sans la position :", erreur)
    donki = []


def trouver_donki(pic):
    meilleur, ecart_min = None, timedelta(minutes=15)
    for d in donki:
        t = en_date(d.get("peakTime"))
        if t and abs(t - pic) <= ecart_min:
            meilleur, ecart_min = d, abs(t - pic)
    return meilleur


liste = []
for e in noaa:
    classe = e.get("max_class") or ""
    pic = en_date(e.get("max_time"))
    debut_e = en_date(e.get("begin_time")) or pic
    if not pic or not debut_e or force(classe) < SEUIL:
        continue
    d = trouver_donki(pic)
    position = (d or {}).get("sourceLocation") or None
    region = (d or {}).get("activeRegionNum")
    liste.append({
        "debut_utc": en_texte(debut_e),
        "pic_utc": en_texte(pic),
        "classe": classe,
        "region": str(region) if region else None,
        "position": position,
        "vers_terre": vers_la_terre(position),
        "arrivee_estimee_utc": None,
        "fin_utc": en_texte(en_date(e.get("end_time"))),
    })

liste.sort(key=lambda x: x["debut_utc"], reverse=True)

recentes = [x for x in liste if en_date(x["pic_utc"]) >= MAINTENANT - timedelta(hours=HEURES_LISTE)]

resultat = {
    "alerte": any(en_date(x["debut_utc"]) >= MAINTENANT - timedelta(hours=HEURES_ALERTE) for x in recentes),
    "eruptions": recentes,
    "mis_a_jour": MAINTENANT.isoformat(),
}

# On n'écrit le fichier que si quelque chose a changé (pour garder un historique léger)
try:
    with open("alerte.json", encoding="utf-8") as f:
        ancien = json.load(f)
except Exception:
    ancien = {}
if ancien.get("alerte") == resultat["alerte"] and ancien.get("eruptions") == resultat["eruptions"]:
    print("Rien de nouveau, fichier inchangé.")
else:
    with open("alerte.json", "w", encoding="utf-8") as f:
        json.dump(resultat, f, indent=2, ensure_ascii=False)
    print("Fichier mis à jour.")


# --- Historique : on garde la trace des éruptions passées ---
def lire_fichier(nom, defaut):
    try:
        with open(nom, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defaut


histo = {x["pic_utc"]: x for x in lire_fichier("historique.json", {"eruptions": []}).get("eruptions", []) if x.get("pic_utc")}
for x in liste:  # liste = les éruptions des 7 derniers jours (source NOAA)
    ancien = histo.get(x["pic_utc"], {})
    fusion = dict(x)
    for cle in ("region", "position", "arrivee_estimee_utc", "fin_utc"):
        if fusion.get(cle) is None and ancien.get(cle) is not None:
            fusion[cle] = ancien[cle]
    if fusion["vers_terre"] == "inconnu" and ancien.get("vers_terre") not in (None, "inconnu"):
        fusion["vers_terre"] = ancien["vers_terre"]
    histo[x["pic_utc"]] = fusion

limite_faibles = MAINTENANT - timedelta(days=JOURS_HISTO_FAIBLES)
gardees = [
    x for x in histo.values()
    if force(x["classe"]) >= 10 or en_date(x["pic_utc"]) >= limite_faibles
]
gardees.sort(key=lambda x: x["pic_utc"], reverse=True)

ancien_histo = lire_fichier("historique.json", {}).get("eruptions")
if ancien_histo == gardees:
    print("Historique inchangé.")
else:
    with open("historique.json", "w", encoding="utf-8") as f:
        json.dump({"eruptions": gardees}, f, indent=1, ensure_ascii=False)
    print("Historique mis à jour :", len(gardees), "éruptions.")
