import json
import tempfile
import unittest
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

import mail_client as mail


def message(subject="Reunión de redes", body="Entrega del práctico", **headers):
    msg = EmailMessage()
    msg["From"] = "Ana <ana@example.com>"
    msg["To"] = "equipo@example.com"
    msg["Subject"] = subject
    msg["Date"] = "Thu, 22 Oct 2026 12:00:00 -0300"
    msg["Message-ID"] = "<original@example.com>"
    for key, value in headers.items():
        msg[key] = value
    msg.set_content(body)
    return msg


class MailTests(unittest.TestCase):
    def test_mime_unicode_and_search(self):
        item = mail.parse_message("uid-1", message().as_bytes())
        self.assertEqual(item.subject, "Reunión de redes")
        self.assertIn("práctico", item.body)
        self.assertTrue(mail.matches(item, {"body": "PRÁCTICO", "to": "equipo", "since": date(2026, 10, 22)}))
        self.assertFalse(mail.matches(item, {"subject": "otro"}))
        self.assertFalse(mail.matches(item, {"until": date(2026, 10, 21)}))

    def test_html_fallback_ignores_scripts_and_attachments(self):
        msg = message()
        msg.set_content("<p>Hola <b>equipo</b></p><script>secreto()</script>", subtype="html")
        msg.add_attachment(b"no es cuerpo", maintype="application", subtype="octet-stream", filename="archivo.bin")
        item = mail.parse_message("1", msg.as_bytes())
        self.assertIn("Hola equipo", item.body)
        self.assertNotIn("secreto", item.body)
        self.assertNotIn("no es cuerpo", item.body)

    def test_reply_preserves_thread_and_reply_to(self):
        item = mail.parse_message("1", message(**{"Reply-To": "respuesta@example.com"}).as_bytes())
        draft = mail.make_draft(item, "reply")
        self.assertEqual(draft["to"], "respuesta@example.com")
        self.assertEqual(draft["subject"], "Re: Reunión de redes")
        self.assertIn("> Entrega", draft["body"])
        outgoing, recipients = mail.compose("yo@example.com", **draft)
        self.assertEqual(outgoing["In-Reply-To"], "<original@example.com>")
        self.assertEqual(recipients, ["respuesta@example.com"])

    def test_forward_has_original_headers_and_no_thread(self):
        item = mail.parse_message("1", message().as_bytes())
        draft = mail.make_draft(item, "forward")
        self.assertEqual(draft["to"], "")
        self.assertIn("ana@example.com", draft["body"])
        draft["to"] = "otro@example.com"
        outgoing, _ = mail.compose("yo@example.com", **draft)
        self.assertIsNone(outgoing["In-Reply-To"])

    def test_compose_cc_and_reject_header_injection(self):
        msg, recipients = mail.compose("yo@example.com", "uno@example.com", "Asunto", "Cuerpo", cc="dos@example.com")
        self.assertEqual(recipients, ["uno@example.com", "dos@example.com"])
        self.assertEqual(msg["Cc"], "dos@example.com")
        for recipient in ["sin-arroba", "uno@example.com\nBcc: otro@example.com", ""]:
            with self.assertRaises(ValueError):
                mail.compose("yo@example.com", recipient, "Hola", "Cuerpo")

    def test_config_never_persists_secrets(self):
        config = mail.MailConfig(password="super-secreto", username="yo@example.com")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            mail.save_config(config, path)
            self.assertNotIn("password", json.loads(path.read_text(encoding="utf-8")))
            self.assertNotIn("super-secreto", path.read_text(encoding="utf-8"))
            self.assertEqual(mail.load_config(path).username, config.username)

    def test_plaintext_restricted_to_loopback(self):
        config = mail.MailConfig(incoming_host="mail.example.com", incoming_security="NONE")
        with self.assertRaises(ValueError):
            config.validate()

    def test_pop_delete_uses_uidl_and_quit_commit(self):
        client = mail.MailService(mail.MailConfig(protocol="POP3", incoming_host="localhost", incoming_security="NONE", smtp_host="localhost"))
        with patch("mail_client.poplib.POP3") as constructor:
            pop = constructor.return_value
            pop.uidl.return_value = (b"+OK", [b"1 newer", b"2 wanted"], 0)
            client.delete_message("wanted")
            pop.dele.assert_called_once_with(2)
            pop.quit.assert_called_once()

    def test_imap_delete_does_not_expunge_other_messages(self):
        client = mail.MailService(mail.MailConfig(incoming_host="localhost", incoming_security="NONE", smtp_host="localhost"))
        with patch("mail_client.imaplib.IMAP4") as constructor:
            imap = constructor.return_value
            imap.login.return_value = ("OK", [])
            imap.response.return_value = ("UIDVALIDITY", [b"1"])
            imap.select.return_value = ("OK", [])
            imap.uid.return_value = ("OK", [])
            imap.capabilities = (b"IMAP4rev1",)
            client.delete_message("42")
            imap.uid.assert_called_once_with("STORE", "42", "+FLAGS.SILENT", "(\\Deleted)")
            imap.expunge.assert_not_called()
            imap.close.assert_not_called()
            imap.logout.assert_called_once()

    def test_imap_specific_expunge_when_supported(self):
        client = mail.MailService(mail.MailConfig(incoming_host="localhost", incoming_security="NONE", smtp_host="localhost"))
        with patch("mail_client.imaplib.IMAP4") as constructor:
            imap = constructor.return_value
            imap.select.return_value = ("OK", [])
            imap.uid.return_value = ("OK", [])
            imap.response.return_value = ("UIDVALIDITY", [b"1"])
            imap.capabilities = (b"IMAP4rev1", b"UIDPLUS")
            client.delete_message("42")
            self.assertEqual(imap.uid.call_args_list[-1].args, ("EXPUNGE", "42"))

    def test_imap_uidvalidity_change_blocks_stale_delete(self):
        client = mail.MailService(mail.MailConfig(incoming_host="localhost", incoming_security="NONE", smtp_host="localhost"))
        with patch("mail_client.imaplib.IMAP4") as constructor:
            imap = constructor.return_value
            imap.select.return_value = ("OK", [])
            imap.uid.return_value = ("OK", [b""])
            imap.response.return_value = ("UIDVALIDITY", [b"1"])
            client.list_messages()
            imap.uid.reset_mock()
            imap.response.return_value = ("UIDVALIDITY", [b"2"])
            with self.assertRaisesRegex(ValueError, "buzón cambió"):
                client.delete_message("42")
            imap.uid.assert_not_called()

    def test_starttls_happens_before_authentication(self):
        config = mail.MailConfig(address="yo@example.com", username="yo@example.com", password="clave",
                                 incoming_host="mail.example.com", incoming_security="STARTTLS", smtp_host="mail.example.com")
        with patch("mail_client.smtplib.SMTP") as constructor:
            smtp = constructor.return_value
            smtp.__enter__.return_value = smtp
            smtp.send_message.return_value = {}
            mail.MailService(config).send("otro@example.com", "TLS", "Cuerpo")
            calls = [call[0] for call in smtp.method_calls]
            self.assertLess(calls.index("starttls"), calls.index("login"))
            context = smtp.starttls.call_args.kwargs["context"]
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, mail.ssl.CERT_REQUIRED)

    def test_failed_starttls_never_sends_password_or_message(self):
        config = mail.MailConfig(address="yo@example.com", username="yo@example.com", password="clave", smtp_host="mail.example.com", incoming_host="mail.example.com")
        with patch("mail_client.smtplib.SMTP") as constructor:
            smtp = constructor.return_value
            smtp.__enter__.return_value = smtp
            smtp.starttls.side_effect = mail.ssl.SSLError("certificado rechazado")
            with self.assertRaises(mail.ssl.SSLError):
                mail.MailService(config).send("otro@example.com", "TLS", "Cuerpo")
            smtp.login.assert_not_called()
            smtp.send_message.assert_not_called()

    def test_partial_delivery_reports_ambiguity(self):
        config = mail.MailConfig(address="yo@example.com", smtp_host="localhost", smtp_security="NONE", incoming_host="localhost")
        with patch("mail_client.smtplib.SMTP") as constructor:
            smtp = constructor.return_value
            smtp.__enter__.return_value = smtp
            smtp.send_message.return_value = {"dos@example.com": (550, b"rechazado")}
            with self.assertRaisesRegex(RuntimeError, "Envío parcial"):
                mail.MailService(config).send("uno@example.com, dos@example.com", "Hola", "Cuerpo")

    def test_pop_failure_closes_without_committing_deletion(self):
        config = mail.MailConfig(protocol="POP3", incoming_host="localhost", incoming_security="NONE", smtp_host="localhost")
        with patch("mail_client.poplib.POP3") as constructor:
            pop = constructor.return_value
            pop.uidl.return_value = (b"+OK", [b"1 otro"], 0)
            with self.assertRaises(ValueError):
                mail.MailService(config).delete_message("no-existe")
            pop.quit.assert_not_called()
            pop.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
