"""Smoke test de Tkinter; no envía correos ni muestra diálogos modales."""
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from app import MailApp, SettingsDialog, Composer
from demo_server import DemoServers
from mail_client import MailConfig


class UITests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = MailApp(self.root, config_path=Path(self.temp.name) / "config.json")
        self.addCleanup(lambda: self.root.after_cancel(self.app.poll_id))

    def wait(self):
        deadline = time.monotonic() + 10
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertFalse(self.app.busy, "La operación no terminó")

    def test_widgets_and_composer(self):
        settings = SettingsDialog(self.app)
        settings.load_demo("ana@demo.local")
        self.assertEqual(settings.variables["incoming_port"].get(), "1143")
        self.assertEqual(settings.variables["password"].get(), "demo1234")
        settings.window.destroy()
        composer = Composer(self.app)
        composer.body.insert("1.0", "Borrador con acentos")
        self.assertIn("Borrador", composer.body.get("1.0", "end"))
        composer.window.destroy()

    def test_send_button_visible_at_default_and_minimum_size(self):
        self.root.deiconify()
        composer = Composer(self.app)
        self.addCleanup(composer.window.destroy)
        for geometry in ("760x570", "550x400"):
            with self.subTest(geometry=geometry):
                composer.window.geometry(geometry)
                self.root.update()
                button = composer.send_button
                self.assertTrue(button.winfo_ismapped(), "Enviar quedó oculto por el área del mensaje")
                self.assertGreater(button.winfo_width(), 30)
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     composer.window.winfo_rootx() + composer.window.winfo_width())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                     composer.window.winfo_rooty() + composer.window.winfo_height())

    def test_connect_read_and_search_with_real_sockets(self):
        servers = DemoServers(0, 0, 0)
        servers.start()
        self.addCleanup(servers.stop)
        config = MailConfig(address="ana@demo.local", username="ana@demo.local", password="demo1234",
                            incoming_host="127.0.0.1", incoming_port=servers.imap_port,
                            incoming_security="NONE", smtp_host="127.0.0.1", smtp_port=servers.smtp_port,
                            smtp_security="NONE")
        self.app.connect(config)
        self.wait()
        self.assertEqual(len(self.app.items), 1)
        uid = next(iter(self.app.items))
        self.app.tree.selection_set(uid)
        self.app.show_selected()
        self.assertIn("¡Éxitos", self.app.reader.get("1.0", "end"))
        self.app.search_vars["body"].set("no existe")
        self.app.search()
        self.wait()
        self.assertEqual(len(self.app.items), 0)

    def test_failed_folder_refresh_restores_displayed_folder(self):
        self.app.service = unittest.mock.Mock()
        self.app.display([])
        self.app.folder.set("Archive")
        self.app.service.list_messages.side_effect = OSError("desconectado")
        with patch("app.messagebox.showerror"):
            self.app.refresh()
            self.wait()
        self.assertEqual(self.app.folder.get(), "INBOX")


if __name__ == "__main__":
    unittest.main()
