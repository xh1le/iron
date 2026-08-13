from desktop import Bridge, open_window


def test_bridge_safe_without_window():
    b = Bridge()
    b.minimize()
    b.toggle_max()
    b.close()
    assert callable(open_window)
