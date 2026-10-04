import json

from hca.audit import AuditLog, verify


def make(tmp_path, n=5):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    for i in range(n):
        log.append("proposal", i=i, changes={"web_t": 1.6})
    return p


def test_chain_verifies(tmp_path):
    p = make(tmp_path)
    assert verify(p)[0]
    AuditLog(p).append("review", approved=True)  # reopening continues the chain
    ok, msg = verify(p)
    assert ok and "6 records" in msg


def test_modified_record_detected(tmp_path):
    p = make(tmp_path)
    lines = p.read_text().splitlines()
    rec = json.loads(lines[2])
    rec["data"]["changes"]["web_t"] = 0.2
    lines[2] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    ok, msg = verify(p)
    assert not ok and "line 3" in msg


def test_deleted_and_reordered_records_detected(tmp_path):
    p = make(tmp_path)
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:2] + lines[3:]) + "\n")
    assert not verify(p)[0]
    p = make(tmp_path / "b")
    lines = p.read_text().splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    p.write_text("\n".join(lines) + "\n")
    assert not verify(p)[0]
