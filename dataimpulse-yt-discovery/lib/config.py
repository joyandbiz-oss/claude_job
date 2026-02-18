"""
YAML configuration loader with environment variable merging.
"""

import logging
import os
import sys

import yaml

log = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    """Load config.yaml, merge with environment variables, validate required fields."""
    if not os.path.isfile(path):
        log.error("Config file not found: %s", path)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    if not isinstance(cfg, dict):
        log.error("Config file is not a valid YAML dict: %s", path)
        sys.exit(1)

    # Merge proxy URL from environment
    proxy_cfg = cfg.get("proxy", {})
    env_var = proxy_cfg.get("env_var", "DI_PROXY_URL")
    env_val = os.environ.get(env_var)
    if env_val:
        proxy_cfg["resolved_url"] = env_val
        log.info("Proxy URL loaded from env var %s", env_var)
    elif proxy_cfg.get("default_url"):
        proxy_cfg["resolved_url"] = proxy_cfg["default_url"]
        log.info("Proxy URL loaded from config default_url")
    else:
        proxy_cfg["resolved_url"] = None
        log.warning("No proxy URL configured (env %s not set, no default_url)", env_var)

    # Validate required sections
    required = ["queries", "keywords", "competitor_substrings"]
    for key in required:
        if key not in cfg:
            log.error("Missing required config section: %s", key)
            sys.exit(1)

    # Flatten queries if a specific tier is requested (handled by caller)
    # Ensure keyword lists exist
    kw = cfg.get("keywords", {})
    for subkey in ("hard", "soft", "use_case_hard", "negative"):
        if subkey not in kw:
            log.warning("Missing keywords.%s in config, defaulting to empty list", subkey)
            kw[subkey] = []

    # Ensure thresholds have defaults
    thresholds = cfg.setdefault("thresholds", {})
    thresholds.setdefault("min_subs", 500)
    thresholds.setdefault("min_score_outreach", 30)
    thresholds.setdefault("max_recency_days", 180)
    thresholds.setdefault("max_shorts_share", 0.8)
    thresholds.setdefault("min_median_views", 100)

    # Ensure rate_limit defaults
    rl = cfg.setdefault("rate_limit", {})
    rl.setdefault("requests_per_second", 1.5)
    rl.setdefault("retry_max", 3)
    rl.setdefault("retry_base_wait", 2)

    # Ensure discovery defaults
    disc = cfg.setdefault("discovery", {})
    disc.setdefault("pages_per_query", 4)
    disc.setdefault("video_results_per_query", 50)
    disc.setdefault("min_subs_discovery", 300)

    # Export defaults
    exp = cfg.setdefault("export", {})
    exp.setdefault("output_dir", "./output")
    exp.setdefault("timestamp_files", True)

    return cfg


def get_queries_for_tier(cfg: dict, tier: str | None) -> list[tuple[str, str]]:
    """
    Return list of (query_text, tier_name) pairs.
    If tier is None, return all tiers.  If tier is specified, return only that tier.
    """
    queries_cfg = cfg.get("queries", {})

    if tier:
        if tier not in queries_cfg:
            available = ", ".join(queries_cfg.keys())
            log.error("Tier '%s' not found. Available: %s", tier, available)
            sys.exit(1)
        return [(q, tier) for q in queries_cfg[tier]]

    result = []
    for tier_name, q_list in queries_cfg.items():
        for q in q_list:
            result.append((q, tier_name))
    return result
