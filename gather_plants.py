#!/usr/bin/env python3
r"""Gather the research for new plants in one go, so they can be added to the planner without a long web search.

  python gather_plants.py new-plants.txt          research every plant in the list
  python gather_plants.py "Tiarella cordifolia"   or name one or more plants on the command line
  python gather_plants.py new-plants.txt --no-photos   skip the photo downloads
  python gather_plants.py new-plants.txt --site "C:\path\to\perennial-bed-planner"   if the website folder is elsewhere

It's the research half of the Perennial Bed Planner (https://github.com/spreck79/perennial-bed-planner).
Keep this folder next to the website folder, like this, and it finds the website by itself:

    perennial-bed-planner\             the website
    perennial-bed-planner-research\    this program

The list is a plain text file, one plant per line: the botanical name, and if you like a "|" and the common name.
Lines starting with # are ignored. For example:

    Tiarella cordifolia | Foamflower
    Geranium maculatum
    # Hosta 'June'       (cultivars work too: quote marks are fine)

For each plant it visits the same trusted sources every time, saves a plain-text copy of every page it read,
pulls out the facts it can find, downloads free-licensed photos from Wikimedia Commons with their credits,
and writes a draft plants.js entry. Everything goes into the  inbox  folder next to this script:

    inbox/report.md               easy-to-read summary of every plant: what was found, where, and what's missing
    inbox/packets.json            the same, as data
    inbox/<id>/photo-1.jpg ...    up to 3 photo choices, with their credits in packets.json
    inbox/<id>/pages/*.txt        the text of each source page, with its link at the top

Then zip the inbox folder and give it to Claude (or point Claude at it) and say which plants to add.
Claude checks the facts against the saved pages, finishes the entry and runs the rest of the website's
research/ADDING-A-PLANT.md (photo, companions, sources, final check).

Sources (the same ones the planner's research has used):
  GBIF (accepted botanical name, family), Missouri Botanical Garden Plant Finder (height, spread, bloom, sun,
  water), NC State Extension Plant Toolbox (second opinion, poison notes), Rutgers NJAES deer-resistance list,
  ASPCA toxic and non-toxic plant lists for dogs and cats, Michigan native nurseries and Michigan Tech's native
  table (Michigan native check), Michigan Flora, and Wikimedia Commons (photos).

Only needs Python 3 (no extra packages). Pages are cached in inbox/.cache for a week, so running it again is quick
and polite to the websites. Use --fresh to ignore the cache.
"""
import html, html.parser, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error, hashlib, datetime

# Check websites' security certificates with the computer's own certificate store (the same one the browser uses),
# so sites whose certificate chain needs Windows to fill in a missing link still work. Falls back to Python's own.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# when built as a Windows program, keep the inbox next to the .exe (not in the temporary unpack folder)
HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
INBOX = os.path.join(HERE, "inbox")
SITE_NAME = "perennial-bed-planner"

def find_site(given=None):
    """The website folder (the one with plants.js), so new plants can be checked against the ones already in it.
    Looks where --site says, then next to this folder, then one level up (if this sits inside the website folder)."""
    tries = ([given] if given else []) + [os.path.join(HERE, SITE_NAME), os.path.join(HERE, "..", SITE_NAME), os.path.join(HERE, ".."), os.path.join(HERE, "..", "..")]
    for t in tries:
        if t and os.path.isfile(os.path.join(t, "plants.js")): return os.path.abspath(t)
    return None
SITE = None
CACHE = os.path.join(INBOX, ".cache")
UA = "PerennialBedPlanner-research/1.0 (https://github.com/spreck79/perennial-bed-planner; plant research for a garden planner)"
CACHE_DAYS = 7
FRESH = False
LOG = []
OUT = None        # the window version sets this to show progress as it happens

# ---------------------------------------------------------------- fetching

def say(msg):
    LOG.append(msg)
    if OUT: OUT(msg)
    else:
        try: print(msg, flush=True)
        except Exception: pass

_last = [0.0]
DEAD = set()      # websites that couldn't be reached this run: not tried again
def host(url): return urllib.parse.urlsplit(url).netloc
def unreachable(url): return host(url) in DEAD

def fetch(url, binary=False, tries=3):
    """GET a URL (cached). Returns text (or bytes) or None if it couldn't be read."""
    key = hashlib.sha1(url.encode()).hexdigest()[:20] + (".bin" if binary else ".txt")
    path = os.path.join(CACHE, key)
    if not FRESH and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_DAYS * 86400:
        with open(path, "rb") as f: data = f.read()
        return data if binary else data.decode("utf-8", "replace")
    if unreachable(url): return None
    for attempt in range(tries):
        wait = 1.0 - (time.time() - _last[0])     # at most about one request a second
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                cs = r.headers.get_content_charset() or "utf-8"
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "wb") as f: f.write(data if binary else data.decode(cs, "replace").encode("utf-8"))
            return data if binary else data.decode(cs, "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code == 429 or e.code >= 500:
                time.sleep(int(e.headers.get("Retry-After", "0") or 0) or 5 * (attempt + 1)); continue
            say(f"    ! {e.code} from {url}"); return None
        except Exception as e:
            if isinstance(e, urllib.error.URLError) and ("Tunnel" in str(e) or "getaddrinfo" in str(e) or "refused" in str(e) or "Name or service" in str(e)):
                attempt = tries - 1     # the site can't be reached at all: no point retrying
            if attempt == tries - 1:
                DEAD.add(host(url)); say(f"    ! couldn't reach {host(url)} ({e.__class__.__name__}: {e}); skipping it for the rest of this run"); return None
            time.sleep(2 * (attempt + 1))
    return None

def get_json(url):
    t = fetch(url)
    try: return json.loads(t) if t else None
    except ValueError: return None

class _Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "section", "table", "ul", "ol", "header", "footer", "article"}
    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.skip = 0; self.links = []; self._a = None
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"): self.skip += 1
        if tag in self.BLOCK: self.out.append("\n")
        if tag in ("td", "th"): self.out.append(" | ")
        if tag == "a":
            self._a = [dict(attrs).get("href", ""), ""]
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip: self.skip -= 1
        if tag in self.BLOCK: self.out.append("\n")
        if tag == "a" and self._a: self.links.append(tuple(self._a)); self._a = None
    def handle_data(self, d):
        if self.skip: return
        self.out.append(d)
        if self._a is not None: self._a[1] += d

def page_text(markup):
    """HTML -> (readable text, [(href, link text)])"""
    p = _Text()
    try: p.feed(markup)
    except Exception: pass
    t = "".join(p.out).replace("\xa0", " ")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip(), p.links

def save_page(pk, name, url, text):
    d = os.path.join(INBOX, pk["id"], "pages"); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name + ".txt"), "w", encoding="utf-8") as f:
        f.write(f"Source: {url}\nRead: {datetime.date.today().isoformat()}\n\n{text}\n")
    pk["pages"].append({"source": name, "url": url})

def norm(s): return re.sub(r"[^a-z]+", " ", (s or "").lower()).strip()

def binomial(latin):
    """'Tiarella cordifolia var. collina' or "Hosta 'June'" -> 'Tiarella cordifolia' / 'Hosta'"""
    w = re.sub(r"['\"‘’“”].*$", "", latin).split()
    if len(w) >= 3 and w[1] in ("x", "×"): return " ".join(w[:3])          # hybrid: 'Geranium × cantabrigiense'
    return " ".join(w[:2]) if len(w) >= 2 and w[1][:1].islower() and w[1] not in ("x", "×") else (w[0] if w else latin)

# ---------------------------------------------------------------- sources

def src_gbif(pk):
    name = pk["latin"]
    m = get_json("https://api.gbif.org/v1/species/match?verbose=false&name=" + urllib.parse.quote(binomial(name)))
    if not m:
        pk["missing"].append("GBIF couldn't be reached" if unreachable("https://api.gbif.org/") else "GBIF gave no answer"); return
    if m.get("matchType") in (None, "NONE"):
        pk["missing"].append("GBIF had no match for the botanical name (check the spelling)"); return
    acc = m.get("species") or m.get("canonicalName")
    pk["facts"]["family"] = {"value": m.get("family"), "src": "GBIF", "url": f"https://www.gbif.org/species/{m.get('usageKey')}"}
    if m.get("status") == "SYNONYM" or (acc and norm(acc) != norm(binomial(name))):
        pk["facts"]["accepted_name"] = {"value": acc, "src": "GBIF", "url": f"https://www.gbif.org/species/{m.get('acceptedUsageKey') or m.get('usageKey')}",
                                       "note": f"'{binomial(name)}' is listed as a synonym; sources may use either name"}
        pk["synonyms"].append(acc)

MBG = "https://www.missouribotanicalgarden.org/PlantFinder/"
MBG_LABELS = ["Common Name", "Type", "Family", "Native Range", "Zone", "Height", "Spread", "Bloom Time", "Bloom Description",
              "Sun", "Water", "Maintenance", "Suggested Use", "Flower", "Leaf", "Attracts", "Tolerate", "Other"]

def labelled(text, labels):
    """Pull 'Label: value' pairs out of page text, whether the value is on the same line or the next."""
    out = {}
    for lab in labels:
        m = re.search(r"(?im)^\s*\|?\s*" + re.escape(lab) + r"\s*:?\s*\|?\s*(?:\n\s*\|?\s*)?([^\n|][^\n]*)", text)
        if m:
            v = m.group(1).strip(" |:")
            if v and not any(v.lower().startswith(l.lower() + ":") for l in labels): out[lab] = v
    return out

def src_mbg(pk):
    for q in [pk["latin"], binomial(pk["latin"])] + pk["synonyms"]:
        url = MBG + "PlantFinderSearchResults.aspx?basic=" + urllib.parse.quote(q)
        t = fetch(url)
        if not t: continue
        if "PlantFinderDetails" in url or re.search(r"(?i)Bloom Time\s*:", page_text(t)[0]):   # went straight to a plant page
            det_url, det = url, t
        else:
            _, links = page_text(t); det_url = None
            want = norm(binomial(q))
            for href, txt in links:
                if "PlantFinderDetails.aspx" in href and want and want in norm(txt):
                    det_url = urllib.parse.urljoin(MBG, href); break
            if not det_url:
                for href, txt in links:
                    if "PlantFinderDetails.aspx" in href:
                        det_url = urllib.parse.urljoin(MBG, href); pk["warn"].append(f"Missouri Botanical Garden: no result named '{q}', used the first result ({txt.strip()[:60]}): check it's the right plant"); break
            if not det_url: continue
            det = fetch(det_url)
            if not det: continue
        text, _ = page_text(det)
        save_page(pk, "missouri-botanical-garden", det_url, text)
        f = labelled(text, MBG_LABELS)
        for k, v in f.items(): pk["facts"]["mbg_" + k.lower().replace(" ", "_")] = {"value": v, "src": "Missouri Botanical Garden Plant Finder", "url": det_url}
        # the 'Culture' and 'Noteworthy Characteristics' paragraphs are useful for the notes; keep a short cut
        for head in ("Culture", "Noteworthy Characteristics", "Problems", "Garden Uses"):
            m = re.search(r"(?s)\n" + head + r"\s*\n(.{40,900}?)(?:\n[A-Z][A-Za-z ]{3,30}\n|\Z)", text)
            if m: pk["facts"]["mbg_" + head.lower().replace(" ", "_")] = {"value": re.sub(r"\s+", " ", m.group(1)).strip()[:900], "src": "Missouri Botanical Garden Plant Finder", "url": det_url}
        return
    pk["missing"].append("Missouri Botanical Garden Plant Finder " + ("couldn't be reached" if unreachable(MBG) else "had no page for it"))

NCSU_LABELS = ["Height", "Width", "Light", "Soil Drainage", "Flower Bloom Time", "Flower Color", "Resistance To Challenges",
               "Poison Severity", "Poison Symptoms", "Poison Toxic Principle", "Causes Contact Dermatitis", "Poison Part",
               "Life Cycle", "Woody Plant Leaf Characteristics", "Country Or Region Of Origin", "Distribution", "Wildlife Value"]

def src_ncsu(pk):
    tries = [binomial(pk["latin"])] + pk["synonyms"]
    tries.append(binomial(pk["latin"]).split()[0])     # many garden plants are filed under the genus alone ("dahlia")
    for q in tries:
        slug = re.sub(r"[^a-z]+", "-", q.lower()).strip("-")
        url = f"https://plants.ces.ncsu.edu/plants/{slug}/"
        t = fetch(url)
        if not t: continue
        text, _ = page_text(t)
        if "Height" not in text: continue
        save_page(pk, "nc-state-plant-toolbox", url, text)
        if len(q.split()) == 1 and len(binomial(pk["latin"]).split()) > 1: pk["warn"].append(f"NC State: used its page for the whole genus ({q})")
        for k, v in labelled(text, NCSU_LABELS).items():
            pk["facts"]["ncsu_" + k.lower().replace(" ", "_")] = {"value": v, "src": "NC State Extension Plant Toolbox", "url": url}
        return
    pk["missing"].append("NC State Plant Toolbox " + ("couldn't be reached" if unreachable("https://plants.ces.ncsu.edu/") else "had no page for it"))

_shared = {}
def shared_page(key, url):
    """A list page used for every plant (deer list, ASPCA lists, nursery lists): fetched once per run."""
    if key not in _shared:
        t = fetch(url); _shared[key] = page_text(t)[0] if t else None
        if t is None and not unreachable(url): say(f"    ! couldn't read {key} ({url})")
    return _shared[key]

def find_name(text, names):
    """Find the first place a botanical name (or just its genus + species words) appears in a list page."""
    if not text: return None
    low = text.lower()
    for n in names:
        n = n.lower().strip()
        if not n: continue
        i = low.find(n)
        if i >= 0: return i
        parts = n.split()
        if len(parts) >= 2:   # allow a cultivar/variety or odd spacing between the words
            m = re.search(re.escape(parts[0]) + r"\W+(?:[a-z.]+\W+)?" + re.escape(parts[1]), low)
            if m: return m.start()
    return None

def snippet(text, i, before=120, after=220):
    return re.sub(r"\s+", " ", text[max(0, i - before): i + after]).strip()

RUTGERS = "https://njaes.rutgers.edu/deer-resistant-plants/"
def src_rutgers(pk):
    t = shared_page("Rutgers deer", RUTGERS)
    if not t: pk["missing"].append("Rutgers deer list couldn't be read"); return
    names = [pk["latin"], binomial(pk["latin"])] + pk["synonyms"]
    i = find_name(t, names)
    exact = i is not None
    if i is None:   # Rutgers often lists the genus only ("Tiarella")
        g = binomial(pk["latin"]).split()[0]
        m = re.search(r"(?im)^.*\b" + re.escape(g) + r"\b(?!\s+[a-z])", t); i = m.start() if m else None
    if i is None:
        pk["facts"]["deer"] = {"value": None, "src": "Rutgers NJAES", "url": RUTGERS, "note": "not on the Rutgers list: leave 'deer' out"}; return
    sn = snippet(t, i, 40, 260)
    # the rating is a single capital letter A-D right after the name, in its own cell
    m = re.search(r"(?:^|\|)\s*([ABCD])\s*(?:\||$)", t[i:i + 400], re.M) or re.search(r"\b([ABCD])\b(?![a-z.])", t[i + 3:i + 300])
    pk["facts"]["deer"] = {"value": m.group(1) if m else None, "src": "Rutgers NJAES", "url": RUTGERS,
                           "note": ("" if exact else "matched the genus only; ") + "context: " + sn}

ASPCA = {"dogs": "https://www.aspca.org/pet-care/animal-poison-control/dogs-plant-list",
         "cats": "https://www.aspca.org/pet-care/animal-poison-control/cats-plant-list"}
def src_aspca(pk):
    names = [pk["latin"], binomial(pk["latin"])] + pk["synonyms"]
    for animal, url in ASPCA.items():
        t = shared_page("ASPCA " + animal, url)
        if not t: pk["missing"].append(f"ASPCA {animal} list couldn't be read"); continue
        i = find_name(t, names); genus_only = False
        if i is None:   # ASPCA often lists a whole genus: "Scientific Names: Dahlia species" / "Narcissus spp"
            gen = binomial(pk["latin"]).split()[0]
            m = re.search(r"(?i)scientific names?:[^|\n]*\b" + re.escape(gen) + r"\s+(?:spp?\b\.?|species\b)", t)
            if m: i, genus_only = m.start(), True
        if i is None:
            pk["facts"]["aspca_" + animal] = {"value": "not listed", "src": "ASPCA", "url": url}; continue
        # the page has a toxic section, then a non-toxic section: see which heading comes last before the match
        before = t[:i].lower()
        tox = max(before.rfind("plants toxic to"), before.rfind("toxic plants"))
        non = max(before.rfind("non-toxic to"), before.rfind("plants non-toxic"), before.rfind("non-toxic plants"))
        verdict = "non-toxic" if non > tox else "toxic" if tox >= 0 else "listed (check)"
        pk["facts"]["aspca_" + animal] = {"value": verdict, "src": "ASPCA", "url": url,
                                          "note": ("listed for the whole genus; " if genus_only else "") + "context: " + snippet(t, i, 60, 200)}

MI_NATIVE = [   # Michigan sources that list native plants (already used in sources.js)
    ("Black Cap Plants (Onekama, Michigan)", "https://www.blackcapplants.com/species-list"),
    ("Michigan Tech KISMA native species table", "https://www.mtu.edu/kisma/native-alternatives/native-species-table/"),
    ("Michigan Wildflower Farm: dryland list", "https://www.michiganwildflowerfarm.com/seed-species-and-pricing/dryland-species-2/"),
    ("Michigan Wildflower Farm: wetland list", "https://www.michiganwildflowerfarm.com/seed-species-and-pricing/wetland-species/"),
]
def src_michigan(pk):
    names = [binomial(pk["latin"])] + pk["synonyms"]
    found, read = [], []
    for title, url in MI_NATIVE:
        t = shared_page(title, url)
        if not t: continue
        read.append(title)
        i = find_name(t, names)
        if i is not None:
            sn = snippet(t, i, 80, 160)
            line = t[t.rfind("\n", 0, i) + 1: (t.find("\n", i) + 1 or len(t) + 1) - 1]   # the whole entry line
            found.append({"source": title, "url": url, "context": sn, "flagged": "*" in line})
    pk["facts"]["michigan_lists"] = {"value": found, "src": "Michigan native nursery lists", "url": "",
                                     "note": "listed by these Michigan sources" if found else
                                             ("not on the Michigan native lists checked: probably a garden favorite (or check Michigan Flora)" if read else "none of the Michigan lists could be read")}
    if not read: pk["missing"].append("none of the Michigan native lists could be read")
    # Michigan Flora (U of Michigan Herbarium) is the authority; its site is an app, so save the search link for checking by hand
    q = urllib.parse.quote(binomial(pk["latin"]))
    pk["facts"]["michigan_flora_search"] = {"value": f"https://michiganflora.net/search?q={q}", "src": "Michigan Flora", "url": f"https://michiganflora.net/search?q={q}",
                                            "note": "open to confirm native or introduced status if the lists above disagree"}

# ---------------------------------------------------------------- photos (Wikimedia Commons)

COMMONS = "https://commons.wikimedia.org/w/api.php"
FREE = re.compile(r"(?i)^(cc0|public domain|pd\b|pdm|cc[ -]by(?:[ -]sa)?[ -]\d|cc[ -]by(?:[ -]sa)?$|cc by-sa|cc by\b)")
BAD_WORDS = re.compile(r"(?i)herbarium|specimen|illustration|drawing|botanical plate|map|distribution|range|seed|stamp|kew|plate \d|\.svg|\.tif|diagram|scan|label|sheet")

def strip_tags(s): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def src_photos(pk, want=3):
    q = binomial(pk["latin"]) if "'" not in pk["latin"] else pk["latin"].replace("'", "")
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": "6", "gsrlimit": "40",
              "gsrsearch": f'"{q}" filetype:bitmap', "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": "1600"}
    d = get_json(COMMONS + "?" + urllib.parse.urlencode(params))
    pages = list(((d or {}).get("query") or {}).get("pages", {}).values())
    cands = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]; md = ii.get("extmetadata") or {}
        title = p.get("title", "")[5:]
        lic = strip_tags((md.get("LicenseShortName") or {}).get("value", ""))
        if ii.get("mime") != "image/jpeg" or BAD_WORDS.search(title) or not FREE.search(lic) or re.search(r"(?i)\bnc\b|\bnd\b|non.?commercial|no.?deriv", lic): continue
        w, h = ii.get("width", 0), ii.get("height", 0)
        if w < 800 or h < 600: continue
        score = min(w * h, 12e6) / 1e6 + (3 if w >= h else 0) + (2 if norm(binomial(pk["latin"])) in norm(title) else 0)
        cats = (md.get("Categories") or {}).get("value", "")
        if re.search(r"(?i)quality images|featured pictures|valued images", cats): score += 6
        cands.append({"score": round(score, 1), "file": title, "page": p.get("canonicalurl") or ("https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(title.replace(" ", "_"))),
                      "by": strip_tags((md.get("Artist") or {}).get("value", ""))[:120], "lic": lic,
                      "licUrl": strip_tags((md.get("LicenseUrl") or {}).get("value", "")) or None,
                      "desc": strip_tags((md.get("ImageDescription") or {}).get("value", ""))[:200],
                      "size": f"{w}x{h}", "thumb": ii.get("thumburl") or ii.get("url")})
    cands.sort(key=lambda c: -c["score"])
    seen, firsts, rest = set(), [], []          # one photo per photographer first, so the choices really differ
    for c in cands: (rest if c["by"] in seen else firsts).append(c); seen.add(c["by"])
    cands = firsts + rest
    got = []
    for c in cands:
        if len(got) >= want: break
        data = fetch(c["thumb"], binary=True)
        if not data or data[:2] != b"\xff\xd8": continue
        fn = f"photo-{len(got) + 1}.jpg"
        d2 = os.path.join(INBOX, pk["id"]); os.makedirs(d2, exist_ok=True)
        with open(os.path.join(d2, fn), "wb") as f: f.write(data)
        c["saved_as"] = f"{pk['id']}/{fn}"; got.append(c)
    pk["photos"] = got
    if not got: pk["missing"].append("no free-licensed Commons photo found: attach your own or pick one by hand")

# ---------------------------------------------------------------- the draft entry

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
FERN_FAMS = {"Pteridaceae", "Dryopteridaceae", "Athyriaceae", "Onocleaceae", "Osmundaceae", "Polypodiaceae", "Aspleniaceae",
             "Thelypteridaceae", "Dennstaedtiaceae", "Woodsiaceae", "Blechnaceae", "Cystopteridaceae", "Equisetaceae"}

def feet_range(v):
    """'1.00 to 2.00 feet' / '1 ft. 6 in. - 2 ft. 0 in.' / '12-18 inches' -> (lo, hi) in inches"""
    if not v: return None
    v = v.lower().replace("\u2013", "-").replace("\u2014", "-")
    v = re.split(r"[;(]", v)[0]
    sides = [x for x in re.split(r"\s+to\s+|\s*-\s*(?=\d)", v) if re.search(r"\d", x)][:2]
    if not sides: return None
    default = "in" if re.search(r"\bin(ch|ches)?\b|\bin\.", v) and not re.search(r"\bf(ee)?t\b|feet|foot|ft\.", v) else "ft"
    vals = []
    for side in sides:
        parts = re.findall(r"(\d+(?:\.\d+)?)\s*(in\b|in\.|inch|inches|ft\b|ft\.|feet|foot|')?", side)
        if not parts: continue
        tot = 0.0
        for n, u in parts:
            u = u or default
            tot += float(n) * (1 if u.startswith("in") else 12)
        vals.append(tot)
    if not vals: return None
    if len(vals) == 1: vals.append(vals[0])
    return (round(min(vals)), round(max(vals)))

def bloom_months(v):
    if not v: return None
    ms = [MONTHS[m[:3].lower()] for m in re.findall(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", v)]
    if not ms: return None
    return [float(ms[0]), float(min(ms[-1] + 1, 12))]

def sun_list(v):
    if not v: return None
    v = v.lower(); s = []
    if "full sun" in v: s.append("full")
    if "part" in v or "partial" in v or "dappled" in v or "filtered" in v: s.append("part")
    if "full shade" in v or "deep shade" in v or re.search(r"(?<!part )(?<!partial )shade\b", v.replace("part shade", "").replace("partial shade", "")): s.append("shade")
    return [x for x in ("full", "part", "shade") if x in s] or None

def moisture_words(v):
    if not v: return None
    v = v.lower()
    mp = [("dry", "Dry"), ("medium", "Average"), ("wet", "Moist")]
    got = [w for k, w in mp if k in v]
    return " to ".join([got[0], got[-1]] if len(got) > 1 else got).lower().capitalize() if got else None

def make_id(pk, used_ids):
    base = re.sub(r"[^a-z]", "", (pk["common"] or binomial(pk["latin"])).lower())[:14] or "plant"
    i, cand = 2, base
    while cand in used_ids: cand = f"{base}{i}"; i += 1
    return cand

def make_code(pk, used_codes):
    words = re.findall(r"[A-Za-z]+", pk["common"] or pk["latin"])
    tries = []
    if len(words) >= 2: tries.append(words[0][0].upper() + words[1][0].lower())
    w = words[0] if words else "Pl"
    tries += [w[0].upper() + c.lower() for c in w[1:]]
    tries += [w[0].upper() + c for c in "abcdefghijklmnopqrstuvwxyz"]
    for t in tries:
        if t not in used_codes: return t
    return "??"

def draft(pk, used_ids, used_codes):
    F = lambda k: (pk["facts"].get(k) or {}).get("value")
    h = feet_range(F("mbg_height")) or feet_range(F("ncsu_height"))
    sp = feet_range(F("mbg_spread")) or feet_range(F("ncsu_width"))
    fam = F("family") or ""
    kind = "fern" if fam in FERN_FAMS else "grass" if fam in ("Poaceae", "Cyperaceae", "Juncaceae") else "clump"
    if fam in ("Amaryllidaceae", "Liliaceae") and re.search(r"(?i)bulb", F("mbg_type") or ""): kind = "bulb"
    blurb = " ".join(str(F(k) or "") for k in ("mbg_culture", "mbg_noteworthy_characteristics", "mbg_suggested_use", "mbg_garden_uses"))
    if kind == "clump" and re.search(r"(?i)ground ?cover|stolon|forms? (a )?(dense )?(mat|carpet|colon)", blurb): kind = "mat"
    if re.search(r"(?i)\bdorman(t|cy)\b|ephemeral|dies back|disappears? (by|in) (mid|early|late)?\s?summer", blurb):
        pk["warn"].append("the notes mention dormancy: decide whether it needs 'dormant: true'")
    lists = F("michigan_lists") or []
    native = bool([x for x in lists if not x.get("flagged")])
    toxic = [a for a in ("dogs", "cats") if F("aspca_" + a) == "toxic"]
    e = {"id": make_id(pk, used_ids), "code": make_code(pk, used_codes), "name": pk["common"] or (F("mbg_common_name") or "").title() or "?",
         "latin": pk["latin"], "native": native, "kind": kind,
         "hLo": h[0] if h else None, "hHi": h[1] if h else None,
         "spacing": (round((sp[0] + sp[1]) / 2) if sp else None),
         "bloom": None if kind in ("fern", "grass") else bloom_months(F("mbg_bloom_time") or F("ncsu_flower_bloom_time")),
         "color": F("mbg_bloom_description") or F("ncsu_flower_color"), "hex": None, "txt": None,
         "light": F("mbg_sun") or F("ncsu_light"), "sun": sun_list(F("mbg_sun") or F("ncsu_light")),
         "moisture": moisture_words(F("mbg_water")), "notes": None,
         "deer": F("deer"), "toxic": (toxic or None), "toxSrc": ("ASPCA lists it as toxic to " + " and ".join(toxic)) if toxic else None,
         "fam": "daisy" if fam == "Asteraceae" else None,
         "credit": ({"file": pk["photos"][0]["file"].replace(" ", "_"), "by": pk["photos"][0]["by"], "lic": pk["photos"][0]["lic"]} if pk["photos"] else None)}
    pk["draft"] = {k: v for k, v in e.items() if v not in (None, [], "")}
    pk["to_finish"] = [k for k in ("name", "hLo", "hHi", "spacing", "light", "sun", "moisture", "color", "hex", "txt", "notes", "credit") if e.get(k) in (None, "", "?")]
    if kind in ("clump", "mat"): pk["to_finish"].append(f"kind (clump, mat, fern, grass or bulb: guessed '{kind}')")
    used_ids.add(e["id"]); used_codes.add(e["code"])

# ---------------------------------------------------------------- run

def existing():
    ids, codes, latins = set(), set(), {}
    if not SITE: return ids, codes, latins
    try:
        t = open(os.path.join(SITE, "plants.js"), encoding="utf-8").read()
        for m in re.finditer(r'\{\s*id:\s*"([^"]+)"(.*?)\n', t):
            ids.add(m.group(1)); line = m.group(0) + t[m.end():m.end() + 400]
            c = re.search(r'code:\s*"([^"]+)"', line); l = re.search(r'latin:\s*"([^"]+)"', line); n = re.search(r'name:\s*"([^"]+)"', line)
            if c: codes.add(c.group(1))
            if l: latins[norm(binomial(l.group(1)))] = n.group(1) if n else m.group(1)
    except OSError: pass
    return ids, codes, latins

LATIN = re.compile(r"^[A-Z][a-z]+(\s+(x|×)\s+[a-z-]+|\s+[a-z][a-z-]+)?(\s+(var\.|subsp\.|ssp\.)\s+[a-z-]+)?(\s+['‘’\"].+)?$")
def looks_latin(s): return bool(LATIN.match(s.strip())) and len(s.split()) >= 1 and s.split()[0].lower() not in COMMON_FIRST
COMMON_FIRST = {"wild", "purple", "blue", "white", "red", "yellow", "golden", "black", "great", "common", "swamp", "prairie", "woodland", "false",
                "hardy", "creeping", "lady", "virginia", "canada", "solomons", "solomon's", "jacobs", "jacob's", "joe", "bleeding", "coral", "lambs", "lamb's"}
GBIF_BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"

def resolve_common(name):
    """'Foamflower' -> ('Tiarella cordifolia', note) using GBIF's plant names; None if nothing sensible comes back."""
    q = urllib.parse.urlencode({"q": name, "qField": "VERNACULAR", "rank": "SPECIES", "status": "ACCEPTED", "highertaxonKey": "6",
                                "datasetKey": GBIF_BACKBONE, "limit": "8"})
    d = get_json("https://api.gbif.org/v1/species/search?" + q)
    res = (d or {}).get("results") or []
    want = norm(name)
    def vern_hit(r):  # prefer a result whose English common names include exactly what was typed
        return any(norm(v.get("vernacularName")) == want for v in (r.get("vernacularNames") or []) if (v.get("language") in (None, "", "eng", "en")))
    res.sort(key=lambda r: (not vern_hit(r), r.get("kingdom") != "Plantae"))
    for r in res:
        n = r.get("canonicalName") or r.get("species")
        if n and len(n.split()) >= 2:
            others = [x.get("canonicalName") for x in res if x is not r and x.get("canonicalName")][:3]
            return n, f"looked up from the common name '{name}'" + (f" (other matches: {', '.join(others)})" if others else "") + ": check it's the right plant"
    return None

def parse_lines(lines):
    """Text lines -> [(latin or common, common)]: 'Tiarella cordifolia | Foamflower', 'Tiarella cordifolia' or just 'Foamflower'."""
    items = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"): continue
        a, _, b = ln.partition("|")
        items.append((a.strip(), b.strip()))
    return items

def read_list(args):
    items = []
    for a in args:
        items += parse_lines(open(a, encoding="utf-8").read().splitlines() if os.path.isfile(a) else [a])
    return items

def report(packets):
    out = [f"# New plant research ({datetime.date.today().isoformat()})", "",
           "Made by gather_plants.py. Facts are what the sources say; check them, finish the entry, then follow ADDING-A-PLANT.md.", ""]
    for pk in packets:
        out += [f"## {pk['common'] or pk['latin']} (*{pk['latin']}*)", ""]
        if pk.get("already"): out += [f"**Already in the planner as {pk['already']}.**", ""]
        out.append("| Fact | Value | Source |"); out.append("|---|---|---|")
        for k, f in pk["facts"].items():
            v = f.get("value")
            if isinstance(v, list): v = "; ".join(x["source"] + (" (marked as not native)" if x.get("flagged") else "") for x in v) if v and isinstance(v[0], dict) else ", ".join(map(str, v))
            v = (str(v) if v not in (None, "") else "-").replace("|", "/")
            if f.get("note"): v += f" ({f['note'][:180].replace('|', '/')})"
            out.append(f"| {k} | {v[:400]} | {f.get('src', '')} |")
        out.append("")
        if pk["photos"]:
            out.append("Photos:")
            for i, p in enumerate(pk["photos"], 1): out.append(f"{i}. `{p['saved_as']}` {p['file']}, {p['by'] or 'author unknown'}, {p['lic']} ({p['size']}) {p['page']}")
            out.append("")
        out += ["Draft entry:", "", "```js", "  " + json.dumps(pk["draft"], ensure_ascii=False), "```", ""]
        if pk["to_finish"]: out += ["Still to finish: " + ", ".join(pk["to_finish"]), ""]
        if pk["warn"]: out += ["Check: " + "; ".join(pk["warn"]), ""]
        if pk["missing"]: out += ["Couldn't get: " + "; ".join(pk["missing"]), ""]
    if LOG: out += ["## Run log", "", "```"] + LOG[-200:] + ["```"]
    return "\n".join(out) + "\n"

def run(items, photos=True, fresh=False, site=None):
    """Research every (name, common name) in items; writes inbox/report.md and packets.json. Returns the packets."""
    global FRESH, SITE
    FRESH = fresh; del LOG[:]; DEAD.clear(); _shared.clear()
    SITE = find_site(site)
    if SITE: say(f"Website folder: {SITE}")
    else: say("Note: couldn't find the website folder (perennial-bed-planner), so new plants aren't checked against the ones\n"
              "already in the planner, and the draft ids and 2-letter codes may clash.")
    os.makedirs(INBOX, exist_ok=True)
    used_ids, used_codes, latins = existing()
    packets = []
    for n, (latin, common) in enumerate(items, 1):
        warn0 = []
        one_word_common = False
        if looks_latin(latin) and len(latin.split()) == 1:   # 'Astilbe' (a genus) or 'Foamflower' (a common name)?
            m = get_json("https://api.gbif.org/v1/species/match?verbose=false&kingdom=Plantae&name=" + urllib.parse.quote(latin))
            one_word_common = bool(m) and not (m.get("matchType") == "EXACT" and m.get("rank") in ("GENUS", "SPECIES"))
        if not looks_latin(latin) or one_word_common:       # a common name on its own: look up the botanical name
            say(f"[{n}/{len(items)}] {latin}: looking up the botanical name")
            got = resolve_common(latin)
            if got: common, latin, note = (common or latin.title()), got[0], got[1]; warn0.append(note); say(f"    found {latin}")
            else: say(f"    ! couldn't find a botanical name for '{latin}'; using it as typed")
        say(f"[{n}/{len(items)}] {common or latin} ({latin})")
        pk = {"latin": latin, "common": common, "id": "", "facts": {}, "synonyms": [], "pages": [], "photos": [], "missing": [], "warn": warn0}
        pk["id"] = make_id(pk, used_ids)
        if norm(binomial(latin)) in latins and "'" not in latin: pk["already"] = latins[norm(binomial(latin))]; say(f"    note: already in the planner as {pk['already']}")
        for step, fn in [("name check (GBIF)", src_gbif), ("Missouri Botanical Garden", src_mbg), ("NC State", src_ncsu),
                         ("Rutgers deer list", src_rutgers), ("ASPCA", src_aspca), ("Michigan native lists", src_michigan)] + \
                        ([("photos", src_photos)] if photos else []):
            say("    " + step)
            try: fn(pk)
            except Exception as e: pk["missing"].append(f"{step} failed ({e.__class__.__name__}: {e})"); say(f"    ! {step} failed: {e}")
        draft(pk, used_ids, used_codes)
        packets.append(pk)
        with open(os.path.join(INBOX, "packets.json"), "w", encoding="utf-8") as f: json.dump(packets, f, indent=1, ensure_ascii=False)
    md = report(packets)
    with open(os.path.join(INBOX, "report.md"), "w", encoding="utf-8") as f: f.write(md)
    with open(os.path.join(INBOX, "report.html"), "w", encoding="utf-8") as f: f.write(report_html(md))
    say("\nDone. Open the report, then make the zip for Claude.")
    return packets

def report_html(md):
    """The report as a plain web page, so it opens with a double-click on Windows."""
    out, in_code, in_table = [], False, False
    inline = lambda t: re.sub(r"(https?://[^\s)|<]+)", r'<a href="\1">\1</a>', re.sub(r"\*(.+?)\*", r"<i>\1</i>", re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", re.sub(r"`(.+?)`", r"<code>\1</code>", html.escape(t, quote=False)))))
    for ln in md.splitlines():
        if ln.startswith("```"):
            out.append("</pre>" if in_code else "<pre>"); in_code = not in_code; continue
        if in_code: out.append(html.escape(ln)); continue
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if set("".join(cells)) <= set("-"): continue
            if not in_table: out.append("<table>"); in_table = True; out.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>"); continue
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>"); continue
        if in_table: out.append("</table>"); in_table = False
        if ln.startswith("## "): out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("# "): out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif re.match(r"^\d+\. ", ln): out.append(f"<p class=li>{inline(ln)}</p>")
        elif ln.strip(): out.append(f"<p>{inline(ln)}</p>")
    if in_table: out.append("</table>")
    css = ("body{font:15px/1.45 'Segoe UI',system-ui,sans-serif;color:#2E3A2C;max-width:1000px;margin:24px auto;padding:0 16px;background:#F4F2EA}"
           "h1{color:#3E6B35}h2{color:#3E6B35;border-top:2px solid #d8dccf;padding-top:14px;margin-top:28px}"
           "table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}td,th{border:1px solid #d8dccf;padding:4px 7px;text-align:left;vertical-align:top}"
           "th{background:#e7ecdf}pre{background:#fff;border:1px solid #d8dccf;padding:10px;overflow:auto;font-size:12px;white-space:pre-wrap}code{font-size:12px}p.li{margin:2px 0 2px 12px}")
    return f"<!doctype html><meta charset=utf-8><title>Plant research</title><style>{css}</style>\n" + "\n".join(out)

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args or "--help" in flags: print(__doc__); return
    given = next((sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == "--site"), None)
    if given: args = [a for a in args if a != given]
    items = read_list(args)
    if not items: sys.exit("No plants in the list.")
    run(items, photos="--no-photos" not in flags, fresh="--fresh" in flags, site=given)

if __name__ == "__main__":
    main()
