"""
twitch2podcast.py — version GitHub Actions.

Télécharge les nouvelles VODs d'une chaîne Twitch en audio, envoie chaque
fichier dans une Release GitHub et régénère docs/feed.xml (servi par GitHub Pages).

Variables d'environnement (fournies par le workflow) :
    TWITCH_CHANNEL     nom de la chaîne Twitch
    MAX_VODS           nombre de VODs récentes à vérifier (défaut 5)
    GITHUB_REPOSITORY  "pseudo/depot" (automatique dans Actions)
    GH_TOKEN           jeton pour la commande gh (automatique dans Actions)
"""
import email.utils
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import yt_dlp

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
DB = ROOT / "episodes.json"
FEED = ROOT / "docs" / "feed.xml"
MAX_ASSET = 2 * 1024**3  # limite GitHub par fichier de Release

CHANNELS = os.environ["TWITCH_CHANNEL"]  # une ou plusieurs chaînes séparées par des virgules
CHANNEL = ""
MAX_VODS = int(os.environ.get("MAX_VODS", "5"))
REBUILD = os.environ.get("REBUILD") == "true"  # retélécharge tous les épisodes déjà connus
LIVE_MARGIN = 45 * 60  # une VOD qui a grandi il y a moins de 45 min = live encore en cours
REPO = os.environ["GITHUB_REPOSITORY"]
OWNER, NAME = REPO.split("/")
PAGES_URL = f"https://{OWNER.lower()}.github.io/{NAME}"


def load_db() -> dict:
    return json.loads(DB.read_text(encoding="utf-8")) if DB.exists() else {}


def save_db(db: dict) -> None:
    DB.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


def upload(vid: str, title: str, path: Path) -> str:
    """Crée une Release « vod-<id> » contenant le fichier audio, renvoie son URL."""
    tag = f"vod-{vid}"
    # Une Release laissée par un lancement interrompu bloquerait la création : on la remplace.
    subprocess.run(["gh", "release", "delete", tag, "--repo", REPO, "--yes", "--cleanup-tag"],
                   capture_output=True)
    subprocess.run(
        ["gh", "release", "create", tag, str(path),
         "--repo", REPO, "--title", title[:120], "--notes", f"Twitch VOD {vid}"],
        check=True,
    )
    return f"https://github.com/{REPO}/releases/download/{tag}/{path.name}"


def fetch_vods(db: dict) -> None:
    entries = []
    # La liste « archives » revient parfois vide : on retombe sur la liste complète.
    for url in (f"https://www.twitch.tv/{CHANNEL}/videos?filter=archives&sort=time",
                f"https://www.twitch.tv/{CHANNEL}/videos?filter=all&sort=time"):
        with yt_dlp.YoutubeDL({"extract_flat": True, "playlistend": MAX_VODS}) as ydl:
            entries = list(ydl.extract_info(url, download=False).get("entries") or [])
        print(f"{CHANNEL} : {len(entries)} vidéo(s) trouvée(s) via {url}")
        if entries:
            break
    todo = [(e["id"], e["url"]) for e in entries if REBUILD or e["id"] not in db]
    if REBUILD:  # on reprend aussi les anciens épisodes, plus vieux que la liste
        listed = {vid for vid, _ in todo}
        todo += [(vid, f"https://www.twitch.tv/videos/{vid.lstrip('v')}")
                 for vid in db if vid not in listed]
    for vid in {e["id"] for e in entries} & db.keys() - {v for v, _ in todo}:
        print(f"Déjà présent : {vid}")
    for vid, url in todo:
        process(vid, url, db)


def probe_duration(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return int(float(out.stdout.strip() or 0))


def process(vid: str, url: str, db: dict) -> None:
    """Télécharge une VOD, la réencode en audio léger et la publie."""
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        print(f"Ignoré {vid} : {e}")  # VOD supprimée par Twitch ou réservée aux abonnés
        return

    # Pendant un live, la VOD existe déjà mais s'allonge encore : la prendre maintenant
    # donnerait un épisode coupé. On attend la vérification suivante.
    end = (info.get("timestamp") or 0) + (info.get("duration") or 0)
    if datetime.now(timezone.utc).timestamp() - end < LIVE_MARGIN:
        print(f"Live encore en cours, repoussé : {vid}")
        return

    # « Audio_Only » est le flux audio seul de Twitch ; à défaut, le plus petit flux vidéo.
    opts = {"format": "Audio_Only/bestaudio/worst", "outtmpl": str(WORK / f"{vid}.src.%(ext)s")}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.process_ie_result(info, download=True)
    src = next(WORK.glob(f"{vid}.src.*"))  # l'extension dépend du flux choisi

    # Réencodage explicite : mono AAC 64 kbps (~30 Mo/h) et index en tête du fichier
    # (+faststart) pour qu'Apple Podcasts puisse lire avant la fin du téléchargement.
    path = WORK / f"{vid}.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn",
                    "-ac", "1", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
                    str(path)], check=True)
    src.unlink()

    size = path.stat().st_size
    if size > MAX_ASSET:
        print(f"Ignoré {vid} : fichier trop gros ({size} octets)")
        path.unlink()
        return
    title = info.get("title") or vid
    db[vid] = {
        "title": title,
        "description": info.get("description") or "",
        "url": upload(vid, title, path),
        "size": size,
        "duration": probe_duration(path),  # durée réelle du fichier, pas celle annoncée par Twitch
        "date": info.get("timestamp") or datetime.now(timezone.utc).timestamp(),
        "link": info.get("webpage_url", ""),
        "thumbnail": info.get("thumbnail", ""),
    }
    path.unlink()
    save_db(db)  # sauvegarde après chaque épisode, au cas où la suite échoue


def build_feed(db: dict) -> None:
    items = []
    for vid, ep in sorted(db.items(), key=lambda kv: kv[1]["date"], reverse=True):
        image = f'<itunes:image href="{escape(ep["thumbnail"])}"/>' if ep["thumbnail"] else ""
        items.append(f"""    <item>
      <title>{escape(ep['title'])}</title>
      <description>{escape(ep['description'] or ep['title'])}</description>
      <guid isPermaLink="false">twitch-{vid}</guid>
      <pubDate>{email.utils.formatdate(ep['date'], usegmt=True)}</pubDate>
      <link>{escape(ep['link'])}</link>
      <enclosure url="{escape(ep['url'])}" length="{ep['size']}" type="audio/x-m4a"/>
      <itunes:duration>{ep['duration']}</itunes:duration>
      {image}
    </item>""")

    FEED.parent.mkdir(exist_ok=True)
    FEED.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(CHANNEL)} — Lives Twitch</title>
    <link>https://www.twitch.tv/{escape(CHANNEL)}</link>
    <description>Rediffusions audio des lives de {escape(CHANNEL)} (usage personnel).</description>
    <language>fr</language>
    <itunes:author>{escape(CHANNEL)}</itunes:author>
    <itunes:explicit>false</itunes:explicit>
    <itunes:block>Yes</itunes:block>
{chr(10).join(items)}
  </channel>
</rss>
""", encoding="utf-8")
    print(f"Flux : {PAGES_URL}/{FEED.name}")


def main() -> None:
    global CHANNEL, DB, FEED
    WORK.mkdir(exist_ok=True)
    # Un podcast par chaîne : episodes/<chaine>.json et docs/<chaine>.xml
    for CHANNEL in [c.strip() for c in CHANNELS.split(",") if c.strip()]:
        DB = ROOT / "episodes" / f"{CHANNEL}.json"
        FEED = ROOT / "docs" / f"{CHANNEL}.xml"
        DB.parent.mkdir(exist_ok=True)
        db = load_db()
        fetch_vods(db)
        build_feed(db)


if __name__ == "__main__":
    main()
