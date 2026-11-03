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

1. On this project's GitHub page, open **Releases** (right-hand side) and download **Plant.Research.exe** from the newest one (GitHub swaps the space for a dot; rename it if you like).
2. Make a folder called `perennial-bed-planner-research` next to your `perennial-bed-planner` website folder and put the
   .exe in it (or put the .exe straight into the folder that holds the website folder). It finds the website by itself and
   checks new plants against the ones already in the planner; if it can't, use the **Website folder…** button.
3. Double-click it. Windows may say it's from an unknown publisher (the program isn't paid-signed): choose
   **More info**, then **Run anyway**.
4. Type or paste the plants, one per line. A common name is fine (`Foamflower`), or the botanical name
   (`Tiarella cordifolia`), or both (`Tiarella cordifolia | Foamflower`). A plant typed by common name is looked up,
   and the report asks you to confirm it's the right one.
5. Press **Start** (a progress bar and clock show what it's doing). When it says Finished, **Open report** shows what was
   found, and **Choose photos…** lets you click the photo to use on the website for each plant (photo 1 unless you pick
   another). Then **Make zip for Claude** makes a zip to attach in your chat.
6. The zip is ready for the website: for each plant it holds the finished plant entry, the chosen photo in the
   website's sizes (full size and the small preview), the photo credit, the Michigan native or garden-center source,
   and the care group. On the website side, `research/add_plants.py <zip>` puts it all in place and runs the checks. Claude checks the facts against the saved pages and finishes the job using the website's
   [research/ADDING-A-PLANT.md](https://github.com/spreck79/perennial-bed-planner/blob/main/research/ADDING-A-PLANT.md)
   (photo, companions, sources, final check).

The window has three tabs:

- **Research new plants**: type the plants and press Start. Any plant already on the website (matched by its common or
  botanical name, also after a common name is looked up) isn't researched again; you're told where it is instead.
- **On the website**: every plant already in the planner, read from the website folder, with a search box. Double-click one
  for its page: photo, every detail, the photo credit, its Michigan source, care and companion plants.
  **Update all** / **Update selected** re-check those plants (no photos) for hardiness zones and winter care; **Updates page**
  shows what was found (and where the sources now differ from the website), and **Make update zip for Claude** packs it.
  Claude adds it with the website's `research/add_plants.py <zip> --update`, which adds only zones and winter care.
- **To be added**: researched plants waiting to go on the website, each with its own page. Choose photos, remove a plant
  from the list, or make the zip for Claude from here.

Folders beside the .exe (none of them is uploaded):

- `To be added\`: one folder per researched plant with its page (`report.html`), photo choices, the text of every source page
  it read and the website-ready files (`website\`); `report.html` here is the overview. Plants stay here until removed, so
  several runs can build up a batch.
- `Website plants\`: the pages for plants already on the website (made fresh each time one is opened).
- `Website updates\`: hardiness zones and winter care prepared for website plants, with `updates.html`.
- `new-plants.txt`: the list you last typed.

Copies of the pages it reads are kept for a week in `To be added\.cache`, so a second run is quick and easy on the websites
(they're left out of the zip). If a website can't be reached or has changed its layout, the page says what's missing.

## How the .exe is made

GitHub builds it automatically from the code here (see `.github/workflows/build-windows.yml`) every time the program
changes, and attaches it to a new release. You can also run the Python files directly if you ever have Python:
`python plant_research_app.py` for the window, or `python gather_plants.py new-plants.txt` from a command line.

## License

See LICENSE.txt: CC BY-NC 4.0, (c) 2026 spreck79. Downloaded photos keep their own licenses.
