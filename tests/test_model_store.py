"""AI model packs: catalog, download with hash check, unzip, install marker, cancel, errors."""
import hashlib
import io
import zipfile

import pytest

from capture_tool.core import model_store as ms


def zip_bytes(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return b.getvalue()


class FakeWeb:
    def __init__(self, blobs):
        self.blobs, self.calls = dict(blobs), []

    def __call__(self, url, timeout=30):
        self.calls.append(url)
        if url not in self.blobs:
            raise OSError("HTTP 404")
        data = self.blobs[url]
        r = io.BytesIO(data)
        r.length = len(data)
        return r


def pack_of(blobs, unzip=False, pid="mt-xx_en", kind="mt"):
    files = tuple(ms.ModelFile(url=u, sha256=hashlib.sha256(d).hexdigest(), size=len(d),
                               name=u.rsplit("/", 1)[1], unzip=unzip) for u, d in blobs.items())
    return ms.Pack(pid, "테스트", kind, files)


def test_MS_01_download_verify_unzip_and_mark_installed(tmp_path):
    z = zip_bytes({"xx_en/model/model.bin": b"M" * 1000, "xx_en/sentencepiece.model": b"S"})
    web = FakeWeb({"https://h/p.zip": z})
    pack = pack_of(web.blobs, unzip=True)
    seen = []
    d = ms.download(pack, tmp_path, fetch=web, progress=lambda done, total: seen.append((done, total)))
    assert ms.installed_dir(pack, [tmp_path]) == d
    assert (d / "xx_en" / "model" / "model.bin").read_bytes() == b"M" * 1000
    assert seen[-1] == (len(z), len(z)) and all(a <= b for a, b in seen)
    assert not list(tmp_path.rglob("*.part")) and not list(tmp_path.rglob("*.zip"))


def test_MS_02_hash_mismatch_is_rejected_and_nothing_installed(tmp_path):
    web = FakeWeb({"https://h/m.onnx": b"good"})
    pack = pack_of(web.blobs)
    web.blobs["https://h/m.onnx"] = b"evil"
    with pytest.raises(ms.DownloadError) as e:
        ms.download(pack, tmp_path, fetch=web)
    assert "손상" in str(e.value)
    assert ms.installed_dir(pack, [tmp_path]) is None
    assert not list(tmp_path.rglob("*.part"))


def test_MS_03_cancel_cleans_up(tmp_path):
    web = FakeWeb({"https://h/big.bin": b"x" * (3 << 20)})
    pack = pack_of(web.blobs)
    with pytest.raises(ms.Cancelled):
        ms.download(pack, tmp_path, fetch=web, cancel=lambda: True)
    assert ms.installed_dir(pack, [tmp_path]) is None and not list(tmp_path.rglob("*.part"))


def test_MS_04_network_error_is_friendly(tmp_path):
    pack = pack_of({"https://h/none.bin": b"1"})
    with pytest.raises(ms.DownloadError) as e:
        ms.download(pack, tmp_path, fetch=FakeWeb({}))
    assert "인터넷" in str(e.value)


def test_MS_05_not_enough_disk_space(tmp_path, monkeypatch):
    pack = pack_of({"https://h/a.bin": b"1" * 10})
    monkeypatch.setattr(ms, "free_bytes", lambda p: 5)
    with pytest.raises(ms.DownloadError) as e:
        ms.download(pack, tmp_path, fetch=FakeWeb({"https://h/a.bin": b"1" * 10}))
    assert "공간" in str(e.value)


def test_MS_06_bundled_root_is_found_first(tmp_path):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    pack = pack_of({"https://h/a.bin": b"1"})
    ms.download(pack, bundled, fetch=FakeWeb({"https://h/a.bin": b"1"}))
    assert ms.installed_dir(pack, [bundled, user]) == bundled / pack.id


def test_MS_07_half_written_pack_is_not_installed(tmp_path):
    pack = pack_of({"https://h/a.bin": b"1"})
    (tmp_path / pack.id).mkdir()
    (tmp_path / pack.id / "a.bin").write_bytes(b"1")      # no install marker: interrupted earlier
    assert ms.installed_dir(pack, [tmp_path]) is None


def test_MS_08_catalog_is_complete_and_pinned():
    for src, tgt in [("ko", "en"), ("en", "ko"), ("ja", "en"), ("en", "ja"), ("zh", "en"), ("en", "zh"),
                     ("fr", "en"), ("en", "fr"), ("es", "en"), ("en", "es"), ("de", "en"), ("en", "de")]:
        p = ms.CATALOG[ms.mt_pack_id(src, tgt)]
        assert p.kind == "mt" and len(p.files) == 1 and p.files[0].unzip
    llm = ms.CATALOG[ms.LLM_PACK]
    assert llm.kind == "llm" and sum(f.size for f in llm.files) > 1_000_000_000
    for p in ms.CATALOG.values():
        for f in p.files:
            assert f.url.startswith("https://") and len(f.sha256) == 64 and f.size > 0
        assert all("/resolve/main/" not in f.url for f in p.files)     # pinned revision, never "main"


def test_MS_09_mt_pack_model_dir(tmp_path):
    z = zip_bytes({"xx_en/model/model.bin": b"M", "xx_en/sentencepiece.model": b"S"})
    web = FakeWeb({"https://h/p.zip": z})
    pack = pack_of(web.blobs, unzip=True)
    d = ms.download(pack, tmp_path, fetch=web)
    model_dir, sp = ms.mt_files(d)
    assert model_dir.name == "model" and sp.name == "sentencepiece.model"


def test_MS_10_zip_with_path_traversal_is_refused(tmp_path):
    z = zip_bytes({"../evil.txt": b"x"})
    web = FakeWeb({"https://h/p.zip": z})
    with pytest.raises(ms.DownloadError):
        ms.download(pack_of(web.blobs, unzip=True), tmp_path / "root", fetch=web)
    assert not (tmp_path / "evil.txt").exists()


def test_MS_11_bpe_pack_model_dir(tmp_path):
    z = zip_bytes({"es_en/model/model.bin": b"M", "es_en/bpe.model": b"#version", "es_en/metadata.json": b"{}"})
    web = FakeWeb({"https://h/p.zip": z})
    d = ms.download(pack_of(web.blobs, unzip=True), tmp_path, fetch=web)
    model_dir, tok = ms.mt_files(d)
    assert tok.name == "bpe.model"
