"""Host encoding must preserve the existing durable hash contract byte for byte."""

from hashlib import sha256

import pytest

from code_visualizer.persistence.canonical import canonical_data_bytes, canonical_data_chunks


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"z": [True, False, None, -0.0, 1e-30, 10**100], "a": '\u03bb\U0001f600\n\\"'},
        {"rows": [{"index": i, "value": "\u03bb" * 80} for i in range(2000)]},
        "\u03bb" * 100000,
    ],
    ids=["null", "scalars", "large-container", "large-string"],
)
def test_incremental_source_encoding_preserves_existing_bytes_and_hash(value):
    chunks = tuple(canonical_data_chunks(value))
    expected = canonical_data_bytes(value)
    assert b"".join(chunks) == expected
    assert all(0 < len(chunk) <= 64 * 1024 for chunk in chunks)
    digest = sha256()
    for chunk in chunks:
        digest.update(chunk)
    assert digest.digest() == sha256(expected).digest()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_incremental_encoding_rejects_noncanonical_numbers(value):
    with pytest.raises(ValueError):
        tuple(canonical_data_chunks({"value": value}))
