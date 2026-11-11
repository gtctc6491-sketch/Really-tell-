from admin import (admins, appearance, broadcast, channels, fallback, gifts, panel, requests, settings, texts,
                   tickets, users)

# order matters: the permission-denied fallback must be last
routers = [
    panel.router, users.router, requests.router, gifts.router, tickets.router, broadcast.router,
    texts.router, appearance.router, channels.router, admins.router, settings.router, fallback.router,
]
