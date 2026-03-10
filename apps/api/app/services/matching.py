from __future__ import annotations

import re

from rapidfuzz import fuzz

from apps.api.app.schemas import CandidateProfilePayload, RankingResult

TITLE_NORMALIZATIONS = {
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "swe": "software engineer",
    "pm": "product manager",
}
TITLE_STOPWORDS = {
    "senior",
    "sr",
    "junior",
    "jr",
    "lead",
    "principal",
    "staff",
    "head",
    "global",
    "ii",
    "iii",
    "iv",
    "remote",
    "hybrid",
}
ROLE_FAMILIES = {
    "technical": {
        "engineer",
        "engineering",
        "developer",
        "software",
        "platform",
        "backend",
        "frontend",
        "fullstack",
        "machine",
        "learning",
        "artificial",
        "intelligence",
        "data",
        "scientist",
        "analytics",
        "analyst",
        "research",
        "architect",
        "devops",
        "infrastructure",
    },
    "product": {"product", "owner"},
    "design": {"design", "designer", "ux", "ui"},
    "go_to_market": {
        "sales",
        "marketing",
        "growth",
        "business",
        "account",
        "customer",
        "success",
        "revenue",
        "partnerships",
    },
    "operations": {
        "operations",
        "ops",
        "program",
        "project",
        "recruiter",
        "talent",
        "people",
        "support",
    },
}
PRIMARY_TITLE_FAMILY_PATTERNS = {
    "support": [
        r"\bproduct support\b",
        r"\bcustomer support\b",
        r"\btechnical support\b",
        r"\bsupport engineer(?:ing)?\b",
        r"\bsupport operations\b",
        r"\bsupport specialist\b",
        r"\bsupport\b",
    ],
    "software_engineering": [
        r"\bsoftware engineer(?:ing)?\b",
        r"\bbackend\b",
        r"\bfrontend\b",
        r"\bfull ?stack\b",
        r"\bplatform engineer(?:ing)?\b",
        r"\bsystems engineer(?:ing)?\b",
        r"\bapi\b",
        r"\binference\b",
        r"\bdeveloper\b",
    ],
    "infrastructure": [
        r"\binfrastructure\b",
        r"\bdevops\b",
        r"\bsite reliability\b",
        r"\bsre\b",
        r"\bdatacenter\b",
        r"\bserver lifecycle\b",
        r"\bsecurity engineer(?:ing)?\b",
    ],
    "product": [
        r"\bproduct manager\b",
        r"\bproduct owner\b",
    ],
    "customer_success": [
        r"\bcustomer success\b",
        r"\bcustomer trust\b",
    ],
    "research": [
        r"\bresearch engineer\b",
        r"\bresearch scientist\b",
        r"\bresearch\b",
        r"\bscientist\b",
    ],
}
SCOPE_LEVELS = {
    "junior_ic": 1,
    "ic": 2,
    "senior_ic": 3,
    "lead": 4,
    "manager": 5,
    "senior_manager": 6,
    "director_plus": 7,
}
TITLE_SCOPE_PATTERNS = [
    (
        "director_plus",
        [
            r"\bhead\b",
            r"\bdirector\b",
            r"\bvice president\b",
            r"\bvp\b",
            r"\bchief\b",
        ],
    ),
    ("senior_manager", [r"\bsenior manager\b", r"\bsr manager\b"]),
    ("manager", [r"\bmanager\b"]),
    ("lead", [r"\blead\b", r"\bleader\b"]),
    ("senior_ic", [r"\bprincipal\b", r"\bstaff\b", r"\bsenior\b"]),
    (
        "ic",
        [
            r"\bengineer\b",
            r"\bspecialist\b",
            r"\banalyst\b",
            r"\bassociate\b",
            r"\bdeveloper\b",
            r"\bscientist\b",
            r"\barchitect\b",
        ],
    ),
    ("junior_ic", [r"\bjunior\b", r"\bgraduate\b", r"\bintern\b"]),
]
SUMMARY_SCOPE_PATTERNS = [
    ("director_plus", [r"\bdepartment head\b", r"\bhead of\b"]),
    (
        "manager",
        [
            r"\bmanaging (?:global )?teams?\b",
            r"\bmanage(?:d)? (?:global )?teams?\b",
            r"\bpeople management\b",
            r"\bpeople manager\b",
            r"\bown budget\b",
            r"\borg design\b",
        ],
    ),
]
LOCATION_GROUPS = {
    "uk": {
        "uk",
        "united kingdom",
        "england",
        "scotland",
        "wales",
        "northern ireland",
        "london",
        "manchester",
        "edinburgh",
        "glasgow",
        "birmingham",
        "bristol",
        "leeds",
    },
    "europe": {
        "europe",
        "france",
        "paris",
        "germany",
        "berlin",
        "netherlands",
        "amsterdam",
        "spain",
        "madrid",
        "ireland",
        "dublin",
        "portugal",
        "lisbon",
        "italy",
        "milan",
        "rome",
        "sweden",
        "stockholm",
        "denmark",
        "copenhagen",
    },
    "emea": {"emea"},
    "us": {
        "united states",
        "usa",
        "new york",
        "san francisco",
        "california",
        "austin",
        "seattle",
        "boston",
        "chicago",
        "los angeles",
        "washington dc",
    },
    "canada": {"canada", "toronto", "vancouver", "montreal"},
    "apac": {"apac", "singapore", "australia", "sydney", "melbourne", "india", "tokyo"},
    "global": {"global", "worldwide", "anywhere", "international"},
}
CITY_TERMS = {
    "london",
    "manchester",
    "edinburgh",
    "glasgow",
    "paris",
    "berlin",
    "amsterdam",
    "dublin",
    "new york",
    "san francisco",
    "austin",
    "seattle",
    "boston",
    "toronto",
    "vancouver",
}
COMPATIBLE_LOCATION_GROUPS = {
    "uk": {"uk", "europe", "emea", "global"},
    "europe": {"uk", "europe", "emea", "global"},
    "emea": {"uk", "europe", "emea", "global"},
    "us": {"us", "global"},
    "canada": {"canada", "global"},
    "apac": {"apac", "global"},
}


def rank_job(profile: CandidateProfilePayload, job: dict) -> RankingResult:
    job_title = job.get("title", "")
    job_text = " ".join(
        part
        for part in [
            job_title,
            job.get("description", ""),
            " ".join(job.get("requirements", [])),
            str(job.get("metadata_json", {})),
        ]
        if part
    )
    job_text_lower = job_text.lower()

    matched_skills = [skill for skill in profile.skills if skill.lower() in job_text_lower]
    title_score, title_matches, title_warnings = _title_alignment(profile, job_title)
    scope_score, scope_matches, scope_warnings = _scope_alignment(profile, job_title)
    location_score, location_matches, location_warnings = _location_alignment(
        profile.location,
        job,
    )
    summary_match = fuzz.token_set_ratio((profile.summary or "").lower(), job_text_lower)
    skill_score = min(24.0, len(matched_skills) * 4.0)
    score = min(
        100.0,
        round(
            max(
                0.0,
                title_score
                + scope_score
                + skill_score
                + (summary_match * 0.08)
                + location_score,
            ),
            2,
        ),
    )
    score = _apply_fit_caps(score, title_warnings, location_warnings)

    missing_skill_signals = [
        signal
        for signal in _extract_candidate_keywords(job_text_lower)
        if signal not in {skill.lower() for skill in profile.skills}
    ][:6]
    missing_signals = _dedupe(
        [*location_warnings, *title_warnings, *scope_warnings, *missing_skill_signals]
    )[:6]
    matched_signals = _dedupe(
        [*title_matches, *scope_matches, *location_matches, *matched_skills]
    )[:6]
    summary = _build_summary(
        score,
        matched_skills,
        title_warnings,
        scope_warnings,
        location_warnings,
        missing_skill_signals,
    )
    return RankingResult(
        score=score,
        matched_skills=matched_skills,
        matched_signals=matched_signals,
        missing_signals=missing_signals,
        summary=summary,
    )


def _build_summary(
    score: float,
    matched_skills: list[str],
    title_warnings: list[str],
    scope_warnings: list[str],
    location_warnings: list[str],
    missing_skills: list[str],
) -> str:
    if location_warnings:
        return "Skill overlap exists, but the role location looks weak for your current base."
    if title_warnings:
        return "Some skill overlap, but the job title does not align well with your recent roles."
    if scope_warnings:
        if any("people management" in warning for warning in scope_warnings):
            return "Relevant overlap exists, but the role expects more people-management scope."
        if any("individual contributor" in warning for warning in scope_warnings):
            return "Relevant overlap exists, but the role looks more individual contributor than your recent scope."
        if any("more junior" in warning for warning in scope_warnings):
            return "Relevant overlap exists, but the role may sit below your recent seniority."
        if any("more senior" in warning for warning in scope_warnings):
            return "Relevant overlap exists, but the role may sit above your recent seniority."
    if score >= 75:
        top_matches = ", ".join(matched_skills[:3]) or "core requirements"
        return f"Strong fit with clear overlap in {top_matches}."
    if score >= 50:
        top_gaps = ", ".join(missing_skills[:3]) or "specific tooling"
        return f"Promising fit, but review gaps around {top_gaps}."
    top_gaps = ", ".join(missing_skills[:3]) or "role alignment"
    return f"Lower fit right now; major gaps include {top_gaps}."


def _title_alignment(
    profile: CandidateProfilePayload,
    job_title: str,
) -> tuple[float, list[str], list[str]]:
    candidate_titles = _candidate_titles(profile)
    if not candidate_titles or not job_title:
        return 0.0, [], []

    normalized_job_title = _normalize_title_text(job_title)
    job_tokens = set(_title_tokens(job_title))
    candidate_tokens = {
        token for title in candidate_titles for token in _title_tokens(title)
    }
    best_title_ratio = max(
        fuzz.token_set_ratio(_normalize_title_text(title), normalized_job_title)
        for title in candidate_titles
    )
    overlap = sorted(candidate_tokens & job_tokens)
    family_score, family_warning = _role_family_alignment(candidate_tokens, job_tokens)
    primary_family_score, primary_family_matches, primary_family_warnings = (
        _primary_title_family_alignment(candidate_titles, job_title)
    )

    score = (
        (best_title_ratio * 0.28)
        + (min(len(overlap), 3) * 7.0)
        + family_score
        + primary_family_score
    )
    matches: list[str] = []
    warnings: list[str] = []

    if best_title_ratio >= 70:
        matches.append("title match")
    elif overlap:
        matches.append("shared role terms")
    matches.extend(primary_family_matches)

    if family_warning and best_title_ratio < 55:
        warnings.append(family_warning)
    elif best_title_ratio < 35 and not overlap:
        warnings.append("job title looks outside your recent role history")
    warnings.extend(primary_family_warnings)

    return score, _dedupe(matches), _dedupe(warnings)


def _scope_alignment(
    profile: CandidateProfilePayload,
    job_title: str,
) -> tuple[float, list[str], list[str]]:
    candidate_scope = _candidate_scope_level(profile)
    job_scope = _detect_scope_level(job_title, TITLE_SCOPE_PATTERNS)
    if candidate_scope is None or job_scope is None:
        return 0.0, [], []

    candidate_is_management = candidate_scope >= SCOPE_LEVELS["manager"]
    job_is_management = job_scope >= SCOPE_LEVELS["manager"]
    matches: list[str] = []
    warnings: list[str] = []

    if candidate_is_management and job_is_management:
        diff = abs(candidate_scope - job_scope)
        if diff == 0:
            return 10.0, ["management scope aligned"], []
        if diff == 1:
            return 6.0, ["management scope adjacent"], []
        if candidate_scope > job_scope:
            return -3.0, [], ["role may sit slightly below your recent management scope"]
        return -6.0, [], ["job expects broader management scope"]

    if candidate_is_management and not job_is_management:
        if job_scope >= SCOPE_LEVELS["lead"]:
            warnings.append("role looks more individual contributor than your recent scope")
            return -4.0, matches, warnings
        warnings.append("role looks more individual contributor than your recent scope")
        return -10.0, matches, warnings

    if not candidate_is_management and job_is_management:
        warnings.append("job expects people management scope")
        if candidate_scope >= SCOPE_LEVELS["lead"]:
            return -6.0, matches, warnings
        return -10.0, matches, warnings

    diff = abs(candidate_scope - job_scope)
    if diff == 0:
        return 6.0, ["seniority aligned"], []
    if diff == 1:
        return 3.0, ["seniority adjacent"], []
    if candidate_scope > job_scope:
        return -4.0, [], ["role looks more junior than your recent scope"]
    return -6.0, [], ["role looks more senior than your recent scope"]


def _location_alignment(
    profile_location: str | None,
    job: dict,
) -> tuple[float, list[str], list[str]]:
    if not profile_location:
        return 0.0, [], []

    job_location_text = _job_location_text(job)
    if not job_location_text:
        return 0.0, [], []

    normalized_profile = _normalize_text(profile_location)
    normalized_job_location = _normalize_text(job_location_text)
    shared_cities = _detect_cities(normalized_profile) & _detect_cities(normalized_job_location)
    profile_groups = _detect_location_groups(normalized_profile)
    job_groups = _detect_location_groups(normalized_job_location)
    is_remote = any(
        term in normalized_job_location for term in {"remote", "distributed", "anywhere"}
    )
    is_hybrid = "hybrid" in normalized_job_location
    is_onsite = "onsite" in normalized_job_location or "on site" in normalized_job_location

    if shared_cities:
        city = next(iter(shared_cities)).title()
        return 18.0, [f"location matches {city}"], []

    if is_remote and (not job_groups or "global" in job_groups):
        return 8.0, ["remote role"], []

    if _locations_are_compatible(profile_groups, job_groups):
        if is_remote:
            return 12.0, ["remote geography aligns"], []
        if is_hybrid or is_onsite:
            return 8.0, ["compatible office region"], []
        return 10.0, ["location aligned"], []

    if job_groups:
        label = _format_location_groups(job_groups)
        if is_remote:
            return -16.0, [], [f"remote role appears restricted to {label}"]
        return -28.0, [], [f"job location appears to be {label}"]

    if is_hybrid or is_onsite:
        return -8.0, [], ["job may require a different office location"]

    return 0.0, [], []


def _extract_candidate_keywords(job_text: str) -> list[str]:
    matches = re.findall(
        r"\b(python|sql|aws|gcp|docker|kubernetes|react|typescript|llm|nlp|pytorch|tensorflow|airflow|spark)\b",
        job_text,
    )
    return list(dict.fromkeys(matches))


def _candidate_titles(profile: CandidateProfilePayload) -> list[str]:
    titles = [profile.headline or ""]
    titles.extend(experience.title or "" for experience in profile.experiences)
    return _dedupe([title for title in titles if title.strip()])


def _candidate_scope_level(profile: CandidateProfilePayload) -> int | None:
    title_text = " ".join(_candidate_titles(profile))
    title_scope = _detect_scope_level(title_text, TITLE_SCOPE_PATTERNS)
    summary_scope = _detect_scope_level(profile.summary or "", SUMMARY_SCOPE_PATTERNS)
    if title_scope is None:
        return summary_scope
    if summary_scope is None:
        return title_scope
    if title_scope < SCOPE_LEVELS["manager"] and summary_scope >= SCOPE_LEVELS["manager"]:
        return SCOPE_LEVELS["manager"]
    if title_scope >= SCOPE_LEVELS["manager"]:
        return max(title_scope, min(summary_scope, title_scope + 1))
    return max(title_scope, summary_scope)


def _normalize_title_text(value: str) -> str:
    normalized = _normalize_text(value)
    for source, target in TITLE_NORMALIZATIONS.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    return normalized


def _title_tokens(value: str) -> list[str]:
    normalized = _normalize_title_text(value)
    return [token for token in normalized.split() if token not in TITLE_STOPWORDS]


def _detect_scope_level(
    text: str,
    patterns: list[tuple[str, list[str]]],
) -> int | None:
    normalized_text = _normalize_title_text(text)
    for label, label_patterns in patterns:
        if any(re.search(pattern, normalized_text) for pattern in label_patterns):
            return SCOPE_LEVELS[label]
    return None


def _role_family_alignment(
    candidate_tokens: set[str],
    job_tokens: set[str],
) -> tuple[float, str | None]:
    candidate_families = _detect_role_families(candidate_tokens)
    job_families = _detect_role_families(job_tokens)
    if not candidate_families or not job_families:
        return 0.0, None
    if candidate_families & job_families:
        return 10.0, None
    return -18.0, "job title sits in a different role family"


def _detect_role_families(tokens: set[str]) -> set[str]:
    families = set()
    for family, keywords in ROLE_FAMILIES.items():
        if tokens & keywords:
            families.add(family)
    return families


def _primary_title_family_alignment(
    candidate_titles: list[str],
    job_title: str,
) -> tuple[float, list[str], list[str]]:
    candidate_families = _detect_primary_title_families(" ".join(candidate_titles))
    job_families = _detect_primary_title_families(job_title)
    if not candidate_families or not job_families:
        return 0.0, [], []

    shared_families = candidate_families & job_families
    if shared_families:
        label = _format_primary_family(next(iter(shared_families)))
        return 12.0, [f"{label} title match"], []

    if "support" in candidate_families and "software_engineering" in job_families:
        return (
            -24.0,
            [],
            ["job title leans toward software engineering rather than support"],
        )
    if "support" in candidate_families and "infrastructure" in job_families:
        return (
            -18.0,
            [],
            ["job title leans toward infrastructure engineering rather than support"],
        )
    if "support" in candidate_families and "research" in job_families:
        return (
            -24.0,
            [],
            ["job title leans toward research rather than support"],
        )
    if "support" in candidate_families and "customer_success" in job_families:
        return 6.0, ["adjacent customer role"], []

    return -12.0, [], ["job title sits outside your core title track"]


def _detect_primary_title_families(text: str) -> set[str]:
    normalized_text = _normalize_title_text(text)
    families = set()
    for family, patterns in PRIMARY_TITLE_FAMILY_PATTERNS.items():
        if any(re.search(pattern, normalized_text) for pattern in patterns):
            families.add(family)
    return families


def _format_primary_family(family: str) -> str:
    if family == "software_engineering":
        return "software engineering"
    if family == "customer_success":
        return "customer"
    return family.replace("_", " ")


def _job_location_text(job: dict) -> str:
    metadata = job.get("metadata_json", {}) or {}
    offices = metadata.get("offices", [])
    office_names = []
    for office in offices:
        if isinstance(office, dict) and office.get("name"):
            office_names.append(office["name"])
    location_parts = [
        job.get("location", ""),
        str(metadata.get("workplaceType", "")),
        " ".join(office_names),
    ]
    return " ".join(part for part in location_parts if part)


def _detect_location_groups(text: str) -> set[str]:
    groups = set()
    padded_text = f" {text} "
    for group, terms in LOCATION_GROUPS.items():
        if any(_contains_term(padded_text, term) for term in terms):
            groups.add(group)
    return groups


def _detect_cities(text: str) -> set[str]:
    padded_text = f" {text} "
    return {city for city in CITY_TERMS if _contains_term(padded_text, city)}


def _locations_are_compatible(
    profile_groups: set[str],
    job_groups: set[str],
) -> bool:
    if not profile_groups or not job_groups:
        return False

    for profile_group in profile_groups:
        compatible_groups = COMPATIBLE_LOCATION_GROUPS.get(profile_group, {profile_group})
        if compatible_groups & job_groups:
            return True
    return False


def _format_location_groups(groups: set[str]) -> str:
    if "uk" in groups:
        return "the UK"
    if "us" in groups:
        return "the US"
    if "europe" in groups:
        return "Europe"
    if "emea" in groups:
        return "EMEA"
    if "canada" in groups:
        return "Canada"
    if "apac" in groups:
        return "APAC"
    if "global" in groups:
        return "a global location"
    return "another region"


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _contains_term(text: str, term: str) -> bool:
    normalized_term = f" {_normalize_text(term)} "
    return normalized_term in text


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _apply_fit_caps(
    score: float,
    title_warnings: list[str],
    location_warnings: list[str],
) -> float:
    capped_score = score
    if location_warnings:
        hard_location_mismatch = any(
            "restricted to" in warning or "appears to be" in warning
            for warning in location_warnings
        )
        capped_score = min(capped_score, 40.0 if hard_location_mismatch else 55.0)

    if title_warnings:
        capped_score = min(capped_score, 55.0)

    return round(capped_score, 2)
