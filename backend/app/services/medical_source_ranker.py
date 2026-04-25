"""
Query-aware ranking of medical knowledge sources.
Isolated utility used by knowledge search for better source ordering.
"""
from typing import Iterable


_NUTRITION_KEYS = (
    "питание",
    "диета",
    "рацион",
    "калори",
    "белок",
    "жир",
    "углевод",
    "витамин",
    "железо",
    "магний",
    "b12",
    "nutrition",
    "diet",
    "calorie",
    "protein",
)
_DRUG_KEYS = ("лекар", "препарат", "доз", "drug", "medication", "fda", "side effect", "interaction")
_ACTIVITY_KEYS = (
    "шаг",
    "трен",
    "кардио",
    "силов",
    "йога",
    "пилатес",
    "активност",
    "activity",
    "physical",
    "exercise",
    "workout",
    "fitness",
)
_RESEARCH_KEYS = ("исслед", "study", "trial", "pubmed", "pmc", "evidence", "guideline")
_METABOLIC_LAB_KEYS = (
    "органическ",
    "аминокис",
    "метабол",
    "ацидеми",
    "ацидур",
    "масс-спектр",
    "масс спектр",
    "gc-ms",
    "гх-мс",
    "креатинин",
    "ммоль/моль",
    "дисбиоз",
    "митохонд",
)


def detect_query_domain(query: str) -> str:
    """Return one of: metabolic_lab, nutrition, drugs, activity, research, clinical."""
    q = (query or "").lower()
    if any(k in q for k in _METABOLIC_LAB_KEYS):
        return "metabolic_lab"
    if any(k in q for k in _NUTRITION_KEYS):
        return "nutrition"
    if any(k in q for k in _DRUG_KEYS):
        return "drugs"
    if any(k in q for k in _ACTIVITY_KEYS):
        return "activity"
    if any(k in q for k in _RESEARCH_KEYS):
        return "research"
    return "clinical"


def rank_sources_for_domain(sources: Iterable[str], domain: str) -> list[str]:
    """Sort source URLs by relevance to requested domain."""
    priorities = {
        "metabolic_lab": (
            "ocr_mass_spec_differential_diagnosis",
            "otsenka_mass_spektrometricheskih",
            "ocr_organic_and_aminoacids",
            "organic_and_aminoacids",
            "ocr_aminoacids_help",
            "aminoacids_help",
            "pubmed",
            "pmc",
            "who.int",
            "nice.org.uk",
            "medlineplus",
            "cdc.gov",
            "fda.gov",
        ),
        "nutrition": ("medlineplus", "who.int", "nice.org.uk", "cdc.gov", "pubmed", "pmc", "fda.gov"),
        "drugs": ("fda.gov", "who.int", "medlineplus", "nice.org.uk", "cdc.gov", "pubmed", "pmc"),
        "activity": ("who.int", "cdc.gov", "nice.org.uk", "medlineplus", "pubmed", "pmc", "fda.gov"),
        "research": ("pubmed", "pmc", "nice.org.uk", "who.int", "cdc.gov", "medlineplus", "fda.gov"),
        "clinical": ("nice.org.uk", "cdc.gov", "who.int", "medlineplus", "pubmed", "pmc", "fda.gov"),
    }
    order = priorities.get(domain or "clinical", priorities["clinical"])

    def score(url: str) -> tuple[int, str]:
        u = (url or "").lower()
        rank = len(order) + 1
        for i, token in enumerate(order):
            if token in u:
                rank = i
                break
        return (rank, u)

    uniq = list(dict.fromkeys([s for s in sources if s]))
    uniq.sort(key=score)
    # Hard calibration: activity queries should start with CDC/WHO source.
    if (domain or "").lower() == "activity":
        cdc_url = "https://www.cdc.gov/health-topics.html"
        who_url = "https://www.who.int/news-room/fact-sheets/detail/physical-activity"
        # Always prioritize CDC as top-1 for activity queries (explicit calibration request).
        uniq = [cdc_url] + [x for x in uniq if x != cdc_url]
        # Keep WHO physical-activity factsheet high as well.
        if who_url not in uniq:
            uniq.insert(1, who_url)
        else:
            uniq = [uniq[0], who_url] + [x for x in uniq[1:] if x != who_url]
    return uniq

