#!/usr/bin/env python3
"""
YouTube Influencer Discovery V2 for DataImpulse
Uses web scraping (no API quota needed) with all V2 bugfixes:
  - Relevance validation (prevents false positives)
  - ER% capped at 100%
  - Minimum 500 subscribers
  - Competitor detection → separate CSV
  - Company/tool channel detection → separate CSV
  - Rejected channels log with reasons
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

TODAY = datetime.now().strftime("%Y-%m-%d")
PROGRESS_FILE = "discovery_v2_progress.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)
session.verify = False

# Proxy config (fallback if direct blocked)
PROXY_URL = "http://c607101cbc744679901d_country-us:71addcef09210b43@gw.dataimpulse.com:823"
USE_PROXY = False  # Will toggle on if direct access gets blocked

EMAIL_REGEX = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

# ── Search queries by tier ──────────────────────────────────────────────────
QUERIES = {
    "Tier 1 - Core proxy/scraping": [
        "web scraping tutorial", "web scraping python",
        "residential proxy tutorial", "data scraping tools",
        "scraping automation", "python automation tutorial",
        "web crawling tutorial", "no code web scraping",
        "scrape website python", "web scraping proxies",
        "proxy for web scraping", "scraping proxies",
    ],
    "Tier 2 - Semantic core": [
        "telegram proxy tutorial", "proxy for telegram setup",
        "serp scraper api tutorial", "rank tracker proxies",
        "proxies for SEO tutorial", "google scraping proxies",
        "ad verification proxy", "proxies for ad verification",
        "proxies for brand protection", "proxies for price monitoring",
        "sneaker proxies tutorial", "residential sneaker proxies",
        "proxy for discord setup", "geo targeted proxies tutorial",
        "what is residential proxy", "datacenter vs residential proxies",
        "mobile proxy tutorial",
    ],
    "Tier 3 - Competitor review": [
        "bright data review", "bright data tutorial",
        "oxylabs review", "scraperapi review", "scraperapi tutorial",
        "smartproxy review", "apify tutorial", "multilogin review",
        "iproyal review", "webshare proxy review", "netnut proxy review",
    ],
    "Tier 4 - Technical audience": [
        "sneaker bot tutorial", "sneaker bot proxy setup",
        "instagram automation bot", "telegram bot tutorial python",
        "tiktok automation tools", "social media automation tools",
        "data engineering tutorial", "ETL pipeline tutorial",
        "data pipeline python", "API scraping tutorial",
        "OSINT tools tutorial", "penetration testing reconnaissance",
        "cybersecurity tools tutorial",
    ],
    "Tier 5 - Browser automation": [
        "puppeteer web scraping", "puppeteer browser automation",
        "playwright web scraping", "playwright browser automation",
        "selenium web scraping advanced", "n8n automation tutorial",
        "make.com automation tutorial", "browser automation scraping",
        "antidetect browser tutorial",
    ],
    "Tier 6 - Non-English": [
        "web scraping tutorial español", "web scraping python español",
        "automatización web python", "web scraping tutorial português",
        "automação web python", "web scraping Python deutsch",
        "automatisierung Python deutsch", "web scraping tutoriel français",
        "scraping données python", "web scraping tutorial hindi",
    ],
}

# ── Existing handles to skip ────────────────────────────────────────────────
EXISTING_HANDLES = {h.lower().lstrip('@') for h in [
    "@0x5am5","@100xEngineers","@AI_Genix4","@AI_Zayan","@Abdelmalekmessaoudi",
    "@Adanghd","@AdrianSaenz","@AiFinder11","@AkamaiDeveloper","@Alex.Followell",
    "@AliAbdaal","@AliShahin","@AllTipsBoss","@AmirDiscoveries","@AmyWang",
    "@AndreasSpiess","@AnkitArora","@AppFind","@AriellePhoenix","@AthleticInterest",
    "@Augmented_AI","@AureliusTjin","@Azerbaijan","@BadrAlhanaky","@BangTutorial",
    "@BeerMoneyForum","@Betechco","@BilawalSidhu","@BillyHowell","@Block-Chain-World",
    "@BrianJung","@BrototypeMalayalam","@BuildersCentral","@BusyFunda","@Buzz2dayTech",
    "@CalebHammer","@CaspianReport","@ChrisKoerner","@ChromeDevs","@ClicksDontLie",
    "@CodeWithHarry","@Codepur","@Codevolution","@Codezilla","@CodingPhase",
    "@CodingWithLewis","@ComputerGeeks","@CreatorMagicAI","@CryptoGeographic",
    "@CryptoMK","@CuttingEdgeSchool","@CyberWithBen","@DIGITALPIYUSH","@Daniel-Dann",
    "@DanielDavidson","@DataCamp","@DavidCantone","@DesignCourse","@DocWilliams",
    "@DopeMotions","@DrVegan","@DvLZStaTioN","@EarningsCircuitAI",
    "@EconomicsExplained","@EddyBallesteros","@EliRigobeliAI","@ElliotChoy",
    "@EmprendeAprendiendo","@EricStruk","@EricWTech","@ErikaKullberg",
    "@FLICKETCRYPTO","@FactoHolic","@FaijulIslam68","@FazeelUsmaniOfficial",
    "@FaztTech","@FelipeVergara","@Fireship","@ForrestKnight","@GaoDalie_AI",
    "@GeekWork","@Get365AI","@GrahamStephan","@GreatStack","@HINDZ",
    "@HacksmithIndustries","@HarryLee","@HealthwithCory","@HenryBelcaster",
    "@HistoryoftheUniverse","@HocVienMarketingOnlineAI","@HolaMundoDev",
    "@HoradeNegcios","@HowMoneyWorks","@HowTech1","@HozhiLearn",
    "@HrishikeshRoyOfficial","@Hyeser","@InsideYourHustle","@InstantlyAI",
    "@InternetMadeCoder","@IshanSharma","@Itssssss_Jack","@JackGordon",
    "@JacobLee","@JashRadia","@JeffSu","@JennyHoyos","@JessRamosData",
    "@JoCoding","@JoeColantonio","@JooCurry","@JoshArt","@JoshMadakor",
    "@KSRDatavizon","@KarineLago","@KelasTerbuka","@KenjiExplains",
    "@KitbogaShow","@KiunB","@Konstantinos","@KunalKushwaha","@KyleFrielTech",
    "@LastMomentTuitions","@LewLater","@LewisHowes","@LiamOttley",
    "@LightsOnData","@LindaRaynier","@LinusMediaGroup","@LoganSkiFinance",
    "@LogicallyAnswered","@LuanaFranco","@LucasMontano","@LuckyStudios76",
    "@LuisUrrutia","@MagnatesMedia","@MarcoBucciArt","@MariRel","@MarieStella",
    "@MarinaMogilko","@MarkTilbury","@MaxTechOfficial","@MedSchoolInsiders",
    "@MersudinForbes","@MerveOzkaynak","@Meta4sec","@MeticsMedia","@MidasTomi",
    "@MikeDee","@MikeyNoCode","@MrGrowth","@NIIT_Limited","@NareshIT",
    "@NerdsdeNegcios","@NetMentor","@NeuralNine",
    "@NiallMacMillanTheAwkwardPOVGuy",
    "@NikhilPawarMotionDesignerAICreator","@NishantChahar11","@NoCodeMBA",
    "@OMilionrio","@Octoparsewebscraping","@OneSkillPowerPoint",
    "@OnlineWebTutor","@PapayaCoders","@PaulDickson7","@PaytonClarkSmith",
    "@PijushSahaBD","@Polyfjord","@PriaMasaDepan","@PritikaLoonia",
    "@ProgramadorX","@PythonSimplified","@QuangLeLife","@RafaelPantoja",
    "@RajPhotoEditingandMuchMore","@Rajeevdaz","@RobShocks","@RoboNuggets",
    "@Romania","@SailingSVDelos","@ShaneHummus","@SinghinUSA","@SleepyCatHey",
    "@Snovio","@Socialselleracademy","@Sop","@StewartGauld",
    "@StudyAutomationAcademy","@SundasKhalid","@SupplyScience","@SwaroopVITB",
    "@THEECOMKING","@TechGo6","@TechInRealEstate","@TechWithTim",
    "@Techscope01","@TheCodingBus","@TheIcedCoffeeHour","@TheMetaverseGuy",
    "@ThePptPro","@ThioJoe","@TiagoCurcio","@TinaHuang1","@Tooltester",
    "@UTHMANSTECHHUB","@Upflip","@UskoKruM2010","@VaibhavJain","@VarunMayya",
    "@Vchannel79","@VensyKrishna","@VirtualTechBox","@WebsiteLearners",
    "@YoussefNejjari","@Zero2LaunchAI","@_katiepeake","@aEscoladeSites",
    "@affiliatemarketingdude","@agustinmedinaIA","@aimevzulari",
    "@alejavirivera","@ambitious1z","@andylokcl","@atefataya",
    "@basic.techtube","@bassemmagdy0","@batuhandurmaz-seo","@bigboxSWE",
    "@bigpoppacode","@boualiali","@boxput","@brunobelissimoai","@bycloudAI",
    "@charliebarberbiz","@codebasics","@codewithjoshoffical","@codigofontetv",
    "@dailylifereviews98","@dansmarttutorials","@davidbombal","@deaafrizal",
    "@decodingyt","@derekcheungsa","@drantunes","@drissas","@droidcrunch",
    "@elephorm","@elestio","@elimaurtua","@emiliatalexandre",
    "@empreendedorserial","@eugenekadzin","@f.fontoura","@frank_moss",
    "@graceatwood","@grillodesigns","@harkirat1","@hasanaboulhasan",
    "@highpartymusic","@hivecorp","@holoconnect228","@igorzuevich",
    "@iishtheceo","@intheworldofai","@jasoncooperson","@jessecunninghamv",
    "@jojol","@jonocatliff","@jovensdenegocios","@kingy-ai","@kingyAI",
    "@knowledge4all","@krishnaik06","@leonardogrig","@letscodewithavinash",
    "@maddy_gutierrez_","@malkhatib","@manodeyvin","@mdalmamunit427",
    "@meetdavidalex","@meetusama","@mehulmpt","@michtortiyt","@midudev",
    "@mikimikiweb","@mostafanouman","@mr_web","@mrait","@mreflow",
    "@munchdine","@n8n-io","@nateherk","@nerdsdenegocios","@ninjadoexcel",
    "@notjustdev","@nyesworldTV","@oliviahamerwebb","@ondeeuclico",
    "@onezyhcn","@oxylabs","@pildorasinformaticas","@polcorominas",
    "@procodrr","@promptwarrior","@quantroom","@reeceisrandom",
    "@ryiyshacker","@sankyverse","@scottdclary","@simonscrapes","@spunkram",
    "@starterstory","@stylistunnie","@sudhanshuedu","@syntaxfm",
    "@talkmoneywithpavan","@techwithazizul","@teknikforce","@theaerogr",
    "@theicai","@thomasjanssen-tech","@timdessaint","@timexplainsai",
    "@tinotech01","@trickpilott","@victorroblesweb","@vinceopra",
    "@vuduchong","@wscubetech","@yulittle6079","@zCaxap","@zinhoautomates",
    # V1 found channels
    "@JohnWatsonRooney","@DEW-Automatisation","@Apify","@thepycoachES",
    "@scrapebox","@aiautomationkit","@the-web-scraping-guy","@ParsehubApp",
    "@sdetpavan","@AutomatewithRakesh","@Pythonclcoding","@planetnocode",
    "@VincentDoAI","@automation-tribe","@AnshLambaJSR","@itversity",
    "@afaqueahmad7117","@learnbydoingit","@LearnAutomationOnline",
    "@OSINTDojo","@Bendobrown","@CyberSudoYT","@TraceLabsVideos",
    "@sikholive","@WsCubeCyberSecurity","@testautomation999",
    "@HaradhanAutomationLibrary","@AI-GPTWorkshop","@EdHillAI","@KiaGhasem",
    "@itsmake","@maxvcollenburg","@_jimmyrose",
    "@AutomatizaConMakeIntegromat","@nicksaraev","@RaghavPal",
    "@Playwrightdev","@KameleoTeam","@capsolver","@SeleniumExpress",
    "@ai-automation-station","@jsautomates",
]}

# ── Tech keywords for relevance validation ───────────────────────────────────
TECH_KEYWORDS = [
    "scraping", "scrape", "proxy", "proxies", "automation", "automate",
    "bot", "crawler", "crawling", "data extraction", "web data", "seo",
    "serp", "api", "antidetect", "anti-detect", "residential ip", "captcha",
    "browser automation", "selenium", "playwright", "puppeteer", "n8n",
    "make.com", "zapier", "python", "programming", "coding", "code",
    "cybersecurity", "ethical hack", "osint", "penetration test", "pentest",
    "e-commerce", "ecommerce", "price monitor", "ad verification",
    "brand protection", "sneaker", "data engineer", "etl", "pipeline",
    "telegram bot", "machine learning", "artificial intelligence", "ai tool",
    "no-code", "nocode", "web development", "javascript", "react", "node",
    "devops", "cloud", "rest", "graphql", "software", "developer",
    "tutorial", "tech",
]

# ── Competitor detection ─────────────────────────────────────────────────────
COMPETITOR_DESC_PHRASES = [
    "proxy provider", "proxy service", "our proxies", "buy proxy",
    "proxy solution", "proxy network", "residential proxy", "rotating proxy",
    "datacenter proxy", "mobile proxy", "proxy pool", "proxy plan", "million ip",
]

COMPETITOR_BRAND_SUBSTRINGS = [
    "proxy4u", "711proxy", "lunaproxy", "iproyal", "proxystore", "proxyempire",
    "proxy-cheap", "pyproxy", "ip2world", "yiluproxy", "swiftproxy", "resiprox",
    "alertproxies", "mobilehop", "cloudrouter", "fleetproxy", "proxylink",
    "proxywing", "proxyjet", "proxybdix", "nocturnal", "lightningprox",
    "cloudproxylab", "bestproxy", "piaproxy", "kiotproxy", "xproxy",
    "realproxybot", "decodo", "smartproxy", "abcproxy", "starvpn", "9proxy",
    "metroproxy", "saglamproxy", "okkproxy", "dataimpulse",
]

# ── Company/tool channel detection ──────────────────────────────────────────
COMPANY_DESC_PHRASES = [
    "our platform", "our tool", "our product", "we offer", "we provide",
    "our api", "sign up", "try for free", "get started", "pricing",
    "free trial", "our service", "our solution", "download our",
    "our software", "enterprise", "start your free",
]

KNOWN_COMPANY_NAMES = {n.lower() for n in [
    "Apify", "ParseHub", "Make", "Playwright", "ScrapeOps", "ScraperAPI",
    "SerpApi", "Crawlbase", "BrightLocal", "Scrapeless", "Kameleo",
    "CapSolver", "Ideogram", "DataForSEO", "ScrapeGraphAI", "Parsera",
    "Octoparse", "Robomotion", "Pixalate", "BotBee",
]}

# ── Scoring keyword tiers ────────────────────────────────────────────────────
DIRECT_PROXY_SCRAPING = [
    "scraping", "scrape", "proxy", "proxies", "web scraping", "data extraction",
    "crawler", "crawling", "residential proxy", "rotating proxy",
]
STRONG_ADJACENT = [
    "automation", "automate", "bot", "seo", "serp", "osint",
    "ad verification", "brand protection", "e-commerce", "ecommerce",
    "price monitor", "antidetect", "anti-detect", "sneaker",
]
MODERATE_ADJACENT = [
    "python", "cybersecurity", "no-code", "nocode", "testing",
    "data engineer", "etl", "pipeline", "pentest", "penetration test",
]
WEAK_ADJACENT = [
    "coding", "code", "programming", "ai tool", "machine learning",
    "web development", "javascript", "react", "devops", "cloud",
]


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def extract_emails(text):
    if not text:
        return []
    emails = EMAIL_REGEX.findall(text)
    filtered = []
    for e in emails:
        lower = e.lower()
        if any(lower.endswith(ext) for ext in ['.png', '.jpg', '.gif', '.svg', '.jpeg', '.webp']):
            continue
        filtered.append(e)
    return filtered


def parse_sub_count(text):
    """Parse subscriber count text like '104K subscribers' to integer."""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    text = re.sub(r'\s*subscribers?\s*', '', text, flags=re.I).strip()
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
    text = text.replace(",", "")
    text = re.sub(r'\s*views?\s*', '', text, flags=re.I).strip()
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


def fetch_page(url, retries=3):
    """Fetch a page with retries; falls back to proxy if direct fails."""
    global USE_PROXY
    for attempt in range(retries):
        try:
            kwargs = {"timeout": 25}
            if USE_PROXY:
                kwargs["proxies"] = {
                    "http": PROXY_URL,
                    "https": PROXY_URL,
                }
            resp = session.get(url, **kwargs)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 429:
                wait = min(5 * (attempt + 1), 30)
                print(f"    [429 Rate limited] Waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                # Try enabling proxy
                if not USE_PROXY:
                    print("    [403] Trying with proxy...")
                    USE_PROXY = True
                    continue
                time.sleep(3)
                continue
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"    [ERROR] {e}")
    return None


def text_contains_keywords(text, keywords):
    """Return list of keywords found in text (case-insensitive)."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


# ═══════════════════════════════════════════════════════════════════════════
# YOUTUBE SCRAPING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def search_youtube_channels(query):
    """Search YouTube for channels matching query."""
    url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}&sp=EgIQAg%3D%3D"
    channels = []

    html = fetch_page(url)
    if not html:
        return channels

    match = re.search(r'var ytInitialData = ({.*?});\s*</script>', html)
    if not match:
        match = re.search(r'var ytInitialData = ({.*?});', html)
    if not match:
        return channels

    try:
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
                sub_text = ch.get("subscriberCountText", {}).get("simpleText", "")
                handle = ""
                canonical = ch.get("navigationEndpoint", {}).get("browseEndpoint", {}).get("canonicalBaseUrl", "")
                if canonical and canonical.startswith("/@"):
                    handle = canonical[1:]
                elif canonical:
                    handle = canonical.replace("/", "")

                desc_runs = ch.get("descriptionSnippet", {}).get("runs", [])
                desc_text = "".join(r.get("text", "") for r in desc_runs)

                channels.append({
                    "channel_id": ch_id,
                    "title": title,
                    "handle": handle,
                    "search_description": desc_text,
                    "sub_text": sub_text,
                    "subscribers_approx": parse_sub_count(sub_text),
                })
    except (json.JSONDecodeError, KeyError) as e:
        print(f"    [PARSE ERROR] {e}")

    return channels


def get_channel_details(channel_id, handle=""):
    """Fetch detailed channel info from channel page."""
    if handle and handle.startswith("@"):
        url = f"https://www.youtube.com/{handle}"
    else:
        url = f"https://www.youtube.com/channel/{channel_id}"

    html = fetch_page(url)
    if not html:
        return None

    match = re.search(r'var ytInitialData = ({.*?});\s*</script>', html)
    if not match:
        match = re.search(r'var ytInitialData = ({.*?});', html)
    if not match:
        return None

    try:
        data = json.loads(match.group(1))
        metadata = data.get("metadata", {}).get("channelMetadataRenderer", {})
        microformat = data.get("microformat", {}).get("microformatDataRenderer", {})

        title = metadata.get("title", "")
        description = metadata.get("description", "")
        vanity_url = metadata.get("vanityChannelUrl", "")

        handle_extracted = ""
        if vanity_url:
            m = re.search(r'/@([^/]+)', vanity_url)
            if m:
                handle_extracted = "@" + m.group(1)

        all_json_str = json.dumps(data)

        # Subscriber count
        sub_text = ""
        sub_match = re.search(r'"(\d[\d,.]*[KMB]?) subscribers?"', all_json_str)
        if sub_match:
            sub_text = sub_match.group(1) + " subscribers"

        # View counts from recent videos
        view_counts = []
        view_pattern = re.findall(
            r'"viewCountText":\s*\{"simpleText":\s*"([\d,.]+ views?)"', all_json_str
        )
        for v in view_pattern[:10]:
            view_counts.append(parse_view_count(v))
        if len(view_counts) < 3:
            short_pattern = re.findall(
                r'"shortViewCountText":\s*\{"simpleText":\s*"([^"]+) views?"', all_json_str
            )
            for v in short_pattern[:10]:
                vc = parse_view_count(v + " views")
                if vc > 0:
                    view_counts.append(vc)

        # Video count
        vid_count_match = re.search(
            r'"videosCountText":\s*\{"runs":\s*\[\{"text":\s*"([\d,]+)"', all_json_str
        )
        video_count = 0
        if vid_count_match:
            video_count = int(vid_count_match.group(1).replace(",", ""))

        # Country
        country = ""
        country_match = re.search(r'"country":\s*\{"simpleText":\s*"([^"]+)"', all_json_str)
        if country_match:
            country = country_match.group(1)

        # Recent video titles (for validation)
        video_titles = []
        title_matches = re.findall(
            r'"title":\s*\{"runs":\s*\[\{"text":\s*"([^"]{5,120})"', all_json_str
        )
        # Filter out non-video titles (channel name etc)
        seen = set()
        for t in title_matches:
            t_clean = t.strip()
            if t_clean.lower() == title.lower():
                continue
            if t_clean not in seen and len(t_clean) > 5:
                seen.add(t_clean)
                video_titles.append(t_clean)
            if len(video_titles) >= 10:
                break

        emails = extract_emails(description)

        return {
            "title": title,
            "description": description,
            "handle": handle_extracted or handle,
            "youtube_link": vanity_url or f"https://www.youtube.com/channel/{channel_id}",
            "sub_text": sub_text,
            "subscribers": parse_sub_count(sub_text),
            "email": emails[0] if emails else "",
            "country": country,
            "video_count": video_count,
            "recent_view_counts": view_counts[:10],
            "recent_video_titles": video_titles[:10],
        }
    except (json.JSONDecodeError, KeyError) as e:
        print(f"    [PARSE ERROR channel details] {e}")
        return None


def get_video_titles_from_videos_tab(channel_id, handle=""):
    """Fetch video titles from channel's videos tab (fallback for validation)."""
    if handle and handle.startswith("@"):
        url = f"https://www.youtube.com/{handle}/videos"
    else:
        url = f"https://www.youtube.com/channel/{channel_id}/videos"

    html = fetch_page(url)
    if not html:
        return []

    match = re.search(r'var ytInitialData = ({.*?});\s*</script>', html)
    if not match:
        match = re.search(r'var ytInitialData = ({.*?});', html)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
        all_json_str = json.dumps(data)
        titles = []
        title_matches = re.findall(
            r'"title":\s*\{"runs":\s*\[\{"text":\s*"([^"]{5,120})"', all_json_str
        )
        seen = set()
        for t in title_matches:
            t_clean = t.strip()
            if t_clean not in seen and len(t_clean) > 5:
                seen.add(t_clean)
                titles.append(t_clean)
            if len(titles) >= 5:
                break
        return titles
    except (json.JSONDecodeError, KeyError):
        return []


# ═══════════════════════════════════════════════════════════════════════════
# CLASSIFICATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def validate_relevance(channel):
    """
    Validate channel tech relevance. Returns (is_relevant, reason).
    Checks description first, then video titles if needed.
    """
    desc = channel.get("description", "")
    desc_matches = text_contains_keywords(desc, TECH_KEYWORDS)
    if desc_matches:
        return True, f"Description matches: {', '.join(desc_matches[:5])}"

    # Check video titles from channel page data
    video_titles = channel.get("recent_video_titles", [])
    if video_titles:
        title_match_count = 0
        for t in video_titles[:5]:
            if text_contains_keywords(t, TECH_KEYWORDS):
                title_match_count += 1
        if title_match_count >= 2:
            return True, f"{title_match_count}/{min(len(video_titles),5)} video titles match tech keywords"

    # Last resort: fetch videos tab
    video_titles_fetched = get_video_titles_from_videos_tab(
        channel.get("channel_id", ""), channel.get("handle", "")
    )
    if video_titles_fetched:
        title_match_count = 0
        for t in video_titles_fetched[:5]:
            if text_contains_keywords(t, TECH_KEYWORDS):
                title_match_count += 1
        if title_match_count >= 2:
            return True, f"{title_match_count}/{len(video_titles_fetched)} fetched video titles match"

    return False, "No tech relevance found in description or recent videos"


def is_competitor(channel):
    """Check if a channel is a competitor proxy service."""
    desc_lower = channel.get("description", "").lower()
    name_slug = (channel.get("title", "") + " " + channel.get("handle", "")).lower()
    name_slug = name_slug.replace(" ", "").replace("-", "").replace("_", "")

    for brand in COMPETITOR_BRAND_SUBSTRINGS:
        if brand in name_slug:
            return True, f"Brand match: {brand}"

    matches = text_contains_keywords(desc_lower, COMPETITOR_DESC_PHRASES)
    if len(matches) >= 2:
        return True, f"Description competitor phrases: {', '.join(matches[:3])}"

    return False, ""


def is_company_channel(channel):
    """Check if a channel is an official company/tool channel."""
    name_lower = channel.get("title", "").lower().strip()
    handle_lower = channel.get("handle", "").lower().lstrip("@")

    for company in KNOWN_COMPANY_NAMES:
        if name_lower == company or handle_lower == company:
            return True, f"Known company: {company}"

    desc_lower = channel.get("description", "").lower()
    matches = text_contains_keywords(desc_lower, COMPANY_DESC_PHRASES)
    if len(matches) >= 2:
        return True, f"Company phrases: {', '.join(matches[:3])}"

    return False, ""


def detect_language(description, country):
    """Detect channel language from description and country."""
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
        "Russia": "Russian", "RU": "Russian",
        "Indonesia": "Indonesian", "ID": "Indonesian",
        "Turkey": "Turkish", "TR": "Turkish",
        "Japan": "Japanese", "JP": "Japanese",
        "South Korea": "Korean", "KR": "Korean",
    }
    if country and country in country_map:
        return country_map[country]

    spanish_words = ["cómo", "automatización", "herramientas", "datos", "programación"]
    portuguese_words = ["automação", "ferramentas", "dados", "programação", "aula"]
    french_words = ["tutoriel", "comment", "outils", "données"]
    german_words = ["anleitung", "werkzeuge", "daten", "automatisierung"]

    sp = sum(1 for w in spanish_words if w in desc_lower)
    pt = sum(1 for w in portuguese_words if w in desc_lower)
    fr = sum(1 for w in french_words if w in desc_lower)
    de = sum(1 for w in german_words if w in desc_lower)
    scores = {"Spanish": sp, "Portuguese": pt, "French": fr, "German": de}
    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best

    return "English"


def score_relevance(channel):
    """Calculate relevance score 0-10."""
    score = 0.0
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    subs = channel.get("subscribers", 0)
    er = channel.get("er_pct", 0)

    # Content relevance (0-4)
    if text_contains_keywords(text, DIRECT_PROXY_SCRAPING):
        score += 4
    elif text_contains_keywords(text, STRONG_ADJACENT):
        score += 3
    elif text_contains_keywords(text, MODERATE_ADJACENT):
        score += 2
    elif text_contains_keywords(text, WEAK_ADJACENT):
        score += 1

    # Audience size (0-2)
    if 10000 <= subs <= 500000:
        score += 2
    elif (5000 <= subs < 10000) or (500000 < subs <= 2000000):
        score += 1

    # Engagement rate (0-2)
    if er >= 5:
        score += 2
    elif er >= 1:
        score += 1

    # Contactability (0-1)
    if channel.get("email"):
        score += 1

    # Language bonus (0-1)
    lang = channel.get("language", "")
    if lang == "English":
        score += 1
    elif lang in ("Spanish", "Portuguese", "French", "German", "Hindi"):
        score += 0.5

    return min(round(score, 1), 10.0)


def classify_content_type(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    if any(w in text for w in ["review", "comparison", "vs ", "versus", "compare"]):
        return "Review"
    if any(w in text for w in ["tutorial", "learn", "course", "how to", "guide"]):
        return "Tutorial"
    if any(w in text for w in ["news", "update", "latest", "weekly"]):
        return "News"
    if any(w in text for w in ["podcast", "interview", "talk"]):
        return "Podcast"
    return "Tutorial"


def classify_whale_potential(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    if any(kw in text for kw in ["scraping", "proxy", "e-commerce", "ecommerce",
                                  "sneaker", "ad verification", "brand protection",
                                  "price monitor", "data collection"]):
        return "High"
    if any(kw in text for kw in ["automation", "bot", "seo", "serp", "data",
                                  "osint", "cybersecurity", "monitoring"]):
        return "Medium"
    return "Low"


def classify_audience_level(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    if any(w in text for w in ["enterprise", "business", "corporate", "agency"]):
        return "Enterprise"
    if any(w in text for w in ["professional", "advanced", "expert", "devops", "data engineer"]):
        return "Professional"
    if any(w in text for w in ["small business", "smb", "freelance", "startup"]):
        return "SMB"
    if any(w in text for w in ["beginner", "learn", "student", "course", "introduction"]):
        return "Student"
    return "Mixed"


def suggest_use_case(channel):
    text = (channel.get("title", "") + " " + channel.get("description", "")).lower()
    queries = " ".join(channel.get("found_via", [])).lower()
    combined = text + " " + queries

    if any(kw in combined for kw in ["ad verification", "ad fraud"]):
        return "Ad Verification"
    if any(kw in combined for kw in ["brand protection", "counterfeit"]):
        return "Brand Protection"
    if any(kw in combined for kw in ["serp", "rank tracker"]):
        return "SERP Tracking"
    if "seo" in combined and "serp" not in combined:
        return "SERP Tracking"
    if any(kw in combined for kw in ["price monitor", "price track", "e-commerce", "ecommerce"]):
        return "Price Monitoring"
    if any(kw in combined for kw in ["sneaker bot", "sneaker prox"]):
        return "Sneaker Proxies"
    if any(kw in combined for kw in ["instagram", "tiktok", "telegram", "social media automation", "discord"]):
        return "Social Automation"
    if any(kw in combined for kw in ["data engineer", "etl", "data pipeline"]):
        return "Data Engineering"
    if any(kw in combined for kw in ["osint", "penetration", "cybersecurity", "recon"]):
        return "OSINT"
    if any(kw in combined for kw in ["bright data", "oxylabs", "smartproxy", "iproyal",
                                      "scraperapi", "webshare", "netnut", "multilogin"]):
        return "Competitor Review"
    if any(kw in combined for kw in ["scraping", "scrape", "crawl", "proxy", "web crawl"]):
        return "Web Scraping"
    if any(kw in combined for kw in ["automation", "playwright", "puppeteer",
                                      "selenium", "n8n", "make.com", "browser automation"]):
        return "General Automation"
    return "General Automation"


# ═══════════════════════════════════════════════════════════════════════════
# PROGRESS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def save_progress(data):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"completed_queries": [], "channels": {}, "rejected": [],
            "detailed": [], "validated": []}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  YouTube Influencer Discovery V2 for DataImpulse")
    print(f"  Date: {TODAY}")
    print(f"  Fixes: validation, ER cap, min 500 subs, competitor/company split")
    print("=" * 70)

    progress = load_progress()
    channels = progress.get("channels", {})       # channel_id -> basic info
    completed_queries = set(progress.get("completed_queries", []))
    rejected = progress.get("rejected", [])
    detailed_ids = set(progress.get("detailed", []))
    validated_ids = set(progress.get("validated", []))

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1-2: Search for channels & deduplicate
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 1-2] Searching for channels and deduplicating")
    print("=" * 70)

    total_queries = sum(len(v) for v in QUERIES.values())
    query_num = 0

    for tier, queries in QUERIES.items():
        print(f"\n  --- {tier} ---")
        for query in queries:
            query_num += 1
            if query in completed_queries:
                print(f"  [{query_num}/{total_queries}] SKIP (cached): {query}")
                continue

            print(f"  [{query_num}/{total_queries}] Searching: {query}", end="", flush=True)
            time.sleep(1.5)  # Rate limit between searches

            results = search_youtube_channels(query)
            new_count = 0
            for ch in results:
                cid = ch["channel_id"]
                if cid in channels:
                    if query not in channels[cid].get("found_via", []):
                        channels[cid]["found_via"].append(query)
                else:
                    channels[cid] = {
                        "channel_id": cid,
                        "title": ch["title"],
                        "handle": ch.get("handle", ""),
                        "search_description": ch.get("search_description", ""),
                        "subscribers_approx": ch.get("subscribers_approx", 0),
                        "found_via": [query],
                        "status": "new",
                    }
                    new_count += 1

            print(f"  → {len(results)} results, {new_count} new")
            completed_queries.add(query)
            progress["completed_queries"] = list(completed_queries)
            progress["channels"] = channels
            save_progress(progress)

    total_raw = len(channels)
    print(f"\n  Total unique channels after search: {total_raw}")

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: Filter <500 subs (early filter using search page data)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 3] Early filter: skip channels with <500 subs from search")
    print("=" * 70)

    # Also filter existing handles early
    skip_existing = 0
    skip_low_subs = 0
    to_detail = []

    for cid, ch in channels.items():
        if ch.get("status") in ("detailed", "filtered", "rejected"):
            if ch.get("status") == "detailed":
                to_detail.append(cid)  # Already detailed, carry forward
            continue

        handle = ch.get("handle", "").lower().lstrip("@")
        if handle and handle in EXISTING_HANDLES:
            ch["status"] = "filtered"
            rejected.append({
                "title": ch.get("title", ""),
                "handle": ch.get("handle", ""),
                "youtube_link": f"https://www.youtube.com/{ch.get('handle', '')}",
                "subscribers": ch.get("subscribers_approx", 0),
                "description": ch.get("search_description", "")[:200],
                "found_via": "; ".join(ch.get("found_via", [])),
                "rejection_reason": "Already in existing database",
            })
            skip_existing += 1
            continue

        approx_subs = ch.get("subscribers_approx", 0)
        if 0 < approx_subs < 500:
            ch["status"] = "filtered"
            rejected.append({
                "title": ch.get("title", ""),
                "handle": ch.get("handle", ""),
                "youtube_link": f"https://www.youtube.com/{ch.get('handle', '')}",
                "subscribers": approx_subs,
                "description": ch.get("search_description", "")[:200],
                "found_via": "; ".join(ch.get("found_via", [])),
                "rejection_reason": f"Too few subscribers: {approx_subs} < 500",
            })
            skip_low_subs += 1
            continue

        if cid not in detailed_ids:
            to_detail.append(cid)

    print(f"  Filtered {skip_existing} already-in-database channels")
    print(f"  Filtered {skip_low_subs} channels with <500 subs")
    print(f"  Channels to get details for: {len(to_detail)}")

    progress["channels"] = channels
    progress["rejected"] = rejected
    save_progress(progress)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 4: Get channel details
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 4] Fetching channel details")
    print("=" * 70)

    needs_detail = [cid for cid in to_detail if cid not in detailed_ids]
    print(f"  Channels needing details: {len(needs_detail)}")

    for idx, cid in enumerate(needs_detail):
        ch = channels[cid]
        handle = ch.get("handle", "")
        print(f"  [{idx+1}/{len(needs_detail)}] {ch.get('title', 'Unknown')[:40]}", end="", flush=True)

        time.sleep(1.5)  # Rate limit
        details = get_channel_details(cid, handle)

        if details:
            ch.update(details)
            ch["language"] = detect_language(details.get("description", ""), details.get("country", ""))

            # Re-check subs with accurate data
            if details["subscribers"] < 500 and details["subscribers"] > 0:
                ch["status"] = "filtered"
                rejected.append({
                    "title": details.get("title", ""),
                    "handle": details.get("handle", ""),
                    "youtube_link": details.get("youtube_link", ""),
                    "subscribers": details["subscribers"],
                    "description": details.get("description", "")[:200],
                    "found_via": "; ".join(ch.get("found_via", [])),
                    "rejection_reason": f"Too few subscribers: {details['subscribers']} < 500",
                })
                print(f"  → SKIP ({details['subscribers']} subs)")
            else:
                ch["status"] = "detailed"
                subs_display = f"{details['subscribers']:,}" if details['subscribers'] else "?"
                print(f"  → {subs_display} subs")
        else:
            ch["status"] = "detailed"  # Mark as attempted
            print(f"  → no data")

        detailed_ids.add(cid)

        if (idx + 1) % 10 == 0:
            progress["channels"] = channels
            progress["rejected"] = rejected
            progress["detailed"] = list(detailed_ids)
            save_progress(progress)

    progress["channels"] = channels
    progress["rejected"] = rejected
    progress["detailed"] = list(detailed_ids)
    save_progress(progress)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 5: Validate relevance
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 5] Validating channel relevance")
    print("=" * 70)

    to_validate = [
        cid for cid, ch in channels.items()
        if ch.get("status") == "detailed"
        and cid not in validated_ids
        and ch.get("subscribers", ch.get("subscribers_approx", 0)) >= 500
    ]
    # Also include previously validated ones
    already_valid = [cid for cid in validated_ids if cid in channels and channels[cid].get("status") == "validated"]

    print(f"  Channels to validate: {len(to_validate)}")
    print(f"  Already validated: {len(already_valid)}")

    valid_count = 0
    reject_count = 0

    for idx, cid in enumerate(to_validate):
        ch = channels[cid]
        is_relevant, reason = validate_relevance(ch)

        if is_relevant:
            ch["status"] = "validated"
            ch["relevance_reason"] = reason
            valid_count += 1
        else:
            ch["status"] = "rejected"
            rejected.append({
                "title": ch.get("title", ""),
                "handle": ch.get("handle", ""),
                "youtube_link": ch.get("youtube_link", f"https://www.youtube.com/{ch.get('handle', '')}"),
                "subscribers": ch.get("subscribers", 0),
                "description": ch.get("description", "")[:200],
                "found_via": "; ".join(ch.get("found_via", [])),
                "rejection_reason": reason,
            })
            reject_count += 1

        validated_ids.add(cid)

        if (idx + 1) % 20 == 0:
            print(f"    Validated {idx+1}/{len(to_validate)} — {valid_count} pass, {reject_count} rejected")
            progress["channels"] = channels
            progress["rejected"] = rejected
            progress["validated"] = list(validated_ids)
            save_progress(progress)

    print(f"  Validation: {valid_count} relevant, {reject_count} rejected")
    progress["channels"] = channels
    progress["rejected"] = rejected
    progress["validated"] = list(validated_ids)
    save_progress(progress)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 6: Classify (Creator / Company / Competitor)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 6] Classifying channels")
    print("=" * 70)

    valid_cids = [cid for cid, ch in channels.items() if ch.get("status") == "validated"]

    competitor_ids = []
    company_ids = []
    creator_ids = []

    for cid in valid_cids:
        ch = channels[cid]

        comp, comp_reason = is_competitor(ch)
        if comp:
            ch["bucket"] = "COMPETITOR"
            ch["bucket_reason"] = comp_reason
            competitor_ids.append(cid)
            continue

        is_co, co_reason = is_company_channel(ch)
        if is_co:
            ch["bucket"] = "COMPANY"
            ch["bucket_reason"] = co_reason
            company_ids.append(cid)
            continue

        ch["bucket"] = "CREATOR"
        creator_ids.append(cid)

    print(f"  Competitors: {len(competitor_ids)}")
    print(f"  Companies:   {len(company_ids)}")
    print(f"  Creators:    {len(creator_ids)}")

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 7-8: Calculate ER% for all valid channels
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 7-8] Calculating engagement rates")
    print("=" * 70)

    for cid in valid_cids:
        ch = channels[cid]
        views = ch.get("recent_view_counts", [])
        subs = max(ch.get("subscribers", 1), 1)

        if views:
            avg_views = sum(views) / len(views)
        elif ch.get("video_count", 0) > 0:
            avg_views = ch.get("total_views", 0) / ch["video_count"] if ch.get("total_views") else 0
        else:
            avg_views = 0

        ch["avg_views"] = round(avg_views)

        raw_er = (avg_views / subs) * 100
        if raw_er > 100:
            ch["er_pct"] = 100.0
            ch["er_note"] = "Viral/anomaly"
        else:
            ch["er_pct"] = round(raw_er, 2)
            ch["er_note"] = ""

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 9-10: Score & metadata
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 9-10] Scoring and adding metadata")
    print("=" * 70)

    for cid in valid_cids:
        ch = channels[cid]
        ch["relevance_score"] = score_relevance(ch)
        ch["content_type"] = classify_content_type(ch)
        ch["whale_potential"] = classify_whale_potential(ch)
        ch["audience_level"] = classify_audience_level(ch)
        ch["use_case"] = suggest_use_case(ch)

    save_progress(progress)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 11: Write output files
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("[STEP 11] Writing output files")
    print("=" * 70)

    csv_columns = [
        "Creator", "Username", "YouTube_Link", "Email", "Subscribers",
        "Views_per_video", "ER%", "ER_Note", "Country", "Description",
        "Language", "Relevance_Score", "Content_Type", "Whale_Potential",
        "Audience_Level", "Suggested_Use_Case", "Found_Via_Query",
        "Channel_Bucket", "Source",
    ]

    def channel_to_row(ch):
        return {
            "Creator": ch.get("title", ""),
            "Username": ch.get("handle", ""),
            "YouTube_Link": ch.get("youtube_link", ""),
            "Email": ch.get("email", ""),
            "Subscribers": ch.get("subscribers", 0),
            "Views_per_video": ch.get("avg_views", 0),
            "ER%": ch.get("er_pct", 0),
            "ER_Note": ch.get("er_note", ""),
            "Country": ch.get("country", ""),
            "Description": ch.get("description", ch.get("search_description", ""))[:500],
            "Language": ch.get("language", ""),
            "Relevance_Score": ch.get("relevance_score", 0),
            "Content_Type": ch.get("content_type", ""),
            "Whale_Potential": ch.get("whale_potential", ""),
            "Audience_Level": ch.get("audience_level", ""),
            "Suggested_Use_Case": ch.get("use_case", ""),
            "Found_Via_Query": "; ".join(ch.get("found_via", [])),
            "Channel_Bucket": ch.get("bucket", ""),
            "Source": "Claude Code Discovery V2",
        }

    # File 1: Creators
    creator_data = sorted(
        [channels[cid] for cid in creator_ids],
        key=lambda x: x.get("relevance_score", 0), reverse=True,
    )
    fname1 = f"creators_for_outreach_{TODAY}.csv"
    with open(fname1, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_columns)
        w.writeheader()
        for ch in creator_data:
            w.writerow(channel_to_row(ch))
    print(f"  {fname1}: {len(creator_data)} creators")

    # File 2: Companies
    company_data = sorted(
        [channels[cid] for cid in company_ids],
        key=lambda x: x.get("relevance_score", 0), reverse=True,
    )
    fname2 = f"companies_for_partnership_{TODAY}.csv"
    with open(fname2, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_columns)
        w.writeheader()
        for ch in company_data:
            w.writerow(channel_to_row(ch))
    print(f"  {fname2}: {len(company_data)} companies")

    # File 3: Competitors
    competitor_data = sorted(
        [channels[cid] for cid in competitor_ids],
        key=lambda x: x.get("subscribers", 0), reverse=True,
    )
    fname3 = f"competitors_monitor_{TODAY}.csv"
    with open(fname3, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_columns)
        w.writeheader()
        for ch in competitor_data:
            w.writerow(channel_to_row(ch))
    print(f"  {fname3}: {len(competitor_data)} competitors")

    # File 4: Rejected
    rejected_columns = [
        "Creator", "Username", "YouTube_Link", "Subscribers",
        "Description", "Found_Via_Query", "Rejection_Reason",
    ]
    fname4 = f"rejected_channels_log_{TODAY}.csv"
    with open(fname4, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rejected_columns)
        w.writeheader()
        for r in rejected:
            w.writerow({
                "Creator": r.get("title", ""),
                "Username": r.get("handle", ""),
                "YouTube_Link": r.get("youtube_link", ""),
                "Subscribers": r.get("subscribers", 0),
                "Description": r.get("description", "")[:300],
                "Found_Via_Query": r.get("found_via", ""),
                "Rejection_Reason": r.get("rejection_reason", ""),
            })
    print(f"  {fname4}: {len(rejected)} rejected")

    # ═══════════════════════════════════════════════════════════════════════
    # SUMMARY REPORT
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  SUMMARY REPORT")
    print("=" * 70)

    print(f"\n  Total channels discovered (raw):     {total_raw}")
    print(f"  Filtered out (rejected):             {len(rejected)}")

    reason_counts = {}
    for r in rejected:
        reason = r.get("rejection_reason", "Unknown")
        if "Too few subscribers" in reason:
            key = "Too few subscribers (<500)"
        elif "Already in existing" in reason:
            key = "Already in existing database"
        elif "No tech relevance" in reason:
            key = "No tech relevance"
        else:
            key = reason[:60]
        reason_counts[key] = reason_counts.get(key, 0) + 1

    print(f"\n  Rejection reasons:")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}")

    print(f"\n  Competitors found:                   {len(competitor_ids)}")
    print(f"  Companies for partnership:            {len(company_ids)}")
    print(f"  Creators for outreach:               {len(creator_ids)}")

    # Score tiers
    s8 = sum(1 for ch in creator_data if ch.get("relevance_score", 0) >= 8)
    s67 = sum(1 for ch in creator_data if 6 <= ch.get("relevance_score", 0) < 8)
    s45 = sum(1 for ch in creator_data if 4 <= ch.get("relevance_score", 0) < 6)
    s_low = sum(1 for ch in creator_data if ch.get("relevance_score", 0) < 4)
    print(f"\n  Creator score breakdown:")
    print(f"    Score 8+:  {s8}")
    print(f"    Score 6-7: {s67}")
    print(f"    Score 4-5: {s45}")
    print(f"    Score <4:  {s_low}")

    # Use case breakdown
    print(f"\n  Use Case breakdown (creators):")
    uc_counts = {}
    for ch in creator_data:
        uc = ch.get("use_case", "Other")
        uc_counts[uc] = uc_counts.get(uc, 0) + 1
    for uc, c in sorted(uc_counts.items(), key=lambda x: -x[1]):
        print(f"    {uc}: {c}")

    # Language breakdown
    print(f"\n  Language breakdown (creators):")
    lang_counts = {}
    for ch in creator_data:
        lang = ch.get("language", "Unknown")
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    for lang, c in sorted(lang_counts.items(), key=lambda x: -x[1]):
        print(f"    {lang}: {c}")

    # Top 20 creators
    print(f"\n  Top 20 Creators:")
    print(f"  {'#':<3} {'Name':<35} {'Subs':>10} {'ER%':>7} {'Score':>6} {'Use Case':<22} {'Email':>5}")
    print(f"  {'─'*3} {'─'*35} {'─'*10} {'─'*7} {'─'*6} {'─'*22} {'─'*5}")
    for i, ch in enumerate(creator_data[:20]):
        has_email = "Yes" if ch.get("email") else "No"
        name = ch.get("title", "")[:35]
        subs = ch.get("subscribers", 0)
        er = ch.get("er_pct", 0)
        score = ch.get("relevance_score", 0)
        uc = ch.get("use_case", "")[:22]
        print(f"  {i+1:<3} {name:<35} {subs:>10,} {er:>6.1f}% {score:>6} {uc:<22} {has_email:>5}")

    # Top 10 companies
    if company_data:
        print(f"\n  Top 10 Companies for Partnership:")
        print(f"  {'#':<3} {'Name':<35} {'Subs':>10} {'Reason'}")
        print(f"  {'─'*3} {'─'*35} {'─'*10} {'─'*30}")
        for i, ch in enumerate(company_data[:10]):
            name = ch.get("title", "")[:35]
            subs = ch.get("subscribers", 0)
            reason = ch.get("bucket_reason", "")[:50]
            print(f"  {i+1:<3} {name:<35} {subs:>10,} {reason}")

    # Top 10 competitors
    if competitor_data:
        print(f"\n  Top 10 Competitors Found:")
        print(f"  {'#':<3} {'Name':<35} {'Subs':>10} {'Reason'}")
        print(f"  {'─'*3} {'─'*35} {'─'*10} {'─'*30}")
        for i, ch in enumerate(competitor_data[:10]):
            name = ch.get("title", "")[:35]
            subs = ch.get("subscribers", 0)
            reason = ch.get("bucket_reason", "")[:50]
            print(f"  {i+1:<3} {name:<35} {subs:>10,} {reason}")

    print(f"\n{'='*70}")
    print("  Discovery V2 complete!")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
