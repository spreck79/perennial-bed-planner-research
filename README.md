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

## Download and run (Windows, nothing to install)

1. On this project's GitHub page, open **Releases** (right-hand side) and download **Plant Research.exe** from the newest one.
2. Make a folder called `perennial-bed-planner-research` next to your `perennial-bed-planner` website folder and put the
   .exe in it (or put the .exe straight into the folder that holds the website folder). It finds the website by itself and
   checks new plants against the ones already in the planner; if it can't, use the **Website folder…** button.
3. Double-click it. Windows may say it's from an unknown publisher (the program isn't paid-signed): choose
   **More info**, then **Run anyway**.
4. Type or paste the plants, one per line. A common name is fine (`Foamflower`), or the botanical name
   (`Tiarella cordifolia`), or both (`Tiarella cordifolia | Foamflower`). A plant typed by common name is looked up,
   and the report asks you to confirm it's the right one.
5. Press **Start**. When it's done, **Open report** shows what was found, and **Make zip for Claude** makes a zip
   to attach in your chat. Claude checks the facts against the saved pages and finishes the job using the website's
   [research/ADDING-A-PLANT.md](https://github.com/spreck79/perennial-bed-planner/blob/main/research/ADDING-A-PLANT.md)
   (photo, companions, sources, final check).

The list you type is kept for next time (`new-plants.txt` beside the .exe), and the results go in an `inbox` folder beside it:

- `report.html` (and `report.md`): each plant's facts with their sources, a draft plants.js entry, and what's still missing
- `<id>\photo-1.jpg` to `photo-3.jpg`: the photo choices (credits are in the report)
- `<id>\pages\`: the text of every page it read, with the link at the top

Copies of the pages are kept for a week in `inbox\.cache`, so a second run is quick and easy on the websites
(they're left out of the zip). If a website can't be reached or has changed its layout, the report says what's missing
and that part is researched by hand. Nothing is uploaded; delete the inbox when you're done.

## How the .exe is made

GitHub builds it automatically from the code here (see `.github/workflows/build-windows.yml`) every time the program
changes, and attaches it to a new release. You can also run the Python files directly if you ever have Python:
`python plant_research_app.py` for the window, or `python gather_plants.py new-plants.txt` from a command line.

## License

See LICENSE.txt: CC BY-NC 4.0, (c) 2026 spreck79. Downloaded photos keep their own licenses.
