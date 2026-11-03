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
PROGRESS = None   # and this: PROGRESS(steps_done, steps_total, "Plant 1 of 2, Dahlia: NC State")

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

def mbg_search_urls(q):
    gen = binomial(q).split()[0]
    return [MBG + "PlantFinderSearchResults.aspx?basic=" + urllib.parse.quote(q),      # basic search (older address)
            MBG + "PlantFinderProfileResults.aspx?gen=" + urllib.parse.quote(gen)]      # results for the whole genus (newer address)

def src_mbg(pk):
    tried = []
    names = [pk["latin"], binomial(pk["latin"])] + pk["synonyms"]
    for q in dict.fromkeys(names):
        for url in mbg_search_urls(q):
            if url in tried: continue
            tried.append(url)
            t = fetch(url)
            if not t: continue
            if re.search(r"(?i)Bloom Time\s*:", page_text(t)[0]):    # went straight to a plant page
                det_url, det = url, t
            else:
                _, links = page_text(t); det_url = None
                want = norm(binomial(q))
                for href, txt in links:
                    if "plantfinderdetails.aspx" in href.lower() and want and want in norm(txt):
                        det_url = urllib.parse.urljoin(url, href); break
                if not det_url and "basic=" in url:
                    for href, txt in links:
                        if "plantfinderdetails.aspx" in href.lower():
                            det_url = urllib.parse.urljoin(url, href); pk["warn"].append(f"Missouri Botanical Garden: no result named '{q}', used the first result ({txt.strip()[:60]}): check it's the right plant"); break
                if not det_url: continue
                det = fetch(det_url)
                if not det: continue
            text, _ = page_text(det)
            save_page(pk, "missouri-botanical-garden", det_url, text)
            for k, v in labelled(text, MBG_LABELS).items(): pk["facts"]["mbg_" + k.lower().replace(" ", "_")] = {"value": v, "src": "Missouri Botanical Garden Plant Finder", "url": det_url}
            for head in ("Culture", "Noteworthy Characteristics", "Problems", "Garden Uses"):
                m = re.search(r"(?s)\n" + head + r"\s*\n(.{40,900}?)(?:\n[A-Z][A-Za-z ]{3,30}\n|\Z)", text)
                if m: pk["facts"]["mbg_" + head.lower().replace(" ", "_")] = {"value": re.sub(r"\s+", " ", m.group(1)).strip()[:900], "src": "Missouri Botanical Garden Plant Finder", "url": det_url}
            return
    pk["missing"].append("Missouri Botanical Garden Plant Finder " + ("couldn't be reached" if unreachable(MBG) else "had no page for it")
                         + " (tried: " + ", ".join(tried) + ")")

NCSU_LABELS = ["Height", "Width", "Plant Type", "Habit/Form", "Light", "Soil Drainage", "Soil Texture", "USDA Plant Hardiness Zone",
               "Flower Bloom Time", "Flower Color", "Flower Description", "Leaf Color", "Leaf Description", "Resistance To Challenges",
               "Poison Severity", "Poison Symptoms", "Poison Toxic Principle", "Causes Contact Dermatitis", "Poison Part",
               "Life Cycle", "Landscape Location", "Country Or Region Of Origin", "Distribution", "Wildlife Value", "Maintenance"]

def labelled_lists(text, labels):
    """NC State style: 'Label:' then one value per line until the next 'Something:' line. Values joined with '; '."""
    out, lines = {}, [l.strip() for l in text.splitlines()]
    is_label = lambda l: bool(re.fullmatch(r"[A-Z][A-Za-z/ ,&()'-]{1,45}:", l))
    for lab in labels:
        for i, l in enumerate(lines):
            if l.lower() == lab.lower() + ":":
                vals = []
                for l2 in lines[i + 1:]:
                    if not l2: continue
                    if is_label(l2) or l2.startswith(("Download", "×")): break
                    vals.append(l2)
                    if len(vals) >= 12: break
                if vals: out[lab] = "; ".join(vals)
                break
            if l.lower().startswith(lab.lower() + ":") and len(l) > len(lab) + 1:      # value on the same line ("Height: 1 ft...")
                out[lab] = l[len(lab) + 1:].strip(); break
    return out

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
        for k, v in labelled_lists(text, NCSU_LABELS).items():
            pk["facts"]["ncsu_" + re.sub(r"[^a-z]+", "_", k.lower()).strip("_")] = {"value": v, "src": "NC State Extension Plant Toolbox", "url": url}
        m = re.search(r"This plant has (low|medium|high) severity poison characteristics", text, re.I)
        if m: pk["facts"]["ncsu_poison_severity"] = {"value": m.group(1).capitalize(), "src": "NC State Extension Plant Toolbox", "url": url}
        m = re.search(r"(?s)\nDescription\n+(.+?)(?:\n(?:VIDEO|Profile Video|See this plant|Cultivars / Varieties|Tags):)", text)
        if m: pk["facts"]["ncsu_description"] = {"value": re.sub(r"\s+", " ", m.group(1)).strip()[:1500], "src": "NC State Extension Plant Toolbox", "url": url}
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
RUT_ENTRY = re.compile(r"(?m)^(?P<common>[^\n]+?) - (?P<latin>[^\n]+)\n+Type:\s*\n+(?P<type>[^\n]+)\n+Rating:\s*\n+[^\n]*\n+-\s*(?P<r>[ABCD])\b")

def rutgers_entries(text):
    """The page lists 'Common - Latin / Type: ... / Rating: ... - A' entries (20 at a time, so search by keyword)."""
    return [m.groupdict() for m in RUT_ENTRY.finditer(text or "")]

def src_rutgers(pk):
    want = norm(binomial(pk["latin"])); gen = binomial(pk["latin"]).split()[0]
    entries, url_used, any_read = [], RUTGERS, False
    for kw in [gen, pk.get("common") or ""] + [s.split()[0] for s in pk["synonyms"]]:
        if not kw: continue
        url = RUTGERS + "?" + urllib.parse.urlencode({"keys": kw})
        t = fetch(url)
        if t is None: continue
        any_read = True; text = page_text(t)[0]
        found = rutgers_entries(text)
        if found:
            entries += found; url_used = url
            if any(norm(binomial(e["latin"])) == want for e in found): break
    if not any_read:
        pk["missing"].append("Rutgers deer list " + ("couldn't be reached" if unreachable(RUTGERS) else "couldn't be read")); return
    exact = [e for e in entries if norm(binomial(e["latin"])) == want]
    genus = [e for e in entries if norm(e["latin"]).split()[:1] == [norm(gen)] and re.search(r"\bspp?\.?(\s|$)|\(", e["latin"] + " ")]
    same_common = [e for e in entries if pk.get("common") and norm(e["common"]) == norm(pk["common"])]   # old names: Dicentra = Lamprocapnos
    hit = (exact or genus or same_common or [None])[0]
    if not hit:
        pk["facts"]["deer"] = {"value": None, "src": "Rutgers NJAES", "url": url_used, "note": "not on the Rutgers list: leave 'deer' out"}; return
    pk["facts"]["deer"] = {"value": hit["r"], "src": "Rutgers NJAES", "url": url_used,
                           "note": ("" if exact else "listed for the whole genus; " if genus else "matched by common name, check it's the same plant; ")
                                   + f"Rutgers entry: {hit['common']} - {hit['latin']} ({hit['type']})"}

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
BORDINES = ("Bordine's (Michigan garden center): perennials by bloom time, 2026", "https://bordines.com/wp-content/uploads/2026/08/bloom-time.pdf")

def pdf_text(data):
    try:
        import io, logging
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return None

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
    if not [x for x in found if not x.get("flagged")]:      # not a Michigan native: is it a garden favorite sold here?
        if "Bordine's" not in _shared:
            data = fetch(BORDINES[1], binary=True); _shared["Bordine's"] = pdf_text(data) if data else None
        t = _shared["Bordine's"]; hit = None
        if t:
            i = find_name(t, names)
            if i is None and pk.get("common"): i = find_name(t, [pk["common"]])
            if i is None:
                gen = binomial(pk["latin"]).split()[0]
                m = re.search(r"(?i)\b" + re.escape(gen) + r"\b", t); i = m.start() if m else None
            if i is not None: hit = snippet(t, i, 40, 120)
        pk["facts"]["garden_center"] = {"value": "listed" if hit else ("not listed" if t else "couldn't read"), "src": BORDINES[0], "url": BORDINES[1],
                                        "note": ("context: " + hit) if hit else ""}
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
    """The label drawn on the plan: up to 4 letters from the common name, the same pattern the website's checker enforces.
    One word: first 4 letters (Foam); two words: 2 letters of each (WiGe); three or more: first letter of each word (WBPh)."""
    name = pk["common"] or pk["latin"]
    words = [w for w in re.split(r"[^A-Za-z]+", re.sub(r"['\u2019]s\b", "s", re.sub(r"'[^']*'", "", name))) if w] or ["Plant"]
    taken = {c.lower() for c in used_codes}
    tries = []
    if len(words) == 1:
        w = words[0]; tries.append(w[:4].capitalize())
        cons = w[0] + "".join(ch for ch in w[1:] if ch.lower() not in "aeiou")      # drop vowels: Hosta -> Hst...
        tries += [cons[:4].capitalize(), (w[0] + w[2:5]).capitalize(), (w[:3] + w[-1]).capitalize()]
    elif len(words) == 2:
        a, b = words
        tries += [a[:2].capitalize() + b[:2].capitalize(), a[:1].upper() + b[:3].capitalize(), a[:3].capitalize() + b[:1].upper(),
                  a[:2].capitalize() + b[0].upper() + (b[2:3] or "")]
    else:
        ini = "".join(w[0].upper() for w in words[:4])
        tries += [ini + (words[-1][1:2] if len(ini) < 4 else ""), ini[:3], words[0][:2].capitalize() + words[-1][:2].capitalize()]
    for t in tries:
        if 2 <= len(t) <= 4 and t.lower() not in taken: return t
    base = (words[0][:3]).capitalize()
    for ch in "abcdefghijklmnopqrstuvwxyz":
        if (base + ch).lower() not in taken: return base + ch
    return "????"

# ---- turning the facts into finished planner fields

SEASONS = {"spring": (4.0, 6.0), "summer": (6.0, 9.0), "fall": (9.0, 10.5), "autumn": (9.0, 10.5), "winter": (3.0, 4.0)}
def bloom_from(mbg, ncsu):
    b = bloom_months(mbg)
    if b: return b, "Missouri Botanical Garden bloom time"
    ss = [SEASONS[w.lower()] for w in re.findall(r"(?i)\b(spring|summer|fall|autumn|winter)\b", ncsu or "")]
    if ss: return [min(a for a, _ in ss), max(b2 for _, b2 in ss)], "NC State bloom seasons"
    return None, ""

def zone_name(z): return f"{int(z)}{'b' if z % 1 else 'a'}"

def zone_range(mbg_zone, ncsu_zone):
    """-> (low, high) as numbers like 6.5 for 6b, or None"""
    m = re.search(r"(\d+)\s*(?:to|-)\s*(\d+)", mbg_zone or "")
    if m: return float(m.group(1)), float(m.group(2)) + 0.5
    zs = [int(n) + (0.5 if l.lower() == "b" else 0) for n, l in re.findall(r"\b(\d{1,2})([ab])\b", ncsu_zone or "")]
    if zs: return min(zs), max(zs)
    return None

def moisture_from(mbg_water, ncsu_drain):
    w = moisture_words(mbg_water)
    if w: return w
    d = (ncsu_drain or "").lower()
    if not d: return None
    dry, wet = "dry" in d, ("wet" in d or "standing water" in d)
    moist = "moist" in d
    if wet: return "Moist to wet"
    if dry and moist: return "Dry to moist"
    if dry: return "Dry to average"
    if moist: return "Average to moist"
    return "Average"

def light_words(sun, soil_bits):
    phrase = {("full",): "Full sun", ("full", "part"): "Sun to part shade", ("part",): "Part shade",
              ("part", "shade"): "Part shade to shade", ("shade",): "Shade", ("full", "part", "shade"): "Sun to shade"}.get(tuple(sun or ()), None)
    if not phrase: return None
    return phrase + ("; " + soil_bits if soil_bits else "")

def soil_words(moist, texture, drain):
    bits = []
    t = (texture or "").lower(); d = (drain or "").lower()
    if "organic" in t or "rich" in t: bits.append("rich")
    if moist and "moist" in moist.lower(): bits.append("moist")
    if moist and moist.lower().startswith("dry"): bits.append("dry to average")
    if "good drainage" in d or "well-drained" in d: bits.append("well-drained")
    return (", ".join(bits) + " soil") if bits else ""

COLOR_NAMES = [("white", (245, 245, 240)), ("cream", (240, 232, 205)), ("yellow", (240, 205, 60)), ("gold", (225, 165, 30)), ("orange", (235, 125, 40)),
               ("red", (200, 40, 45)), ("burgundy", (125, 30, 55)), ("pink", (235, 140, 175)), ("rose", (205, 85, 125)), ("magenta", (195, 60, 150)),
               ("lavender", (190, 160, 220)), ("purple", (125, 70, 160)), ("blue", (85, 120, 205)), ("green", (110, 150, 90)), ("brown", (130, 95, 65))]
def color_name(rgb):
    return min(COLOR_NAMES, key=lambda c: sum((a - b) ** 2 for a, b in zip(rgb, c[1])))[0]

def photo_color(path, foliage=False):
    """The main flower color in a photo (or the leaf green for ferns and grasses). Needs Pillow; returns '#RRGGBB' or None."""
    try:
        from PIL import Image
        import colorsys
    except Exception:
        return None
    try:
        im = Image.open(path).convert("RGB"); im.thumbnail((160, 120))
        w, h = im.size; px = list(im.getdata())
    except Exception:
        return None
    bins = {}
    for k, (r, g, b) in enumerate(px):
        x, y = k % w, k // w
        centre = 1.0 + 0.8 * (1 - (abs(x - w / 2) / (w / 2) + abs(y - h / 2) / (h / 2)) / 2)   # the subject is usually near the middle
        hh, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        green = 0.17 <= hh <= 0.47
        if foliage:
            if not green or ss < 0.18 or vv < 0.2: continue
            key = "g"
        else:
            if vv < 0.22: continue
            if ss < 0.12 and vv > 0.82: key = "white"                          # white and pale flowers
            elif green or ss < 0.22 or (0.05 <= hh <= 0.13 and vv < 0.55): continue   # leaves, sky-greys, soil and shadows
            else: key = int(hh * 24) % 24
        weight = centre * (1.6 if key == "white" else (0.5 + ss) * vv)
        bt = bins.setdefault(key, [0.0, 0.0, 0.0, 0.0]); bt[0] += weight; bt[1] += r * weight; bt[2] += g * weight; bt[3] += b * weight
    if not bins: return None
    key, (wt, R, G, B) = max(bins.items(), key=lambda kv: kv[1][0])
    if not foliage and key == "white" and len(bins) > 1:
        others = sorted((v for k2, v in bins.items() if k2 != "white"), key=lambda v: -v[0])
        if others and others[0][0] > wt * 0.9: wt, R, G, B = others[0]       # only call it white when white clearly wins
    rgb = tuple(int(c / wt) for c in (R, G, B))
    if not foliage:   # soften towards the planner's pastel-ish palette so labels stay readable
        rgb = tuple(int(c * 0.85 + 255 * 0.15) for c in rgb)
    return "#%02X%02X%02X" % rgb

# Planner-style colors for the words sources use. Order matters: the first word found in the text wins,
# and two-word colors are checked before single words.
WORD_HEX = [("blue-violet", "#5F63C0"), ("violet-blue", "#5F63C0"), ("blue-lavender", "#C2C5EE"), ("pink-lavender", "#D3A2D3"),
            ("lavender-blue", "#AEB4E6"), ("blue-purple", "#6A5FC0"), ("purple-blue", "#6A5FC0"), ("rose-pink", "#D96E95"), ("red-orange", "#E2603A"),
            ("yellow-green", "#C5D86A"), ("blue-green", "#9DB2A0"), ("gray-green", "#A7B29C"), ("grey-green", "#A7B29C"),
            ("chartreuse", "#C5D86A"), ("lime", "#C5D86A"), ("silver", "#BFC3B8"), ("variegated", "#B9CF95"),
            ("white", "#F3F1E6"), ("cream", "#F0E8CD"), ("ivory", "#F3F0DE"), ("yellow", "#F2D04A"), ("gold", "#E8B23A"), ("orange", "#EE8A3C"),
            ("scarlet", "#D2453F"), ("red", "#D2453F"), ("burgundy", "#8E2E4A"), ("maroon", "#8E2E4A"), ("crimson", "#B8324A"),
            ("magenta", "#C2509C"), ("fuchsia", "#C2509C"), ("rose", "#D06A8E"), ("pink", "#E59AB8"), ("mauve", "#C8A2C0"),
            ("lilac", "#C9B0E0"), ("lavender", "#C2A9DE"), ("violet", "#6E4FB0"), ("purple", "#8A5FC2"), ("blue", "#6C8FD8"),
            ("green", "#7FAA6C"), ("bronze", "#A67C4E"), ("brown", "#8C6A4A"), ("copper", "#B8733E")]
def word_hex(text):
    t = re.sub(r"\b\w+ish\b[- ]?", "", (text or "").lower()); best = None          # 'greenish-white' -> 'white'
    pale = re.search(r"\b(pale|soft|light|pastel)\b", t)
    for w, hx in WORD_HEX:
        k = t.find(w)
        if k >= 0 and (best is None or k < best[0] or (k == best[0] and len(w) > best[2])): best = (k, hx, len(w))
    if not best: return None
    hx = best[1]
    if pale:
        hx = "#%02X%02X%02X" % tuple(int(int(hx[i:i + 2], 16) * 0.55 + 255 * 0.45) for i in (1, 3, 5))
    return hx

def refine_with_photo(hexc, path):
    """Nudge a named color toward the photo's real shade, using only photo pixels close to that hue."""
    try:
        from PIL import Image
        import colorsys
        im = Image.open(path).convert("RGB"); im.thumbnail((160, 120)); px = list(im.getdata())
    except Exception:
        return hexc
    r0, g0, b0 = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h0, s0, v0 = colorsys.rgb_to_hsv(r0, g0, b0)
    if s0 < 0.15: return hexc                     # whites and creams: keep the clean planner shade
    acc, n = [0, 0, 0], 0
    for (r, g, b) in px:
        hh, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        dh = min(abs(hh - h0), 1 - abs(hh - h0))
        if dh < 0.05 and ss > 0.25 and vv > 0.3: acc[0] += r; acc[1] += g; acc[2] += b; n += 1
    if n < len(px) * 0.02: return hexc            # not enough of that color in the photo to trust it
    pr = [c / n for c in acc]
    mix = [int(0.5 * a * 255 + 0.5 * b) for a, b in zip((r0, g0, b0), pr)]
    return "#%02X%02X%02X" % tuple(mix)

def label_color(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#2E3A2C" if L > 0.32 else "#FFFFFF"

GOOD = re.compile(r"(?i)\b(attract|pollinat|butterfl|bees?\b|hummingbird|bloom|flower|foliage|leaves|fall color|evergreen|groundcover|ground cover|shade|deer|rabbit|native|edging|border|spread|clump|drought|long-lived|easy|low.maintenance|fragran)")
SKIP = re.compile(r"(?i)\b(named (after|for)|genus|etymolog|is native to|native range|synonym|botanist|derived from|latin|greek|USDA|zone|cultivar names?|commonly called|family \()")
CARE = re.compile(r"(?i)\b(soil|water|mulch|fertil|stak|deadhead|propagat|divid|plant(ed|ing)? (in|at)|grown? (best|in)|needs?\b|prefers?\b|tolerat|cut back|store)")
def draft_notes(*texts):
    """Two plain sentences on why it's worth growing, picked from the sources' descriptions (Claude rewords them)."""
    scored = []
    for t in texts:
        for k, snt in enumerate(re.split(r"(?<=[.!])\s+", t or "")):
            snt = snt.strip()
            if not (30 <= len(snt) <= 230) or SKIP.search(snt): continue
            score = 2 * len(re.findall(r"(?i)attract|pollinat|butterfl|hummingbird|\bbees?\b|bloom|flower|foliage|fall colou?r|evergreen|fragran|showy|long-lived", snt))
            score += len(GOOD.findall(snt)) - 3 * bool(CARE.search(snt)) - 0.05 * k
            if score > 0 and snt not in [x[1] for x in scored]: scored.append((score, snt))
    if not scored: return None
    scored.sort(key=lambda x: -x[0])
    out = scored[0][1]
    if len(scored) > 1 and len(out) + len(scored[1][1]) < 260: out += " " + scored[1][1]
    return out

def kind_from(fam, mbg_type, ncsu_type, blurb):
    t = ((mbg_type or "") + " " + (ncsu_type or "")).lower()
    if fam in FERN_FAMS or "fern" in t: return "fern", "family or plant type"
    if fam in ("Poaceae", "Cyperaceae", "Juncaceae") or "grass" in t or "sedge" in t: return "grass", "family or plant type"
    if "bulb" in t: return "bulb", "plant type says bulb"
    if "ground cover" in t or "groundcover" in t or re.search(r"(?i)ground ?cover|stolon|forms? (a )?(dense )?(mat|carpet|colon)", blurb or ""):
        return "mat", "described as a groundcover"
    return "clump", "no sign of fern, grass, bulb or groundcover"

def care_group(kind, fam, blurb, dormant, evergreen_hint):
    """The care.js cutting group: how the planner tells people to cut it back."""
    b = (blurb or "").lower()
    if kind == "bulb": return "bulb"
    if dormant: return "ephemeral"
    if kind == "grass": return "sedge" if fam == "Cyperaceae" else "grass"
    if kind == "fern": return "evfern" if evergreen_hint else "fern"
    if evergreen_hint and kind == "mat": return "tidy"
    if re.search(r"cut (it |them |the foliage |plants |stems )?back (to the ground )?(in|after) (the )?(fall|autumn|frost)|remove (the )?foliage in (the )?fall|powdery mildew|leaf blight|iris borer", b):
        return "fall"
    return None    # the standard spring cleanup

def status_record(pk):
    """Where the native / garden-favorite check came from, as a sources.js record."""
    F = lambda k: (pk["facts"].get(k) or {}).get("value")
    lists = [x for x in (F("michigan_lists") or []) if not x.get("flagged")]
    if lists: return {"kind": "native", "title": lists[0]["source"], "url": lists[0]["url"]}
    gc = pk["facts"].get("garden_center") or {}
    if gc.get("value") == "listed": return {"kind": "garden", "title": BORDINES[0], "url": BORDINES[1]}
    return None

def build_package(pk, choice=0):
    """Everything the website needs for this plant, made from the chosen photo, in inbox/<id>/website/."""
    d = os.path.join(INBOX, pk["id"], "website"); os.makedirs(d, exist_ok=True)
    entry = dict(pk["draft"]); photo = None
    if pk["photos"]:
        choice = max(0, min(choice, len(pk["photos"]) - 1)); photo = pk["photos"][choice]
        entry["credit"] = {"file": photo["file"].replace(" ", "_"), "by": photo["by"], "lic": photo["lic"]}
        # the color from the sources stays; nudge it to this photo's shade if it was a named color
        try:
            from PIL import Image, ImageOps
            import base64, io
            img = ImageOps.exif_transpose(Image.open(os.path.join(INBOX, photo["saved_as"])))
            w, h = img.size
            if w / h > 4 / 3: nw = round(h * 4 / 3); img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
            else: nh = round(w * 3 / 4); img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
            def b64(size, q):
                out = io.BytesIO(); img.convert("RGB").resize(size, Image.LANCZOS).save(out, "JPEG", quality=q, optimize=True, progressive=True)
                return base64.b64encode(out.getvalue()).decode()
            open(os.path.join(d, "photo-full.txt"), "w").write(b64((640, 480), 82))     # same sizes as the website's make_photos.py
            open(os.path.join(d, "photo-preview.txt"), "w").write(b64((240, 180), 60))
        except Exception as e:
            pk["warn"].append(f"couldn't make the website photo files ({e})")
    pk["photo_choice"] = choice
    lic_url = (photo or {}).get("licUrl") or ""
    if lic_url.startswith("//"): lic_url = "https:" + lic_url
    pkg = {"id": entry["id"], "entry": entry,
           "credit": ({"file": photo["file"], "by": photo["by"], "lic": photo["lic"], "licUrl": lic_url, "page": photo["page"]} if photo else None),
           "status": status_record(pk), "care": pk.get("care"), "warn": pk["warn"], "made": datetime.date.today().isoformat()}
    with open(os.path.join(d, "plant.json"), "w", encoding="utf-8") as f: json.dump(pkg, f, indent=1, ensure_ascii=False)
    return pkg

def choose_photos(choices):
    """choices: {plant id: photo index}. Rebuilds those plants' website files and the report."""
    path = os.path.join(INBOX, "packets.json")
    packets = json.load(open(path, encoding="utf-8"))
    for pk in packets:
        if pk["id"] in choices: build_package(pk, choices[pk["id"]])
    with open(path, "w", encoding="utf-8") as f: json.dump(packets, f, indent=1, ensure_ascii=False)
    md = report(packets)
    with open(os.path.join(INBOX, "report.md"), "w", encoding="utf-8") as f: f.write(md)
    with open(os.path.join(INBOX, "report.html"), "w", encoding="utf-8") as f: f.write(report_html(md))
    return packets

def draft(pk, used_ids, used_codes):
    F = lambda k: (pk["facts"].get(k) or {}).get("value")
    W = pk["warn"]
    h = feet_range(F("mbg_height")) or feet_range(F("ncsu_height"))
    sp = feet_range(F("mbg_spread")) or feet_range(F("ncsu_width"))
    fam = F("family") or ""
    blurb = " ".join(str(F(k) or "") for k in ("mbg_culture", "mbg_noteworthy_characteristics", "mbg_suggested_use", "mbg_garden_uses", "ncsu_description"))
    kind, why_kind = kind_from(fam, F("mbg_type"), F("ncsu_plant_type"), blurb)
    if re.search(r"(?i)\bdorman(t|cy)\b|ephemeral|dies back|disappears? (by|in) (mid|early|late)?\s?summer", blurb):
        W.append("a source mentions it going dormant: 'dormant: true' may be needed")
    zr = zone_range(F("mbg_zone"), F("ncsu_usda_plant_hardiness_zone"))
    if zr:
        pk["facts"]["hardy_in_6b"] = {"value": "yes" if zr[0] <= 6.5 <= zr[1] else "NO",
                                      "src": "Missouri Botanical Garden" if F("mbg_zone") else "NC State",
                                      "url": "", "note": f"hardiness zones {zone_name(zr[0])} to {zone_name(zr[1])} (Michigan here is 6B)"}
        if not (zr[0] <= 6.5 <= zr[1]): W.append(f"NOT hardy in Michigan zone 6B (sources say zones {zone_name(zr[0])} to {zone_name(zr[1])}): it won't come back each year, so it doesn't belong in the planner")
    lists = F("michigan_lists") or []
    native = bool([x for x in lists if not x.get("flagged")])
    # light and sun
    light_src = F("mbg_sun") or F("ncsu_light")
    sun = sun_list(light_src)
    moist = moisture_from(F("mbg_water"), F("ncsu_soil_drainage"))
    light = light_words(sun, soil_words(moist, F("ncsu_soil_texture"), F("ncsu_soil_drainage"))) or light_src
    # bloom and color
    bloom, why_bloom = (None, "") if kind in ("fern", "grass") else bloom_from(F("mbg_bloom_time"), F("ncsu_flower_bloom_time"))
    if kind not in ("fern", "grass") and not bloom: W.append("no bloom time found: grown for its leaves? (bloom: null)")
    foliage = kind in ("fern", "grass") or bloom is None
    src_colors = F("mbg_bloom_description") or F("ncsu_flower_color") or ""
    photo1 = os.path.join(INBOX, pk["photos"][0]["saved_as"]) if pk["photos"] else None
    many = len([c for c in re.split(r"[;,/]", src_colors) if c.strip()]) > 3
    words_for_hex = (F("ncsu_leaf_color") or "green") if foliage else ("" if many else src_colors)
    hexc, how_hex = word_hex(words_for_hex), "the color named by the sources"
    if hexc and photo1: hexc = refine_with_photo(hexc, photo1)
    if not hexc and many and photo1: hexc, how_hex = photo_color(photo1, foliage), "main color of photo 1 (sold in many colors)"
    if not hexc and photo1: hexc, how_hex = photo_color(photo1, foliage), "main color of photo 1 (no source named a color)"
    if foliage:
        color = (F("ncsu_leaf_color") or "Green").split(";")[0].strip() + " leaves"
    elif src_colors and not many:
        color = re.sub(r"\s*;\s*", " / ", src_colors).strip().capitalize()
    elif hexc:
        color = "Many colors (" + color_name(tuple(int(hexc[i:i + 2], 16) for i in (1, 3, 5))) + " shown)" if many else color_name(tuple(int(hexc[i:i + 2], 16) for i in (1, 3, 5))).capitalize()
    else:
        color = None
    if how_hex.startswith("main") and hexc and src_colors and not many and not foliage:
        named = color_name(tuple(int(hexc[i:i + 2], 16) for i in (1, 3, 5)))
        if named not in src_colors.lower() and not (named in ("cream", "white") and re.search(r"(?i)white|cream", src_colors)):
            W.append(f"the photo's main color looks {named}, the sources say '{src_colors}': check the photo or the color")
    if not hexc: hexc = "#6E9A5B" if foliage else "#C9A9D6"; W.append("couldn't read a color from the photo: hex is a placeholder")
    # safety
    toxic, why_tox = [], []
    sev = F("ncsu_poison_severity")
    if sev: toxic.append("people"); why_tox.append(f"NC State notes {sev.lower()}-severity poison")
    tox_pets = [a for a in ("dogs", "cats") if F("aspca_" + a) == "toxic"]
    toxic += tox_pets
    if tox_pets: why_tox.insert(0, "ASPCA lists it as toxic to " + " and ".join(tox_pets))
    notes = draft_notes(F("mbg_noteworthy_characteristics"), F("ncsu_description"), F("mbg_culture"), F("ncsu_flower_description"))
    filler = kind == "mat" and h and h[1] <= 12
    e = {"id": make_id(pk, used_ids), "code": make_code(pk, used_codes), "name": pk["common"] or (F("mbg_common_name") or "").title() or pk["latin"],
         "latin": pk["latin"], "native": native, "kind": kind, "filler": True if filler else None,
         "hLo": h[0] if h else None, "hHi": h[1] if h else None,
         "spacing": (round((sp[0] + sp[1]) / 2) if sp else None),
         "bloom": bloom, "color": color, "hex": hexc, "txt": label_color(hexc),
         "light": light, "sun": sun, "moisture": moist, "notes": notes,
         "deer": F("deer"), "toxic": (toxic or None), "toxSrc": ("; ".join(why_tox) if toxic else None),
         "fam": "daisy" if fam == "Asteraceae" else None,
         "credit": ({"file": pk["photos"][0]["file"].replace(" ", "_"), "by": pk["photos"][0]["by"], "lic": pk["photos"][0]["lic"]} if pk["photos"] else None)}
    dormant = bool(re.search(r"(?i)\bdorman(t|cy)\b|ephemeral|dies back|disappears? (by|in) (mid|early|late)?\s?summer", blurb))
    evergreen = bool(re.search(r"(?i)\bevergreen\b|semi-evergreen", blurb + " " + str(F("ncsu_woody_plant_leaf_characteristics") or "")))
    pk["care"] = care_group(kind, fam, blurb, dormant, evergreen)
    if dormant: e["dormant"] = True
    pk["draft"] = {k: v for k, v in e.items() if v not in (None, [], "")}
    if "bloom" not in pk["draft"]: pk["draft"]["bloom"] = None
    if not status_record(pk): W.append("not found on the Michigan native lists or the Michigan garden-center list: check it's sold here")
    pk["how"] = {"kind": why_kind, "care": pk["care"] or "standard spring cleanup", "bloom": why_bloom or ("fern/grass" if kind in ("fern", "grass") else "not found"),
                 "hex": how_hex, "notes": "picked from the source descriptions"}
    pk["to_finish"] = [k for k in ("name", "hLo", "hHi", "spacing", "light", "sun", "moisture", "color", "notes", "credit") if e.get(k) in (None, "", [])]
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
           "Made by Plant Research. Every field of the draft entry is filled from the sources and photo 1; Claude checks it against the saved pages and the Check notes, then adds the plant with ADDING-A-PLANT.md.", ""]
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
            ch = pk.get("photo_choice", 0)
            for i, p in enumerate(pk["photos"], 1): out.append(f"{i}. {'**USED ON THE WEBSITE** ' if i - 1 == ch else ''}`{p['saved_as']}` {p['file']}, {p['by'] or 'author unknown'}, {p['lic']} ({p['size']}) {p['page']}")
            out.append("")
            out.append(" ".join(f"![Photo {i}{' (used)' if i - 1 == ch else ''}]({p['saved_as']})" for i, p in enumerate(pk["photos"], 1)))   # shown as pictures in report.html
            out.append("")
        st = status_record(pk)
        out += [f"Native / garden favorite: {st['kind']} ({st['title']})" if st else "Native / garden favorite: not confirmed", "",
                f"Care group: {pk.get('care') or 'standard spring cleanup'}", ""]
        out += ["Plant entry (ready for the website):", "", "```js", "  " + json.dumps(pk["draft"], ensure_ascii=False), "```", ""]
        if pk.get("how"): out += ["How the draft was filled: " + "; ".join(f"{k}: {v}" for k, v in pk["how"].items()), ""]
        if pk["to_finish"]: out += ["Couldn't fill (no source had it): " + ", ".join(pk["to_finish"]), ""]
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
    per = 7 + (1 if photos else 0)          # name lookup + 6 sources (+ photos) per plant
    total, done = per * len(items), 0
    def prog(label):
        if PROGRESS:
            try: PROGRESS(done, total, label)
            except Exception: pass
    for n, (latin, common) in enumerate(items, 1):
        prog(f"Plant {n} of {len(items)}, {common or latin}: finding its botanical name")
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
        done += 1
        say(f"[{n}/{len(items)}] {common or latin} ({latin})")
        pk = {"latin": latin, "common": common, "id": "", "facts": {}, "synonyms": [], "pages": [], "photos": [], "missing": [], "warn": warn0}
        pk["id"] = make_id(pk, used_ids)
        if norm(binomial(latin)) in latins and "'" not in latin: pk["already"] = latins[norm(binomial(latin))]; say(f"    note: already in the planner as {pk['already']}")
        for step, fn in [("name check (GBIF)", src_gbif), ("Missouri Botanical Garden", src_mbg), ("NC State", src_ncsu),
                         ("Rutgers deer list", src_rutgers), ("ASPCA", src_aspca), ("Michigan native lists", src_michigan)] + \
                        ([("photos", src_photos)] if photos else []):
            say("    " + step); prog(f"Plant {n} of {len(items)}, {common or latin}: {step}")
            try: fn(pk)
            except Exception as e: pk["missing"].append(f"{step} failed ({e.__class__.__name__}: {e})"); say(f"    ! {step} failed: {e}")
            done += 1
        draft(pk, used_ids, used_codes)
        build_package(pk, 0)
        packets.append(pk)
        with open(os.path.join(INBOX, "packets.json"), "w", encoding="utf-8") as f: json.dump(packets, f, indent=1, ensure_ascii=False)
    md = report(packets)
    with open(os.path.join(INBOX, "report.md"), "w", encoding="utf-8") as f: f.write(md)
    with open(os.path.join(INBOX, "report.html"), "w", encoding="utf-8") as f: f.write(report_html(md))
    done = total; prog("Finished")
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
        imgs = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", ln)
        if imgs and re.fullmatch(r"(\s*!\[[^\]]*\]\([^)]+\))+\s*", ln):
            out.append('<div class="pics">' + "".join(
                f'<a href="{html.escape(src)}" target="_blank"><img src="{html.escape(src)}" alt="{html.escape(alt)}"><span>{html.escape(alt)}</span></a>'
                for alt, src in imgs) + "</div>"); continue
        if ln.startswith("## "): out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("# "): out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif re.match(r"^\d+\. ", ln): out.append(f"<p class=li>{inline(ln)}</p>")
        elif ln.strip(): out.append(f"<p>{inline(ln)}</p>")
    if in_table: out.append("</table>")
    css = ("body{font:15px/1.45 'Segoe UI',system-ui,sans-serif;color:#2E3A2C;max-width:1000px;margin:24px auto;padding:0 16px;background:#F4F2EA}"
           "h1{color:#3E6B35}h2{color:#3E6B35;border-top:2px solid #d8dccf;padding-top:14px;margin-top:28px}"
           "table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}td,th{border:1px solid #d8dccf;padding:4px 7px;text-align:left;vertical-align:top}"
           "th{background:#e7ecdf}pre{background:#fff;border:1px solid #d8dccf;padding:10px;overflow:auto;font-size:12px;white-space:pre-wrap}code{font-size:12px}p.li{margin:2px 0 2px 12px}"
           ".pics{display:flex;flex-wrap:wrap;gap:12px;margin:10px 0 16px}.pics a{display:block;text-decoration:none;color:#2E3A2C;text-align:center;font-weight:600}"
           ".pics img{display:block;width:260px;height:195px;object-fit:cover;border-radius:8px;border:1px solid #d8dccf;background:#fff;margin-bottom:4px}")
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
