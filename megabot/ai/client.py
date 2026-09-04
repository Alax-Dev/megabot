# OpenRouter API client
import json
import logging
import aiohttp

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL

log = logging.getLogger(__name__)


async def call_openrouter_json(system_prompt: str, user_prompt: str,
                               temperature: float = 0.2) -> dict | None:
    """
    Send a prompt to OpenRouter and parse the returned JSON response.
    Returns None on failure or if OPENROUTER_API_KEY is not configured.
    """
    if not OPENROUTER_API_KEY:
        log.info("OPENROUTER_API_KEY not configured; AI agent inactive.")
        return None

    url = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/megabot",
        "X-Title": "MegaBot",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    log.warning("OpenRouter API returned HTTP %s: %s", resp.status, err_body[:300])
                    return None

                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                if not content:
                    return None

                # Clean markdown fencing if present
                clean = content.strip()
                if clean.startswith("```json"):
                    clean = clean[7:]
                elif clean.startswith("```"):
                    clean = clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()

                import ast
                import re

                try:
                    return json.loads(clean)
                except Exception:
                    try:
                        res = ast.literal_eval(clean)
                        if isinstance(res, dict):
                            return res
                    except Exception:
                        pass
                    match = re.search(r"(\{[\s\S]*\})", clean)
                    if match:
                        candidate = match.group(1)
                        try:
                            return json.loads(candidate)
                        except Exception:
                            try:
                                res = ast.literal_eval(candidate)
                                if isinstance(res, dict):
                                    return res
                            except Exception:
                                pass
                    raise

    except aiohttp.ClientError as e:
        log.warning("Network error calling OpenRouter: %s", e)
        return None
    except json.JSONDecodeError as e:
        log.warning("Failed to parse JSON response from OpenRouter: %s", e)
        return None
    except Exception as e:
        log.warning("Unexpected error during OpenRouter call: %s", e)
        return None


async def call_openrouter_text(system_prompt: str, user_prompt: str,
                              temperature: float = 0.7) -> str | None:
    """
    Send a conversational prompt to the AI provider and return plain text.
    """
    if not OPENROUTER_API_KEY:
        log.info("OPENROUTER_API_KEY not configured; AI agent inactive.")
        return None

    url = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/megabot",
        "X-Title": "MegaBot",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    log.warning("AI provider returned HTTP %s: %s", resp.status, err_body[:300])
                    return None

                data = await resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                return content.strip() if content else None

    except Exception as e:
        log.warning("AI text call error: %s", e)
        return None
