"""Recorrido HTTP de las páginas de servicio al cliente."""

from __future__ import annotations

import unittest

from test_e2e.store_pages.utils.fixtures import (
    cleanup_db,
    headers_for,
    load_seller,
    photo_upload,
    seed_seller,
)
from test_e2e.utils.api import api_client
from test_e2e.utils.database import mongo_configured
from test_e2e.utils.locations import PROVINCE_ID, SELLER_MUNICIPALITY_ID


def _doc(*blocks: dict) -> dict:
    return {"type": "doc", "content": list(blocks)}


def _image(src: str, width: int | None = 100) -> dict:
    attrs = {"src": src, "alt": "Local"}
    if width is not None:
        attrs["width"] = width
    return {"type": "image", "attrs": attrs}


@unittest.skipUnless(mongo_configured(), "MONGODB_URL no configurada")
class StorePagesE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_db()

    def test_saved_page_keeps_image_width_and_is_public(self) -> None:
        seller = seed_seller()
        content = _doc(
            {"type": "paragraph", "content": [{"type": "text", "text": "Preguntas frecuentes", "marks": [{"type": "bold"}]}]},
            _image("/uploads/store-pages/foto.jpg", 40),
        )

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "faq", "content": content},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            page = saved.json()["store_pages"]["faq"]
            self.assertEqual(page["content"][1]["attrs"]["width"], 40)
            self.assertEqual(page["content"][1]["attrs"]["src"], "/uploads/store-pages/foto.jpg")

            me = client.get("/api/auth/me", headers=headers_for(seller))
            self.assertEqual(me.status_code, 200, me.text)
            self.assertEqual(me.json()["store_pages"]["faq"]["content"][1]["attrs"]["width"], 40)

            public = client.get(f"/api/marketplace/stores/{seller['store_slug']}/pages/faq")
            self.assertEqual(public.status_code, 200, public.text)
            body = public.json()
            self.assertEqual(body["title"], "FAQ")
            self.assertEqual(body["content"]["content"][1]["attrs"]["width"], 40)
            self.assertTrue(body["store_pages"]["faq"])
            self.assertFalse(body["store_pages"]["about"])

            catalog = client.get(
                f"/api/marketplace/stores/{seller['store_slug']}/catalog",
                params={"province_id": PROVINCE_ID, "municipality_id": SELLER_MUNICIPALITY_ID},
            )
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertTrue(catalog.json()["store_pages"]["faq"])
            self.assertFalse(catalog.json()["store_pages"]["terms"])

        stored = load_seller(seller["seller_id"])
        self.assertEqual(stored["store_pages"]["faq"]["content"][1]["attrs"]["width"], 40)

    def test_missing_width_is_stored_as_full_size(self) -> None:
        seller = seed_seller()
        content = _doc(_image("https://res.cloudinary.com/demo/image/upload/v1/pala-jaba/store-pages/a.jpg", None))

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "about", "content": content},
            )

        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["store_pages"]["about"]["content"][0]["attrs"]["width"], 100)

    def test_foreign_image_and_invalid_width_are_rejected(self) -> None:
        seller = seed_seller()

        with api_client() as client:
            foreign = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "terms", "content": _doc(_image("https://evil.example/a.png", 80))},
            )
            narrow = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "terms", "content": _doc(_image("/uploads/store-pages/foto.jpg", 4))},
            )

        self.assertEqual(foreign.status_code, 400, foreign.text)
        self.assertEqual(foreign.json()["detail"], "La imagen de la página no es válida.")
        self.assertEqual(narrow.status_code, 400, narrow.text)
        self.assertEqual(narrow.json()["detail"], "El tamaño de la imagen no es válido.")
        self.assertNotIn("store_pages", load_seller(seller["seller_id"]))

    def test_empty_page_stays_out_of_the_public_store(self) -> None:
        seller = seed_seller()
        content = _doc({"type": "paragraph"})

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "delivery_policy", "content": content},
            )
            self.assertEqual(saved.status_code, 200, saved.text)

            public = client.get(
                f"/api/marketplace/stores/{seller['store_slug']}/pages/politica-de-entrega"
            )
            self.assertEqual(public.status_code, 404, public.text)

            catalog = client.get(
                f"/api/marketplace/stores/{seller['store_slug']}/catalog",
                params={"province_id": PROVINCE_ID, "municipality_id": SELLER_MUNICIPALITY_ID},
            )
            self.assertEqual(catalog.status_code, 200, catalog.text)
            self.assertFalse(catalog.json()["store_pages"]["delivery_policy"])

    def test_uploaded_image_can_be_saved_in_the_page(self) -> None:
        seller = seed_seller()

        with api_client() as client:
            uploaded = client.post(
                "/api/auth/me/store-pages/images",
                headers=headers_for(seller),
                files={"photo": photo_upload()},
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            url = uploaded.json()["url"]
            self.assertTrue(url.startswith("/uploads/store-pages/") or "res.cloudinary.com" in url)

            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "terms", "content": _doc(_image(url, 60))},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["store_pages"]["terms"]["content"][0]["attrs"]["width"], 60)
            self.assertEqual(saved.json()["store_pages"]["terms"]["content"][0]["attrs"]["src"], url)

    def test_heading_and_text_color_stay_public(self) -> None:
        seller = seed_seller()
        content = _doc(
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [
                    {
                        "type": "text",
                        "text": "Bienvenida",
                        "marks": [
                            {"type": "bold"},
                            {"type": "textStyle", "attrs": {"color": "#7B4C38"}},
                        ],
                    }
                ],
            },
            {
                "type": "heading",
                "attrs": {"level": 4},
                "content": [
                    {
                        "type": "text",
                        "text": "Detalle",
                        "marks": [{"type": "textStyle", "attrs": {"color": "#abc"}}],
                    }
                ],
            },
        )

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "about", "content": content},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            blocks = saved.json()["store_pages"]["about"]["content"]
            self.assertEqual(blocks[0]["attrs"]["level"], 1)
            self.assertEqual(
                blocks[0]["content"][0]["marks"],
                [
                    {"type": "bold"},
                    {"type": "textStyle", "attrs": {"color": "#7b4c38"}},
                ],
            )
            self.assertEqual(blocks[1]["attrs"]["level"], 4)
            self.assertEqual(blocks[1]["content"][0]["marks"][0]["attrs"]["color"], "#aabbcc")

            public = client.get(f"/api/marketplace/stores/{seller['store_slug']}/pages/sobre-nosotros")
            self.assertEqual(public.status_code, 200, public.text)
            self.assertEqual(public.json()["content"]["content"][0]["attrs"]["level"], 1)
            self.assertEqual(
                public.json()["content"]["content"][1]["content"][0]["marks"][0]["attrs"]["color"],
                "#aabbcc",
            )

    def test_editor_rgb_color_and_image_are_saved(self) -> None:
        seller = seed_seller()
        content = _doc(
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "marks": [{"type": "bold"}], "text": "Uniendo familias"}],
            },
            {"type": "paragraph"},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "BanderaExpress",
                        "marks": [{"type": "textStyle", "attrs": {"color": "rgb(71, 85, 105)"}}],
                    }
                ],
            },
            {
                "type": "image",
                "attrs": {
                    "src": "/uploads/store-pages/foto.jpg",
                    "alt": "Imagen de la página",
                    "title": None,
                    "width": 63,
                    "height": None,
                },
            },
        )

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "about", "content": content},
            )

        self.assertEqual(saved.status_code, 200, saved.text)
        blocks = saved.json()["store_pages"]["about"]["content"]
        self.assertEqual(blocks[2]["content"][0]["marks"][0]["attrs"]["color"], "#475569")
        self.assertEqual(
            blocks[3]["attrs"],
            {"src": "/uploads/store-pages/foto.jpg", "width": 63, "alt": "Imagen de la página"},
        )

    def test_text_and_image_links_are_saved(self) -> None:
        seller = seed_seller()
        content = _doc(
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Sitio",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {
                                    "href": "https://bandera.example/envio",
                                    "target": "_blank",
                                    "rel": "noopener",
                                    "class": "evil",
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "type": "image",
                "attrs": {
                    "src": "/uploads/store-pages/foto.jpg",
                    "alt": "Local",
                    "width": 50,
                    "href": "/faq",
                },
            },
        )

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "about", "content": content},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            blocks = saved.json()["store_pages"]["about"]["content"]
            self.assertEqual(blocks[0]["content"][0]["marks"], [{"type": "link", "attrs": {"href": "https://bandera.example/envio"}}])
            self.assertEqual(blocks[1]["attrs"]["href"], "/faq")

            public = client.get(f"/api/marketplace/stores/{seller['store_slug']}/pages/sobre-nosotros")
            self.assertEqual(public.status_code, 200, public.text)
            published = public.json()["content"]["content"]
            self.assertEqual(published[0]["content"][0]["marks"][0]["attrs"]["href"], "https://bandera.example/envio")
            self.assertEqual(published[1]["attrs"]["href"], "/faq")

            script = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={
                    "page": "terms",
                    "content": _doc(
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Mal",
                                    "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                                }
                            ],
                        }
                    ),
                },
            )
            image = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={
                    "page": "terms",
                    "content": _doc(
                        {
                            "type": "image",
                            "attrs": {
                                "src": "/uploads/store-pages/foto.jpg",
                                "width": 40,
                                "href": "javascript:alert(1)",
                            },
                        }
                    ),
                },
            )

        self.assertEqual(script.status_code, 400, script.text)
        self.assertEqual(image.status_code, 400, image.text)
        self.assertEqual(script.json()["detail"], "El contenido de la página no es válido.")
        self.assertEqual(image.json()["detail"], "El contenido de la página no es válido.")

    def test_text_and_image_alignment_are_saved(self) -> None:
        seller = seed_seller()
        content = _doc(
            {
                "type": "heading",
                "attrs": {"level": 2, "textAlign": "center"},
                "content": [{"type": "text", "text": "Centro"}],
            },
            {
                "type": "paragraph",
                "attrs": {"textAlign": "right"},
                "content": [{"type": "text", "text": "Derecha"}],
            },
            {
                "type": "paragraph",
                "attrs": {"textAlign": "left"},
                "content": [{"type": "text", "text": "Izquierda"}],
            },
            {
                "type": "image",
                "attrs": {
                    "src": "/uploads/store-pages/foto.jpg",
                    "alt": "Local",
                    "width": 40,
                    "textAlign": "center",
                },
            },
        )

        with api_client() as client:
            saved = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "faq", "content": content},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            blocks = saved.json()["store_pages"]["faq"]["content"]
            self.assertEqual(blocks[0]["attrs"], {"level": 2, "textAlign": "center"})
            self.assertEqual(blocks[1]["attrs"]["textAlign"], "right")
            self.assertNotIn("attrs", blocks[2])
            self.assertEqual(blocks[3]["attrs"]["textAlign"], "center")
            self.assertEqual(blocks[3]["attrs"]["width"], 40)

            public = client.get(f"/api/marketplace/stores/{seller['store_slug']}/pages/faq")
            self.assertEqual(public.status_code, 200, public.text)
            published = public.json()["content"]["content"]
            self.assertEqual(published[0]["attrs"]["textAlign"], "center")
            self.assertEqual(published[1]["attrs"]["textAlign"], "right")
            self.assertEqual(published[3]["attrs"]["textAlign"], "center")

        bad = _doc(
            {
                "type": "paragraph",
                "attrs": {"textAlign": "center;color:red"},
                "content": [{"type": "text", "text": "Mal"}],
            }
        )
        with api_client() as client:
            rejected = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "terms", "content": bad},
            )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(rejected.json()["detail"], "El contenido de la página no es válido.")

    def test_invalid_text_color_and_heading_are_rejected(self) -> None:
        seller = seed_seller()
        bad_color = _doc(
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Hola",
                        "marks": [{"type": "textStyle", "attrs": {"color": "red; background:url(x)"}}],
                    }
                ],
            }
        )
        bad_heading = _doc(
            {
                "type": "heading",
                "attrs": {"level": 5},
                "content": [{"type": "text", "text": "Hola"}],
            }
        )

        with api_client() as client:
            color = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "faq", "content": bad_color},
            )
            heading = client.patch(
                "/api/auth/me/store-pages",
                headers=headers_for(seller),
                json={"page": "faq", "content": bad_heading},
            )

        self.assertEqual(color.status_code, 400, color.text)
        self.assertEqual(color.json()["detail"], "El contenido de la página no es válido.")
        self.assertEqual(heading.status_code, 400, heading.text)
        self.assertEqual(heading.json()["detail"], "El contenido de la página no es válido.")
        self.assertNotIn("store_pages", load_seller(seller["seller_id"]))
