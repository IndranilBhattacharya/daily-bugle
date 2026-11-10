"""Daily WhatsApp brief: global/AI/science news + a motivational story.

Pipeline: RSS feeds -> Gemini (summarize + pick what matters) -> CallMeBot WhatsApp.
Stdlib only. Env: GEMINI_API_KEY, CALLMEBOT_PHONE, CALLMEBOT_APIKEY, optional GEMINI_MODEL.
Without CALLMEBOT_* set it just prints (handy for local dry runs).
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (daily-news-bot)"}

FEEDS = {
    "World": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    ],
    "AI & Tech": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://hnrss.org/frontpage?points=300",
        "https://news.google.com/rss/search?q=(AI+model+launch+OR+benchmark+OR+LLM)+when:1d&hl=en-US&gl=US&ceid=US:en",
    ],
    "Science & Space": [
        "https://www.sciencedaily.com/rss/top/science.xml",
        "https://phys.org/rss-feed/",
        "https://www.space.com/feeds/all",
        "https://www.nasa.gov/news-release/feed/",
    ],
}
PER_FEED = 15
MAX_AGE = timedelta(hours=30)

# ponytail: fixed rotation by date = no state to store. Hand-picked so nobody shady sneaks in.
PEOPLE = [
    "Srinivasa Ramanujan", "Satyendra Nath Bose", "Albert Einstein", "Isaac Newton", "Marie Curie",
    "Michael Faraday", "Galileo Galilei", "Johannes Kepler", "Nikola Tesla", "C. V. Raman",
    "Jagadish Chandra Bose", "Aryabhata", "Leonhard Euler", "Carl Friedrich Gauss", "Evariste Galois",
    "Emmy Noether", "Sophie Germain", "Alan Turing", "Ada Lovelace", "Subrahmanyan Chandrasekhar",
    "Homi J. Bhabha", "Vikram Sarabhai", "A. P. J. Abdul Kalam", "Meghnad Saha", "Prafulla Chandra Ray",
    "Bhagat Singh", "Subhas Chandra Bose", "Khudiram Bose", "Surya Sen", "Rani Lakshmibai",
    "Chandrashekhar Azad", "Matangini Hazra", "Nelson Mandela", "Martin Luther King Jr.", "Harriet Tubman",
    "Frederick Douglass", "Swami Vivekananda", "Rabindranath Tagore", "Ishwar Chandra Vidyasagar", "Helen Keller",
    "Stephen Hawking", "Rosalind Franklin", "Katherine Johnson", "Carl Sagan", "Edwin Hubble",
    "Henrietta Swan Leavitt", "Nicolaus Copernicus", "Archimedes", "Leonardo da Vinci", "The Wright brothers",
    "Louis Pasteur", "Alexander Fleming", "Dmitri Mendeleev", "Niels Bohr", "Paul Dirac",
    "Richard Feynman", "Kalpana Chawla", "Tim Berners-Lee", "Claude Shannon", "Grace Hopper",
    "Dennis Ritchie", "Linus Torvalds", "Bernhard Riemann", "Niels Henrik Abel", "Brahmagupta",
    "Bhaskara II", "Madhava of Sangamagrama", "Hypatia of Alexandria", "Ibn al-Haytham", "Muhammad ibn Musa al-Khwarizmi",
    "Abdus Salam", "Harish-Chandra", "Savitribai Phule", "Toussaint Louverture", "Jose Rizal",
    "Anandi Gopal Joshi", "Jane Goodall", "Wangari Maathai", "Yuri Gagarin", "Sergei Korolev",
]
THEMES = [
    "handling ego and admitting you were wrong", "staying positive after failure", "listening more than talking",
    "forgiving people and moving on", "not comparing yourself to others", "keeping friendships alive",
    "patience with family", "handling criticism calmly", "gratitude in small things", "saying sorry first",
    "staying humble after success", "respecting people who disagree with you", "consistency over motivation",
    "letting go of what you can't control",
]


def text_of(el, *tags):
    for t in tags:
        found = el.find(t)
        if found is not None:
            return (found.text or found.get("href") or "").strip()
    return ""


def parse_feed(xml_bytes, now):
    """Return [(title, link, summary)] from RSS or Atom, newer than MAX_AGE."""
    atom = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.iter("item"):
        out.append((text_of(it, "title"), text_of(it, "link"), text_of(it, "description"), text_of(it, "pubDate")))
    for it in root.iter(atom + "entry"):
        out.append((text_of(it, atom + "title"), text_of(it, atom + "link"),
                    text_of(it, atom + "summary", atom + "content"), text_of(it, atom + "updated", atom + "published")))
    items = []
    for title, link, summary, stamp in out:
        try:
            when = parsedate_to_datetime(stamp) if "," in stamp else datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if now - when > MAX_AGE:
                continue
        except (TypeError, ValueError):
            pass  # no/odd date: keep it, Gemini filters
        if title and link:
            # ponytail: crude tag strip, Gemini only needs a hint of the content
            summary = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", summary)).split())
            items.append((title, link, summary[:300]))
        if len(items) >= PER_FEED:
            break
    return items


def gather():
    now = datetime.now(timezone.utc)
    lines = []
    for section, urls in FEEDS.items():
        lines.append(f"\n## {section}")
        for url in urls:
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                    items = parse_feed(r.read(), now)
            except Exception as e:  # one dead feed shouldn't kill the brief
                print(f"feed failed {url}: {e}", file=sys.stderr)
                continue
            lines += [f"- {t} | {l} | {s}" for t, l, s in items]
    return "\n".join(lines)


def build_prompt(headlines, today):
    n = today.toordinal()
    person, theme = PEOPLE[n % len(PEOPLE)], THEMES[n % len(THEMES)]
    return f"""You write a personal morning brief delivered on WhatsApp. Today is {today:%A, %d %B %Y}.

READER'S INTERESTS (strict priority):
1. AI news: new model launches (overall performance, benchmark numbers vs rivals if known), major AI company moves, research breakthroughs.
2. Significant progress in tech, science, astronomy/space.
3. Major global events only: wars, large protests, viral high-profile crimes, big disasters.
SKIP: routine/local politics, celebrity gossip, sports, stock tips, minor product updates, ads.

TASK: From the headlines below (last ~24h), pick only what is genuinely significant (max ~8 stories, fewer is fine).
Merge duplicates. If a section has nothing significant, write "Nothing significant today." - never force filler.
You may use Google Search to verify facts or fetch benchmark numbers, but every story must carry a link
copied EXACTLY from the headline list below. Never invent links or numbers.

For each story use very simple, easy English (a 15-year-old should understand):
*<emoji> Title*
*What happened:* 1-2 sentences
*How:* 1-2 sentences
*Why it matters / why it happened:* 1-2 sentences
Link: <url>

Then a section *🌱 Story of the Day* about {person}: a true, vivid ~180-word story of their struggle -
what obstacles they faced, what they did, how they achieved it, and one lesson. Facts only, no myths.

Then *🧘 Mindset* - 3-4 warm, practical lines on: {theme}. Positive, not preachy.

FORMAT: WhatsApp formatting only (*bold*, _italic_). No markdown headers, no tables.
Start with "☀️ *Good morning! Your brief for {today:%d %b}*". Sections in order:
*🤖 AI & Tech*, *🔭 Science & Space*, *🌍 World*, then Story of the Day, then Mindset.
Separate stories with a blank line.

HEADLINES (title | link | snippet):
{headlines}
"""


def gemini(prompt):
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    base = {"contents": [{"parts": [{"text": prompt}]}]}
    # ponytail: 2 tries with search grounding, last try without (in case grounding quota is out). 503s are common.
    for attempt, body in enumerate([{**base, "tools": [{"google_search": {}}]}] * 2 + [base]):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode(), headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                parts = json.load(r)["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except Exception as e:
            detail = e.read().decode()[:500] if hasattr(e, "read") else e
            print(f"gemini attempt {attempt + 1} failed: {detail}", file=sys.stderr)
            time.sleep(20)
    raise SystemExit("Gemini failed 3 times")


def chunks(text, limit=1500):
    """Split on blank lines so stories stay whole; hard-cut anything still too long."""
    out, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            out.append(cur)
            cur = ""
        while len(block) > limit:
            out.append(block[:limit])
            block = block[limit:]
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        out.append(cur)
    return out


def send(text):
    phone, key = os.environ.get("CALLMEBOT_PHONE"), os.environ.get("CALLMEBOT_APIKEY")
    if not (phone and key):
        print("CALLMEBOT_* not set, dry run only.")
        return
    for part in chunks(text):
        q = urllib.parse.urlencode({"phone": phone, "text": part, "apikey": key})
        with urllib.request.urlopen(f"https://api.callmebot.com/whatsapp.php?{q}", timeout=60) as r:
            print("callmebot:", r.status)
        time.sleep(5)  # CallMeBot throttles rapid messages


if __name__ == "__main__":
    brief = gemini(build_prompt(gather(), datetime.now(IST).date()))
    print(brief)
    send(brief)
