"""Laboratorio local SMTP/IMAP/POP3. Subconjunto de comandos; no usar en producción.

Sin TLS y solo en 127.0.0.1. Tres cuentas, clave demo1234, mensajes en memoria.
"""
import argparse
import base64
import logging
import re
import shlex
import socketserver
import threading
from dataclasses import dataclass
from email import policy

from mail_client import compose

LOG = logging.getLogger("demo")
USERS = ("ana@demo.local", "bruno@demo.local", "docente@demo.local")
PASSWORD = "demo1234"


@dataclass
class StoredMail:
    uid: str
    raw: bytes
    deleted: bool = False


class MailStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.boxes = {user: [] for user in USERS}
        self.next_uid = 1
        for user in USERS:
            msg, _ = compose("docente@demo.local", user, "Bienvenidos al TP7",
                             "Probá enviar, responder, reenviar y buscar correos.\n¡Éxitos con Redes!")
            self.deliver([user], msg.as_bytes(policy=policy.SMTP))

    def deliver(self, recipients, raw):
        with self.lock:
            for user in recipients:
                self.boxes[user].append(StoredMail(str(self.next_uid), raw))
                self.next_uid += 1
        LOG.info("SMTP entrega aceptada: %d destinatario(s)", len(recipients))

    def messages(self, user):
        with self.lock:
            return list(self.boxes[user])

    def remove(self, user, uids):
        with self.lock:
            self.boxes[user] = [m for m in self.boxes[user] if m.uid not in uids]


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


class Handler(socketserver.StreamRequestHandler):
    timeout = 30

    def line(self, value):
        self.wfile.write(value.encode("utf-8") + b"\r\n")

    def read(self):
        raw = self.rfile.readline(1024 * 1024)
        if not raw:
            raise EOFError
        return raw.rstrip(b"\r\n").decode("utf-8", "replace")

    @property
    def store(self):
        return self.server.store

    @staticmethod
    def valid(user, password):
        return user in USERS and password == PASSWORD

    def handle(self):
        try:
            self.session()
        except (EOFError, ConnectionError, TimeoutError, OSError):
            pass


class SMTPHandler(Handler):
    def session(self):
        self.line("220 localhost TP7 laboratorio SMTP")
        authenticated = False
        recipients = []
        sender = False
        while True:
            line = self.read()
            command, _, argument = line.partition(" ")
            command = command.upper()
            if command in ("EHLO", "HELO"):
                self.line("250-localhost")
                self.line("250-AUTH PLAIN")
                self.line("250 SIZE 10485760")
            elif command == "AUTH":
                try:
                    mechanism, _, token = argument.partition(" ")
                    if mechanism.upper() != "PLAIN":
                        self.line("504 Solo AUTH PLAIN")
                        continue
                    if not token:
                        self.line("334 ")
                        token = self.read()
                    _, user, password = base64.b64decode(token, validate=True).decode().split("\x00")
                    authenticated = self.valid(user, password)
                except (ValueError, UnicodeError):
                    authenticated = False
                self.line("235 Autenticado" if authenticated else "535 Credenciales incorrectas")
            elif command == "MAIL":
                if not authenticated:
                    self.line("530 Autenticacion requerida")
                    continue
                sender = True
                recipients = []
                self.line("250 Remitente aceptado")
            elif command == "RCPT":
                match = re.search(r"<([^>]+)>", argument)
                user = match[1].lower() if match else ""
                if sender and user in USERS:
                    if user not in recipients:
                        recipients.append(user)
                    self.line("250 Destinatario aceptado")
                else:
                    self.line("550 Solo cuentas del laboratorio")
            elif command == "DATA" and authenticated and recipients:
                self.line("354 Terminar con punto")
                chunks = []
                size = 0
                while True:
                    raw = self.rfile.readline(1024 * 1024)
                    if not raw:
                        return
                    if raw in (b".\r\n", b".\n"):
                        break
                    if raw.startswith(b".."):
                        raw = raw[1:]
                    size += len(raw)
                    if size > 10 * 1024 * 1024:
                        self.line("552 Mensaje demasiado grande")
                        return
                    chunks.append(raw)
                self.store.deliver(recipients, b"".join(chunks))
                self.line("250 Mensaje aceptado")
                sender, recipients = False, []
            elif command == "RSET":
                sender, recipients = False, []
                self.line("250 Reiniciado")
            elif command == "NOOP":
                self.line("250 OK")
            elif command == "QUIT":
                self.line("221 Hasta luego")
                return
            else:
                self.line("503 Comando no disponible")


class IMAPHandler(Handler):
    def session(self):
        self.line("* OK TP7 laboratorio IMAP")
        user = None
        selected = False
        while True:
            line = self.read()
            try:
                args = shlex.split(line)
                tag, command = args[:2]
                args = args[2:]
            except ValueError:
                self.line("* BAD Sintaxis incorrecta")
                continue
            command = command.upper()
            if command == "CAPABILITY":
                self.line("* CAPABILITY IMAP4rev1 UIDPLUS")
            elif command == "LOGIN" and len(args) == 2:
                if not self.valid(*args):
                    self.line(tag + " NO Credenciales incorrectas")
                    continue
                user = args[0]
            elif command == "LOGOUT":
                self.line("* BYE Hasta luego")
                self.line(tag + " OK LOGOUT")
                return
            elif not user:
                self.line(tag + " NO Autenticacion requerida")
                continue
            elif command == "LIST":
                self.line('* LIST (\\HasNoChildren) "/" "INBOX"')
            elif command in ("SELECT", "EXAMINE") and args == ["INBOX"]:
                selected = True
                self.line("* FLAGS (\\Seen \\Deleted)")
                self.line(f"* {len(self.store.messages(user))} EXISTS")
                self.line("* OK [UIDVALIDITY 1] UIDs de laboratorio")
            elif command == "UID" and selected and len(args) >= 2:
                operation = args[0].upper()
                uid = args[1]
                messages = self.store.messages(user)
                if operation == "SEARCH":
                    self.line("* SEARCH " + " ".join(m.uid for m in messages if not m.deleted))
                elif operation == "FETCH":
                    found = next(((i, m) for i, m in enumerate(messages, 1) if m.uid == uid), None)
                    if found:
                        index, message = found
                        self.line(f"* {index} FETCH (UID {uid} BODY[] {{{len(message.raw)}}}")
                        self.wfile.write(message.raw)
                        self.line(")")
                elif operation == "STORE":
                    with self.store.lock:
                        for message in messages:
                            if message.uid == uid:
                                message.deleted = True
                elif operation == "EXPUNGE":
                    for index, message in enumerate(messages, 1):
                        if message.uid == uid and message.deleted:
                            self.store.remove(user, {uid})
                            self.line(f"* {index} EXPUNGE")
                else:
                    self.line(tag + " BAD Subcomando no disponible")
                    continue
            elif command != "NOOP":
                self.line(tag + " BAD Comando no disponible")
                continue
            self.line(tag + " OK " + command)


class POPHandler(Handler):
    def session(self):
        self.line("+OK TP7 laboratorio POP3")
        user = None
        authenticated = False
        pending = set()
        snapshot = []
        while True:
            command, _, argument = self.read().partition(" ")
            command = command.upper()
            if command == "USER":
                user = argument
                self.line("+OK Ingrese clave")
            elif command == "PASS":
                authenticated = self.valid(user, argument)
                if authenticated:
                    snapshot = self.store.messages(user)
                self.line("+OK Autenticado" if authenticated else "-ERR Credenciales incorrectas")
            elif command == "QUIT":
                if authenticated:
                    self.store.remove(user, pending)
                self.line("+OK Cambios confirmados")
                return
            elif not authenticated:
                self.line("-ERR Autenticacion requerida")
            elif command == "UIDL":
                self.line("+OK Identificadores")
                for i, message in enumerate(snapshot, 1):
                    if message.uid not in pending:
                        self.line(f"{i} {message.uid}")
                self.line(".")
            elif command in ("RETR", "DELE"):
                try:
                    number = int(argument)
                    if not 1 <= number <= len(snapshot):
                        raise ValueError
                    message = snapshot[number - 1]
                    if message.uid in pending:
                        raise ValueError
                except (ValueError, IndexError):
                    self.line("-ERR Mensaje inexistente")
                    continue
                if command == "DELE":
                    pending.add(message.uid)
                    self.line("+OK Marcado para eliminar")
                else:
                    self.line("+OK Mensaje")
                    for raw in message.raw.splitlines():
                        self.wfile.write((b"." if raw.startswith(b".") else b"") + raw + b"\r\n")
                    self.line(".")
            elif command == "RSET":
                pending.clear()
                self.line("+OK Marcas eliminadas")
            elif command == "STAT":
                active = [m for m in snapshot if m.uid not in pending]
                self.line(f"+OK {len(active)} {sum(len(m.raw) for m in active)}")
            elif command == "NOOP":
                self.line("+OK")
            else:
                self.line("-ERR Comando no disponible")


class DemoServers:
    def __init__(self, smtp_port=1025, imap_port=1143, pop_port=1110):
        self.store = MailStore()
        self.servers = []
        try:
            for name, port, handler in (("smtp", smtp_port, SMTPHandler), ("imap", imap_port, IMAPHandler), ("pop", pop_port, POPHandler)):
                server = Server(("127.0.0.1", port), handler)
                server.store = self.store
                self.servers.append(server)
                setattr(self, name + "_port", server.server_address[1])
        except OSError:
            for server in self.servers:
                server.server_close()
            raise

    def start(self):
        for server in self.servers:
            threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def stop(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smtp-port", type=int, default=1025)
    parser.add_argument("--imap-port", type=int, default=1143)
    parser.add_argument("--pop-port", type=int, default=1110)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    servers = DemoServers(args.smtp_port, args.imap_port, args.pop_port)
    servers.start()
    print(f"Laboratorio en 127.0.0.1: SMTP {servers.smtp_port}, IMAP {servers.imap_port}, POP3 {servers.pop_port}")
    print("Cuentas: " + ", ".join(USERS) + " | Clave: demo1234")
    print("Solo memoria y sin cifrado. No envía a Internet. Ctrl+C para terminar.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        servers.stop()


if __name__ == "__main__":
    main()
