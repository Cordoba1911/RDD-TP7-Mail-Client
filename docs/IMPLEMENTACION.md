# Diseño y plan aprobado

Cliente de escritorio en Python + Tkinter para el punto 1 del TP7 de Redes.
El usuario aprobó esta tecnología y autorizó implementar en este repositorio.

## Alcance

- SMTP para enviar; IMAP y POP3 para recibir y eliminar.
- Responder, reenviar, buscar por remitente, destinatario, asunto, cuerpo y fechas.
- Interfaz en español con trabajo de red en segundo plano.
- Contraseñas solo en memoria, TLS con verificación de certificados y logging sin secretos.
- Sin dependencias de terceros. Servidor local de demostración con los tres protocolos.

## Componentes

- `mail_client.py`: configuración, mensajes MIME y operaciones de protocolo.
- `app.py`: interfaz Tkinter, ejecución en segundo plano y presentación de resultados.
- `demo_server.py`: servidor de laboratorio limitado a loopback, con buzón en memoria
  y cuentas Ana, Bruno y Docente (todas admiten envío y recepción).
- `tests/`: pruebas unitarias y de integración con sockets locales.

## Secuencia de trabajo

1. Escribir y ejecutar pruebas de MIME, búsqueda, redacción, configuración y eliminación.
2. Implementar el servicio y verificar las pruebas.
3. Construir el servidor de demostración y pruebas de integración de los tres protocolos.
4. Construir la interfaz y verificar creación de ventanas y acciones básicas.
5. Documentar ejecución, semántica de los protocolos, límites y guion de exposición.

## Decisiones

- IMAP usa UID; POP3 usa UIDL, evitando borrar por un número de mensaje desactualizado.
- IMAP usa UID EXPUNGE solo con UIDPLUS; sin esa extensión marca el mensaje como eliminado,
  evitando un EXPUNGE global que podría borrar mensajes marcados por otro cliente.
- La búsqueda descarga el buzón seleccionado y filtra localmente para ofrecer los mismos
  criterios en POP3 e IMAP. La bandeja inicial muestra los últimos 100 mensajes.
- Texto plano; HTML recibido se convierte a texto y nunca se ejecuta.
- Sin adjuntos, OAuth2, múltiples cuentas simultáneas ni sincronización en segundo plano.
- El modo sin cifrado se permite exclusivamente con localhost/loopback para el laboratorio.
