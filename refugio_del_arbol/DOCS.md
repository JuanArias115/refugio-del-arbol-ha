# Portal Refugio del Arbol

Portal local para huéspedes. El portal expone únicamente cuatro luces del área Domo 1:

- Luces externas
- Luces nocheros
- Luz puente
- Luz baranda

Los relés del jacuzzi, reserva y mantenimiento no se exponen a huéspedes.

Después de instalar y arrancar la aplicación, abrir desde la red local:

`http://homeassistant.local:8099`

No se publica mediante Home Assistant Cloud. La aplicación no expone el token de Home Assistant y rechaza cualquier control que no esté incluido en su lista fija.

La administración se realiza desde un dashboard nativo de Home Assistant. Los helpers de ese dashboard permiten mostrar u ocultar cada luz y cambiar su nombre visible en el portal. El cableado de los relés no se puede cambiar desde ese dashboard.
