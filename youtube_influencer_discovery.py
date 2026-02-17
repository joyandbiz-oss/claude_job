#!/usr/bin/env python3
"""
YouTube Influencer Discovery Script for DataImpulse
Discovers relevant YouTube channels by scraping YouTube search results
and channel pages directly (no API quota needed).
"""

import csv
import json
import os
import re
import sys
import time
import warnings
from datetime import datetime

import requests

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

PROGRESS_FILE = "discovery_progress.json"
TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_CSV = f"dataimpulse_new_influencers_{TODAY}.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SEARCH_QUERIES = {
    "Tier 1": [
        "web scraping tutorial", "web scraping python", "proxy tutorial",
        "residential proxy", "data scraping tools", "scraping automation",
        "python automation tutorial", "web crawling tutorial",
        "no code web scraping", "scrape website python",
    ],
    "Tier 2": [
        "ad verification tools", "ad fraud detection", "brand protection online",
        "counterfeit detection marketplace", "price monitoring ecommerce",
        "competitor price tracking", "SERP tracking tutorial",
        "rank tracker SEO tool", "local SEO tools tutorial", "SEO automation",
    ],
    "Tier 3": [
        "sneaker bot tutorial", "sneaker proxy setup", "instagram automation bot",
        "telegram bot tutorial python", "tiktok automation",
        "social media automation tools", "data engineering tutorial",
        "ETL pipeline tutorial", "data pipeline python", "API scraping tutorial",
    ],
    "Tier 4": [
        "web scraping tutorial español", "scraping python español",
        "automatización web", "web scraping tutorial português",
        "automação python", "scraping tutorial hindi", "proxy tutorial deutsch",
        "web scraping tutoriel français",
    ],
    "Tier 5": [
        "OSINT tools tutorial", "penetration testing tools",
        "network reconnaissance", "cybersecurity tools tutorial",
        "load testing tutorial", "website monitoring tools",
        "browser automation playwright", "puppeteer tutorial",
        "selenium tutorial advanced", "n8n automation tutorial",
        "make.com tutorial",
    ],
}

EXISTING_HANDLES = {
    "@0x5am5", "@100xEngineers", "@AI_Genix4", "@AI_Zayan",
    "@Abdelmalekmessaoudi", "@Adanghd", "@AdrianSaenz", "@AiFinder11",
    "@AkamaiDeveloper", "@Alex.Followell", "@AliAbdaal", "@AliShahin",
    "@AllTipsBoss", "@AmirDiscoveries", "@AmyWang", "@AndreasSpiess",
    "@AnkitArora", "@AppFind", "@AriellePhoenix", "@AthleticInterest",
    "@Augmented_AI", "@AureliusTjin", "@Azerbaijan", "@BadrAlhanaky",
    "@BangTutorial", "@BeerMoneyForum", "@Betechco", "@BilawalSidhu",
    "@BillyHowell", "@Block-Chain-World", "@BrianJung",
    "@BrototypeMalayalam", "@BuildersCentral", "@BusyFunda",
    "@Buzz2dayTech", "@CalebHammer", "@CaspianReport", "@ChrisKoerner",
    "@ChromeDevs", "@ClicksDontLie", "@CodeWithHarry", "@Codepur",
    "@Codevolution", "@Codezilla", "@CodingPhase", "@CodingWithLewis",
    "@ComputerGeeks", "@CreatorMagicAI", "@CryptoGeographic", "@CryptoMK",
    "@CuttingEdgeSchool", "@CyberWithBen", "@DIGITALPIYUSH",
    "@Daniel-Dann", "@DanielDavidson", "@DataCamp", "@DavidCantone",
    "@DesignCourse", "@DocWilliams", "@DopeMotions", "@DrVegan",
    "@DvLZStaTioN", "@EarningsCircuitAI", "@EconomicsExplained",
    "@EddyBallesteros", "@EliRigobeliAI", "@ElliotChoy",
    "@EmprendeAprendiendo", "@EricStruk", "@EricWTech", "@ErikaKullberg",
    "@FLICKETCRYPTO", "@FactoHolic", "@FaijulIslam68",
    "@FazeelUsmaniOfficial", "@FaztTech", "@FelipeVergara", "@Fireship",
    "@ForrestKnight", "@GaoDalie_AI", "@GeekWork", "@Get365AI",
    "@GrahamStephan", "@GreatStack", "@HINDZ", "@HacksmithIndustries",
    "@HarryLee", "@HealthwithCory", "@HenryBelcaster",
    "@HistoryoftheUniverse", "@HocVienMarketingOnlineAI", "@HolaMundoDev",
    "@HoradeNegcios", "@HowMoneyWorks", "@HowTech1", "@HozhiLearn",
    "@HrishikeshRoyOfficial", "@Hyeser", "@InsideYourHustle",
    "@InstantlyAI", "@InternetMadeCoder", "@IshanSharma",
    "@Itssssss_Jack", "@JackGordon", "@JacobLee", "@JashRadia",
    "@JeffSu", "@JennyHoyos", "@JessRamosData", "@JoCoding",
    "@JoeColantonio", "@JooCurry", "@JoshArt", "@JoshMadakor",
    "@KSRDatavizon", "@KarineLago", "@KelasTerbuka", "@KenjiExplains",
    "@KitbogaShow", "@KiunB", "@Konstantinos", "@KunalKushwaha",
    "@KyleFrielTech", "@LastMomentTuitions", "@LewLater", "@LewisHowes",
    "@LiamOttley", "@LightsOnData", "@LindaRaynier", "@LinusMediaGroup",
    "@LoganSkiFinance", "@LogicallyAnswered", "@LuanaFranco",
    "@LucasMontano", "@LuckyStudios76", "@LuisUrrutia",
    "@MagnatesMedia", "@MarcoBucciArt", "@MariRel", "@MarieStella",
    "@MarinaMogilko", "@MarkTilbury", "@MaxTechOfficial",
    "@MedSchoolInsiders", "@MersudinForbes", "@MerveOzkaynak",
    "@Meta4sec", "@MeticsMedia", "@MidasTomi", "@MikeDee",
    "@MikeyNoCode", "@MrGrowth", "@NIIT_Limited", "@NareshIT",
    "@NerdsdeNegcios", "@NetMentor", "@NeuralNine",
    "@NiallMacMillanTheAwkwardPOVGuy",
    "@NikhilPawarMotionDesignerAICreator", "@NishantChahar11",
    "@NoCodeMBA", "@OMilionrio", "@Octoparsewebscraping",
    "@OneSkillPowerPoint", "@OnlineWebTutor", "@PapayaCoders",
    "@PaulDickson7", "@PaytonClarkSmith", "@PijushSahaBD", "@Polyfjord",
    "@PriaMasaDepan", "@PritikaLoonia", "@ProgramadorX",
    "@PythonSimplified", "@QuangLeLife", "@RafaelPantoja",
    "@RajPhotoEditingandMuchMore", "@Rajeevdaz", "@RobShocks",
    "@RoboNuggets", "@Romania", "@SailingSVDelos", "@ShaneHummus",
    "@SinghinUSA", "@SleepyCatHey", "@Snovio",
    "@Socialselleracademy", "@Sop", "@StewartGauld",
    "@StudyAutomationAcademy", "@SundasKhalid", "@SupplyScience",
    "@SwaroopVITB", "@THEECOMKING", "@TechGo6", "@TechInRealEstate",
    "@TechWithTim", "@Techscope01", "@TheCodingBus",
    "@TheIcedCoffeeHour", "@TheMetaverseGuy", "@ThePptPro", "@ThioJoe",
    "@TiagoCurcio", "@TinaHuang1", "@Tooltester", "@UTHMANSTECHHUB",
    "@Upflip", "@UskoKruM2010", "@VaibhavJain", "@VarunMayya",
    "@Vchannel79", "@VensyKrishna", "@VirtualTechBox",
    "@WebsiteLearners", "@YoussefNejjari", "@Zero2LaunchAI",
    "@_katiepeake", "@aEscoladeSites", "@affiliatemarketingdude",
    "@agustinmedinaIA", "@aimevzulari", "@alejavirivera",
    "@ambitious1z", "@andylokcl", "@atefataya", "@basic.techtube",
    "@bassemmagdy0", "@batuhandurmaz-seo", "@bigboxSWE",
    "@bigpoppacode", "@boualiali", "@boxput", "@brunobelissimoai",
    "@bycloudAI", "@charliebarberbiz", "@codebasics",
    "@codewithjoshoffical", "@codigofontetv", "@dailylifereviews98",
    "@dansmarttutorials", "@davidbombal", "@deaafrizal", "@decodingyt",
    "@derekcheungsa", "@drantunes", "@drissas", "@droidcrunch",
    "@elephorm", "@elestio", "@elimaurtua", "@emiliatalexandre",
    "@empreendedorserial", "@eugenekadzin", "@f.fontoura",
    "@frank_moss", "@graceatwood", "@grillodesigns", "@harkirat1",
    "@hasanaboulhasan", "@highpartymusic", "@hivecorp",
    "@holoconnect228", "@igorzuevich", "@iishtheceo",
    "@intheworldofai", "@jasoncooperson", "@jessecunninghamv",
    "@jojol", "@jonocatliff", "@jovensdenegocios", "@kingy-ai",
    "@kingyAI", "@knowledge4all", "@krishnaik06", "@leonardogrig",
    "@letscodewithavinash", "@maddy_gutierrez_", "@malkhatib",
    "@manodeyvin", "@mdalmamunit427", "@meetdavidalex", "@meetusama",
    "@mehulmpt", "@michtortiyt", "@midudev", "@mikimikiweb",
    "@mostafanouman", "@mr_web", "@mrait", "@mreflow", "@munchdine",
    "@n8n-io", "@nateherk", "@nerdsdenegocios", "@ninjadoexcel",
    "@notjustdev", "@nyesworldTV", "@oliviahamerwebb", "@ondeeuclico",
    "@onezyhcn", "@oxylabs", "@pildorasinformaticas", "@polcorominas",
    "@procodrr", "@promptwarrior", "@quantroom", "@reeceisrandom",
    "@ryiyshacker", "@sankyverse", "@scottdclary", "@simonscrapes",
    "@spunkram", "@starterstory", "@stylistunnie", "@sudhanshuedu",
    "@syntaxfm", "@talkmoneywithpavan", "@techwithazizul",
    "@teknikforce", "@theaerogr", "@theicai", "@thomasjanssen-tech",
    "@timdessaint", "@timexplainsai", "@tinotech01", "@trickpilott",
    "@victorroblesweb", "@vinceopra", "@vuduchong", "@wscubetech",
    "@yulittle6079", "@zCaxap", "@zinhoautomates",
}

EXISTING_HANDLES_LOWER = {h.lower() for h in EXISTING_HANDLES}

EMAIL_REGEX = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

DIRECT_KEYWORDS = {"scraping", "proxy", "residential proxy", "data collection",
                   "web crawling", "web scraper", "scrape", "proxies"}
STRONG_ADJACENT = {"automation", "bot", "seo tools", "e-commerce analytics",
                   "competitive intelligence", "ad verification",
                   "brand protection", "osint", "sneaker bot", "sneaker proxy",
                   "ad fraud"}
MODERATE_ADJACENT = {"python", "programming", "cybersecurity", "no-code",
                     "api", "testing", "data engineering", "selenium",
                     "playwright", "puppeteer", "etl", "pipeline",
                     "penetration testing", "load testing"}
WEAK_ADJACENT = {"tech", "ai tools", "coding", "developer", "tutorial",
                 "software", "review"}

session = requests.Session()
session.headers.update(HEADERS)
session.verify = False


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {"completed_queries": [], "channels": {}}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)


def extract_emails(text):
    if not text:
        return []
    emails = EMAIL_REGEX.findall(text)
    filtered = []
    for e in emails:
        lower = e.lower()
        if any(lower.endswith(ext) for ext in ['.png', '.jpg', '.gif', '.svg', '.jpeg']):
            continue
        filtered.append(e)
    return filtered


def parse_sub_count(text):
    """Parse subscriber count text like '104K subscribers' to integer."""
    if not text:
        return 0
    text = text.strip().replace(",", "").replace(" subscribers", "").replace(" subscriber", "")
    text = text.strip()
    try:
        if text.endswith("K"):
            return int(float(text[:-1]) * 1000)
        elif text.endswith("M"):
            return int(float(text[:-1]) * 1000000)
        elif text.endswith("B"):
            return int(float(text[:-1]) * 1000000000)
        else:
            return int(float(text))
    except (ValueError, IndexError):
        return 0


def parse_view_count(text):
    """Parse view count text like '1,234 views' to integer."""
    if not text:
        return 0
    text = text.replace(",", "").replace(" views", "").replace(" view", "").strip()
    try:
        if text.endswith("K"):
            return int(float(text[:-1]) * 1000)
        elif text.endswith("M"):
            return int(float(text[:-1]) * 1000000)
        elif text.endswith("B"):
            return int(float(text[:-1]) * 1000000000)
        else:
            return int(float(text))
    except (ValueError, IndexError):
        return 0


def search_youtube_channels(query, retries=2):
    """Search YouTube for channels matching query, return list of channel dicts."""
    # sp=EgIQAg%3D%3D is the filter for "Channels" type
    url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}&sp=EgIQAg%3D%3D"
    channels = []

    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return channels

            match = re.search(r'var ytInitialData = ({.*?});\s*</script>', resp.text)
            if not match:
                match = re.search(r'var ytInitialData = ({.*?});', resp.text)
            if not match:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return channels

            data = json.loads(match.group(1))
            contents = (data.get("contents", {})
                       .get("twoColumnSearchResultsRenderer", {})
                       .get("primaryContents", {})
                       .get("sectionListRenderer", {})
                       .get("contents", []))

            for section in contents:
                items = section.get("itemSectionRenderer", {}).get("contents", [])
                for item in items:
                    ch = item.get("channelRenderer", {})
                    if not ch:
                        continue

                    ch_id = ch.get("channelId", "")
                    if not ch_id:
                        continue

                    title = ch.get("title", {}).get("simpleText", "")

                    # Get subscriber text from subscriberCountText
                    sub_text = ch.get("subscriberCountText", {}).get("simpleText", "")

                    # Get handle from vanityUrl or ownerBadges
                    handle = ""
                    nav_endpoint = ch.get("navigationEndpoint", {}).get("browseEndpoint", {})
                    canonical = nav_endpoint.get("canonicalBaseUrl", "")
                    if canonical and canonical.startswith("/@"):
                        handle = canonical[1:]  # Remove leading /
                    elif canonical:
                        handle = canonical.replace("/", "")

                    # Get description snippet
                    desc_runs = ch.get("descriptionSnippet", {}).get("runs", [])
                    desc_text = "".join(r.get("text", "") for r in desc_runs)

                    # Video count
                    vid_count_text = ""
                    for overlay in ch.get("videoCountText", {}).get("runs", []):
                        vid_count_text += overlay.get("text", "")

                    channels.append({
                        "channel_id": ch_id,
                        "title": title,
                        "custom_url": handle,
                        "search_description": desc_text,
                        "sub_text": sub_text,
                        "video_count_text": vid_count_text,
                    })

            return channels

        except (json.JSONDecodeError, KeyError) as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            print(f"    [ERROR] Parse error: {e}")
            return channels
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            print(f"    [ERROR] Request error: {e}")
            return channels

    return channels


def get_channel_details(channel_id, handle=""):
    """Fetch detailed channel info from channel page."""
    if handle and handle.startswith("@"):
        url = f"https://www.youtube.com/{handle}"
    else:
        url = f"https://www.youtube.com/channel/{channel_id}"

    try:
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            return None

        match = re.search(r'var ytInitialData = ({.*?});\s*</script>', resp.text)
        if not match:
            match = re.search(r'var ytInitialData = ({.*?});', resp.text)
        if not match:
            return None

        data = json.loads(match.group(1))
        metadata = data.get("metadata", {}).get("channelMetadataRenderer", {})
        header = data.get("header", {})
        microformat = data.get("microformat", {}).get("microformatDataRenderer", {})

        title = metadata.get("title", "")
        description = metadata.get("description", "")
        vanity_url = metadata.get("vanityChannelUrl", "")

        # Extract handle from vanity URL
        handle_extracted = ""
        if vanity_url:
            m = re.search(r'/@([^/]+)', vanity_url)
            if m:
                handle_extracted = "@" + m.group(1)

        # Country from microformat
        countries = microformat.get("availableCountries", [])
        # Try to find country from metadata or description
        country = ""

        # Get subscriber count from page
        all_json = json.dumps(data)
        sub_text = ""
        sub_match = re.search(r'"(\d[\d,.]*[KMB]?) subscribers?"', all_json)
        if sub_match:
            sub_text = sub_match.group(1) + " subscribers"

        # Get video view counts from recent videos on channel page
        view_counts = []
        view_pattern = re.findall(r'"viewCountText":\s*\{"simpleText":\s*"([\d,.]+ views?)"', all_json)
        for v in view_pattern[:10]:
            view_counts.append(parse_view_count(v))

        # Also try short view count
        if len(view_counts) < 3:
            short_view_pattern = re.findall(r'"shortViewCountText":\s*\{"simpleText":\s*"([^"]+) views?"', all_json)
            for v in short_view_pattern[:10]:
                vc = parse_view_count(v + " views")
                if vc > 0:
                    view_counts.append(vc)

        # Get video count
        vid_count_match = re.search(r'"videosCountText":\s*\{"runs":\s*\[\{"text":\s*"([\d,]+)"', all_json)
        video_count = 0
        if vid_count_match:
            video_count = int(vid_count_match.group(1).replace(",", ""))

        # Try to find country from header metadata
        country_match = re.search(r'"country":\s*\{"simpleText":\s*"([^"]+)"', all_json)
        if country_match:
            country = country_match.group(1)

        # Extract emails from description
        emails = extract_emails(description)

        return {
            "title": title,
            "description": description,
            "custom_url": handle_extracted or handle,
            "youtube_link": vanity_url or f"https://www.youtube.com/channel/{channel_id}",
            "sub_text": sub_text,
            "subscribers": parse_sub_count(sub_text),
            "email": emails[0] if emails else "",
            "country": country,
            "video_count": video_count,
            "recent_view_counts": view_counts[:10],
        }

    except (json.JSONDecodeError, KeyError) as e:
        return None
    except requests.exceptions.RequestException as e:
        return None


def detect_language(description, country):
    if not description:
        description = ""
    desc_lower = description.lower()

    if any(w in desc_lower for w in ["español", "en español"]):
        return "Spanish"
    if any(w in desc_lower for w in ["português", "em português"]):
        return "Portuguese"
    if any(w in desc_lower for w in ["français", "en français"]):
        return "French"
    if any(w in desc_lower for w in ["deutsch", "auf deutsch"]):
        return "German"
    if any(w in desc_lower for w in ["hindi", "हिंदी", "हिन्दी"]):
        return "Hindi"

    country_map = {
        "Spain": "Spanish", "Mexico": "Spanish", "Argentina": "Spanish",
        "Colombia": "Spanish", "Chile": "Spanish", "Peru": "Spanish",
        "ES": "Spanish", "MX": "Spanish", "AR": "Spanish", "CO": "Spanish",
        "Brazil": "Portuguese", "Portugal": "Portuguese",
        "BR": "Portuguese", "PT": "Portuguese",
        "France": "French", "FR": "French",
        "Germany": "German", "Austria": "German", "DE": "German", "AT": "German",
        "India": "Hindi", "IN": "Hindi",
        "United States": "English", "United Kingdom": "English",
        "Canada": "English", "Australia": "English",
        "US": "English", "GB": "English", "CA": "English", "AU": "English",
    }

    if country and country in country_map:
        return country_map[country]

    spanish_words = ["cómo", "español", "automatización", "herramientas", "datos", "programación"]
    portuguese_words = ["como", "português", "automação", "ferramentas", "dados", "programação", "aula"]
    french_words = ["tutoriel", "comment", "français", "outils", "données"]
    german_words = ["anleitung", "deutsch", "werkzeuge", "daten", "automatisierung"]

    sp_count = sum(1 for w in spanish_words if w in desc_lower)
    pt_count = sum(1 for w in portuguese_words if w in desc_lower)
    fr_count = sum(1 for w in french_words if w in desc_lower)
    de_count = sum(1 for w in german_words if w in desc_lower)

    scores = {"Spanish": sp_count, "Portuguese": pt_count,
              "French": fr_count, "German": de_count}
    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best

    return "English"


def score_relevance(channel):
    score = 0.0
    text = ((channel.get("title", "") + " " + channel.get("description", "")).lower())

    kw_score = 0
    if any(kw in text for kw in DIRECT_KEYWORDS):
        kw_score = 4
    elif any(kw in text for kw in STRONG_ADJACENT):
        kw_score = 3
    elif any(kw in text for kw in MODERATE_ADJACENT):
        kw_score = 2
    elif any(kw in text for kw in WEAK_ADJACENT):
        kw_score = 1
    score += kw_score

    subs = channel.get("subscribers", 0)
    if 10000 <= subs <= 500000:
        score += 2
    elif 500000 < subs <= 2000000:
        score += 1

    er = channel.get("engagement_rate", 0)
    if er > 5:
        score += 2
    elif er >= 1:
        score += 1

    if channel.get("email"):
        score += 1

    lang = channel.get("language", "")
    if lang == "English":
        score += 1
    elif lang in ("Spanish", "Portuguese", "French", "German"):
        score += 0.5

    return min(score, 10)


def classify_content_type(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    if any(w in text for w in ["tutorial", "learn", "course", "how to", "guide", "teach"]):
        return "Tutorial"
    if any(w in text for w in ["review", "comparison", "best", "top"]):
        return "Review"
    if any(w in text for w in ["news", "update", "latest", "weekly"]):
        return "News"
    if any(w in text for w in ["podcast", "interview", "talk", "conversation"]):
        return "Podcast"
    return "Tutorial"


def classify_whale_potential(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    if any(kw in text for kw in ["enterprise", "business", "agency", "company",
                                  "scraping", "proxy", "data collection",
                                  "e-commerce", "brand protection",
                                  "ad verification"]):
        return "High"
    if any(kw in text for kw in ["automation", "bot", "seo", "monitoring",
                                  "competitive", "sneaker"]):
        return "Medium"
    return "Low"


def classify_audience_level(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    if any(w in text for w in ["enterprise", "business", "corporate", "agency"]):
        return "Enterprise"
    if any(w in text for w in ["professional", "advanced", "expert", "devops",
                                "data engineer"]):
        return "Professional"
    if any(w in text for w in ["beginner", "learn", "student", "course",
                                "introduction"]):
        return "Student"
    if any(w in text for w in ["small business", "smb", "freelance",
                                "solopreneur", "startup"]):
        return "SMB"
    return "Mixed"


def suggest_use_case(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    queries = channel.get("found_via", "").lower()
    combined = text + " " + queries

    if any(kw in combined for kw in ["ad verification", "ad fraud"]):
        return "Ad Verification"
    if any(kw in combined for kw in ["brand protection", "counterfeit"]):
        return "Brand Protection"
    if any(kw in combined for kw in ["serp", "rank tracker", "seo"]):
        return "SERP Tracking"
    if any(kw in combined for kw in ["price monitoring", "price tracking",
                                      "e-commerce", "ecommerce", "competitor price"]):
        return "Price Monitoring"
    if any(kw in combined for kw in ["sneaker bot", "sneaker proxy"]):
        return "Sneaker Proxies"
    if any(kw in combined for kw in ["instagram", "tiktok", "telegram",
                                      "social media automation", "social automation"]):
        return "Social Automation"
    if any(kw in combined for kw in ["data engineering", "etl", "data pipeline"]):
        return "Data Engineering"
    if any(kw in combined for kw in ["scraping", "scrape", "crawl", "proxy",
                                      "web crawl"]):
        return "Web Scraping"
    if any(kw in combined for kw in ["automation", "playwright", "puppeteer",
                                      "selenium", "n8n", "make.com"]):
        return "General Automation"
    if any(kw in combined for kw in ["osint", "penetration", "cybersecurity",
                                      "reconnaissance"]):
        return "Web Scraping"
    return "General Automation"


def main():
    progress = load_progress()
    channels = progress.get("channels", {})
    completed_queries = set(progress.get("completed_queries", []))

    # Flatten queries with tier info
    all_queries = []
    for tier, queries in SEARCH_QUERIES.items():
        for q in queries:
            all_queries.append((tier, q))

    # =========================================================
    # STEP 1: Search for channels
    # =========================================================
    print("=" * 60)
    print("STEP 1: Searching for channels via YouTube scraping")
    print("=" * 60)

    for tier, query in all_queries:
        if query in completed_queries:
            print(f"  [SKIP] Already completed: {query}")
            continue

        print(f"  [{tier}] Searching: {query}", end="", flush=True)

        found = search_youtube_channels(query)
        new_count = 0
        for ch in found:
            ch_id = ch["channel_id"]
            if ch_id not in channels:
                channels[ch_id] = {
                    "channel_id": ch_id,
                    "title": ch["title"],
                    "custom_url": ch.get("custom_url", ""),
                    "search_description": ch.get("search_description", ""),
                    "sub_text_search": ch.get("sub_text", ""),
                    "found_via": query,
                }
                new_count += 1
            else:
                existing = channels[ch_id].get("found_via", "")
                if query not in existing:
                    channels[ch_id]["found_via"] = existing + ", " + query

        print(f" -> {len(found)} results, {new_count} new (total: {len(channels)})")

        completed_queries.add(query)
        progress["completed_queries"] = list(completed_queries)
        progress["channels"] = channels
        save_progress(progress)
        time.sleep(1.5)  # Be polite to YouTube

    print(f"\n  Total unique channels from search: {len(channels)}")

    # =========================================================
    # STEP 2 & 3: Get channel details + recent video views
    # =========================================================
    print("\n" + "=" * 60)
    print("STEP 2-3: Getting channel details and video stats")
    print("=" * 60)

    channel_ids = list(channels.keys())
    fetched = 0
    total = len(channel_ids)

    for cid in channel_ids:
        ch = channels[cid]
        if ch.get("details_fetched"):
            fetched += 1
            continue

        handle = ch.get("custom_url", "")
        details = get_channel_details(cid, handle)

        if details:
            ch.update({
                "title": details["title"] or ch.get("title", ""),
                "description": details["description"],
                "custom_url": details["custom_url"] or ch.get("custom_url", ""),
                "youtube_link": details["youtube_link"],
                "subscribers": details["subscribers"],
                "email": details["email"],
                "country": details["country"],
                "video_count": details["video_count"],
                "recent_view_counts": details["recent_view_counts"],
            })

            # Calculate avg views and ER
            views = details["recent_view_counts"]
            avg_views = round(sum(views) / len(views)) if views else 0
            subs = details["subscribers"]
            er = round((avg_views / subs * 100), 2) if subs > 0 else 0

            ch["avg_views"] = avg_views
            ch["engagement_rate"] = er
        else:
            # Use search data as fallback
            ch.setdefault("description", ch.get("search_description", ""))
            ch.setdefault("subscribers", parse_sub_count(ch.get("sub_text_search", "")))
            ch.setdefault("youtube_link", f"https://www.youtube.com/channel/{cid}")
            ch.setdefault("avg_views", 0)
            ch.setdefault("engagement_rate", 0)
            ch.setdefault("email", "")
            ch.setdefault("country", "")
            ch.setdefault("video_count", 0)

        ch["details_fetched"] = True
        fetched += 1

        if fetched % 10 == 0:
            print(f"  Progress: {fetched}/{total} channels processed")
            progress["channels"] = channels
            save_progress(progress)

        time.sleep(1.0)  # Rate limiting

    progress["channels"] = channels
    save_progress(progress)
    print(f"  Completed: {fetched}/{total} channels processed")

    # =========================================================
    # STEP 4-7: Deduplicate, score, classify
    # =========================================================
    print("\n" + "=" * 60)
    print("STEP 4-7: Deduplicating, scoring, and classifying")
    print("=" * 60)

    results = []
    deduped_count = 0

    for cid, ch in channels.items():
        handle = ch.get("custom_url", "")
        # Check handle against existing list
        if handle:
            handle_check = handle if handle.startswith("@") else "@" + handle
            if handle_check.lower() in EXISTING_HANDLES_LOWER:
                deduped_count += 1
                continue

        ch["language"] = detect_language(ch.get("description", ""), ch.get("country", ""))
        ch["relevance_score"] = score_relevance(ch)
        ch["content_type"] = classify_content_type(ch)
        ch["whale_potential"] = classify_whale_potential(ch)
        ch["audience_level"] = classify_audience_level(ch)
        ch["suggested_use_case"] = suggest_use_case(ch)

        results.append(ch)

    print(f"  Removed {deduped_count} channels matching existing handles")
    print(f"  {len(results)} new unique channels remaining")

    results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    # =========================================================
    # STEP 8: Output CSV
    # =========================================================
    print("\n" + "=" * 60)
    print(f"STEP 8: Writing CSV to {OUTPUT_CSV}")
    print("=" * 60)

    csv_columns = [
        "Creator", "Username", "YouTube_Link", "Email", "Subscribers",
        "Views_per_video", "ER%", "Categories", "Country", "Description",
        "Language", "Relevance_Score", "Content_Type", "Whale_Potential",
        "Audience_Level", "Suggested_Use_Case", "Found_Via_Query", "Source",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_columns)
        writer.writeheader()
        for ch in results:
            writer.writerow({
                "Creator": ch.get("title", ""),
                "Username": ch.get("custom_url", ""),
                "YouTube_Link": ch.get("youtube_link", ""),
                "Email": ch.get("email", ""),
                "Subscribers": ch.get("subscribers", 0),
                "Views_per_video": ch.get("avg_views", 0),
                "ER%": ch.get("engagement_rate", 0),
                "Categories": ch.get("suggested_use_case", ""),
                "Country": ch.get("country", ""),
                "Description": (ch.get("description", "") or "")[:500],
                "Language": ch.get("language", ""),
                "Relevance_Score": ch.get("relevance_score", 0),
                "Content_Type": ch.get("content_type", ""),
                "Whale_Potential": ch.get("whale_potential", ""),
                "Audience_Level": ch.get("audience_level", ""),
                "Suggested_Use_Case": ch.get("suggested_use_case", ""),
                "Found_Via_Query": ch.get("found_via", ""),
                "Source": "Claude Code Discovery",
            })

    print(f"  Saved {len(results)} channels to {OUTPUT_CSV}")

    # =========================================================
    # STEP 9: Summary report
    # =========================================================
    print("\n" + "=" * 60)
    print("SUMMARY REPORT")
    print("=" * 60)

    top_tier = [r for r in results if r.get("relevance_score", 0) >= 8]
    mid_tier = [r for r in results if 6 <= r.get("relevance_score", 0) < 8]
    low_tier = [r for r in results if r.get("relevance_score", 0) < 6]

    print(f"\n  Total new unique channels found: {len(results)}")
    print(f"  Channels with score >= 8 (top tier): {len(top_tier)}")
    print(f"  Channels with score 6-7 (worth reviewing): {len(mid_tier)}")
    print(f"  Channels with score < 6 (low priority): {len(low_tier)}")

    print("\n  Breakdown by Suggested Use Case:")
    use_case_counts = {}
    for r in results:
        uc = r.get("suggested_use_case", "Unknown")
        use_case_counts[uc] = use_case_counts.get(uc, 0) + 1
    for uc, count in sorted(use_case_counts.items(), key=lambda x: -x[1]):
        print(f"    {uc}: {count}")

    print("\n  Breakdown by Language:")
    lang_counts = {}
    for r in results:
        lang = r.get("language", "Unknown")
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
        print(f"    {lang}: {count}")

    print("\n  Top 20 Channels:")
    print(f"  {'#':<4} {'Name':<35} {'Subs':<12} {'ER%':<8} {'Score':<7} {'Use Case'}")
    print("  " + "-" * 100)
    for i, ch in enumerate(results[:20], 1):
        name = ch.get("title", "")[:33]
        subs = ch.get("subscribers", 0)
        er = ch.get("engagement_rate", 0)
        score = ch.get("relevance_score", 0)
        uc = ch.get("suggested_use_case", "")
        if subs >= 1000000:
            subs_str = f"{subs/1000000:.1f}M"
        elif subs >= 1000:
            subs_str = f"{subs/1000:.1f}K"
        else:
            subs_str = str(subs)
        print(f"  {i:<4} {name:<35} {subs_str:<12} {er:<8.2f} {score:<7} {uc}")

    print("\n" + "=" * 60)
    print("Discovery complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
