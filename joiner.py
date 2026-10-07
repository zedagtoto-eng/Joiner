# language: Python 3.11, file: joiner.py, runtime: Railway
# pip install requests

import json
import os
import time
import random
import requests
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
log = logging.getLogger("joiner")

HCAPTCHA_SITEKEY = "f5561ba9-8f1e-40ca-9b5b-a0b3f719ef34"
HCAPTCHA_PAGE    = "https://discord.com/invite/"

HEADERS_BASE = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTIwLjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjI2MzE2Niwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIn0=",
}

def load_config() -> dict:
    tokens_env = os.environ.get("TOKEN") or os.environ.get("TOKENS")
    if tokens_env:
        try:
            parsed = json.loads(tokens_env)
            tokens = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            tokens = [tokens_env.strip()]
        return {
            "tokens":      tokens,
            "invite":      os.environ.get("INVITE", ""),
            "nopecha_key": os.environ.get("NOPECHA_KEY", ""),
            "delay":       float(os.environ.get("DELAY", "3")),
            "proxy":       os.environ.get("PROXY", "") or None,
        }
    if os.path.exists("config.json"):
        with open("config.json") as f:
            return json.load(f)
    log.error("No TOKEN env var and no config.json found.")
    exit(1)

def solve_hcaptcha(api_key: str, sitekey: str, url: str) -> str | None:
    log.info(f"Submitting captcha — sitekey: {sitekey}")
    try:
        r = requests.post("https://api.nopecha.com/", json={
            "key":     api_key,
            "type":    "hcaptcha",
            "sitekey": sitekey,
            "url":     url,
        }, timeout=30)
        data = r.json()
        log.info(f"NopeCha submit response: {data}")
        job_id = data.get("data")
        if not job_id:
            log.error(f"NopeCha error: {data}")
            return None
        for attempt in range(24):
            time.sleep(5)
            poll = requests.get("https://api.nopecha.com/",
                params={"key": api_key, "id": job_id}, timeout=15)
            res = poll.json()
            token = res.get("data")
            if token:
                t = token[0] if isinstance(token, list) else token
                if isinstance(t, str) and len(t) > 20:
                    log.info(f"Captcha solved ✅ attempt {attempt + 1}")
                    return t
        log.warning("Captcha timed out.")
        return None
    except Exception as e:
        log.error(f"NopeCha exception: {e}")
        return None

def get_invite_code(invite: str) -> str:
    code = invite.strip().rstrip("/")
    for prefix in ["https://discord.gg/", "http://discord.gg/", "discord.gg/",
                   "https://discord.com/invite/", "http://discord.com/invite/", "discord.com/invite/"]:
        if code.startswith(prefix):
            code = code[len(prefix):]
    return code

def join_server(token: str, invite_code: str, nopecha_key: str, proxy: str | None) -> tuple[bool, str]:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    headers = {**HEADERS_BASE, "Authorization": token}

    for attempt in range(3):
        r = requests.post(
            f"https://discord.com/api/v9/invites/{invite_code}",
            json={}, headers=headers, proxies=proxies, timeout=15,
        )

        log.info(f"Discord response: {r.status_code} {r.text[:120]}")

        if r.status_code == 200:
            guild = r.json().get("guild", {})
            return True, guild.get("name", "unknown server")

        if r.status_code == 429:
            wait = r.json().get("retry_after", 5)
            log.warning(f"Rate limited — waiting {wait}s")
            time.sleep(float(wait) + 0.5)
            continue

        if r.status_code == 400:
            body = r.json()
            if "captcha_key" in body:
                sitekey = body.get("captcha_sitekey", HCAPTCHA_SITEKEY)
                log.info(f"Captcha required — sitekey from Discord: {sitekey}")
                cap = solve_hcaptcha(
                    nopecha_key,
                    sitekey,
                    HCAPTCHA_PAGE + invite_code,
                )
                if not cap:
                    return False, "captcha solve failed"
                r2 = requests.post(
                    f"https://discord.com/api/v9/invites/{invite_code}",
                    json={"captcha_key": cap},
                    headers=headers, proxies=proxies, timeout=15,
                )
                log.info(f"Post-captcha response: {r2.status_code} {r2.text[:120]}")
                if r2.status_code == 200:
                    guild = r2.json().get("guild", {})
                    return True, guild.get("name", "unknown server")
                return False, f"post-captcha failed: {r2.status_code} {r2.text[:80]}"
            return False, f"bad request: {body}"

        if r.status_code == 401:
            return False, "token invalid/terminated"
        if r.status_code == 403:
            code = r.json().get("code", 0)
            if code == 40007:
                return False, "banned from this server"
            return False, f"forbidden: {r.json()}"
        if r.status_code == 404:
            return False, "invite invalid or expired"

        return False, f"failed {r.status_code}: {r.text[:80]}"

    return False, "max retries hit"

def main():
    cfg         = load_config()
    tokens      = cfg.get("tokens", [])
    invite      = cfg.get("invite", "")
    nopecha_key = cfg.get("nopecha_key", "")
    delay       = float(cfg.get("delay", 3))
    proxy       = cfg.get("proxy") or None

    if not tokens:
        log.error("No tokens found."); return
    if not invite:
        log.error("No invite found."); return

    invite_code = get_invite_code(invite)
    log.info(f"Invite: {invite_code} | Tokens: {len(tokens)} | Delay: {delay}s | Proxy: {proxy or 'none'}")
    log.info("─" * 40)

    success = failed = 0

    for i, token in enumerate(tokens, 1):
        masked = token[:10] + "..." + token[-5:]
        log.info(f"[{i}/{len(tokens)}] {masked}")
        ok, reason = join_server(token, invite_code, nopecha_key, proxy)
        if ok:
            success += 1
            log.info(f"✅ Joined: {reason}")
        else:
            failed += 1
            log.warning(f"❌ Failed: {reason}")
        if i < len(tokens):
            wait = random.uniform(delay, delay * 4)
            log.info(f"Waiting {wait:.1f}s...")
            time.sleep(wait)

    log.info("─" * 40)
    log.info(f"Done — ✅ {success} joined | ❌ {failed} failed")

if __name__ == "__main__":
    main()
