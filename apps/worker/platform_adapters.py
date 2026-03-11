from __future__ import annotations

FIELD_HINTS = {
    "greenhouse": {
        "first_name": [
            "input[name='first_name']",
            "input[id='first_name']",
            "input[id*='first_name']",
            "input[autocomplete='given-name']",
        ],
        "last_name": [
            "input[name='last_name']",
            "input[id='last_name']",
            "input[id*='last_name']",
            "input[autocomplete='family-name']",
        ],
        "full_name": ["input[name='name']", "input[id='name']"],
        "email": [
            "input[name='email']",
            "input[id='email']",
            "input[type='email']",
            "input[autocomplete='email']",
        ],
        "phone": [
            "input[name='phone']",
            "input[id='phone']",
            "input[type='tel']",
            "input[autocomplete='tel']",
        ],
        "location": [
            "input[name='location[location]']",
            "input[name*='location']",
            "input[id*='location']",
            "input[id='country']",
        ],
        "linkedin": [
            "input[name*='linkedin']",
            "input[id*='linkedin']",
            "input[aria-label*='LinkedIn' i]",
        ],
        "github": [
            "input[name*='github']",
            "input[id*='github']",
            "input[aria-label*='GitHub' i]",
        ],
        "website": [
            "input[name*='website']",
            "input[id*='website']",
            "input[aria-label*='website' i]",
        ],
        "resume_path": [
            "input[type='file'][name*='resume']",
            "input[id='resume']",
            "input[type='file']",
        ],
        "cover_note": [
            "textarea[name*='cover_letter']",
            "textarea[id*='cover_letter']",
            "textarea[aria-label*='why' i]",
            "textarea",
        ],
    },
    "lever": {
        "first_name": [
            "input[name='firstName']",
            "input[id='firstName']",
            "input[autocomplete='given-name']",
        ],
        "last_name": [
            "input[name='lastName']",
            "input[id='lastName']",
            "input[autocomplete='family-name']",
        ],
        "full_name": ["input[name='name']", "input[id='name']"],
        "email": [
            "input[name='email']",
            "input[id='email']",
            "input[type='email']",
            "input[autocomplete='email']",
        ],
        "phone": ["input[name='phone']", "input[id='phone']", "input[type='tel']"],
        "location": ["input[name*='location']", "input[id*='location']"],
        "linkedin": [
            "input[name*='linkedin']",
            "input[id*='linkedin']",
            "input[aria-label*='LinkedIn' i]",
        ],
        "github": [
            "input[name*='github']",
            "input[id*='github']",
            "input[aria-label*='GitHub' i]",
        ],
        "website": [
            "input[name*='website']",
            "input[id*='website']",
            "input[aria-label*='website' i]",
        ],
        "resume_path": [
            "input[type='file'][name*='resume']",
            "input[type='file'][id*='resume']",
            "input[type='file']",
        ],
        "cover_note": ["textarea[name='comments']", "textarea[aria-label*='cover' i]", "textarea"],
    },
    "ashbyhq": {},
    "generic": {
        "first_name": ["input[name*='first']", "input[id*='first']"],
        "last_name": ["input[name*='last']", "input[id*='last']"],
        "full_name": ["input[name*='name']", "input[id*='name']"],
        "email": [
            "input[type='email']",
            "input[name*='email']",
            "input[id*='email']",
            "input[autocomplete='email']",
        ],
        "phone": ["input[type='tel']", "input[name*='phone']", "input[id*='phone']"],
        "location": ["input[name*='location']", "input[id*='location']", "input[name*='address']"],
        "linkedin": ["input[name*='linkedin']", "input[id*='linkedin']"],
        "github": ["input[name*='github']", "input[id*='github']"],
        "website": ["input[name*='website']", "input[id*='website']", "input[name*='portfolio']"],
        "resume_path": ["input[type='file']"],
        "cover_note": ["textarea[name*='cover']", "textarea[name*='message']", "textarea"],
    },
}

SUBMIT_HINTS = {
    "greenhouse": [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit application')",
        "button:has-text('Submit Application')",
        "button:has-text('Submit')",
    ],
    "lever": [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit application')",
        "button:has-text('Submit')",
    ],
    "ashbyhq": [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit application')",
        "button:has-text('Submit Application')",
        "button:has-text('Submit')",
    ],
    "generic": ["button[type='submit']", "input[type='submit']", "button:has-text('Submit')"],
}


def detect_platform(target_url: str, platform_hint: str) -> str:
    if platform_hint != "generic":
        return platform_hint
    if "greenhouse" in target_url:
        return "greenhouse"
    if "lever.co" in target_url:
        return "lever"
    if "ashbyhq.com" in target_url:
        return "ashbyhq"
    return "generic"


def get_selector_fallbacks(platform: str, canonical_key: str | None) -> list[str]:
    if not canonical_key:
        return []
    platform_hints = FIELD_HINTS.get(platform, {})
    generic_hints = FIELD_HINTS["generic"]
    return [*platform_hints.get(canonical_key, []), *generic_hints.get(canonical_key, [])]


def get_submit_hints(platform: str) -> list[str]:
    return SUBMIT_HINTS.get(platform, SUBMIT_HINTS["generic"])
