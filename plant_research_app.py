"""Plant Research: the window version of gather_plants.py, built into a Windows program (Plant Research.exe).

Type or paste plant names, one per line (common names like "Foamflower" work, or botanical names, or
"Tiarella cordifolia | Foamflower"), press Start, then "Make zip for Claude" when it's done.
"""
import os, queue, sys, threading, zipfile, datetime, subprocess, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import gather_plants as g

LIST_FILE = os.path.join(g.HERE, "new-plants.txt")          # the typed list is kept between runs
SETTINGS = os.path.join(g.HERE, "plant-research-settings.txt")  # remembers the website folder, if picked by hand
GREEN, INK, BG = "#3E6B35", "#2E3A2C", "#F4F2EA"

def open_path(p):
    try:
        if sys.platform.startswith("win"): os.startfile(p)   # noqa: windows only
        elif sys.platform == "darwin": subprocess.Popen(["open", p])
        else: subprocess.Popen(["xdg-open", p])
    except Exception as e:
        messagebox.showerror("Plant Research", f"Couldn't open {p}\n{e}")

class App:
    def __init__(self, root):
        self.root, self.q, self.busy = root, queue.Queue(), False
        root.title("Plant Research (beta): Perennial Bed Planner")
        root.geometry("820x680"); root.minsize(600, 480); root.configure(bg=BG)
        st = ttk.Style(root)
        try: st.theme_use("clam")
        except tk.TclError: pass
        st.configure(".", background=BG, foreground=INK, font=("Segoe UI", 10))
        st.configure("TButton", padding=(10, 5))
        st.configure("Go.TButton", background=GREEN, foreground="white", font=("Segoe UI", 10, "bold"))
        st.map("Go.TButton", background=[("disabled", "#9db394"), ("active", "#4d8243")])
        st.configure("Head.TLabel", font=("Segoe UI", 15, "bold"), foreground=GREEN)
        st.configure("Small.TLabel", foreground="#5c6658")
        st.configure("TNotebook", background=BG); st.configure("TNotebook.Tab", padding=(14, 6), font=("Segoe UI", 10, "bold"))
        st.map("TNotebook.Tab", background=[("selected", "#ffffff"), ("!selected", "#e4e8dc")])
        st.configure("Treeview", rowheight=24, font=("Segoe UI", 10)); st.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        outer = ttk.Frame(root, padding=(14, 10, 14, 14)); outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Plant Research", style="Head.TLabel").pack(anchor="w")
        self.nb = ttk.Notebook(outer); self.nb.pack(fill="both", expand=True, pady=(6, 0))
        f = ttk.Frame(self.nb, padding=12); self.nb.add(f, text="Research new plants")
        self.tab_site = ttk.Frame(self.nb, padding=12); self.nb.add(self.tab_site, text="On the website")
        self.tab_wait = ttk.Frame(self.nb, padding=12); self.nb.add(self.tab_wait, text="To be added")
        ttk.Label(f, style="Small.TLabel", wraplength=740, justify="left",
                  text="Type or paste the plants to research, one per line. A common name is fine (Foamflower), or the "
                       "botanical name (Tiarella cordifolia), or both: Tiarella cordifolia | Foamflower").pack(anchor="w", pady=(2, 8))

        self.text = ScrolledText(f, height=9, wrap="word", font=("Segoe UI", 11), relief="solid", borderwidth=1, undo=True)
        self.text.pack(fill="both", expand=False)
        try:
            with open(LIST_FILE, encoding="utf-8") as fh: self.text.insert("1.0", fh.read().strip() + "\n")
        except OSError: pass

        row = ttk.Frame(f); row.pack(fill="x", pady=8)
        self.photos = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Get photo choices", variable=self.photos).pack(side="left")
        self.go = ttk.Button(row, text="Start", style="Go.TButton", command=self.start); self.go.pack(side="right")

        site_row = ttk.Frame(f); site_row.pack(fill="x")
        self.site = self.saved_site()
        self.site_lbl = ttk.Label(site_row, style="Small.TLabel", wraplength=600, justify="left"); self.site_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(site_row, text="Website folder…", command=self.pick_site).pack(side="right")
        self.show_site()

        # what it's doing right now: a bar, the current plant and source, and a running clock
        stat = ttk.Frame(f); stat.pack(fill="x", pady=(12, 0))
        self.status = tk.StringVar(value="Ready. Type some plants and press Start.")
        ttk.Label(stat, textvariable=self.status, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        st.configure("Green.Horizontal.TProgressbar", background=GREEN, troughcolor="#e4e8dc")
        self.bar = ttk.Progressbar(stat, mode="determinate", maximum=100, style="Green.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(4, 0))
        self.t0, self.label = None, ""
        bot = ttk.Frame(f); bot.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Label(f, text="Details", style="Small.TLabel").pack(anchor="w", pady=(10, 2))
        self.log = ScrolledText(f, height=6, wrap="word", font=("Consolas", 9), relief="solid", borderwidth=1, state="disabled", background="#FBFAF6")
        self.log.pack(fill="both", expand=True)

        self.b_report = ttk.Button(bot, text="Open overview", command=lambda: open_path(os.path.join(g.INBOX, "report.html")))
        self.b_folder = ttk.Button(bot, text="Open To be added folder", command=lambda: open_path(g.INBOX))
        self.b_zip = ttk.Button(bot, text="Make zip for Claude", command=self.make_zip)
        self.b_photos = ttk.Button(bot, text="Choose photos…", command=self.pick_photos)
        for b in (self.b_report, self.b_photos, self.b_folder): b.pack(side="left", padx=(0, 6))
        self.b_zip.pack(side="right")
        self.refresh_buttons()
        self.build_site_tab(); self.build_wait_tab()
        root.after(100, self.pump)

    # ---- tab: plants already on the website
    def site_data(self):
        g.SITE = g.find_site(self.site)
        return g.load_site(g.SITE) if g.SITE else None
    def build_site_tab(self):
        t = self.tab_site
        top = ttk.Frame(t); top.pack(fill="x")
        ttk.Label(top, text="Search").pack(side="left")
        self.site_q = tk.StringVar(); e = ttk.Entry(top, textvariable=self.site_q, width=32); e.pack(side="left", padx=8)
        self.site_q.trace_add("write", lambda *a: self.fill_site())
        ttk.Button(top, text="Refresh", command=self.fill_site).pack(side="right")
        self.site_info = ttk.Label(t, style="Small.TLabel", wraplength=740, justify="left"); self.site_info.pack(anchor="w", pady=(8, 6))
        cols = ("name", "latin", "code", "type")
        b = ttk.Frame(t); b.pack(side="bottom", fill="x", pady=(8, 0))
        fr = ttk.Frame(t); fr.pack(fill="both", expand=True)
        self.site_tv = ttk.Treeview(fr, columns=cols, show="headings", selectmode="extended")
        for c, w, lab in zip(cols, (240, 260, 70, 140), ("Plant", "Botanical name", "Code", "Michigan")): self.site_tv.heading(c, text=lab); self.site_tv.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.site_tv.yview); self.site_tv.configure(yscrollcommand=sb.set)
        self.site_tv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.site_tv.bind("<Double-1>", lambda e: self.open_site_page())
        ttk.Button(b, text="Open its page", style="Go.TButton", command=self.open_site_page).pack(side="left")
        ttk.Button(b, text="Make update zip for Claude", command=self.make_update_zip).pack(side="right")
        ttk.Button(b, text="Updates page", command=self.open_updates).pack(side="right", padx=6)
        b2 = ttk.Frame(t); b2.pack(side="bottom", fill="x", pady=(8, 0), before=b)
        ttk.Button(b2, text="Update selected", command=lambda: self.start_update(selected=True)).pack(side="right")
        ttk.Button(b2, text="Update all", command=lambda: self.start_update(selected=False)).pack(side="right", padx=6)
        ttk.Label(b2, text="Hardiness zones and winter care for website plants:", style="Small.TLabel").pack(side="right", padx=(0, 4))
        self.fill_site()
    def fill_site(self):
        sd = self.site_data(); tv = self.site_tv; tv.delete(*tv.get_children())
        if not sd:
            self.site_info.config(text="The website folder wasn't found. Use \"Website folder…\" on the first tab."); self.nb.tab(self.tab_site, text="On the website"); return
        q = g.norm(self.site_q.get()); n = 0
        for p in sorted(sd["plants"], key=lambda p: p["name"].lower()):
            if q and q not in g.norm(p["name"] + " " + p["latin"] + " " + p.get("code", "")): continue
            tv.insert("", "end", iid=p["id"], values=(p["name"], p["latin"], p.get("code", ""), "native" if p.get("native") else "garden favorite")); n += 1
        self.site_info.config(text=f"{len(sd['plants'])} plants are on the website" + (f" ({n} match the search)" if q else "") + f". Folder: {sd['site']}")
        self.nb.tab(self.tab_site, text=f"On the website ({len(sd['plants'])})")
    def open_updates(self):
        if os.path.isdir(g.UPDATES): open_path(g.write_update_page(self.site_data()))
        else: messagebox.showinfo("Plant Research", "No updates yet. Use \"Update all\" or \"Update selected\" first.")
    def start_update(self, selected):
        if self.busy: return
        sd = self.site_data()
        if not sd: messagebox.showinfo("Plant Research", "The website folder wasn't found."); return
        ids = list(self.site_tv.selection()) if selected else None
        if selected and not ids: messagebox.showinfo("Plant Research", "Select one or more plants in the list first (Ctrl-click for several)."); return
        n = len(ids) if ids else len(sd["plants"])
        mins = max(1, round(n * 6 / 60))
        if not messagebox.askyesno("Plant Research", f"Re-check {n} website plant{'s' if n != 1 else ''} for hardiness zones and winter care?\n\n"
                                   f"This takes about {mins} minute{'s' if mins != 1 else ''} the first time. Nothing on the website changes until Claude adds the update zip."): return
        self.mode = "update"; self.busy = True; self.go.state(["disabled"]); self.go.config(text="Working…"); self.refresh_buttons()
        self.nb.select(0)
        self.log.config(state="normal"); self.log.delete("1.0", "end"); self.log.config(state="disabled")
        g.OUT = lambda m: self.q.put(("log", m))
        g.PROGRESS = lambda d, tot, lab: self.q.put(("prog", (d, tot, lab)))
        self.t0, self.label = time.time(), "starting"; self.bar["value"] = 0
        self.root.title("Working… Plant Research (beta)")
        site = self.site
        def work():
            try: g.run_update(ids, site=site); self.q.put(("done", None))
            except Exception as e: self.q.put(("done", e))
        threading.Thread(target=work, daemon=True).start()
    def make_update_zip(self):
        if not os.path.isdir(g.UPDATES) or not [f for f in os.listdir(g.UPDATES) if f.endswith(".json")]:
            messagebox.showinfo("Plant Research", "No updates yet. Use \"Update all\" or \"Update selected\" first."); return
        name = os.path.join(g.HERE, f"plant-updates-{datetime.date.today().isoformat()}.zip")
        with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in os.listdir(g.UPDATES):
                z.write(os.path.join(g.UPDATES, fn), os.path.join("updates", fn))
        self.write(f"\nMade {name}\nAttach that file in your chat with Claude.")
        open_path(os.path.dirname(name))
    def open_site_page(self, pid=None):
        pid = pid or (self.site_tv.selection() or [None])[0]
        if not pid: return
        sd = self.site_data()
        if sd and pid in sd["by_id"]: open_path(g.site_page(sd, pid))

    # ---- tab: researched plants waiting to go on the website
    def build_wait_tab(self):
        t = self.tab_wait
        self.wait_info = ttk.Label(t, style="Small.TLabel", wraplength=740, justify="left"); self.wait_info.pack(anchor="w", pady=(0, 6))
        cols = ("name", "latin", "photo", "notes")
        b = ttk.Frame(t); b.pack(side="bottom", fill="x", pady=(8, 0))
        fr = ttk.Frame(t); fr.pack(fill="both", expand=True)
        self.wait_tv = ttk.Treeview(fr, columns=cols, show="headings", selectmode="browse")
        for c, w, lab in zip(cols, (200, 210, 70, 260), ("Plant", "Botanical name", "Photo", "Check")): self.wait_tv.heading(c, text=lab); self.wait_tv.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.wait_tv.yview); self.wait_tv.configure(yscrollcommand=sb.set)
        self.wait_tv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.wait_tv.bind("<Double-1>", lambda e: self.open_wait_page())
        ttk.Button(b, text="Open its page", style="Go.TButton", command=self.open_wait_page).pack(side="left")
        ttk.Button(b, text="Choose photos…", command=self.pick_photos).pack(side="left", padx=6)
        ttk.Button(b, text="Remove from list", command=self.remove_waiting).pack(side="left")
        ttk.Button(b, text="Make zip for Claude", command=self.make_zip).pack(side="right")
        self.fill_wait()
    def fill_wait(self):
        tv = self.wait_tv; tv.delete(*tv.get_children()); sd = self.site_data(); pk_all = g.waiting()
        for pk in pk_all:
            notes = []
            inc = pk.get("incomplete")
            if inc is None: inc = ["research it again (made by an older version)"]
            if inc: notes.append("NOT READY, missing: " + ", ".join(inc))
            if any("NOT hardy" in w for w in pk.get("warn", [])): notes.append("not hardy in 6B")
            now = g.site_match(sd, "", pk["latin"]) if sd else None
            if now: notes.append(f"now on the website ({now['name']})")
            if not pk.get("photos"): notes.append("no photo")
            tv.insert("", "end", iid=pk["id"], values=(pk.get("common") or pk["latin"], pk["latin"], f"#{pk.get('photo_choice', 0) + 1}" if pk.get("photos") else "-", "; ".join(notes) or "ready"))
        self.wait_info.config(text=(f"{len(pk_all)} researched plant(s) waiting to go on the website. Double-click one for its page. "
                                    "\"Make zip for Claude\" packs them all.") if pk_all else "Nothing waiting. Research some plants on the first tab.")
        self.nb.tab(self.tab_wait, text=f"To be added ({len(pk_all)})")
    def open_wait_page(self):
        pid = (self.wait_tv.selection() or [None])[0]
        if pid: open_path(os.path.join(g.INBOX, pid, "report.html"))
    def remove_waiting(self):
        pid = (self.wait_tv.selection() or [None])[0]
        if not pid: return
        if not messagebox.askyesno("Plant Research", f"Take {pid} off the To be added list? (Its research folder stays on the computer.)"): return
        import json
        left = [p for p in g.waiting() if p["id"] != pid]
        with open(os.path.join(g.INBOX, "packets.json"), "w", encoding="utf-8") as fh: json.dump(left, fh, indent=1, ensure_ascii=False)
        g.write_reports(left); self.fill_wait(); self.refresh_buttons()

    # ---- website folder (to check new plants against the ones already in the planner)
    def saved_site(self):
        try:
            with open(SETTINGS, encoding="utf-8") as fh: p = fh.read().strip()
            return p if os.path.isfile(os.path.join(p, "plants.js")) else None
        except OSError: return None
    def show_site(self):
        found = g.find_site(self.site)
        self.site_lbl.config(text=f"Website folder: {found}" if found else
                             "Website folder not found. It's optional, but lets new plants be checked against the ones already in the planner.")
    def pick_site(self):
        p = filedialog.askdirectory(title="Pick the perennial-bed-planner website folder (the one with plants.js)")
        if not p: return
        if not os.path.isfile(os.path.join(p, "plants.js")):
            messagebox.showwarning("Plant Research", "That folder doesn't have plants.js in it. Pick the website folder itself."); return
        self.site = p
        try:
            with open(SETTINGS, "w", encoding="utf-8") as fh: fh.write(p)
        except OSError: pass
        self.show_site()

    # ---- running
    def write(self, msg):
        self.log.config(state="normal"); self.log.insert("end", msg + "\n"); self.log.see("end"); self.log.config(state="disabled")
    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log": self.write(val)
                elif kind == "prog":
                    d, tot, self.label = val
                    self.bar["value"] = 100 * d / max(tot, 1)
                elif kind == "done": self.finish(val)
        except queue.Empty: pass
        if self.busy and self.t0:   # keep the clock moving even while one website is slow
            el = int(time.time() - self.t0)
            self.status.set(f"Working… {self.label}  ({el // 60}:{el % 60:02d})")
        self.root.after(100, self.pump)
    def refresh_buttons(self):
        has = os.path.isfile(os.path.join(g.INBOX, "report.md"))
        for b in (self.b_report, self.b_zip, self.b_photos): b.state(["!disabled"] if has and not self.busy else ["disabled"])
        self.b_folder.state(["!disabled"] if os.path.isdir(g.INBOX) else ["disabled"])
    def start(self):
        if self.busy: return
        raw = self.text.get("1.0", "end")
        items = g.parse_lines(raw.splitlines())
        if not items:
            messagebox.showinfo("Plant Research", "Type at least one plant name first."); return
        sd = self.site_data(); found = []
        if sd:
            for it in list(items):
                hit = g.site_match(sd, it[0]) or (g.site_match(sd, it[1]) if it[1] else None)
                if hit: found.append((it[1] or it[0], hit)); items.remove(it)
        if found:
            msg = "Already on the website, so they won't be researched again:\n\n" + "\n".join(f"  • {t}  →  {h['name']} ({h['latin']})" for t, h in found)
            msg += "\n\nTheir pages are on the \"On the website\" tab."
            if not items: messagebox.showinfo("Plant Research", msg); self.nb.select(self.tab_site); self.site_q.set(found[0][1]["name"]); return
            messagebox.showinfo("Plant Research", msg + f"\n\nResearching the other {len(items)}.")
        try:
            with open(LIST_FILE, "w", encoding="utf-8") as fh: fh.write(raw.strip() + "\n")
        except OSError: pass
        self.mode = "research"; self.busy = True; self.go.state(["disabled"]); self.go.config(text="Working…"); self.refresh_buttons()
        self.log.config(state="normal"); self.log.delete("1.0", "end"); self.log.config(state="disabled")
        g.OUT = lambda m: self.q.put(("log", m))
        g.PROGRESS = lambda d, tot, lab: self.q.put(("prog", (d, tot, lab)))
        self.t0, self.label = time.time(), "starting"; self.bar["value"] = 0
        self.root.title("Working… Plant Research (beta)")
        photos, site = self.photos.get(), self.site
        def work():
            try: g.run(items, photos=photos, site=site); self.q.put(("done", None))
            except Exception as e: self.q.put(("done", e))
        threading.Thread(target=work, daemon=True).start()
    def finish(self, err):
        self.busy = False; self.go.state(["!disabled"]); self.go.config(text="Start"); self.refresh_buttons()
        self.fill_wait(); self.fill_site()
        if g.ALREADY and not err:
            messagebox.showinfo("Plant Research", "Already on the website (found after looking up the botanical name), so not researched again:\n\n"
                                + "\n".join(f"  • {a['typed']}  →  {a['name']} ({a['latin']})" for a in g.ALREADY))
        el = int(time.time() - (self.t0 or time.time())); took = f"{el // 60}:{el % 60:02d}"
        now = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
        if err:
            self.status.set(f"Stopped at {now}: something went wrong (see Details)."); self.root.title("Stopped - Plant Research (beta)")
            self.write(f"\nSomething went wrong: {err}"); messagebox.showerror("Plant Research", f"Something went wrong:\n{err}")
        else:
            self.bar["value"] = 100
            upd = getattr(self, "mode", "") == "update"
            self.status.set(f"Finished at {now} (took {took}). " + ("See the Updates page, then Make update zip for Claude (On the website tab)." if upd
                            else "Check the photos (Choose photos…), then Make zip for Claude."))
            self.root.title("Done - Plant Research (beta)")
            if upd:
                self.write("\nNext: on the On the website tab, look at the Updates page, then press \"Make update zip for Claude\".")
                open_path(g.write_update_page(self.site_data()))
            else:
                nr = [pk for pk in g.waiting() if pk.get("incomplete")]
                if nr: self.write("\nNot ready (something wasn't found, so it can't go on the website yet):\n" + "\n".join(f"  {pk.get('common') or pk['latin']}: missing " + ", ".join(pk["incomplete"]) for pk in nr))
                self.write("\nNext: press \"Choose photos…\" to pick the photo for each plant (photo 1 is used unless you change it),\nthen \"Make zip for Claude\" and attach the zip in your chat.")
            try: self.root.bell(); self.root.deiconify(); self.root.lift()
            except tk.TclError: pass

    # ---- choosing each plant's photo for the website
    def pick_photos(self):
        try:
            import json
            from PIL import Image, ImageTk
        except Exception as e:
            messagebox.showerror("Plant Research", f"Photos can't be shown here ({e})."); return
        try: packets = json.load(open(os.path.join(g.INBOX, "packets.json"), encoding="utf-8"))
        except OSError: return
        win = tk.Toplevel(self.root); win.title("Choose the photo for each plant"); win.configure(bg=BG); win.geometry("900x620")
        ttk.Label(win, text="Click the photo to use on the website for each plant. Photo 1 is the best match unless you pick another.",
                  style="Small.TLabel", wraplength=860).pack(anchor="w", padx=14, pady=(12, 6))
        outer = ttk.Frame(win); outer.pack(fill="both", expand=True, padx=8)
        cv = tk.Canvas(outer, bg=BG, highlightthickness=0); sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv); inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=inner, anchor="nw"); cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
        win._imgs, choice = [], {}
        for pk in packets:
            if not pk.get("photos"): continue
            ttk.Label(inner, text=f"{pk['common'] or pk['latin']}  ({pk['latin']})", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 4), padx=6)
            row = ttk.Frame(inner); row.pack(anchor="w", padx=6)
            v = tk.IntVar(value=pk.get("photo_choice", 0)); choice[pk["id"]] = v
            for i, p in enumerate(pk["photos"]):
                cell = ttk.Frame(row); cell.pack(side="left", padx=6)
                try:
                    im = Image.open(os.path.join(g.INBOX, p["saved_as"])); im.thumbnail((260, 195)); ph = ImageTk.PhotoImage(im); win._imgs.append(ph)
                    tk.Radiobutton(cell, image=ph, variable=v, value=i, indicatoron=False, bd=4, relief="flat", bg=BG,
                                   selectcolor=GREEN, activebackground=BG, cursor="hand2").pack()
                except Exception:
                    ttk.Label(cell, text="(couldn't show this photo)").pack()
                ttk.Radiobutton(cell, text=f"Photo {i + 1}  ·  {p.get('by') or 'unknown'}"[:44], variable=v, value=i).pack(anchor="w")
        bar = ttk.Frame(win); bar.pack(fill="x", padx=14, pady=10)
        def save():
            g.choose_photos({k: v.get() for k, v in choice.items()})
            self.write("Photos chosen: " + ", ".join(f"{k} = photo {v.get() + 1}" for k, v in choice.items())); self.fill_wait()
            win.destroy()
        ttk.Button(bar, text="Use these photos", style="Go.TButton", command=save).pack(side="right")
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=8)

    def make_zip(self):
        if not os.path.isdir(g.INBOX): return
        notready = [pk for pk in g.waiting() if pk.get("incomplete") is None or pk.get("incomplete")]
        if notready and not messagebox.askyesno("Plant Research",
                "These plants aren't ready, so they won't go on the website until the missing parts are found:\n\n"
                + "\n".join(f"  • {pk.get('common') or pk['latin']}: " + ", ".join(pk.get("incomplete") or ["research it again"]) for pk in notready)
                + "\n\nMake the zip anyway (the ready plants can still be added)?"): return
        name = os.path.join(g.HERE, f"plant-research-{datetime.date.today().isoformat()}.zip")
        with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
            for d, dirs, files in os.walk(g.INBOX):
                dirs[:] = [x for x in dirs if x != ".cache"]           # the page cache stays behind
                for fn in files:
                    p = os.path.join(d, fn); z.write(p, os.path.join("inbox", os.path.relpath(p, g.INBOX)))
        self.write(f"\nMade {name}\nAttach that file in your chat with Claude.")
        open_path(os.path.dirname(name))

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
