import study_launcher


def test_dev_server_command_uses_python_module(monkeypatch):
    monkeypatch.setattr(study_launcher.sys, "frozen", False, raising=False)
    assert study_launcher._server_command()[-2:] == ["-m", "pokerlab.webapi"]


def test_port_probe_reports_closed_ephemeral_port():
    assert not study_launcher._port_open("127.0.0.1", 1, timeout=0.05)
