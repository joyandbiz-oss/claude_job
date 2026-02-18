"""
YouTube HTML/JSON parsing utilities.

Extracts ytInitialData, INNERTUBE_CONTEXT, channelRenderer, videoRenderer,
richItemRenderer/gridVideoRenderer, channel about/header metadata.

All parsing is defensive: dict.get() chains, never raises on missing data.
"""

import json
import logging
import re
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# ── ytInitialData extraction ─────────────────────────────────


def extract_yt_initial_data(html: str) -> dict | None:
    """Extract the ytInitialData JSON object from page HTML."""
    if not html:
        return None

    # Try pattern 1: var ytInitialData = {...};
    m = re.search(r'var\s+ytInitialData\s*=\s*(\{.*?\})\s*;\s*</script>', html, re.DOTALL)
    if not m:
        # Try pattern 2: window["ytInitialData"] = {...};
        m = re.search(r'window\["ytInitialData"\]\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)
    if not m:
        # Try pattern 3: broader match
        m = re.search(r'var\s+ytInitialData\s*=\s*(\{.+?\})\s*;', html, re.DOTALL)
    if not m:
        log.warning("Could not find ytInitialData in page HTML")
        return None

    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        log.warning("Failed to parse ytInitialData JSON: %s", e)
        return None


def extract_innertube_context(html: str) -> tuple[str | None, dict | None]:
    """
    Extract INNERTUBE_API_KEY and INNERTUBE_CONTEXT from page HTML.
    Returns (api_key, context_dict) or (None, None).
    """
    api_key = None
    context = None

    # API key
    m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    if m:
        api_key = m.group(1)
    else:
        m = re.search(r'"innertubeApiKey"\s*:\s*"([^"]+)"', html)
        if m:
            api_key = m.group(1)

    # Context
    m = re.search(r'"INNERTUBE_CONTEXT"\s*:\s*(\{.*?\})\s*,\s*"', html, re.DOTALL)
    if m:
        try:
            context = json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    if not context:
        # Build a minimal context
        m_ver = re.search(r'"clientVersion"\s*:\s*"([^"]+)"', html)
        client_version = m_ver.group(1) if m_ver else "2.20240313.05.00"
        context = {
            "client": {
                "clientName": "WEB",
                "clientVersion": client_version,
                "hl": "en",
                "gl": "US",
            }
        }

    return api_key, context


def extract_continuation_token(data: dict) -> str | None:
    """
    Recursively find the first continuationCommand/token in ytInitialData.
    Works for both search results and channel video listings.
    """
    if isinstance(data, dict):
        # Direct continuation endpoint
        if "continuationEndpoint" in data:
            ep = data["continuationEndpoint"]
            cmd = ep.get("continuationCommand", {})
            token = cmd.get("token")
            if token:
                return token

        # continuationItemRenderer pattern
        if "continuationItemRenderer" in data:
            cir = data["continuationItemRenderer"]
            ep = cir.get("continuationEndpoint", {})
            cmd = ep.get("continuationCommand", {})
            token = cmd.get("token")
            if token:
                return token

        # nextContinuationData pattern
        if "nextContinuationData" in data:
            return data["nextContinuationData"].get("continuation")

        for v in data.values():
            result = extract_continuation_token(v)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = extract_continuation_token(item)
            if result:
                return result

    return None


# ── Subscriber / view count parsing ──────────────────────────


def parse_count_text(text: str) -> int:
    """
    Parse subscriber/view count text like '104K subscribers' or '1.2M views' to int.
    Returns 0 if unparseable.
    """
    if not text:
        return 0
    text = text.strip().replace(",", "")
    # Remove trailing words
    text = re.sub(r'\s*(subscribers?|views?|videos?)\s*$', '', text, flags=re.I).strip()

    try:
        if text.upper().endswith("K"):
            return int(float(text[:-1]) * 1_000)
        elif text.upper().endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        elif text.upper().endswith("B"):
            return int(float(text[:-1]) * 1_000_000_000)
        else:
            return int(float(text))
    except (ValueError, IndexError):
        return 0


def parse_relative_time(text: str) -> datetime | None:
    """
    Convert relative time strings like '2 weeks ago', '3 months ago',
    'Streamed 1 day ago' to an approximate datetime.
    """
    if not text:
        return None

    text = text.lower().strip()
    # Remove prefixes like "Streamed ", "Updated ", "Premieres in "
    text = re.sub(r'^(streamed|updated|premiered?)\s+', '', text)

    m = re.search(r'(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago', text)
    if not m:
        return None

    amount = int(m.group(1))
    unit = m.group(2)

    now = datetime.utcnow()
    if unit == "second":
        return now - timedelta(seconds=amount)
    elif unit == "minute":
        return now - timedelta(minutes=amount)
    elif unit == "hour":
        return now - timedelta(hours=amount)
    elif unit == "day":
        return now - timedelta(days=amount)
    elif unit == "week":
        return now - timedelta(weeks=amount)
    elif unit == "month":
        return now - timedelta(days=amount * 30)
    elif unit == "year":
        return now - timedelta(days=amount * 365)

    return None


# ── Channel search result parsing ────────────────────────────


def parse_channel_renderers(data: dict) -> list[dict]:
    """
    Parse channelRenderer items from YouTube search results (sp=EgIQAg==).
    Returns list of channel dicts with: channel_id, handle, title,
    subs_approx, description_snippet.
    """
    channels = []
    if not data:
        return channels

    contents = (data.get("contents", {})
                .get("twoColumnSearchResultsRenderer", {})
                .get("primaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", []))

    for section in contents:
        items = section.get("itemSectionRenderer", {}).get("contents", [])
        channels.extend(_extract_channels_from_items(items))

    return channels


def parse_channel_renderers_continuation(data: dict) -> list[dict]:
    """
    Parse channelRenderer items from a continuation response.
    The structure differs from the initial page.
    """
    channels = []
    if not data:
        return channels

    # Continuation responses wrap results in onResponseReceivedCommands
    actions = data.get("onResponseReceivedCommands", [])
    for action in actions:
        items = (action.get("appendContinuationItemsAction", {})
                 .get("continuationItems", []))
        for item in items:
            section = item.get("itemSectionRenderer", {})
            if section:
                channels.extend(
                    _extract_channels_from_items(section.get("contents", []))
                )

    return channels


def _extract_channels_from_items(items: list) -> list[dict]:
    """Extract channel info from a list of search result items."""
    channels = []
    for item in items:
        ch = item.get("channelRenderer")
        if not ch:
            continue

        channel_id = ch.get("channelId", "")
        if not channel_id:
            continue

        title = ch.get("title", {}).get("simpleText", "")
        sub_text = ch.get("subscriberCountText", {}).get("simpleText", "")

        # Handle extraction
        handle = ""
        canonical = (ch.get("navigationEndpoint", {})
                     .get("browseEndpoint", {})
                     .get("canonicalBaseUrl", ""))
        if canonical.startswith("/@"):
            handle = canonical[1:]  # keep the @
        elif canonical:
            handle = canonical.strip("/")

        # Description snippet
        desc_runs = ch.get("descriptionSnippet", {}).get("runs", [])
        desc_text = "".join(r.get("text", "") for r in desc_runs)

        channels.append({
            "channel_id": channel_id,
            "title": title,
            "handle": handle,
            "subs_approx": parse_count_text(sub_text),
            "description_snippet": desc_text,
        })

    return channels


# ── Video search result parsing ──────────────────────────────


def parse_video_renderers(data: dict) -> list[dict]:
    """
    Parse videoRenderer items from YouTube video search results.
    Extracts the author's channel info from each video result.
    Returns list of channel dicts (deduplicated by channel_id).
    """
    channels = {}
    if not data:
        return []

    contents = (data.get("contents", {})
                .get("twoColumnSearchResultsRenderer", {})
                .get("primaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", []))

    for section in contents:
        items = section.get("itemSectionRenderer", {}).get("contents", [])
        _extract_authors_from_video_items(items, channels)

    return list(channels.values())


def parse_video_renderers_continuation(data: dict) -> list[dict]:
    """Parse videoRenderer items from a continuation response."""
    channels = {}
    if not data:
        return []

    actions = data.get("onResponseReceivedCommands", [])
    for action in actions:
        items = (action.get("appendContinuationItemsAction", {})
                 .get("continuationItems", []))
        _extract_authors_from_video_items(items, channels)

    return list(channels.values())


def _extract_authors_from_video_items(items: list, channels: dict):
    """Extract author channel info from video search result items."""
    for item in items:
        vr = item.get("videoRenderer")
        if not vr:
            continue

        # Extract author channel
        owner = vr.get("ownerText", {}).get("runs", [])
        if not owner:
            continue

        author_name = owner[0].get("text", "")
        nav = owner[0].get("navigationEndpoint", {})
        browse = nav.get("browseEndpoint", {})
        channel_id = browse.get("browseId", "")
        canonical = browse.get("canonicalBaseUrl", "")

        if not channel_id:
            continue

        handle = ""
        if canonical.startswith("/@"):
            handle = canonical[1:]
        elif canonical:
            handle = canonical.strip("/")

        if channel_id not in channels:
            channels[channel_id] = {
                "channel_id": channel_id,
                "title": author_name,
                "handle": handle,
                "subs_approx": 0,
                "description_snippet": "",
            }


# ── Channel /about page parsing ─────────────────────────────


def parse_channel_about(data: dict) -> dict:
    """
    Parse channel metadata from the /@handle/about page's ytInitialData.
    Returns dict with: description, country, joined_date, subs, total_views,
    external_links, email.
    """
    result = {
        "description": "",
        "country": "",
        "joined_date": "",
        "subs": 0,
        "total_views": 0,
        "external_links": "",
    }
    if not data:
        return result

    # channelMetadataRenderer (most reliable)
    metadata = data.get("metadata", {}).get("channelMetadataRenderer", {})
    result["description"] = metadata.get("description", "")

    # Header for subs
    header = data.get("header", {})
    c4_header = header.get("c4TabbedHeaderRenderer", {})
    page_header = header.get("pageHeaderRenderer", {})

    # Try c4TabbedHeaderRenderer first
    if c4_header:
        sub_text = c4_header.get("subscriberCountText", {}).get("simpleText", "")
        result["subs"] = parse_count_text(sub_text)

    # Try pageHeaderRenderer (newer layout)
    if not result["subs"] and page_header:
        content = page_header.get("content", {}).get("pageHeaderViewModel", {})
        metadata_vm = content.get("metadata", {}).get("contentMetadataViewModel", {})
        rows = metadata_vm.get("metadataRows", [])
        for row in rows:
            parts = row.get("metadataParts", [])
            for part in parts:
                text_content = part.get("text", {}).get("content", "")
                if "subscriber" in text_content.lower():
                    result["subs"] = parse_count_text(text_content)

    # aboutChannelViewModel (newer format)
    full_json = json.dumps(data)

    # Country
    country_m = re.search(r'"country"\s*:\s*\{\s*"simpleText"\s*:\s*"([^"]+)"', full_json)
    if country_m:
        result["country"] = country_m.group(1)

    # Joined date
    joined_m = re.search(r'"joinedDateText"\s*:\s*\{\s*"runs"\s*:\s*\[.*?"text"\s*:\s*"(Joined\s+[^"]+)"', full_json)
    if joined_m:
        result["joined_date"] = joined_m.group(1).replace("Joined ", "")

    # Total views
    views_m = re.search(r'"viewCountText"\s*:\s*\{\s*"simpleText"\s*:\s*"([\d,]+)\s+views?"', full_json)
    if views_m:
        result["total_views"] = int(views_m.group(1).replace(",", ""))

    # External links
    links = []
    link_matches = re.findall(
        r'"channelExternalLinkViewModel"\s*:\s*\{[^}]*"title"\s*:\s*\{\s*"content"\s*:\s*"([^"]+)"',
        full_json
    )
    if link_matches:
        links.extend(link_matches)
    else:
        # Fallback: primaryLinkRenderer
        link_matches2 = re.findall(
            r'"primaryLinkRenderer"\s*:\s*\{[^}]*"title"\s*:\s*\{\s*"simpleText"\s*:\s*"([^"]+)"',
            full_json
        )
        links.extend(link_matches2)

    # Also look for URLs in links section
    url_matches = re.findall(
        r'"url"\s*:\s*"(https?://(?:www\.)?(?!youtube\.com|google\.com)[^"]+)"',
        full_json
    )
    for u in url_matches[:10]:
        if u not in links and "googleapis" not in u and "gstatic" not in u:
            links.append(u)

    result["external_links"] = " | ".join(links[:10])

    # Email from description
    email_m = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', result["description"])
    # Filter out image extensions
    filtered_emails = [
        e for e in email_m
        if not any(e.lower().endswith(ext) for ext in
                   ['.png', '.jpg', '.gif', '.svg', '.jpeg', '.webp'])
    ]
    result["email"] = filtered_emails[0] if filtered_emails else ""

    return result


# ── Channel /videos tab parsing ──────────────────────────────


def parse_channel_videos(data: dict) -> list[dict]:
    """
    Parse video items from channel /videos tab ytInitialData.
    Returns list of video dicts: video_id, title, published_text,
    published_approx, views, is_short.
    """
    videos = []
    if not data:
        return videos

    # Navigate to the videos tab content
    tabs = (data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", []))

    tab_content = None
    for tab in tabs:
        tab_r = tab.get("tabRenderer", {})
        if tab_r.get("title", "").lower() in ("videos", "vidéos", "vídeos"):
            tab_content = tab_r.get("content", {})
            break
        if tab_r.get("selected") and not tab_content:
            tab_content = tab_r.get("content", {})

    if not tab_content:
        # Fallback: search entire JSON for video items
        return _fallback_extract_videos(data)

    # richGridRenderer → richItemRenderer → richItemRenderer.content.videoRenderer
    rich_grid = tab_content.get("richGridRenderer", {})
    if rich_grid:
        for item in rich_grid.get("contents", []):
            ri = item.get("richItemRenderer", {})
            if ri:
                vr = ri.get("content", {}).get("videoRenderer", {})
                if vr:
                    v = _parse_single_video(vr)
                    if v:
                        videos.append(v)

            # Also check for shortsLockupViewModel in richItemRenderer
            shorts_vm = ri.get("content", {}).get("shortsLockupViewModel", {})
            if shorts_vm:
                v = _parse_shorts_lockup(shorts_vm)
                if v:
                    videos.append(v)

    # sectionListRenderer → itemSectionRenderer → gridVideoRenderer
    if not videos:
        section_list = tab_content.get("sectionListRenderer", {})
        for section in section_list.get("contents", []):
            items_section = section.get("itemSectionRenderer", {})
            grid = items_section.get("contents", [{}])[0].get("gridRenderer", {})
            for grid_item in grid.get("items", []):
                gvr = grid_item.get("gridVideoRenderer", {})
                if gvr:
                    v = _parse_single_grid_video(gvr)
                    if v:
                        videos.append(v)

    return videos[:20]


def _parse_single_video(vr: dict) -> dict | None:
    """Parse a single videoRenderer into a video dict."""
    video_id = vr.get("videoId", "")
    if not video_id:
        return None

    title_runs = vr.get("title", {}).get("runs", [])
    title = title_runs[0].get("text", "") if title_runs else ""
    if not title:
        title = vr.get("title", {}).get("simpleText", "")

    # Published time
    pub_text = vr.get("publishedTimeText", {}).get("simpleText", "")

    # View count
    view_text = vr.get("viewCountText", {}).get("simpleText", "")
    if not view_text:
        view_text = vr.get("shortViewCountText", {}).get("simpleText", "")
    views = parse_count_text(view_text)

    # Detect Shorts
    is_short = False
    nav_ep = vr.get("navigationEndpoint", {})
    reel_ep = nav_ep.get("reelWatchEndpoint")
    if reel_ep:
        is_short = True

    # Check thumbnail overlay for Shorts badge
    overlays = vr.get("thumbnailOverlays", [])
    for overlay in overlays:
        time_status = overlay.get("thumbnailOverlayTimeStatusRenderer", {})
        style = time_status.get("style", "")
        if style == "SHORTS":
            is_short = True
            break
        # Duration check: < 62 seconds
        dur_text = time_status.get("text", {}).get("simpleText", "")
        if dur_text and _duration_seconds(dur_text) < 62 and _duration_seconds(dur_text) > 0:
            is_short = True

    published_approx = parse_relative_time(pub_text)

    return {
        "video_id": video_id,
        "title": title,
        "published_text": pub_text,
        "published_approx": published_approx.strftime("%Y-%m-%d") if published_approx else None,
        "views": views,
        "is_short": is_short,
    }


def _parse_single_grid_video(gvr: dict) -> dict | None:
    """Parse a gridVideoRenderer."""
    video_id = gvr.get("videoId", "")
    if not video_id:
        return None

    title = gvr.get("title", {}).get("simpleText", "")
    if not title:
        runs = gvr.get("title", {}).get("runs", [])
        title = runs[0].get("text", "") if runs else ""

    pub_text = gvr.get("publishedTimeText", {}).get("simpleText", "")
    view_text = gvr.get("viewCountText", {}).get("simpleText", "")
    if not view_text:
        view_text = gvr.get("shortViewCountText", {}).get("simpleText", "")
    views = parse_count_text(view_text)

    published_approx = parse_relative_time(pub_text)

    return {
        "video_id": video_id,
        "title": title,
        "published_text": pub_text,
        "published_approx": published_approx.strftime("%Y-%m-%d") if published_approx else None,
        "views": views,
        "is_short": False,
    }


def _parse_shorts_lockup(vm: dict) -> dict | None:
    """Parse a shortsLockupViewModel."""
    ep = vm.get("onTap", {}).get("innertubeCommand", {})
    reel_ep = ep.get("reelWatchEndpoint", {})
    video_id = reel_ep.get("videoId", "")
    if not video_id:
        return None

    title = vm.get("overlayMetadata", {}).get("primaryText", {}).get("content", "")
    view_text = vm.get("overlayMetadata", {}).get("secondaryText", {}).get("content", "")
    views = parse_count_text(view_text)

    return {
        "video_id": video_id,
        "title": title,
        "published_text": "",
        "published_approx": None,
        "views": views,
        "is_short": True,
    }


def _fallback_extract_videos(data: dict) -> list[dict]:
    """
    Fallback: scan the entire JSON for videoRenderer patterns.
    Used when tab navigation fails.
    """
    videos = []
    full_json = json.dumps(data)

    # Find videoRenderer blocks by regex
    vid_pattern = re.finditer(
        r'"videoRenderer"\s*:\s*\{[^{}]*"videoId"\s*:\s*"([^"]+)"',
        full_json
    )
    seen_ids = set()
    for match in vid_pattern:
        vid_id = match.group(1)
        if vid_id in seen_ids:
            continue
        seen_ids.add(vid_id)

        # Find associated title
        start = match.start()
        chunk = full_json[start:start + 2000]

        title_m = re.search(r'"text"\s*:\s*"([^"]{3,120})"', chunk)
        title = title_m.group(1) if title_m else ""

        view_m = re.search(r'"simpleText"\s*:\s*"([\d,.]+ views?)"', chunk)
        views = parse_count_text(view_m.group(1)) if view_m else 0

        pub_m = re.search(r'"simpleText"\s*:\s*"(\d+ (?:second|minute|hour|day|week|month|year)s? ago)"', chunk)
        pub_text = pub_m.group(1) if pub_m else ""
        published_approx = parse_relative_time(pub_text)

        is_short = '"SHORTS"' in chunk or '"reelWatchEndpoint"' in chunk

        videos.append({
            "video_id": vid_id,
            "title": title,
            "published_text": pub_text,
            "published_approx": published_approx.strftime("%Y-%m-%d") if published_approx else None,
            "views": views,
            "is_short": is_short,
        })

        if len(videos) >= 20:
            break

    return videos


# ── Related / featured channels ──────────────────────────────


def parse_related_channels(data: dict) -> list[dict]:
    """
    Extract related/featured channels from a channel page's sidebar.
    Returns list of dicts with channel_id, title, handle.
    """
    channels = []
    if not data:
        return channels

    full_json = json.dumps(data)

    # Look for miniChannelRenderer or related channel sections
    mini_pattern = re.finditer(
        r'"miniChannelRenderer"\s*:\s*\{[^{}]*"channelId"\s*:\s*"([^"]+)"',
        full_json
    )
    seen = set()
    for match in mini_pattern:
        cid = match.group(1)
        if cid in seen:
            continue
        seen.add(cid)

        chunk = full_json[match.start():match.start() + 500]
        title_m = re.search(r'"title"\s*:\s*\{\s*"simpleText"\s*:\s*"([^"]+)"', chunk)
        title = title_m.group(1) if title_m else ""

        channels.append({
            "channel_id": cid,
            "title": title,
            "handle": "",
            "subs_approx": 0,
            "description_snippet": "",
        })

    # Also check for gridChannelRenderer (featured channels section)
    grid_pattern = re.finditer(
        r'"gridChannelRenderer"\s*:\s*\{[^{}]*"channelId"\s*:\s*"([^"]+)"',
        full_json
    )
    for match in grid_pattern:
        cid = match.group(1)
        if cid in seen:
            continue
        seen.add(cid)

        chunk = full_json[match.start():match.start() + 800]
        title_m = re.search(r'"title"\s*:\s*\{\s*"simpleText"\s*:\s*"([^"]+)"', chunk)
        title = title_m.group(1) if title_m else ""
        handle = ""
        canon_m = re.search(r'"canonicalBaseUrl"\s*:\s*"(/@[^"]+)"', chunk)
        if canon_m:
            handle = canon_m.group(1)[1:]  # keep @

        channels.append({
            "channel_id": cid,
            "title": title,
            "handle": handle,
            "subs_approx": 0,
            "description_snippet": "",
        })

    return channels


def parse_channel_handle_from_page(data: dict) -> str:
    """Extract channel handle from ytInitialData metadata."""
    if not data:
        return ""
    metadata = data.get("metadata", {}).get("channelMetadataRenderer", {})
    vanity = metadata.get("vanityChannelUrl", "")
    m = re.search(r'/@([^/]+)', vanity)
    if m:
        return "@" + m.group(1)
    return ""


# ── Language detection ───────────────────────────────────────


def detect_language(description: str, country: str) -> str:
    """Detect channel language from description text and country."""
    desc_lower = (description or "").lower()

    # Explicit language markers
    if any(w in desc_lower for w in ["español", "en español"]):
        return "Spanish"
    if any(w in desc_lower for w in ["português", "em português"]):
        return "Portuguese"
    if any(w in desc_lower for w in ["français", "en français"]):
        return "French"
    if any(w in desc_lower for w in ["deutsch", "auf deutsch"]):
        return "German"
    if any(w in desc_lower for w in ["hindi", "\u0939\u093f\u0902\u0926\u0940",
                                      "\u0939\u093f\u0928\u094d\u0926\u0940"]):
        return "Hindi"

    # Country mapping
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

    # Word-frequency heuristics
    lang_words = {
        "Spanish": ["cómo", "automatización", "herramientas", "datos", "programación"],
        "Portuguese": ["automação", "ferramentas", "dados", "programação", "aula"],
        "French": ["tutoriel", "comment", "outils", "données"],
        "German": ["anleitung", "werkzeuge", "daten", "automatisierung"],
    }
    scores = {lang: sum(1 for w in words if w in desc_lower)
              for lang, words in lang_words.items()}
    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best

    return "English"


# ── Helpers ──────────────────────────────────────────────────


def _duration_seconds(text: str) -> int:
    """Parse duration text like '1:23' or '0:45' to seconds."""
    parts = text.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return 0
