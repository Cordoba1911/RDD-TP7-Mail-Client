"""Pruebas con conexiones TCP reales a un servidor efímero de laboratorio."""
import unittest

from demo_server import DemoServers
from mail_client import MailConfig, MailService, make_draft, matches


class ProtocolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.servers = DemoServers(smtp_port=0, imap_port=0, pop_port=0)
        self.servers.start()
        self.addCleanup(self.servers.stop)

    def service(self, protocol="IMAP", username="ana@demo.local", password="demo1234"):
        return MailService(MailConfig(
            address=username, username=username, password=password, protocol=protocol,
            incoming_host="127.0.0.1",
            incoming_port=self.servers.imap_port if protocol == "IMAP" else self.servers.pop_port,
            incoming_security="NONE", smtp_host="127.0.0.1", smtp_port=self.servers.smtp_port,
            smtp_security="NONE", smtp_auth=True))

    def test_smtp_send_imap_read_reply_forward_and_delete(self):
        ana = self.service()
        bruno = self.service(username="bruno@demo.local")
        self.assertIn("INBOX", ana.folders())
        ana.send("bruno@demo.local", "Prueba con acentos áéñ", "Cuerpo buscable único")
        items = bruno.list_messages(limit=0)
        original = next(m for m in items if m.subject == "Prueba con acentos áéñ")
        self.assertTrue(matches(original, {"body": "BUSCABLE", "from": "ana@demo.local"}))
        bruno.send(**make_draft(original, "reply"))
        reply = next(m for m in ana.list_messages() if m.subject.startswith("Re: Prueba"))
        self.assertIn(original.message_id, reply.references)
        draft = make_draft(original, "forward")
        draft["to"] = "ana@demo.local"
        bruno.send(**draft)
        self.assertTrue(any(m.subject.startswith("Fwd: Prueba") for m in ana.list_messages()))
        bruno.delete_message(original.uid)
        self.assertFalse(any(m.uid == original.uid for m in bruno.list_messages()))

    def test_pop_uidl_read_delete_and_imap_consistency(self):
        ana = self.service()
        pop = self.service("POP3", "bruno@demo.local")
        ana.send("bruno@demo.local", "POP3", ".Una línea que comienza con punto\nÚltima línea")
        item = next(m for m in pop.list_messages() if m.subject == "POP3")
        self.assertIn(".Una línea", item.body)
        pop.delete_message(item.uid)
        self.assertFalse(any(m.uid == item.uid for m in pop.list_messages()))
        self.assertFalse(any(m.subject == "POP3" for m in self.service(username="bruno@demo.local").list_messages()))

    def test_bad_credentials_fail_for_both_incoming_protocols(self):
        for protocol in ("IMAP", "POP3"):
            with self.subTest(protocol=protocol):
                with self.assertRaises(Exception):
                    self.service(protocol, password="incorrecta").list_messages()

    def test_bad_smtp_credentials_do_not_deliver(self):
        with self.assertRaises(Exception):
            self.service(password="incorrecta").send("bruno@demo.local", "No enviar", "Privado")
        self.assertFalse(any(m.subject == "No enviar" for m in self.service(username="bruno@demo.local").list_messages()))

    def test_reply_to_welcome_reaches_docente_and_docente_can_answer(self):
        ana = self.service()
        welcome = next(m for m in ana.list_messages() if m.subject == "Bienvenidos al TP7")
        ana.send(**make_draft(welcome, "reply"))
        docente = self.service(username="docente@demo.local")
        reply = next(m for m in docente.list_messages() if m.subject == "Re: Bienvenidos al TP7")
        docente.send(**make_draft(reply, "reply"))
        self.assertTrue(any(m.sender == "docente@demo.local" and m.subject.startswith("Re:")
                            for m in ana.list_messages()))
        self.assertTrue(self.service("POP3", "docente@demo.local").list_messages())


if __name__ == "__main__":
    unittest.main()
