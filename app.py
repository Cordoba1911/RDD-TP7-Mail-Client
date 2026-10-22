"""Interfaz de escritorio del cliente de correo del TP7."""
from dataclasses import asdict
from datetime import date
import imaplib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import poplib
import queue
import smtplib
import ssl
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from mail_client import (BASE_DIR, CONFIG_PATH, MailConfig, MailService, addresses,
                         compose, load_config, make_draft, matches, save_config)

LOG = logging.getLogger("mail_client")


def error_text(error):
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return "SMTP rechazó las credenciales. Revisá usuario, clave y método de acceso del proveedor."
    if isinstance(error, ssl.SSLError):
        return "No se pudo verificar la conexión TLS. Revisá servidor, puerto y modo de seguridad."
    if isinstance(error, (imaplib.IMAP4.error, poplib.error_proto)):
        return "El servidor de recepción rechazó la operación. Revisá credenciales, carpeta y protocolo."
    if isinstance(error, TimeoutError):
        return "El servidor tardó demasiado en responder. Revisá la conexión y volvé a intentar."
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "SMTP rechazó todos los destinatarios. Revisá las direcciones."
    if isinstance(error, smtplib.SMTPException):
        return "SMTP no confirmó el envío. Actualizá el buzón del destinatario antes de reintentar: podría haberlo recibido."
    if isinstance(error, OSError):
        return "No se pudo acceder al servidor o al archivo de configuración. Revisá dirección, puerto y permisos."
    if isinstance(error, (ValueError, RuntimeError)):
        return str(error)
    return "No se pudo completar la operación. Revisá la configuración y volvé a intentar."


class MailApp:
    def __init__(self, root, config_path=CONFIG_PATH):
        self.root = root
        self.config_path = Path(config_path)
        self.config = MailConfig()
        self.config_warning = ""
        try:
            self.config = load_config(self.config_path)
        except (OSError, ValueError, TypeError):
            self.config_warning = "No se pudo leer la configuración guardada. Completá una nueva en Cuenta."
        self.service = None
        self.items = {}
        self.busy = False
        self.results = queue.Queue()
        self.buttons = []
        self.folder = tk.StringVar(value="INBOX")
        self.items_folder = "INBOX"
        self.status = tk.StringVar(value=self.config_warning or "Configurá una cuenta o cargá la demo desde Cuenta.")
        self.search_vars = {key: tk.StringVar() for key in ("from", "to", "subject", "body", "since", "until")}
        root.title("RDD · TP7 | Cliente de correo")
        root.geometry("1120x760")
        root.minsize(880, 620)
        root.option_add("*Font", ("Segoe UI", 10))
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("Treeview", rowheight=29)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        shell = ttk.Frame(root, padding=18)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="Correo", style="Title.TLabel").pack(side="left")
        self.account_label = ttk.Label(header, text="SMTP · IMAP · POP3")
        self.account_label.pack(side="right")
        toolbar = ttk.Frame(shell)
        toolbar.pack(fill="x", pady=(0, 12))
        for text, action in (("Cuenta", self.settings), ("Actualizar", self.refresh),
                             ("Nuevo correo", self.new_message), ("Responder", lambda: self.new_message("reply")),
                             ("Reenviar", lambda: self.new_message("forward")), ("Eliminar", self.delete)):
            button = ttk.Button(toolbar, text=text, command=action)
            button.pack(side="left", padx=(0, 7))
            self.buttons.append(button)
        ttk.Label(toolbar, text="Carpeta:").pack(side="left", padx=(12, 5))
        self.folder_box = ttk.Combobox(toolbar, textvariable=self.folder, values=["INBOX"], state="readonly", width=18)
        self.folder_box.pack(side="left", fill="x", expand=True)
        self.folder_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        search_frame = ttk.LabelFrame(shell, text="Buscar en toda la carpeta · los criterios se combinan", padding=10)
        search_frame.pack(fill="x", pady=(0, 12))
        labels = (("from", "Remitente"), ("to", "Destinatario"), ("subject", "Asunto"),
                  ("body", "Cuerpo"), ("since", "Desde (AAAA-MM-DD)"), ("until", "Hasta (AAAA-MM-DD)"))
        for index, (key, label) in enumerate(labels):
            row, col = divmod(index, 3)
            cell = ttk.Frame(search_frame)
            cell.grid(row=row, column=col, sticky="ew", padx=5, pady=3)
            search_frame.columnconfigure(col, weight=1)
            ttk.Label(cell, text=label).pack(anchor="w")
            entry = ttk.Entry(cell, textvariable=self.search_vars[key])
            entry.pack(fill="x")
            entry.bind("<Return>", lambda _event: self.search())
        for index, (text, command) in enumerate((("Buscar", self.search), ("Limpiar / últimos 100", self.clear_search))):
            button = ttk.Button(search_frame, text=text, command=command)
            button.grid(row=index, column=3, padx=(12, 5), pady=5, sticky="ew")
            self.buttons.append(button)
        panes = ttk.Panedwindow(shell, orient="vertical")
        panes.pack(fill="both", expand=True)
        listing = ttk.Frame(panes)
        listing.rowconfigure(0, weight=1)
        listing.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(listing, columns=("sender", "subject", "date"), show="headings", selectmode="browse")
        for key, title, width in (("sender", "De", 250), ("subject", "Asunto", 460), ("date", "Fecha", 220)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=90)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_selected())
        self.tree.bind("<Double-1>", lambda _event: self.new_message("reply"))
        panes.add(listing, weight=2)
        self.reader = ScrolledText(panes, wrap="word", height=13, padx=12, pady=10,
                                   font=("Segoe UI", 11), state="disabled", relief="flat")
        panes.add(self.reader, weight=3)
        self.progress = ttk.Progressbar(shell, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 5))
        ttk.Label(shell, textvariable=self.status, wraplength=1030).pack(anchor="w")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(60, self.poll)

    def run(self, label, work, done):
        if self.busy:
            return False
        self.busy = True
        self.status.set(label)
        self.progress.start(12)
        for button in self.buttons:
            button.state(["disabled"])
        self.folder_box.configure(state="disabled")

        def worker():
            try:
                result = work()
                self.results.put((done, result, None))
            except Exception as error:
                # No registrar texto de excepciones de servidores: puede incluir secretos.
                LOG.warning("Operación fallida: %s", type(error).__name__)
                self.results.put((done, None, error))
        threading.Thread(target=worker, daemon=True).start()
        return True

    def poll(self):
        try:
            done, result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            for button in self.buttons:
                button.state(["!disabled"])
            self.folder_box.configure(state="readonly")
            if error:
                self.folder.set(self.items_folder)
                self.status.set("Operación no completada.")
                messagebox.showerror("No se pudo completar", error_text(error), parent=self.root)
            else:
                done(result)
        self.poll_id = self.root.after(60, self.poll)

    def settings(self):
        SettingsDialog(self)

    def connect(self, config):
        service = MailService(config)

        def work():
            folders = service.folders()
            folder = "INBOX" if "INBOX" in folders else folders[0]
            return folders, folder, service.list_messages(folder)

        def done(result):
            folders, folder, items = result
            self.service, self.config = service, config
            self.folder_box.configure(values=folders)
            self.folder.set(folder)
            self.account_label.configure(text=f"{config.address} · {config.protocol}")
            self.display(items)
            try:
                save_config(config, self.config_path)
            except OSError:
                messagebox.showwarning("Configuración", "Cuenta conectada, pero no se pudo guardar la configuración.", parent=self.root)
        self.run("Conectando y consultando la bandeja…", work, done)

    def connected(self):
        if self.service:
            return True
        messagebox.showinfo("Cuenta", "Primero conectá una cuenta desde el botón Cuenta.", parent=self.root)
        return False

    def display(self, items, searched=False):
        self.items_folder = self.folder.get()
        self.tree.delete(*self.tree.get_children())
        self.items = {item.uid: item for item in items}
        for item in items:
            self.tree.insert("", "end", iid=item.uid, values=(item.sender, item.subject, item.date_text))
        self.set_reader("")
        scope = "resultado(s) en toda la carpeta" if searched else "mensaje(s) · últimos 100 de la carpeta"
        self.status.set(f"{len(items)} {scope}. {self.config.protocol}: {self.folder.get()}")

    def set_reader(self, text):
        self.reader.configure(state="normal")
        self.reader.delete("1.0", "end")
        self.reader.insert("1.0", text)
        self.reader.configure(state="disabled")

    def selected(self):
        selection = self.tree.selection()
        return self.items.get(selection[0]) if selection else None

    def show_selected(self):
        item = self.selected()
        if item:
            self.set_reader(f"De: {item.sender}\nPara / CC: {item.to}\nAsunto: {item.subject}\n"
                            f"Fecha: {item.date_text}\n\n{item.body}")

    def refresh(self):
        if self.connected():
            service, folder = self.service, self.folder.get()
            self.run("Actualizando los últimos 100 mensajes…", lambda: service.list_messages(folder), self.display)

    def clear_search(self):
        for variable in self.search_vars.values():
            variable.set("")
        self.refresh()

    def search(self):
        if not self.connected() or self.busy:
            return
        criteria = {key: variable.get().strip() for key, variable in self.search_vars.items()}
        try:
            for key in ("since", "until"):
                criteria[key] = date.fromisoformat(criteria[key]) if criteria[key] else None
            if criteria["since"] and criteria["until"] and criteria["since"] > criteria["until"]:
                raise ValueError("La fecha Desde debe ser anterior o igual a Hasta.")
        except ValueError:
            messagebox.showerror("Fechas", "Usá fechas AAAA-MM-DD y un rango válido.", parent=self.root)
            return
        service, folder = self.service, self.folder.get()
        self.run("Buscando en toda la carpeta; buzones grandes pueden tardar…",
                 lambda: [item for item in service.list_messages(folder, limit=0) if matches(item, criteria)],
                 lambda items: self.display(items, searched=True))

    def new_message(self, action=None):
        if not self.connected() or self.busy:
            return
        draft = {}
        if action:
            item = self.selected()
            if not item:
                messagebox.showinfo("Seleccioná un correo", "Seleccioná un mensaje de la bandeja.", parent=self.root)
                return
            draft = make_draft(item, action)
        Composer(self, draft)

    def delete(self):
        item = self.selected()
        if not item or self.busy or not self.service:
            return
        note = "POP3 confirma el borrado al cerrar la sesión." if self.config.protocol == "POP3" else "IMAP lo elimina o marca como eliminado según las capacidades del servidor."
        if not messagebox.askyesno("Eliminar correo", f"¿Eliminar «{item.subject}»?\n\n{note}\nNo hay papelera implementada en este cliente.", parent=self.root):
            return
        service, folder = self.service, self.items_folder

        def done(_result):
            # El borrado ya fue confirmado; un fallo de actualización no debe confundirlo.
            self.items.pop(item.uid, None)
            if self.tree.exists(item.uid):
                self.tree.delete(item.uid)
            self.set_reader("")
            self.status.set("Eliminación confirmada por el servidor. Podés actualizar la bandeja.")
        self.run("Eliminando el mensaje seleccionado…", lambda: service.delete_message(item.uid, folder), done)

    def close(self):
        if self.busy:
            messagebox.showinfo("Operación en curso", "Esperá a que termine la operación antes de cerrar.", parent=self.root)
            return
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("Cuenta y servidores")
        self.window.transient(app.root)
        self.window.resizable(False, False)
        self.window.grab_set()
        panel = ttk.Frame(self.window, padding=18)
        panel.pack(fill="both", expand=True)
        self.variables = {key: (tk.BooleanVar(value=value) if isinstance(value, bool) else tk.StringVar(value=value))
                          for key, value in asdict(app.config).items()}
        fields = (("address", "Dirección de correo", None), ("username", "Usuario de autenticación", None),
                  ("password", "Contraseña (solo en memoria)", None), ("protocol", "Protocolo de recepción", ("IMAP", "POP3")),
                  ("incoming_host", "Servidor de recepción", None), ("incoming_port", "Puerto de recepción", None),
                  ("incoming_security", "Seguridad de recepción", ("SSL", "STARTTLS", "NONE")),
                  ("smtp_host", "Servidor SMTP", None), ("smtp_port", "Puerto SMTP", None),
                  ("smtp_security", "Seguridad SMTP", ("SSL", "STARTTLS", "NONE")))
        for row, (key, label, choices) in enumerate(fields):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            if choices:
                widget = ttk.Combobox(panel, textvariable=self.variables[key], values=choices, state="readonly", width=32)
                widget.bind("<<ComboboxSelected>>", lambda _event, field=key: self.default_port(field))
            else:
                widget = ttk.Entry(panel, textvariable=self.variables[key], width=35, show="●" if key == "password" else "")
            widget.grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Checkbutton(panel, text="Autenticar también en SMTP", variable=self.variables["smtp_auth"]).grid(row=10, columnspan=2, sticky="w", pady=5)
        ttk.Label(panel, text="SSL: TLS directo · STARTTLS: actualizar a TLS · NONE: solo loopback.\n"
                  "SMTP y recepción usan el mismo usuario y contraseña.\n"
                  "El proveedor debe admitir acceso con contraseña o contraseña de aplicación.", wraplength=530).grid(row=11, columnspan=2, sticky="w", pady=10)
        actions = ttk.Frame(panel)
        actions.grid(row=12, columnspan=2, sticky="ew")
        ttk.Button(actions, text="Demo: Ana", command=lambda: self.load_demo("ana@demo.local")).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Demo: Bruno", command=lambda: self.load_demo("bruno@demo.local")).pack(side="left")
        ttk.Button(actions, text="Demo: Docente", command=lambda: self.load_demo("docente@demo.local")).pack(side="left", padx=6)
        ttk.Button(actions, text="Conectar y guardar", command=self.apply).pack(side="right")
        ttk.Label(panel, text="Demo: primero ejecutá python demo_server.py en otra terminal.").grid(row=13, columnspan=2, sticky="w", pady=(12, 0))

    def default_port(self, field):
        if field in ("protocol", "incoming_security"):
            protocol = self.variables["protocol"].get()
            secure = self.variables["incoming_security"].get() == "SSL"
            self.variables["incoming_port"].set((993 if secure else 143) if protocol == "IMAP" else (995 if secure else 110))
        elif field == "smtp_security":
            self.variables["smtp_port"].set({"SSL": 465, "STARTTLS": 587, "NONE": 25}[self.variables[field].get()])

    def load_demo(self, user):
        values = dict(address=user, username=user, password="demo1234", protocol="IMAP",
                      incoming_host="127.0.0.1", incoming_port=1143, incoming_security="NONE",
                      smtp_host="127.0.0.1", smtp_port=1025, smtp_security="NONE", smtp_auth=True)
        for key, value in values.items():
            self.variables[key].set(value)

    def apply(self):
        try:
            values = {key: variable.get() for key, variable in self.variables.items()}
            for key in ("incoming_port", "smtp_port"):
                values[key] = int(values[key])
            for key in ("address", "username", "incoming_host", "smtp_host"):
                values[key] = values[key].strip()
            config = MailConfig(**values)
            config.validate()
            addresses(config.address, required=True)
            if not config.username or not config.password:
                raise ValueError("Completá usuario y contraseña.")
        except (TypeError, ValueError) as error:
            messagebox.showerror("Configuración inválida", error_text(error), parent=self.window)
            return
        self.window.destroy()
        self.app.connect(config)


class Composer:
    def __init__(self, app, draft=None):
        self.app = app
        self.draft = draft or {}
        self.window = tk.Toplevel(app.root)
        self.window.title("Redactar correo")
        self.window.geometry("760x570")
        self.window.minsize(550, 400)
        self.window.transient(app.root)
        # Modal: impide cambiar de cuenta con un borrador abierto.
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(self.window, padding=16)
        panel.pack(fill="both", expand=True)
        self.variables = {key: tk.StringVar(value=self.draft.get(key, "")) for key in ("to", "cc", "subject")}
        ttk.Label(panel, text=f"De: {app.config.address}").pack(anchor="w", pady=(0, 8))
        for key, label in (("to", "Para (separar con comas)"), ("cc", "Copia"), ("subject", "Asunto")):
            row = ttk.Frame(panel)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, width=26).pack(side="left")
            ttk.Entry(row, textvariable=self.variables[key]).pack(side="left", fill="x", expand=True)
        self.body = ScrolledText(panel, wrap="word", font=("Segoe UI", 11), padx=8, pady=8, undo=True)
        self.body.insert("1.0", self.draft.get("body", ""))
        footer = ttk.Frame(panel)
        # Reservar la barra antes de expandir el editor evita ocultar Enviar.
        footer.pack(side="bottom", fill="x")
        self.send_button = ttk.Button(footer, text="Enviar", command=self.send)
        self.send_button.pack(side="right")
        ttk.Label(footer, text="Texto plano · sin adjuntos · el envío se realiza por SMTP", wraplength=330).pack(side="left")
        self.body.pack(fill="both", expand=True, pady=12)
        self.body.focus_set()

    def close(self):
        if self.app.busy:
            return
        if messagebox.askyesno("Descartar borrador", "¿Cerrar y descartar este borrador?", parent=self.window):
            self.window.destroy()

    def send(self):
        if self.app.busy:
            return
        values = {key: variable.get().strip() for key, variable in self.variables.items()}
        values["body"] = self.body.get("1.0", "end-1c")
        values["in_reply_to"] = self.draft.get("in_reply_to", "")
        values["references"] = self.draft.get("references", "")
        try:
            compose(self.app.config.address, **values)
        except ValueError as error:
            messagebox.showerror("Revisá el correo", str(error), parent=self.window)
            return
        if not values["subject"] and not messagebox.askyesno("Sin asunto", "¿Enviar sin asunto?", parent=self.window):
            return
        service = self.app.service

        def done(_result):
            self.window.destroy()
            self.app.status.set("Correo aceptado por el servidor SMTP.")
            messagebox.showinfo("Correo enviado", "El servidor SMTP aceptó el mensaje. Actualizá la bandeja del destinatario para consultarlo.", parent=self.app.root)
        self.app.run("Enviando correo por SMTP…", lambda: service.send(**values), done)


def main():
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / "mail.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    root = tk.Tk()
    MailApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
