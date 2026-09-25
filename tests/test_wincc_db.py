"""Deneysel .mdf şema tarayıcı: gerçek SQL Server yok -> sqlcmd taklit edilir; güvenlik davranışı test edilir."""
import subprocess

import pytest

from pcs7_analyzer.wincc_db import ProbeError, probe


class FakeSql:
    def __init__(self, data_dir, fail_attach=False):
        self.data_dir, self.fail_attach, self.queries = data_dir, fail_attach, []

    def __call__(self, cmd, **kw):
        q = cmd[cmd.index("-Q") + 1]
        self.queries.append(q)
        out, rc = "", 0
        if "InstanceDefaultDataPath" in q:
            out = str(self.data_dir) + "\n"
        elif q.startswith("CREATE DATABASE") and self.fail_attach:
            rc, out = 1, "Msg 5120: access denied"
        elif "sys.tables" in q:
            out = "dbo.MCPTCONNECTION\t12\ndbo.MCPTVARIABLEDESC\t951176\n"
        elif "INFORMATION_SCHEMA.COLUMNS" in q:
            out = "dbo.MCPTCONNECTION\tNAME\tnvarchar\ndbo.MCPTCONNECTION\tPARAM\tnvarchar\n"
        return subprocess.CompletedProcess(cmd, rc, out, out if rc else "")


@pytest.fixture
def files(tmp_path):
    src = tmp_path / "backup" / "SRV1"
    src.mkdir(parents=True)
    (src / "SRV1.mdf").write_bytes(b"orijinal mdf")
    (src / "SRV1.ldf").write_bytes(b"orijinal ldf")
    data = tmp_path / "sqldata"
    data.mkdir()
    return src / "SRV1.mdf", data


def test_attaches_only_copy_and_cleans_up(files):
    mdf, data = files
    sql = FakeSql(data)
    text = probe(mdf, runner=sql, sqlcmd="sqlcmd", log=lambda m: None)
    attach = next(q for q in sql.queries if q.startswith("CREATE DATABASE"))
    assert str(mdf) not in attach and str(data) in attach and "FOR ATTACH" in attach
    assert any("sp_detach_db" in q for q in sql.queries)
    assert list(data.iterdir()) == []                       # kopyalar silindi
    assert mdf.read_bytes() == b"orijinal mdf"              # orijinal değişmedi
    assert "dbo.MCPTVARIABLEDESC  [951176 satır]" in text and "NAME:nvarchar" in text


def test_attach_failure_still_cleans_up(files):
    mdf, data = files
    sql = FakeSql(data, fail_attach=True)
    with pytest.raises(ProbeError, match="access denied"):
        probe(mdf, runner=sql, sqlcmd="sqlcmd", log=lambda m: None)
    assert not any("sp_detach_db" in q for q in sql.queries)
    assert list(data.iterdir()) == []


def test_missing_sqlcmd(files, monkeypatch):
    mdf, _ = files
    monkeypatch.setattr("pcs7_analyzer.wincc_db.find_sqlcmd", lambda: None)
    with pytest.raises(ProbeError, match="sqlcmd bulunamadı"):
        probe(mdf, log=lambda m: None)
