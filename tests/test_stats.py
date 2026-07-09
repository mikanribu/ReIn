"""The /stats endpoint returns coherent dashboard KPIs."""


def test_stats_shape_and_invariants(client):
    s = client.get("/stats").json()
    expected = {
        "treaties", "in_force", "awaiting_review", "amendments",
        "approved_versions", "documents", "audit_entries",
    }
    assert set(s) == expected
    assert all(isinstance(s[k], int) and s[k] >= 0 for k in expected)

    # Invariants that hold for any database state.
    assert s["in_force"] <= s["treaties"]
    assert s["approved_versions"] >= s["in_force"]
    if s["treaties"] > 0:
        assert s["documents"] > 0        # every treaty came from a document
        assert s["audit_entries"] > 0    # and produced audit entries
