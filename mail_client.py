"""Cliente SMTP/IMAP/POP3. Solo biblioteca estándar; independiente de la GUI."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, make_msgid, parsedate_to_datetime
from html.parser import HTMLParser
import imaplib
import json
import logging
from pathlib import Path
import poplib
import re
import smtplib
import ssl

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG = logging.getLogger("mail_client")
TIMEOUT = 20


@dataclass
class MailConfig:
    address: str = ""
    username: str = ""
    password: str = ""
    protocol: str = "IMAP"
    incoming_host: str = ""
    incoming_port: int = 993
    incoming_security: str = "SSL"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "STARTTLS"
    smtp_auth: bool = True

    def validate(self):
        if self.protocol not in ("IMAP", "POP3"):
            raise ValueError("El protocolo debe ser IMAP o POP3.")
        for prefix in ("incoming", "smtp"):
            host = getattr(self, prefix + "_host").strip()
            security = getattr(self, prefix + "_security")
            port = getattr(self, prefix + "_port")
            if not host or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("Completá los servidores y puertos válidos (1–65535).")
            if security not in ("SSL", "STARTTLS", "NONE"):
                raise ValueError("Seguridad inválida.")
            if security == "NONE" and host.lower() not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("Sin cifrado solo se permite localhost, 127.0.0.1 o ::1.")


def save_config(config, path=CONFIG_PATH):
    values = asdict(config)
    values.pop("password")
    # Reemplazo atómico: una interrupción no deja un JSON parcialmente escrito.
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_config(path=CONFIG_PATH):
    path = Path(path)
    if not path.exists():
        return MailConfig()
    values = json.loads(path.read_text(encoding="utf-8"))
    return MailConfig(**{key: value for key, value in values.items()
                         if key in MailConfig.__dataclass_fields__ and key != "password"})


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "br", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1
        if tag in ("p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


@dataclass
class MailItem:
    uid: str
    sender: str
    to: str
    subject: str
    body: str
    date_text: str
    day: date | None
    message_id: str
    references: str
    reply_to: str


def parse_message(uid, raw):
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if part:
        payload = part.get_payload(decode=True) or b""
        try:
            body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            body = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            parser = _HTMLText()
            parser.feed(body)
            body = "".join(parser.parts).strip()
    date_text = str(msg.get("Date", ""))
    try:
        day = parsedate_to_datetime(date_text).date()
    except (ValueError, TypeError, OverflowError):
        day = None
    return MailItem(str(uid), str(msg.get("From", "")),
                    ", ".join(str(msg.get(h, "")) for h in ("To", "Cc")),
                    str(msg.get("Subject", "(sin asunto)")), body, date_text, day,
                    str(msg.get("Message-ID", "")), str(msg.get("References", "")),
                    str(msg.get("Reply-To", msg.get("From", ""))))


def matches(item, criteria):
    for key, attribute in (("from", "sender"), ("to", "to"), ("subject", "subject"), ("body", "body")):
        if criteria.get(key, "").casefold() not in getattr(item, attribute).casefold():
            return False
    if criteria.get("since") and (not item.day or item.day < criteria["since"]):
        return False
    if criteria.get("until") and (not item.day or item.day > criteria["until"]):
        return False
    return True


def addresses(text, required=False):
    if "\r" in text or "\n" in text:
        raise ValueError("Las direcciones no pueden contener saltos de línea.")
    if not text.strip():
        if required:
            raise ValueError("Ingresá al menos un destinatario válido.")
        return []
    parsed = getaddresses([text])
    result = []
    for _, address in parsed:
        if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+", address):
            raise ValueError("Dirección de correo inválida: " + address)
        if address not in result:
            result.append(address)
    if required and not result:
        raise ValueError("Ingresá al menos un destinatario válido.")
    return result


def compose(sender, to, subject, body, cc="", in_reply_to="", references=""):
    addresses(sender, required=True)
    recipients = list(dict.fromkeys(addresses(to, required=True) + addresses(cc)))
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    if cc:
        msg["Cc"] = cc
    msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip()
    msg.set_content(body)
    return msg, recipients


def make_draft(item, action):
    if action == "reply":
        subject = item.subject if item.subject.lower().startswith("re:") else "Re: " + item.subject
        return dict(to=item.reply_to, subject=subject,
                    body="\n\nEl " + item.date_text + ", " + item.sender + " escribió:\n" +
                    "\n".join("> " + line for line in item.body.splitlines()),
                    in_reply_to=item.message_id, references=item.references)
    if action != "forward":
        raise ValueError("Acción de redacción desconocida.")
    return dict(to="", subject="Fwd: " + item.subject,
                body=f"\n\n---------- Mensaje reenviado ----------\nDe: {item.sender}\n"
                     f"Para: {item.to}\nFecha: {item.date_text}\nAsunto: {item.subject}\n\n{item.body}")


class MailService:
    def __init__(self, config):
        self.config = config
        self.uid_validities = {}

    @contextmanager
    def _incoming(self):
        c = self.config
        c.validate()
        connection = None
        success = False
        try:
            context = ssl.create_default_context()
            if c.protocol == "IMAP":
                if c.incoming_security == "SSL":
                    connection = imaplib.IMAP4_SSL(c.incoming_host, c.incoming_port, ssl_context=context, timeout=TIMEOUT)
                else:
                    connection = imaplib.IMAP4(c.incoming_host, c.incoming_port, timeout=TIMEOUT)
                    if c.incoming_security == "STARTTLS":
                        connection.starttls(ssl_context=context)
                connection.login(c.username, c.password)
            else:
                if c.incoming_security == "SSL":
                    connection = poplib.POP3_SSL(c.incoming_host, c.incoming_port, context=context, timeout=TIMEOUT)
                else:
                    connection = poplib.POP3(c.incoming_host, c.incoming_port, timeout=TIMEOUT)
                    if c.incoming_security == "STARTTLS":
                        connection.stls(context=context)
                connection.user(c.username)
                connection.pass_(c.password)
            yield connection
            success = True
        finally:
            if connection:
                if c.protocol == "IMAP":
                    # CLOSE expurga todos los \Deleted: no usarlo aquí.
                    try:
                        connection.logout()
                    except (OSError, imaplib.IMAP4.error):
                        pass
                elif success:
                    # QUIT confirma DELE; el error debe llegar a la interfaz.
                    try:
                        connection.quit()
                    finally:
                        connection.close()
                else:
                    # Cierre abrupto: POP3 no debe confirmar eliminaciones fallidas.
                    connection.close()

    @staticmethod
    def _ok(response):
        status, data = response
        if status != "OK":
            raise RuntimeError("El servidor IMAP rechazó la operación.")
        return data

    @staticmethod
    def _select(connection, folder, readonly=True):
        # Las carpetas se reciben del servidor; comillas y escape para espacios.
        quoted = '"' + folder.replace('\\', '\\\\').replace('"', '\\"') + '"'
        MailService._ok(connection.select(quoted, readonly=readonly))
        _, values = connection.response("UIDVALIDITY")
        if not values or not isinstance(values[0], bytes) or not values[0].isdigit():
            raise RuntimeError("IMAP no informó UIDVALIDITY; no es seguro identificar los mensajes.")
        return values[0]

    def folders(self):
        if self.config.protocol == "POP3":
            return ["INBOX"]
        with self._incoming() as connection:
            rows = self._ok(connection.list())
            folders = []
            for row in rows:
                if not row or b"\\Noselect" in row:
                    continue
                match = re.match(rb'\([^)]*\)\s+(?:"[^"]*"|NIL)\s+(.+)', row)
                if match:
                    value = match[1].decode("ascii", "replace")
                    if value.startswith('"') and value.endswith('"'):
                        value = re.sub(r'\\(.)', r'\1', value[1:-1])
                    folders.append(value)
            return folders or ["INBOX"]

    def list_messages(self, folder="INBOX", limit=100):
        items = []
        with self._incoming() as connection:
            if self.config.protocol == "IMAP":
                validity = self._select(connection, folder)
                rows = self._ok(connection.uid("SEARCH", None, "UNDELETED"))
                uids = (rows[0] or b"").split()
                if limit:
                    uids = uids[-limit:]
                for uid in reversed(uids):
                    data = self._ok(connection.uid("FETCH", uid, "(BODY.PEEK[])"))
                    raw = next((row[1] for row in data if isinstance(row, tuple)), None)
                    if raw is not None:
                        items.append(parse_message(uid.decode("ascii"), raw))
            else:
                rows = connection.uidl()[1]
                if limit:
                    rows = rows[-limit:]
                for row in reversed(rows):
                    number, uid = row.split(maxsplit=1)
                    raw = b"\r\n".join(connection.retr(int(number))[1])
                    items.append(parse_message(uid.decode("ascii"), raw))
        if self.config.protocol == "IMAP":
            self.uid_validities[folder] = validity
        LOG.info("Bandeja consultada: protocolo=%s cantidad=%d", self.config.protocol, len(items))
        return items

    def delete_message(self, uid, folder="INBOX"):
        with self._incoming() as connection:
            if self.config.protocol == "IMAP":
                validity = self._select(connection, folder, readonly=False)
                if folder in self.uid_validities and validity != self.uid_validities[folder]:
                    raise ValueError("El buzón cambió de identificadores. Actualizá la bandeja antes de eliminar.")
                self._ok(connection.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)"))
                if b"UIDPLUS" in connection.capabilities:
                    self._ok(connection.uid("EXPUNGE", uid))
            else:
                mapping = {row.split(maxsplit=1)[1].decode("ascii"): int(row.split()[0])
                           for row in connection.uidl()[1]}
                if uid not in mapping:
                    raise ValueError("El mensaje ya no existe. Actualizá la bandeja.")
                connection.dele(mapping[uid])
        LOG.info("Mensaje eliminado: protocolo=%s", self.config.protocol)

    def send(self, to, subject, body, cc="", in_reply_to="", references=""):
        c = self.config
        c.validate()
        message, recipients = compose(c.address, to, subject, body, cc, in_reply_to, references)
        context = ssl.create_default_context()
        if c.smtp_security == "SSL":
            connection = smtplib.SMTP_SSL(c.smtp_host, c.smtp_port, timeout=TIMEOUT, context=context)
        else:
            connection = smtplib.SMTP(c.smtp_host, c.smtp_port, timeout=TIMEOUT)
        with connection:
            connection.ehlo()
            if c.smtp_security == "STARTTLS":
                connection.starttls(context=context)
                connection.ehlo()
            if c.smtp_auth:
                connection.login(c.username, c.password)
            refused = connection.send_message(message, from_addr=addresses(c.address, True)[0], to_addrs=recipients)
        if refused:
            raise RuntimeError("Envío parcial: algunos destinatarios fueron rechazados. No reenvíes a todos sin revisar.")
        LOG.info("Mensaje aceptado por SMTP: destinatarios=%d", len(recipients))
