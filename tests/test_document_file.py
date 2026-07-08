"""The original uploaded file can be retrieved for viewing."""


def _upload_bytes(client, name, data, ctype):
    return client.post(
        "/documents",
        files={"file": (name, data, ctype)},
        data={"kind": "treaty", "actor": "clementine"},
    )


def test_uploaded_file_is_viewable(client):
    # Format-agnostic round-trip: the exact uploaded bytes come back, inline,
    # with the right MIME type. (A text upload avoids PDF parsing in the test.)
    payload = b"Treaty wording bytes for round-trip test.\nLine two."
    up = _upload_bytes(client, "wording.txt", payload, "text/plain")
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]

    resp = client.get(f"/documents/{doc_id}/file")
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"].startswith("text/plain")
    # Inline so the browser previews rather than force-downloads.
    assert "inline" in resp.headers.get("content-disposition", "")
    assert "wording.txt" in resp.headers.get("content-disposition", "")


def test_file_endpoint_404_for_missing_document(client):
    assert client.get("/documents/does-not-exist/file").status_code == 404
