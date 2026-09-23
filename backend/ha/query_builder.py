"""High-signal LinkedIn search queries built from the user's service text.

Weak queries are the single biggest lever on lead quality, so this module
spends real effort phrasing buyer language per lead type instead of dumping
the service word in one generic template. Every search always runs the whole
small base set together — a single narrow phrasing is never the only query —
and the engine later dips into `pool` to diversify when it is short of N.

GENERALIZATION RULE (§0): {service} is an opaque plain string. There is no
branching on what the service *is*, and no service name is baked anywhere —
the same templates must work unmodified for a plumber, a UX designer or a
wedding photographer, purely from the value passed in.

NEGATIVE PAIRING (§6): positive-only queries return garbage, so every query
pairs the buyer phrase with quoted negative seller terms the provider can
honor (LinkedIn supports -"phrase" exclusions). These are generic sell-side
phrases, deliberately not service-specific.

PACKED STYLE (QUERY_STYLE=packed, default): each buyer phrasing is QUOTED
(exact-phrase match instead of bag-of-words) and 2-4 phrasings are OR-grouped
into one query, e.g. ("looking for a video editor" OR "need a video editor")
-"we offer" ... — sharper results and ~3x the phrasings per Serper call.
QUERY_STYLE=legacy restores one unquoted phrasing per query.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from models import LeadType

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&+'-]*")
_ARTICLE = re.compile(r"^(a|an|the)\s+(.+)$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")

# Paired into EVERY query as -"..." exclusions (case-insensitive on the
# provider side; generic sell-side language, no service words). Kept SHORT:
# - a long exclusion tail makes Google drop `site:linkedin.com/posts` and serve
#   job/instagram results instead (verified: 14 negatives -> 1/10 LinkedIn,
#   <=10 negatives -> 10/10 LinkedIn), and
# - a long exclusion tail tanks Google recall; the classifier + prefilter own
#   the remaining seller/job-seeker filtering.
NEGATIVE_QUERY_PHRASES: tuple[str, ...] = (
    "we offer",
    "our services",
    "book a call",
    "dm us",
    "we specialize",
    "we help",
    "open to work",
    "available for hire",
)

# Packed style (QUERY_STYLE=packed, the default) carries a SHORTER tail: Google
# only reads ~32 words per query, and a packed OR-group already spends ~16 of
# them. Exact quoted buyer phrasings rarely appear in seller posts, so three
# high-yield sell-side exclusions are enough (the classifier owns the rest).
PACKED_NEGATIVE_PHRASES: tuple[str, ...] = (
    "we offer",
    "open to work",
    "available for hire",
)

# Word budget for the quoted phrases inside ONE packed query (OR tokens,
# negatives and the site: operator use the rest of Google's ~32-word window).
_PACK_MAX_WORDS = 18
_PACK_MAX_PHRASES = 4
_QUOTED = re.compile(r'"([^"]+)"')


def query_style(style: str | None = None) -> str:
    """Active emission style: "packed" (quoted exact phrases OR-grouped, the
    default) or "legacy" (one unquoted phrasing per query)."""
    raw = (style or os.getenv("QUERY_STYLE", "packed") or "packed").strip().lower()
    return "legacy" if raw == "legacy" else "packed"


# Derive natural role nouns from service phrases ("video editing" -> "video
# editor", "web design" -> "web designer") so queries match how buyers talk.
_ROLE_SUFFIXES: tuple[tuple[str, str], ...] = (
    # Specific crafts first (so "copywriting" -> "copywriter", not "copy writer").
    ("copywriting", "copywriter"), ("ghostwriting", "ghostwriter"),
    ("videography", "videographer"), ("cinematography", "cinematographer"),
    # Local / trade / professional services (any industry, not just tech).
    ("plumbing", "plumber"), ("electrical work", "electrician"), ("carpentry", "carpenter"),
    ("cleaning", "cleaner"), ("catering", "caterer"), ("tutoring", "tutor"),
    ("architecture", "architect"), ("legal", "lawyer"), ("recruitment", "recruiter"),
    ("recruiting", "recruiter"), ("training", "trainer"), ("planning", "planner"),
    ("installation", "installer"), ("repair", "repair technician"),
    ("interpretation", "interpreter"), ("auditing", "auditor"),
    ("editing", "editor"), ("edit", "editor"),
    ("designing", "designer"), ("design", "designer"),
    ("developing", "developer"), ("development", "developer"),
    ("photography", "photographer"), ("photographing", "photographer"),
    ("marketing", "marketer"),
    ("illustrating", "illustrator"), ("illustration", "illustrator"),
    ("animating", "animator"), ("animation", "animator"),
    ("motion graphics", "motion designer"),
    ("consulting", "consultant"), ("consultancy", "consultant"),
    ("coaching", "coach"), ("writing", "writer"),
    ("translation", "translator"), ("translating", "translator"),
    ("accounting", "accountant"), ("bookkeeping", "bookkeeper"),
    ("management", "manager"), ("production", "producer"),
    ("analytics", "analyst"), ("engineering", "engineer"),
    ("automation", "automation specialist"),
    ("strategy", "strategist"),
    ("content creation", "content creator"),
    ("social media management", "social media manager"),
    ("virtual assistance", "virtual assistant"),
    ("customer support", "customer support specialist"),
    ("data entry", "data entry specialist"),
    ("lead generation", "lead generation specialist"),
    ("seo", "seo specialist"),
)


_ROLE_ALIASES: dict[str, str] = {
    "ca": "chartered accountant", "cpa": "certified public accountant",
    "cs": "company secretary", "cfo": "fractional cfo", "advocate": "lawyer",
    "attorney": "lawyer", "solicitor": "lawyer", "va": "virtual assistant",
    "seo": "seo specialist", "smm": "social media manager", "ux": "ux designer",
}


def role_variants(service: str) -> list[str]:
    """Return natural role-noun phrasings derived from a service phrase.

    "video editing" -> ["video editor"]; "web design" -> ["web designer"];
    unknown phrases return [] (caller falls back to the raw phrase).
    """
    svc = _SPACES.sub(" ", (service or "").strip().lower())
    out: list[str] = []
    # Professional abbreviations buyers ALSO spell out ("need a CA" and "need a
    # chartered accountant"): whole-word match only, never inside a word.
    for word in svc.split():
        full = _ROLE_ALIASES.get(word.strip(".,"))
        if full and full not in out:
            out.append(full)
    for suffix, role in _ROLE_SUFFIXES:
        idx = svc.find(suffix)
        if idx < 0:
            continue
        prefix = svc[:idx].strip(" ,-")
        base = f"{prefix} {role}".strip() if prefix else role
        if base not in out:
            out.append(base)
    return out[:5]


_NEG_TERM = re.compile(r'\s+-\"([^\"]+)\"')


def split_query(query: str) -> tuple[str, tuple[str, ...]]:
    """Split an emitted query back into its positive phrasing and the quoted
    negative phrases. Lets providers/mocks honor the exclusions without
    treating '-"we offer"' tokens as matchable keywords."""
    positive = _NEG_TERM.sub("", query).strip()
    negatives = tuple(n.lower() for n in _NEG_TERM.findall(query))
    return positive, negatives


def query_phrases(query: str) -> list[str]:
    """Individual buyer phrasings carried by an emitted query.

    Legacy queries carry one unquoted phrasing; packed queries carry an
    OR-group of quoted exact phrases ('("need a plumber" OR "anyone know a
    good plumber") -"we offer"'). Used for dedupe and by offline mocks."""
    positive, _neg = split_query(query)
    if '"' in positive:
        found = [p.strip() for p in _QUOTED.findall(positive) if p.strip()]
        if found:
            return found
    return [positive] if positive else []


def _with_negatives(query: str, negatives: tuple[str, ...] = NEGATIVE_QUERY_PHRASES) -> str:
    suffix = "".join(f' -"{p}"' for p in negatives)
    return query + suffix


def _clean_phrase(phrase: str) -> str:
    return _SPACES.sub(" ", (phrase or "").replace('"', " ")).strip()


def _render_pack(phrases: list[str]) -> str:
    quoted = [f'"{p}"' for p in phrases]
    if len(quoted) == 1:
        return quoted[0]
    return "(" + " OR ".join(quoted) + ")"


def pack_phrases(phrases: list[str], *, max_words: int = _PACK_MAX_WORDS,
                 max_phrases: int = _PACK_MAX_PHRASES) -> list[str]:
    """Greedily group phrases into quoted OR-packs within Google's word budget.

    Quoting makes each phrasing an EXACT match (the biggest precision lever:
    unquoted phrasings match the words anywhere on the page); OR-packing lets
    one Serper call cover 3-4 phrasings (recall per credit). Order-preserving
    and deterministic, so later iterations slice packs stably."""
    packs: list[str] = []
    cur: list[str] = []
    words = 0
    for raw in phrases:
        phrase = _clean_phrase(raw)
        if not phrase:
            continue
        n = len(phrase.split())
        if cur and (words + n > max_words or len(cur) >= max_phrases):
            packs.append(_render_pack(cur))
            cur, words = [], 0
        cur.append(phrase)
        words += n
    if cur:
        packs.append(_render_pack(cur))
    return packs


@dataclass(frozen=True, slots=True)
class QueryPlan:
    base: tuple[str, ...]  # always run together (3-5 natural phrasings)
    pool: tuple[str, ...]  # diversification candidates for later iterations


# ---------------------------------------------------------------------------
# ANY-INPUT service cleanup. Users type anything: "I am a video editor",
# "we offer SEO services for startups", "UI/UX + web dev", "need clients for
# my bookkeeping business 🙏". Templates (and especially QUOTED exact-phrase
# packs) need the bare service noun buyers would write, so the raw text is
# reduced to 1-3 clean service phrases first. Deterministic and conservative:
# anything it cannot simplify is kept, and long free-text descriptions are
# flagged `messy` so the engine lets the LLM expansion lead instead.
# ---------------------------------------------------------------------------

_INTRO = re.compile(
    r"^(?:(?:hi|hello|hey)\b[\s,!.]*)?(?:"
    r"(?:i|we)\s*(?:am|'m|are|'re)\s+(?:an?\s+|the\s+)?(?:freelance\s+|professional\s+|expert\s+)?"
    r"|(?:i|we)\s+(?:do|offer|provide|sell|deliver|build|create|make|design|develop|run|manage|write|edit"
    r"|specialize\s+in|specialise\s+in|work\s+in|work\s+as\s+an?)\s+"
    r"|(?:i|we)\s+help\s+(?:\w+\s+){0,3}?with\s+"
    r"|my\s+(?:service|business|skill|niche|work)s?\s+(?:is|are|:)\s*"
    r"|(?:looking\s+for|need|want|find|get)\s+(?:me\s+)?(?:new\s+)?(?:clients|leads|customers|work|projects|buyers)"
    r"\s+(?:for|in)\s+(?:my\s+|our\s+)?"
    r"|(?:leads|clients|customers)\s+for\s+(?:my\s+|our\s+)?"
    r")",
    re.IGNORECASE,
)
_TAIL = re.compile(
    r"\s+(?:(?:for|to|in|at|with|near)\s+(?!a\s)(?!an\s).*"
    r"|(?:services?|business|work|freelancing|freelancer|expert|specialist|consultancy|company|studio|agency|"
    r"provider|professional|solutions?)\.?)$",
    re.IGNORECASE,
)
# "UI/UX", "A/B", "2D/3D" are ONE service - never split them.
_SHORT_SLASH = re.compile(r"\b(\w{1,3})\s*/\s*(\w{1,3})\b")
_MULTI_SPLIT = re.compile(r"\s*(?:,|;|/|&|\+|\||\band\b|\bor\b)\s*", re.IGNORECASE)
_JUNK = re.compile(r"[^\w\s&+/,;|'.-]", re.UNICODE)
_MESSY_WORDS = 5


def _clean_one(part: str) -> str:
    s = _SPACES.sub(" ", part).strip(" .,-'")
    for _ in range(3):  # "I am a freelance video editing expert for startups"
        new = _TAIL.sub("", _INTRO.sub("", s)).strip(" .,-'")
        if new == s or not new:
            break
        s = new
    return s


def service_phrases(raw: str, limit: int = 3) -> list[str]:
    """1-3 clean service phrases from ANY user input (primary first).

    Falls back to the whitespace-normalized raw text when cleanup would leave
    nothing, so a query is always produced."""
    text = _SPACES.sub(" ", _JUNK.sub(" ", raw or "")).strip()
    if not text:
        return []
    text = _SHORT_SLASH.sub(lambda m: f"{m.group(1)}\x00{m.group(2)}", text)
    text = _clean_one(text)  # strip an intro that precedes a list of services
    out: list[str] = []
    parts = [p for p in _MULTI_SPLIT.split(text) if p.strip()]
    for part in parts:
        s = _clean_one(part.replace("\x00", "/"))
        # "web design & development" -> the bare second part of a PAIR
        # inherits the first part's qualifier: "web development" (never in a
        # list like "store setup, logo design, branding").
        if len(parts) == 2 and out and len(s.split()) == 1 and len(out[0].split()) >= 2:
            s = " ".join(out[0].split()[:-1] + [s])
        if len(s) >= 2 and s.lower() not in (o.lower() for o in out):
            out.append(s)
    if not out:
        fallback = _SPACES.sub(" ", (raw or "").replace("\x00", "/")).strip()
        return [fallback] if fallback else []
    return out[:limit]


def primary_service(raw: str) -> str:
    phrases = service_phrases(raw)
    return phrases[0] if phrases else _SPACES.sub(" ", (raw or "").strip())


def is_messy_service(raw: str) -> bool:
    """True when even the cleaned primary phrase reads like a sentence, not a
    service noun - template queries built from it would be noise, so the
    engine waits for the LLM's canonical services before round 0."""
    return len(primary_service(raw).split()) > _MESSY_WORDS


def _normalize(service: str) -> tuple[str, str, bool]:
    svc = primary_service(service)
    m = _ARTICLE.match(svc)
    if m:
        return svc, m.group(2).strip(), True
    return svc, svc, False


def _article_phrase(naked: str) -> str | None:
    """Return a natural 'a/an <noun phrase>' when the service is countable,
    else None (service is mass/gerund/plural and reads better bare)."""
    words = naked.split()
    if not words:
        return None
    last = words[-1].lower()
    if last.endswith("ing"):
        return None
    if last.endswith(("ss", "us", "is")):
        pass
    elif last.endswith(("s", "x", "z", "ch", "sh")):
        return None  # looks plural
    return f"{_a(naked)} {naked}"


def _split_service(service: str) -> tuple[str, str, str | None]:
    """(svc, naked, phrase): svc = service as an ACTIVITY ("interior design",
    used in "help with {svc}" / "{svc} agency"), naked = the NOUN buyers ask
    for ("interior designer"), phrase = that noun with its article.

    Exact-phrase (quoted) search makes grammar matter: "need an interior
    design" never appears in a real post, "need an interior designer" does. So
    an activity-style service asks for its role noun in every noun slot."""
    svc, naked, had_article = _normalize(service)
    if had_article:
        return svc, naked, svc
    roles = role_variants(naked)
    if roles and roles[0].lower() != naked.lower():
        role = roles[0]
        return svc, role, _article_phrase(role) or role
    return svc, naked, _article_phrase(naked)


# Acronyms spoken with a leading vowel SOUND take "an" ("an SEO specialist",
# "an HR consultant") - exact-phrase search makes the article matter.
_VOWEL_SOUND_ACRONYMS = frozenset({
    "seo", "sem", "smm", "sms", "hr", "mba", "mvp", "nft", "rpa", "sql", "ml", "llm",
    "fb", "lms", "erp", "hvac", "sap", "saas", "mep", "rfp", "fmcg", "3d", "8d",
})


def _a(phrase: str) -> str:
    """Indefinite article for a phrase ("an interior designer", "an SEO specialist")."""
    words = (phrase or "x").strip().split()
    first = words[0].lower() if words else "x"
    if first in _VOWEL_SOUND_ACRONYMS:
        return "an"
    if first in {"ui", "ux", "ui/ux", "uk", "us", "user", "unique", "university"} or first.startswith(("eu", "one")):
        return "a"
    return "an" if first[:1] in "aeiou" else "a"


def _words(naked: str) -> list[str]:
    return _WORD.findall(naked)


# ---------------------------------------------------------------------------
# Per-lead-type phrasings (§6). {A} = article phrase ("a video editor"),
# {S} = bare service as typed, {N} = service with any leading article stripped.
# ---------------------------------------------------------------------------

def _need_freelancer(svc: str, naked: str, phrase: str | None) -> list[str]:
    A = phrase or svc
    variants = role_variants(naked)
    qs = [
        f"looking for {A}",
        f"need {A}",
        f"anyone know a good {naked}" if phrase else f"recommendations for {svc}",
        # "help with" only reads right for an ACTIVITY ("help with SEO"),
        # never for a person noun ("help with a plumber").
        f"need someone to help with {svc}" if not phrase else "",
    ]
    # When the service is an activity/gerund ("video editing", "logo design"),
    # buyers usually ask for the ROLE ("video editor") — use those phrasings
    # for the base set (raw phrasing still appears in the pool). High-intent,
    # project-scoped phrasings lead so the first discovery round already
    # surfaces budgeted, project-ready buyers.
    if variants:
        role = variants[0]
        A_role = _article_phrase(role) or role
        qs = [
            f"looking for {A_role}",
            f"need {A_role}",
            f"need {A_role} for a project",
            f"anyone know a good {role}",
        ]
    # FIRST-PERSON asks lead: live runs showed impersonal phrasings ("hiring
    # an interior designer", "searching for a ...") mostly match advice posts
    # ("When is it worth hiring an interior designer?") and job ads, while
    # real buyers write "we are looking for ..." / "I need ...".
    noun = variants[0] if variants else naked
    A_noun = (_article_phrase(noun) or noun) if variants else A
    qs += [
        f"we are looking for {A_noun}",
        f"i am looking for {A_noun}",
        f"i need {A_noun}",
        f"we need {A_noun}",
    ]
    return [q for q in qs if q]


def _our_agency(svc: str, naked: str, phrase: str | None) -> list[str]:
    # RETIRED from the UI (kept for engine compat): an agency sourcing
    # freelancers for its own clients. New searches never request this.
    qs = [
        f"looking for {svc} freelancers to work with our agency",
        f"our agency needs extra {svc} help",
        f"{svc} freelancers needed for client projects",
    ]
    return [q for q in qs]


# Provider ORGANISATIONS buyers ask for by name ("looking for a law firm"),
# where "{service} agency" would be nonsense ("a lawyer agency").
_ORG_WORDS = ("firm", "firms", "studio", "consultancy", "practice", "partners",
              "production house", "llp", "chambers", "clinic")
_FIRM_FOR: dict[str, str] = {
    "lawyer": "law firm", "legal": "law firm", "law": "law firm", "advocate": "law firm",
    "attorney": "law firm", "solicitor": "law firm",
    "chartered accountant": "CA firm", "ca": "CA firm", "accountant": "accounting firm",
    "accounting": "accounting firm", "bookkeeping": "bookkeeping firm", "bookkeeper": "bookkeeping firm",
    "audit": "audit firm", "auditing": "audit firm", "auditor": "audit firm",
    "tax": "tax consultancy", "tax filing": "tax consultancy", "company secretary": "CS firm",
    "architect": "architecture firm", "architecture": "architecture firm",
    "consulting": "consulting firm", "consultant": "consulting firm",
    "recruitment": "recruitment firm", "recruiting": "recruitment firm", "recruiter": "recruitment firm",
    "interior design": "interior design firm", "interior designer": "interior design firm",
}


def _org_noun(svc: str) -> str | None:
    """The organisation noun buyers use in Agency mode, when "{svc} agency"
    would be wrong: "law firm" -> itself, "lawyer" -> "law firm", "CA" ->
    "CA firm". None = the classic "{svc} agency" phrasing fits."""
    s = _ARTICLE.sub(r"\2", _SPACES.sub(" ", (svc or "").strip()))
    low = s.lower()
    if any(low == w or low.endswith(" " + w) for w in _ORG_WORDS):
        return s
    if low in _FIRM_FOR:
        return _FIRM_FOR[low]
    for alias, full in _ROLE_ALIASES.items():
        if low == alias and full in _FIRM_FOR:
            return _FIRM_FOR[full]
    return None


def _org_phrases(org: str) -> list[str]:
    A = f"{_a(org)} {org}"
    return [
        f"looking for {A}", f"need {A}", f"we are looking for {A}",
        f"can anyone recommend {A}", f"anyone know a good {org}", f"recommendations for {A}",
        f"looking to hire {A}", f"we need {A}", f"i need {A}", f"need {A} for our",
        f"looking for a reliable {org}", f"suggest a good {org}", f"best {org} for",
        f"hiring {A}", f"searching for {A}",
    ]


def _need_agency(svc: str, naked: str, phrase: str | None) -> list[str]:
    # Agency-wanted lane: a client/owner posting that they want to hire an
    # AGENCY / outside team for the service — the "I'm an Agency" mode.
    # NOT an agency sourcing freelancers (that is the retired sibling).
    org = _org_noun(svc)
    if org:
        return _org_phrases(org)[:6]
    qs = [
        f"looking for an agency for {svc}",
        f"need an agency for {svc}",
        f"recommendations for {_a(svc)} {svc} agency",
        f"looking for {_a(svc)} {svc} agency",
        f"hiring an agency for {svc}",
    ]
    return [q for q in qs]


_BUILDERS = {
    LeadType.NEED_FREELANCER: _need_freelancer,
    LeadType.OUR_AGENCY: _our_agency,
    LeadType.NEED_AGENCY: _need_agency,
}


def _raw_plan(service: str, lead_type: LeadType) -> tuple[list[str], list[str]]:
    """Positive phrasings (no negatives), case-insensitively deduped."""
    svc, naked, phrase = _split_service(service)
    base = _BUILDERS[lead_type](svc, naked, phrase)
    # Abbreviated professions: search the short form too ("need a CA" as well
    # as "need a chartered accountant") - buyers write both.
    if lead_type == LeadType.NEED_FREELANCER and svc.lower() in _ROLE_ALIASES and len(svc) <= 4:
        short = f"{_a(svc)} {svc}"
        base = base[:3] + [f"looking for {short}", f"need {short}", f"i need {short}"] + base[3:]
    pool = _pool(svc, naked, phrase, lead_type)
    seen: set[str] = set()
    out_b: list[str] = []
    for q in base:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out_b.append(q)
    out_p: list[str] = []
    for q in pool:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out_p.append(q)
    return out_b, out_p


# Round 0 in packed style covers the base set PLUS this many of the strongest
# pool phrasings, so the very first discovery round already spans ~12 buyer
# phrasings in ~4 Serper calls instead of 4 phrasings in 4 calls.
_PACKED_BASE_EXTRA = 8
_PACKED_BASE_MAX = 4  # round-0 Serper queries; overflow packs lead the pool


def _loose_packs(service: str, lead_type: LeadType) -> list[str]:
    """Recall packs: the quoted role/service noun + an OR-group of buyer
    verbs anywhere in the post. Looser than exact phrasings, so they run at
    the END of the pool, after every exact phrasing has had its turn."""
    svc, naked, _phrase = _split_service(service)
    if lead_type == LeadType.NEED_AGENCY:
        nouns = [_org_noun(svc) or f"{_ARTICLE.sub(r'\\2', svc)} agency"]
        verbs = ("looking for", "need", "recommend", "hire")
    else:
        nouns = (role_variants(naked) or [naked])[:2]
        verbs = ("looking for", "need", "anyone know", "recommend")
    group = "(" + " OR ".join(f'"{v}"' for v in verbs) + ")"
    return [f'"{_clean_phrase(n)}" {group}' for n in nouns if _clean_phrase(n)]


def build_plan(service: str, lead_type: LeadType, style: str | None = None) -> QueryPlan:
    """Build the base set + a deterministic diversification pool.

    Every emitted query pairs the buyer phrasing with the generic negative
    seller terms (see module docstring / §6). Dedupe happens on the raw
    phrasing before the shared negative suffix is appended.

    style="packed" (default): quoted exact phrases OR-grouped into packs
    (base = base phrasings + the strongest pool phrasings; pool = the rest,
    then loose recall packs). style="legacy": one unquoted phrasing per query.
    """
    base_raw, pool_raw = _raw_plan(service, lead_type)
    if query_style(style) == "legacy":
        return QueryPlan(
            base=tuple(_with_negatives(q) for q in base_raw),
            pool=tuple(_with_negatives(q) for q in pool_raw),
        )
    head = pack_phrases(base_raw + pool_raw[:_PACKED_BASE_EXTRA])
    tail = pack_phrases(pool_raw[_PACKED_BASE_EXTRA:])
    neg = PACKED_NEGATIVE_PHRASES
    base = head[:_PACKED_BASE_MAX]
    pool = head[_PACKED_BASE_MAX:] + tail + _loose_packs(service, lead_type)
    return QueryPlan(
        base=tuple(_with_negatives(p, neg) for p in base),
        pool=tuple(_with_negatives(p, neg) for p in pool),
    )


def _pool(svc: str, naked: str, phrase: str | None, lead_type: LeadType) -> list[str]:
    """Large deterministic diversification pool (service-agnostic).

    Sized so the exact-count engine can keep looping well past the base set —
    each phrasing is still a natural buyer sentence with the user's service
    interpolated as an opaque string. No service names are hardcoded.
    """
    A = phrase or svc  # article phrase ("a plumber") or bare ("video editing")
    N = naked          # service without a leading article
    out: list[str] = []

    if lead_type == LeadType.NEED_FREELANCER:
        # Role-noun variants ("video editor", "web designer") for when the
        # service was phrased as an activity ("video editing", "web design").
        for role in role_variants(svc):
            A_role = _article_phrase(role) or role
            # Buyer-voice first (these lead round 0); impersonal "hiring /
            # searching for" forms - advice-post and job-ad magnets - go last.
            out += [
                f"looking for {A_role}",
                f"need {A_role}",
                f"can anyone recommend {A_role}",
                f"looking for a freelance {role}",
                f"need a freelance {role} for a project",
                f"looking to hire {A_role}",
                f"anyone know a good {role}",
                f"recommendations for {A_role}",
                f"searching for {A_role}",
                f"hiring {A_role}",
            ]
        # --- high-intent first: budget / timeline / project-scoped asks ----
        # These run in early diversification rounds so budgeted, project-ready
        # buyers surface before generic "looking for X" volume.
        for role in role_variants(svc):
            A_role = _article_phrase(role) or role
            out += [
                f"need {A_role} with a budget",
                f"looking for {A_role} budget ready",
                f"hire a freelance {role} for a project",
                f"looking for {A_role} for our project",
                f"need {A_role} for ongoing work",
            ]
        out += [
            f"need {A} this week",
            f"looking for {A} asap",
            f"need {A} for a client project",
            f"looking for a trusted {N}",
        ]
        # --- hiring/needing verbs ------------------------------------------
        verbs = [
            "looking for", "searching for", "in need of", "on the lookout for",
            "trying to find", "looking to find", "hunting for", "want to hire",
            "looking to hire", "need to hire", "looking for recommendations for",
            "in the market for", "on the hunt for",
        ]
        out += [f"{v} {A}" for v in verbs]
        # --- urgency / timing ----------------------------------------------
        for u in ("urgent", "urgently", "asap", "this week", "for next week", "soon"):
            out.append(f"need {A} {u}")
        out.append(f"looking for {A} paid")
        out.append(f"need {A} with a budget")
        # --- referral language ----------------------------------------------
        out.append(f"anyone know a good {N}")
        out.append(f"does anyone know a good {N}")
        out += [f"anyone recommend {A}", f"can anyone recommend {A}", f"who can recommend {A}"]
        out.append(f"recommendations for {A}")
        out.append(f"recommendations needed for {A}")
        # --- help/handle forms ----------------------------------------------
        out += [
            f"need someone to help with {svc}",
            f"need help with {svc}",
            f"looking for someone to help with {svc}",
            f"need someone to handle {svc}",
            f"looking for someone to handle {svc}",
        ]
        # --- short/classified forms ----------------------------------------
        out += [
            f"{N} needed",
            f"freelance {N} needed",
            f"need a freelance {N}",
            f"looking for a freelance {N}",
            "can anyone point me to someone good",
            f"looking to bring on {A}",
            f"my team needs {A}",
            f"we are looking for {A} for some work",
            f"looking for a freelance {N} for a one-off job",
            f"need an independent {N} for a short project",
            f"anyone know a freelance {N} who can help",
        ]
        # --- first-person + social forms LinkedIn posters actually use -------
        out += [
            f"i need someone to help with {svc}",
            f"i am looking for someone to help with {svc}",
            f"i need help with {svc}",
            f"we need help with {svc}",
            f"i want to hire {A}",
            f"we want to hire {A}",
            f"looking for {A} for our project",
            f"need {A} for a client",
            f"looking for {A} for a client",
            f"anyone have a great {N} they recommend",
            f"does anyone have {_a(N)} {N} they can recommend",
            f"looking for recommendations for {A}",
            f"know any good {N}",
            f"looking for {_a(N)} {N} who is available",
            f"need a reliable {N}",
            f"looking for a trusted {N}",
            f"who do you recommend for {svc}",
            f"best {N} for hire",
            f"looking for {A} for ongoing work",
            f"need {A} for ongoing projects",
        ]
        return out

    if lead_type == LeadType.NEED_AGENCY:
        # NEED_AGENCY — a client/owner seeking an agency for their own work.
        # STRICT: no agency-seeks-freelancers phrasings here (that retired
        # sibling direction must never surface in "I'm an Agency" mode).
        org = _org_noun(svc)
        if org:
            return _org_phrases(org)[6:] + [f"outsource {svc} to {_a(org)} {org}"]
        out += [
            f"looking for an agency for {svc}",
            f"need an agency for {svc}",
            f"looking for {_a(svc)} {svc} agency",
            f"need {_a(svc)} {svc} agency",
            f"seeking an agency for {svc}",
            f"anyone recommend {_a(svc)} {svc} agency",
            f"recommendations for {_a(svc)} {svc} agency",
            f"hiring an agency for {svc}",
            f"looking to hire an agency for {svc}",
            f"looking for an agency to handle {svc}",
            f"need an agency to handle {svc}",
            f"recommend a good {svc} agency",
            f"looking for the best {svc} agency",
            f"{svc} agency recommendations",
            f"looking for a company that does {svc}",
            f"need a partner for {svc}",
            f"looking for an expert team for {svc}",
            f"outsource {svc} to an agency",
            f"anyone know a good {svc} agency",
            f"we are looking for an agency for {svc}",
            f"hire {_a(svc)} {svc} agency",
            f"best {svc} agency for hire",
            f"looking for a reliable {svc} agency",
            f"need a full-service {svc} agency",
        ]
        return out

    # OUR_AGENCY (retired from UI) — agency-seeks-freelancers phrasings only.
    lane_a = [
        "looking for freelancers to work with our agency",
        f"looking for {svc} freelancers to work with our agency",
        f"{svc} freelancers needed for client projects",
        f"need extra {svc} help for client projects",
        f"our agency needs extra {svc} help",
        f"looking for extra {svc} help for our clients",
        f"white label {svc} partner wanted",
        f"looking for a white label {svc} partner",
        f"outsource {svc} for client projects",
        f"need {svc} contractors for client projects",
        f"looking for {svc} contractors for client work",
        f"our agency is looking for freelance {svc} for client projects",
        f"need {svc} subcontractors for client projects",
        f"{svc} overflow help for our agency",
        f"overflow {svc} work for our agency",
        f"looking for vetted {svc} freelancers",
        f"hiring freelance {svc} for client projects",
        f"bring on {svc} freelancers for client work",
        f"partner with {svc} freelancers for client projects",
        f"need {svc} help for client work this quarter",
        "need a freelance bench for client work",
        f"any good {svc} freelancers for agency work",
    ]
    out += lane_a
    return out


def seed_phrases(service: str, lead_type: LeadType, limit: int = 10) -> list[str]:
    """The strongest template phrasings (no negatives) for a service - used to
    seed the pool with a user's SECONDARY services and with the LLM's
    canonical reading of a messy input."""
    base, pool = _raw_plan(service, lead_type)
    return (base + pool)[:limit]


def emit_queries(phrases: list[str], style: str | None = None) -> list[str]:
    """Ready-to-run queries for arbitrary phrasings in the active style."""
    if query_style(style) == "legacy":
        return [_with_negatives(_clean_phrase(p)) for p in phrases if _clean_phrase(p)]
    return [_with_negatives(p, PACKED_NEGATIVE_PHRASES) for p in pack_phrases(phrases)]


def _window(iteration: int) -> int:
    return min(3 + iteration, 8)


def next_queries(service: str, lead_type: LeadType, iteration: int,
                 extra_pool: tuple[str, ...] | list[str] = (),
                 style: str | None = None) -> list[str]:
    """Queries to run in engine `iteration` (0 = base set only).

    Later iterations consume NON-OVERLAPPING slices of a merged pool so every
    Serper call in a round buys a genuinely fresh phrasing (the old
    overlapping windows re-sent phrasings the engine had already run, and the
    re-added `base[:1]` slot was always filtered out as a repeat).

    `extra_pool` (optional, e.g. LLM-expanded phrasings) is merged at the HEAD
    of the pool — deduped case-insensitively against the base set — so the
    first diversification rounds spend calls on the niche-aware variants
    before falling back to deterministic templates. Every emitted query pairs
    its positive phrasing with the shared negative seller terms.

    Per-round query count is CAPPED (never grows past ~8) so a single search
    cannot burn unbounded Serper credits on a niche that yields no leads.
    In packed style each query carries 3-4 phrasings, so the same cap buys
    ~3x the phrasing coverage per Serper call.
    """
    style = query_style(style)
    plan = build_plan(service, lead_type, style)
    if iteration <= 0:
        return list(plan.base)
    # Dedupe on the individual POSITIVE phrasings (base/pool entries carry the
    # negative suffix, extra_pool entries do not — comparing raw strings would
    # never match and duplicates would slip through to Serper).
    seen: set[str] = {p.lower() for q in plan.base for p in query_phrases(q)}
    fresh_extra: list[str] = []
    for q in extra_pool:
        positive = _clean_phrase(split_query(q)[0])
        if not positive:
            continue
        key = positive.lower()
        if key in seen:
            continue
        seen.add(key)
        fresh_extra.append(positive)
    merged: list[str]
    if style == "legacy":
        merged = [_with_negatives(p) for p in fresh_extra]
        for q in plan.pool:
            key = split_query(q)[0].lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(q)
    else:
        # Expanded phrasings are packed on their own so they lead round 1;
        # the deterministic pool packs follow in their stable order.
        merged = [_with_negatives(p, PACKED_NEGATIVE_PHRASES) for p in pack_phrases(fresh_extra)]
        merged += list(plan.pool)
    window = _window(iteration)
    # Cumulative start: iteration i consumes the NEXT `window` entries after
    # everything previous iterations already ran (windows grow 4,5,6,7,8,8...).
    start = sum(_window(i) for i in range(1, iteration))
    return merged[start : start + window]
