import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk
from pathlib import Path

from .converter import Converter

# When no per-page progress arrives for this long (model loading, a slow scanned
# page), the bar switches to an animated "busy" pulse so it never looks frozen.
_STALL_SECONDS = 1.2

# Translation targets offered in the UI → argos/ISO-639-1 codes. French first
# (the default target). Models download on first use of a given pair.
_LANG_CODES = {
    "Français": "fr",
    "Anglais": "en",
    "Espagnol": "es",
    "Allemand": "de",
    "Italien": "it",
    "Portugais": "pt",
    "Néerlandais": "nl",
    "Russe": "ru",
    "Chinois": "zh",
    "Arabe": "ar",
    "Japonais": "ja",
}


class _QueueStream:
    """Capture print() depuis le thread de conversion et l'envoie à la queue UI."""
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str):
        if text.strip():
            self._q.put(text.rstrip())

    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("pdf2md — PDF vers Markdown")
        self.resizable(True, True)
        self.minsize(680, 560)
        self._log_queue: queue.Queue = queue.Queue()
        self._converting = False
        self._indeterminate = False
        self._last_progress = 0.0
        self._build()
        self.after(100, self._poll_log)

    def _build(self):
        # Thème moderne si disponible
        try:
            self.tk.call("source", "")
        except Exception:
            pass
        try:
            style = ttk.Style(self)
            style.theme_use("vista")
        except Exception:
            pass

        root = ttk.Frame(self, padding=16)
        root.grid(sticky="nsew")
        # Let the window/frame stretch, and the log row (9) absorb extra height.
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(10, weight=1)

        # ── Source PDF ──────────────────────────────────────────────
        ttk.Label(root, text="Fichier PDF source :").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        self.pdf_var = tk.StringVar()
        ttk.Entry(root, textvariable=self.pdf_var, width=80).grid(
            row=1, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(root, text="Parcourir…", command=self._browse_pdf, width=12).grid(
            row=1, column=1
        )

        ttk.Separator(root, orient="horizontal").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=12
        )

        # ── Dossier de sortie ───────────────────────────────────────
        ttk.Label(root, text="Dossier de sortie :").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        self.out_var = tk.StringVar()
        ttk.Entry(root, textvariable=self.out_var, width=80).grid(
            row=4, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(root, text="Parcourir…", command=self._browse_out, width=12).grid(
            row=4, column=1
        )

        # ── Traduction (optionnelle) ────────────────────────────────
        trans = ttk.Frame(root)
        trans.grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.translate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            trans,
            text="Traduire la sortie vers :",
            variable=self.translate_var,
            command=self._toggle_lang,
        ).pack(side="left")
        self.lang_var = tk.StringVar(value="Français")
        self._lang_combo = ttk.Combobox(
            trans,
            textvariable=self.lang_var,
            width=14,
            state="disabled",
            values=list(_LANG_CODES.keys()),
        )
        self._lang_combo.pack(side="left", padx=(8, 0))

        # ── Bouton convertir ────────────────────────────────────────
        self._btn = ttk.Button(
            root, text="Convertir", command=self._start, width=20
        )
        self._btn.grid(row=6, column=0, columnspan=2, pady=(16, 8))

        # ── Barre de progression ─────────────────────────────────────
        self._progress_var = tk.IntVar(value=0)
        self._progress = ttk.Progressbar(
            root,
            orient="horizontal",
            length=680,
            mode="determinate",
            variable=self._progress_var,
            maximum=100,
        )
        self._progress.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._progress_label = tk.StringVar(value="")
        ttk.Label(root, textvariable=self._progress_label, foreground="gray").grid(
            row=8, column=0, columnspan=2, sticky="e", pady=(0, 4)
        )

        # ── Journal ─────────────────────────────────────────────────
        ttk.Label(root, text="Journal :").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        self._log = scrolledtext.ScrolledText(
            root,
            height=16,
            width=96,
            state="disabled",
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            relief="flat",
        )
        self._log.grid(row=10, column=0, columnspan=2, sticky="nsew")

        # ── Barre de statut ─────────────────────────────────────────
        self._status = tk.StringVar(value="Prêt.")
        ttk.Label(root, textvariable=self._status, foreground="gray").grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

    def _toggle_lang(self):
        """Enable the language picker only when translation is checked."""
        state = "readonly" if self.translate_var.get() else "disabled"
        self._lang_combo.configure(state=state)

    # ── Callbacks ───────────────────────────────────────────────────

    def _browse_pdf(self):
        path = filedialog.askopenfilename(
            title="Sélectionner un PDF ou une image",
            filetypes=[
                ("PDF et images", "*.pdf *.tif *.tiff *.png *.jpg *.jpeg *.jfif "
                                  "*.bmp *.gif *.webp *.ppm *.pgm *.pbm *.pnm "
                                  "*.jp2 *.j2k *.jpx *.ico *.tga *.psd"),
                ("Fichiers PDF", "*.pdf"),
                ("Images", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not path:
            return
        self.pdf_var.set(path)
        if not self.out_var.get():
            self.out_var.set(str(Path(path).parent))

    def _browse_out(self):
        path = filedialog.askdirectory(title="Dossier de sortie")
        if path:
            self.out_var.set(path)

    def _log_append(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _poll_log(self):
        while True:
            try:
                self._log_append(self._log_queue.get_nowait())
            except queue.Empty:
                break
        # Watchdog: if conversion is running but progress has stalled (models
        # loading, slow page), animate the bar so it never looks frozen.
        if self._converting and not self._indeterminate:
            if (
                time.time() - self._last_progress > _STALL_SECONDS
                and self._progress_var.get() < 100
            ):
                self._enter_indeterminate("Traitement en cours (modèles IA)…")
        self.after(100, self._poll_log)

    # ── Progress bar modes ──────────────────────────────────────────

    def _enter_indeterminate(self, label: str):
        """Animated 'busy' pulse — no known fraction (e.g. while models load)."""
        if not self._indeterminate:
            self._indeterminate = True
            self._progress.configure(mode="indeterminate")
            self._progress.start(12)
        self._progress_label.set(label)

    def _enter_determinate(self, pct: int, label: str):
        """Real fraction — stops the pulse and fills to pct."""
        if self._indeterminate:
            self._indeterminate = False
            self._progress.stop()
            self._progress.configure(mode="determinate")
        self._progress_var.set(pct)
        self._progress_label.set(label)
        self._last_progress = time.time()

    def _finish_progress(self, *, success: bool):
        self._converting = False
        if self._indeterminate:
            self._indeterminate = False
            self._progress.stop()
            self._progress.configure(mode="determinate")
        if success:
            self._progress_var.set(100)

    def _start(self):
        pdf = self.pdf_var.get().strip().strip('"')
        out = self.out_var.get().strip().strip('"')

        if not pdf:
            self._log_append("⚠  Sélectionnez un fichier PDF.")
            return
        pdf_path = Path(pdf)
        if not pdf_path.exists():
            self._log_append(f"⚠  Fichier introuvable : {pdf_path}")
            return

        out_path = Path(out) if out else pdf_path.parent
        target_lang = (
            _LANG_CODES.get(self.lang_var.get(), "fr")
            if self.translate_var.get()
            else None
        )
        self._btn.state(["disabled"])
        self._progress_var.set(0)
        self._status.set("Conversion en cours…")
        # Animate immediately — the first heavy step (loading the docling models)
        # reports no per-page progress and would otherwise leave the bar frozen.
        self._converting = True
        self._last_progress = time.time()
        self._enter_indeterminate("Analyse en cours — chargement des modèles IA…")
        threading.Thread(
            target=self._run, args=(pdf_path, out_path, target_lang), daemon=True
        ).start()

    def _on_extract_progress(self, current: int, total: int):
        pct = int(current * 50 / total) if total else 0
        label = f"Extraction  {current} / {total}"
        self.after(0, lambda: self._enter_determinate(pct, label))

    def _on_write_progress(self, current: int, total: int):
        pct = 50 + int(current * 50 / total) if total else 50
        label = f"Page {current} / {total}"
        self.after(0, lambda: self._enter_determinate(pct, label))

    def _run(self, pdf_path: Path, out_path: Path, target_lang: str | None = None):
        old_stdout = sys.stdout
        sys.stdout = _QueueStream(self._log_queue)
        try:
            results = Converter().convert(
                pdf_path, out_path,
                progress_cb=self._on_write_progress,
                extract_progress_cb=self._on_extract_progress,
                target_lang=target_lang,
            )
            for f in results:
                self._log_queue.put(f"  {f.name}")
            self._log_queue.put(f"OK  {len(results)} fichier(s) crees.")
            out_dir = out_path / pdf_path.stem
            self.after(0, lambda: self._finish_progress(success=True))
            self.after(0, lambda: self._status.set("Terminé."))
            self.after(0, lambda: self._progress_label.set("Terminé"))
            self.after(0, lambda d=out_dir: os.startfile(d))
        except Exception as exc:
            self._log_queue.put(f"✗  Erreur : {exc}")
            self.after(0, lambda: self._finish_progress(success=False))
            self.after(0, lambda: self._status.set("Erreur."))
        finally:
            sys.stdout = old_stdout
            self.after(0, lambda: self._btn.state(["!disabled"]))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
