# RDD-TP7-Mail-Client

Cliente de correo de escritorio para el **Trabajo Práctico 7 de Redes de Información,
UTN Facultad Regional Mendoza**. Implementa el punto 1 de la consigna con Python y
Tkinter, sin paquetes de terceros.

## Requisitos y ejecución

- Python **3.11 o superior** con Tcl/Tk (el instalador oficial de Windows permite incluirlo).
- Verificar Tkinter: `python -m tkinter` debe abrir una ventana.
- No hace falta `pip install`.

Desde la carpeta del proyecto:

```powershell
python app.py
```

Si Windows usa el lanzador `py`, reemplazar `python` por `py -3`.
Al abrir no se realiza ninguna conexión: entrar a **Cuenta**, completar los datos
y pulsar **Conectar y guardar**. Se guarda la configuración en `config.json`,
pero **nunca la contraseña**; hay que ingresarla de nuevo en cada ejecución.

## Demostración local sin una cuenta personal

En una terminal:

```powershell
python demo_server.py
```

En otra terminal:

```powershell
python app.py
```

1. Abrir **Cuenta → Demo: Ana → Conectar y guardar**.
2. Abrir otra instancia de `app.py` y elegir **Demo: Bruno**.
3. Enviar un mensaje desde Ana a `bruno@demo.local`.
4. En Bruno, pulsar **Actualizar**, seleccionar el mensaje y usar **Responder** o **Reenviar**.
5. Buscar por cuerpo, asunto, remitente, destinatario o fechas.
6. Para probar POP3, abrir **Cuenta**, seleccionar POP3 y establecer el puerto **1110**
   con seguridad **NONE**. El cambio de protocolo propone el puerto estándar 110;
   reemplazarlo por 1110 para el laboratorio. Conectar nuevamente.
7. Eliminar el mensaje y actualizar la otra instancia para ver el cambio.

| Servicio | Servidor | Puerto | Seguridad |
|---|---|---|---|
| SMTP | `127.0.0.1` | `1025` | `NONE` |
| IMAP | `127.0.0.1` | `1143` | `NONE` |
| POP3 | `127.0.0.1` | `1110` | `NONE` |

Cuentas: **ana@demo.local**, **bruno@demo.local** y **docente@demo.local**.
Contraseña de todas: **demo1234**. Docente también es una cuenta válida:
se puede entrar desde **Demo: Docente** y responder al mensaje de bienvenida.
Después de actualizar el código, reiniciar `demo_server.py` y `app.py` para cargar
los cambios. Reiniciar el servidor borra los mensajes del laboratorio en memoria.
SMTP también requiere autenticación. Se puede copiar `config.example.json` a
`config.json` como alternativa a los botones de configuración.

El servidor de laboratorio usa sockets TCP reales, está limitado a loopback e
implementa el subconjunto de comandos necesario para esta demo. **No es un servidor
de correo de producción**: no ofrece TLS, entrega a Internet ni persistencia. Al
cerrarlo se pierden los correos y al reiniciarlo reaparecen los mensajes iniciales.
Si un puerto está ocupado, admite `--smtp-port`, `--imap-port` y `--pop-port`;
actualizar también los puertos en Cuenta.

## Funciones y cumplimiento

| Requisito | Implementación |
|---|---|
| SMTP | Envío de mensajes de texto con destinatarios y copia |
| IMAP | Carpetas, listado, lectura y eliminación por UID |
| POP3 | Listado, lectura por UIDL y eliminación confirmada con QUIT |
| Responder | Reply-To, asunto Re:, texto citado, In-Reply-To y References |
| Reenviar | Asunto Fwd:, cabeceras originales y cuerpo citado |
| Eliminar | Confirmación explícita antes de modificar el servidor |
| Buscar | Remitente, destinatario (incluye CC), asunto, cuerpo y fechas inclusivas |

La bandeja inicial muestra los últimos **100** mensajes. **Buscar** recorre toda
la carpeta, combinando los filtros con AND, sin distinguir mayúsculas. Con filtros
vacíos lista toda la carpeta. **Limpiar / últimos 100** vuelve a la vista inicial.
Para uniformidad entre protocolos, el filtrado se hace localmente después de
descargar los mensajes; un buzón grande puede demorar y consumir memoria.

**IMAP:** se usa `BODY.PEEK[]` para leer sin marcar como leído y `UNDELETED` para
ocultar eliminados. Con UIDPLUS, el borrado usa `UID EXPUNGE` del mensaje seleccionado.
Sin UIDPLUS se marca `\\Deleted` y se oculta de esta aplicación, quedando pendiente
la eliminación física por el servidor u otro cliente. No se hace un EXPUNGE global,
porque podría borrar mensajes marcados por otra aplicación. Se comprueba UIDVALIDITY
antes de borrar para rechazar identificadores de un buzón recreado.

**POP3:** solo ofrece INBOX. La búsqueda se realiza sobre el contenido descargado.
`DELE` marca un correo y `QUIT` confirma su eliminación; si falla la operación se
cierra la conexión sin confirmar. No se eliminan mensajes al leerlos.

## Cuenta real y seguridad

Consultar los servidores, puertos y métodos de acceso habilitados por el proveedor.
La aplicación admite autenticación por usuario/contraseña, incluida una contraseña
de aplicación cuando el proveedor la permita. **OAuth2 no está implementado**; un
proveedor que lo exija no será compatible con esta versión.

Puertos habituales, que deben confirmarse con el proveedor:

| Protocolo | TLS directo (`SSL`) | STARTTLS |
|---|---|---|
| SMTP | 465 | 587 |
| IMAP | 993 | 143 |
| POP3 | 995 | 110 |

- SMTP y recepción comparten usuario y contraseña; se pueden configurar hosts distintos.
- TLS verifica certificados y nombre del servidor. No hay fallback automático a texto plano.
- `NONE` solo se acepta para `localhost`, `127.0.0.1` o `::1`.
- El correo HTML recibido se convierte a texto; no se ejecutan scripts ni se cargan imágenes.
- No hay adjuntos, OAuth2, papelera, borradores persistentes ni vista de conversaciones.
- SMTP acepta mensajes, pero su aceptación no garantiza la entrega final. No hay reintentos automáticos.
- No se guarda automáticamente una copia en Enviados; SMTP por sí solo no garantiza ese archivado.
- Las operaciones de red se ejecutan en un hilo separado y las actualizaciones de Tkinter
  exclusivamente en el hilo de la interfaz. Hay timeout de 20 segundos por operación de socket.
- Los registros rotativos `logs/mail.log` guardan operaciones, cantidades y tipos de error,
  sin contraseñas, asuntos ni cuerpos. Configuración, logs y cachés están ignorados en Git.

## Pruebas

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py mail_client.py demo_server.py tests
```

Las pruebas de integración levantan servidores efímeros en puertos locales libres.
No requieren que la demo esté ejecutándose ni conectan a proveedores externos.
Comprueban SMTP → IMAP, respuesta con hilo, reenvío, POP3, búsqueda y eliminación,
además del rechazo de contraseñas incorrectas. Las pruebas unitarias cubren MIME,
acentos, HTML, fechas, cabeceras, secretos y borrado seguro. Las pruebas de Tkinter
verifican ventanas, lectura y búsqueda desde la interfaz; se omiten si Tcl/Tk o
un entorno gráfico no están disponibles.

## Organización

```text
app.py                   Interfaz Tkinter y trabajo de red en segundo plano
mail_client.py           Configuración, MIME y clientes SMTP/IMAP/POP3
demo_server.py           Laboratorio local con tres cuentas
config.example.json      Configuración de ejemplo sin contraseña
tests/                   Pruebas unitarias, de protocolos y de interfaz
docs/IMPLEMENTACION.md    Diseño y decisiones
docs/DEFENSA.md           Guion para la exposición oral
```
