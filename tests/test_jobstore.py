"""Tests para la persistencia de la cola de trabajos (jobstore.py)."""

import json

from jobstore import JobStore, StoredJob


def test_save_and_load_roundtrip(tmp_path):
    store = JobStore(path=tmp_path / "queue.json")
    store.set_jobs(
        [
            StoredJob(url="https://tiktok.com/a", status="Listo", result="out.mp4"),
            StoredJob(url="https://tiktok.com/b", status="Falló", error_message="boom"),
        ]
    )
    assert store.save() is True

    reloaded = JobStore(path=tmp_path / "queue.json")
    jobs = reloaded.load()
    assert len(jobs) == 2
    assert jobs[0].status == "Listo"
    assert jobs[1].error_message == "boom"


def test_load_returns_empty_when_file_missing(tmp_path):
    store = JobStore(path=tmp_path / "nope.json")
    assert store.load() == []


def test_load_ignores_corrupt_file(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text("{no es json", encoding="utf-8")
    store = JobStore(path=path)
    assert store.load() == []


def test_load_ignores_incompatible_version(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text(json.dumps({"version": 999, "jobs": []}), encoding="utf-8")
    store = JobStore(path=path)
    assert store.load() == []


def test_update_job_persists_change(tmp_path):
    path = tmp_path / "queue.json"
    store = JobStore(path=path)
    store.set_jobs([StoredJob(url="https://tiktok.com/x")])
    store.save()

    store.update_job("https://tiktok.com/x", status="Listo", result="final.mp4")

    reloaded = JobStore(path=path)
    jobs = reloaded.load()
    assert jobs[0].status == "Listo"
    assert jobs[0].result == "final.mp4"


def test_failed_and_retryable_urls(tmp_path):
    store = JobStore(path=tmp_path / "queue.json")
    store.set_jobs(
        [
            StoredJob(url="a", status="Falló"),
            StoredJob(url="b", status="Listo"),
            StoredJob(url="c", status="Pendiente"),
            StoredJob(url="d", status="Cancelado"),
        ]
    )
    assert [j.url for j in store.failed_jobs()] == ["a"]
    assert store.retryable_urls() == ["a"]
    assert store.pending_urls() == ["c", "d"]


def test_clear_removes_file(tmp_path):
    path = tmp_path / "queue.json"
    store = JobStore(path=path)
    store.set_jobs([StoredJob(url="a")])
    store.save()
    assert path.exists()

    store.clear()
    assert not path.exists()
    assert len(store) == 0


def test_save_is_atomic_leaves_no_temp_files(tmp_path):
    path = tmp_path / "queue.json"
    store = JobStore(path=path)
    store.set_jobs([StoredJob(url="a", title="Título con ñ")])
    store.save()

    # Solo debe quedar el fichero final: los temporales se renombran.
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["queue.json"]
    # El contenido debe estar en UTF-8 real, no escapado.
    assert "Título con ñ" in path.read_text(encoding="utf-8")
