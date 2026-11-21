import io

import pytest

from src.api.storage import LocalStorage, NotFound, S3Storage, make_storage


class FakeS3:
    class _Err(Exception):
        def __init__(self, code):
            self.response = {"Error": {"Code": code}}

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self._Err("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self._Err("404")

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start : start + 2]
        more = start + 2 < len(keys)
        out = {"Contents": [{"Key": k} for k in page], "IsTruncated": more}
        if more:
            out["NextContinuationToken"] = str(start + 2)
        return out


@pytest.fixture(params=["local", "s3"])
def store(request, tmp_path):
    if request.param == "local":
        return LocalStorage(tmp_path)
    return S3Storage("b", client=FakeS3())


def test_roundtrip_list_delete(store):
    store.put("documents/a/meta.json", b"1")
    store.put("documents/b/meta.json", b"2")
    store.put("evaluations/x.json", b"3")
    store.put("documents/c/meta.json", b"4")
    assert store.get("documents/a/meta.json") == b"1"
    assert store.exists("documents/b/meta.json")
    assert store.list("documents/") == [
        "documents/a/meta.json",
        "documents/b/meta.json",
        "documents/c/meta.json",
    ]
    store.delete("documents/a/meta.json")
    assert not store.exists("documents/a/meta.json")


def test_missing_key_raises_not_found(store):
    with pytest.raises(NotFound):
        store.get("nie/ma.json")


@pytest.mark.parametrize("key", ["../x", "/abs", "a//b", ""])
def test_unsafe_keys_rejected(tmp_path, key):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).put(key, b"x")


def test_make_storage_selection(tmp_path):
    local = make_storage({"STORAGE_BACKEND": "local", "STORAGE_DIR": str(tmp_path)})
    assert local.backend == "local"
    with pytest.raises(ValueError):
        make_storage({"STORAGE_BACKEND": "s3"})
    with pytest.raises(ValueError):
        make_storage({"STORAGE_BACKEND": "gcs"})
