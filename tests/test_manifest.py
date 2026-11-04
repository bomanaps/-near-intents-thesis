from __future__ import annotations

import json

import pytest

from analysis import manifest


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "model"
    data_dir.mkdir(parents=True)
    tracked = "data/model/sample.json"
    (tmp_path / tracked).write_text('{"x": 1}')
    record_dir = tmp_path / "data" / "raw" / "fastnear"
    record_dir.mkdir(parents=True)
    monkeypatch.setattr(manifest, "ROOT", tmp_path)
    monkeypatch.setattr(manifest, "MANIFEST", tmp_path / "data" / "manifest.json")
    monkeypatch.setattr(manifest, "UPLOAD_RECORD", record_dir / "last_upload.json")
    monkeypatch.setattr(manifest, "TRACKED", [tracked])
    return tmp_path, tracked


class TestRoundTrip:
    def test_write_then_verify_passes(self, sandbox, capsys):
        manifest.write()
        manifest.verify()
        out = capsys.readouterr().out
        assert "All integrity checks passed" in out

    def test_manifest_excludes_itself(self, sandbox):
        manifest.write()
        data = json.loads((sandbox[0] / "data" / "manifest.json").read_text())
        assert "data/manifest.json" not in data["files"]

    def test_upload_record_embedded_and_checked(self, sandbox, capsys):
        record = {
            "uploaded_at": "2026-11-04T08:00:00Z",
            "lines": 10,
            "sha256": "ab" * 32,
            "bytes": 1000,
            "repo": "x/y",
            "hf_commit": "deadbeef" * 5,
        }
        manifest.UPLOAD_RECORD.write_text(json.dumps(record))
        manifest.write()
        manifest.verify()
        out = capsys.readouterr().out
        assert "events_snapshot pinned to HF commit" in out


class TestTamperDetection:
    def test_modified_file_fails(self, sandbox):
        root, tracked = sandbox
        manifest.write()
        (root / tracked).write_text('{"x": 2}')
        with pytest.raises(SystemExit):
            manifest.verify()

    def test_missing_file_fails(self, sandbox):
        root, tracked = sandbox
        manifest.write()
        (root / tracked).unlink()
        with pytest.raises(SystemExit):
            manifest.verify()

    def test_malformed_upload_record_fails(self, sandbox):
        manifest.UPLOAD_RECORD.write_text(json.dumps({"lines": 5}))
        manifest.write()
        with pytest.raises(SystemExit):
            manifest.verify()
