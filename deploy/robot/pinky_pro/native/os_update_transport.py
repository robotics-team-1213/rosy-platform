"""Deterministic GitHub assets for one unchanged, signed logical OS bundle."""

CHUNK_BYTES = 1024**3
GITHUB_MAX_ASSET_BYTES = 2 * 1024**3 - 1


def bundle_assets(bundle):
    name, size = bundle["filename"], bundle["size_bytes"]
    if (not isinstance(name, str) or not name.endswith(".raucb")
            or any(character in name for character in ("/", "\\", "\0"))):
        raise ValueError("OS transport bundle filename is invalid")
    if type(size) is not int or not 1 <= size <= 16 * 1024**3:
        raise ValueError("OS transport bundle size exceeds its signed limit")
    if size <= GITHUB_MAX_ASSET_BYTES:
        return [(name, size)]
    count = (size + CHUNK_BYTES - 1) // CHUNK_BYTES
    if count > 16:
        raise ValueError("OS transport bundle requires more than sixteen parts")
    return [(f"{name}.part{number:03}", min(CHUNK_BYTES, size - number * CHUNK_BYTES))
            for number in range(count)]
