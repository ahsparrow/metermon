def connect():
    import machine
    import network
    import secrets

    network.hostname("metermon")

    wlan = network.WLAN()
    wlan.active(True)
    if not wlan.isconnected():
        print("connecting to network...")
        wlan.connect("cumulus-2g", secrets.WIFI_PASSWORD)
        while not wlan.isconnected():
            machine.idle()
    print("network config:", wlan.ipconfig("addr4"))


connect()
