"""Model catalog / picker data tests."""

from opencode_harness.models_catalog import build_catalog, find_by_index, find_by_name


def test_catalog_sections_and_config():
    rows = build_catalog(current="kimi", configured=["kimi", "deepseek", "my-local"])
    assert any(r.model == "my-local" and r.section == "Your config" for r in rows)
    assert any(r.is_current and r.model == "kimi" for r in rows)
    # Indices unique & sequential
    idxs = [r.index for r in rows]
    assert idxs == list(range(1, len(rows) + 1))


def test_find_by_index_and_name():
    rows = build_catalog(current="kimi", configured=["kimi", "deepseek"])
    m = find_by_index(rows, 2)
    assert m is not None
    assert find_by_name(rows, "DeEpSeEk") == "deepseek" or find_by_name(rows, "deepseek")
    assert find_by_name(rows, "totally-custom-model") == "totally-custom-model"
