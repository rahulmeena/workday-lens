import os
import pytest
from scripts import demo


def test_demo_refuses_an_existing_unmarked_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path)
    database = tmp_path / "demo.db"
    database.write_bytes(b"unrelated user data")
    with pytest.raises(SystemExit, match="unrelated"):
        demo.configure_demo()
    assert database.read_bytes() == b"unrelated user data"


def test_demo_overrides_inherited_real_data_and_cloud_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path)
    monkeypatch.setattr(os, "environ", {
        "WFHS_DATABASE_URL": "sqlite:////private/real.db",
        "WFHS_OPENAI_API_KEY": "fictional-test-value",
        "WFHS_FAKE_LLM": "false",
        "PATH": "preserved",
    })
    demo.configure_demo()
    assert os.environ["WFHS_DATABASE_URL"] == f"sqlite:///{tmp_path / 'demo.db'}"
    assert os.environ["WFHS_FAKE_LLM"] == "true"
    assert os.environ["WFHS_OPENAI_API_KEY"] == ""
    assert os.environ["PATH"] == "preserved"
    assert (tmp_path / "runtime-secrets.json").read_text() == "{}"
