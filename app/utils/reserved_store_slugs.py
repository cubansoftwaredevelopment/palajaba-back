RESERVED_STORE_SLUGS = frozenset(
    {
        "admin",
        "comprar",
        "login",
        "registro",
        "tienda",
        "configuracion",
        "aplicacion",
        "g",
    }
)


def is_reserved_store_slug(slug: str | None) -> bool:
    if not slug:
        return True
    return slug.strip().lower() in RESERVED_STORE_SLUGS
