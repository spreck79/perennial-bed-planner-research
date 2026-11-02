# Perennial Bed Planner: plant research (beta)

The research half of the [Perennial Bed Planner](https://github.com/spreck79/perennial-bed-planner).
Give it a list of plants and it gathers what's needed to add them to the planner: the facts from trusted
sources, a copy of every page it read, and free-licensed photo choices with their credits.

## What it collects for each plant

| What | Where from |
|---|---|
| Accepted botanical name and family | [GBIF](https://www.gbif.org) |
| Height, spread, bloom time and color, sun, water, culture notes | [Missouri Botanical Garden Plant Finder](https://www.missouribotanicalgarden.org/plantfinder/plantfindersearch.aspx) |
| Second opinion, poison notes | [NC State Extension Plant Toolbox](https://plants.ces.ncsu.edu) |
| Deer resistance (A to D) | [Rutgers NJAES deer-resistant plants list](https://njaes.rutgers.edu/deer-resistant-plants/) |
| Toxic to dogs or cats | [ASPCA plant lists](https://www.aspca.org/pet-care/animal-poison-control/toxic-and-non-toxic-plants) |
| Michigan native check | Black Cap Plants (Onekama), Michigan Tech KISMA, Michigan Wildflower Farm; plus a Michigan Flora link |
| Photos (3 choices, different photographers) | [Wikimedia Commons](https://commons.wikimedia.org), free licenses only (CC0, CC BY, CC BY-SA) |

## Setup

You need **Python 3** (nothing else to install). Put this folder next to the website folder:

    perennial-bed-planner\             the website
    perennial-bed-planner-research\    this program

It finds the website by itself and checks new plants against the ones already in the planner. If the website is
somewhere else, add `--site "C:\path\to\perennial-bed-planner"`.

## Use

1. Copy `new-plants-example.txt` to `new-plants.txt` and list your plants, one per line:
   the botanical name, then `|` and the common name if you like.
2. Run:

        python gather_plants.py new-plants.txt

3. Open `inbox\report.md` to see what was found. Then zip the `inbox` folder and give it to Claude with the plants
   you want added. Claude checks the facts against the saved pages and finishes the job using the website's
   [research/ADDING-A-PLANT.md](https://github.com/spreck79/perennial-bed-planner/blob/main/research/ADDING-A-PLANT.md)
   (photo, companions, sources, final check).

The `inbox` folder holds:

- `report.md`: each plant's facts with their sources, a draft plants.js entry, and what's still missing
- `packets.json`: the same, as data
- `<id>\photo-1.jpg` to `photo-3.jpg`: the photo choices (credits are in the report)
- `<id>\pages\`: the text of every page it read, with the link at the top

Other options: `--no-photos` skips the photos; `--fresh` ignores the saved copies of pages (they're kept for a week
in `inbox\.cache` so a second run is quick and easy on the websites).

If a website can't be reached or has changed its layout, the report says what's missing and that part is
researched by hand. The inbox stays on your computer and isn't uploaded; delete it when you're done.

## License

See LICENSE.txt: CC BY-NC 4.0, (c) 2026 spreck79. Downloaded photos keep their own licenses.
