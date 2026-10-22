# Guion de exposición del cliente de correo

## Preparación

Ejecutar `python demo_server.py` y dos instancias de `python app.py`.
Conectar Ana y Bruno con los botones de demo. No usar cuentas personales durante
la exposición. Ejecutar los tests antes de la presentación.

## Demostración de los requisitos

1. **SMTP:** Ana redacta un correo a Bruno con asunto `Entrega TP7` y cuerpo
   `El informe de Redes está listo`. Explicar que el cliente transmite un mensaje MIME
   con cabeceras y cuerpo, autenticándose en el servidor de envío.
2. **IMAP:** Bruno actualiza INBOX y abre el correo. Explicar que mantiene el buzón en
   el servidor y usa UID para identificar mensajes dentro de una carpeta y UIDVALIDITY.
3. **Responder:** Bruno responde; Ana actualiza y lee la respuesta. Mostrar en el código
   `In-Reply-To` y `References`, que permiten conservar el hilo.
4. **Reenviar:** Bruno reenvía a Ana. Comparar destinatario nuevo, asunto y texto original.
5. **Buscar:** filtrar por asunto `TP7`, cuerpo `Redes`, destinatario y fecha del día.
   Explicar filtros AND, comparación sin mayúsculas y fechas inclusivas.
6. **POP3:** cambiar Bruno a POP3, puerto 1110, NONE. Leer el mismo buzón y explicar
   UIDL, RETR, DELE y la confirmación de eliminaciones en QUIT.
7. **Eliminar:** seleccionar el correo, confirmar y volver a consultar desde IMAP.
8. **Robustez:** intentar conectar con contraseña incorrecta y mostrar el error de la GUI.
9. **Seguridad y logging:** mostrar `config.json` sin password y `logs/mail.log` sin
   datos de los mensajes. Explicar TLS en servidores reales y el loopback de la demo.

## Preguntas frecuentes

- **¿SMTP recibe correos del buzón?** SMTP envía/transporta mensajes. El cliente consulta
  el buzón con IMAP o POP3.
- **¿Por qué no se congela la ventana?** La red trabaja en un hilo secundario. Una cola
  comunica los resultados al hilo de Tkinter, que consulta con `after`.
- **¿Por qué búsqueda local incluso en IMAP?** Para ofrecer los mismos criterios y
  comportamiento en POP3 e IMAP. El costo es descargar el buzón para cada búsqueda.
- **¿El borrado IMAP siempre es inmediato?** Solo se expurga específicamente un UID si
  el servidor anuncia UIDPLUS. De otro modo se marca Deleted sin expurgar globalmente.
- **¿Qué bibliotecas se usan?** `smtplib`, `imaplib`, `poplib`, `email`, `ssl`, `tkinter`,
  `threading`, `queue`, `logging` y `unittest`, todas de la biblioteca estándar.
- **¿El servidor de demostración es el entregable principal?** No. Es un laboratorio
  reproducible de pruebas para el cliente y no implementa todos los RFC de correo.
- **¿Se probó con proveedores externos?** Las pruebas incluidas son locales. No afirmar
  compatibilidad con un proveedor sin comprobar sus protocolos y autenticación.
