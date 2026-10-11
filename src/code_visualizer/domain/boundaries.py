"""Shared public size boundaries, independent of storage and wire encodings."""

# Metadata is portable in one envelope. Large observations belong in resources.
MAX_PORTABLE_ENVELOPE_BYTES = 2 * 1024 * 1024
MAX_RESOURCE_CHUNK_BYTES = 256 * 1024
