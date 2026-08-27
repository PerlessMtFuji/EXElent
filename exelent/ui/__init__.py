"""Warstwa GUI. Jedyne miejsce w projekcie, które importuje Qt.

Rdzeń (analiza → środowisko → build → diagnostyka) nie wie o istnieniu okna;
`tests/test_layering.py` tego pilnuje. Dzięki temu ta sama logika działa z CLI
i da się ją testować bez ekranu.
"""
