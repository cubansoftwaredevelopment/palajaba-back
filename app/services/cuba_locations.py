"""Provincias y municipios de Cuba. Generado por scripts/gen-cuba-locations.mjs."""

from __future__ import annotations

from fastapi import HTTPException, status

PROVINCE_NAMES: dict[str, str] = {
    "pinar-del-rio": "Pinar del Río",
    "artemisa": "Artemisa",
    "la-habana": "La Habana",
    "mayabeque": "Mayabeque",
    "matanzas": "Matanzas",
    "cienfuegos": "Cienfuegos",
    "villa-clara": "Villa Clara",
    "sancti-spiritus": "Sancti Spíritus",
    "ciego-de-avila": "Ciego de Ávila",
    "camaguey": "Camagüey",
    "las-tunas": "Las Tunas",
    "holguin": "Holguín",
    "granma": "Granma",
    "santiago-de-cuba": "Santiago de Cuba",
    "guantanamo": "Guantánamo",
    "isla-de-la-juventud": "Isla de la Juventud"
}

MUNICIPALITIES_BY_PROVINCE: dict[str, dict[str, str]] = {
    "pinar-del-rio": {
        "consolacion-del-sur": "Consolación del Sur",
        "guane": "Guane",
        "la-palma": "La Palma",
        "los-palacios": "Los Palacios",
        "mantua": "Mantua",
        "minas-de-matahambre": "Minas de Matahambre",
        "pinar-del-rio": "Pinar del Río",
        "san-juan-y-martinez": "San Juan y Martínez",
        "san-luis": "San Luis",
        "sandino": "Sandino",
        "vinales": "Viñales"
    },
    "artemisa": {
        "alquizar": "Alquízar",
        "artemisa": "Artemisa",
        "bahia-honda": "Bahía Honda",
        "bauta": "Bauta",
        "caimito": "Caimito",
        "candelaria": "Candelaria",
        "guanajay": "Guanajay",
        "guira-de-melena": "Güira de Melena",
        "mariel": "Mariel",
        "san-antonio-de-los-banos": "San Antonio de los Baños",
        "san-cristobal": "San Cristóbal"
    },
    "la-habana": {
        "arroyo-naranjo": "Arroyo Naranjo",
        "boyeros": "Boyeros",
        "centro-habana": "Centro Habana",
        "cerro": "Cerro",
        "cotorro": "Cotorro",
        "diez-de-octubre": "Diez de Octubre",
        "guanabacoa": "Guanabacoa",
        "la-habana-del-este": "La Habana del Este",
        "la-habana-vieja": "La Habana Vieja",
        "la-lisa": "La Lisa",
        "marianao": "Marianao",
        "playa": "Playa",
        "plaza-de-la-revolucion": "Plaza de la Revolución",
        "regla": "Regla",
        "san-miguel-del-padron": "San Miguel del Padrón"
    },
    "mayabeque": {
        "batabano": "Batabanó",
        "bejucal": "Bejucal",
        "guines": "Güines",
        "jaruco": "Jaruco",
        "madruga": "Madruga",
        "melena-del-sur": "Melena del Sur",
        "nueva-paz": "Nueva Paz",
        "quivican": "Quivicán",
        "san-jose-de-las-lajas": "San José de las Lajas",
        "san-nicolas": "San Nicolás",
        "santa-cruz-del-norte": "Santa Cruz del Norte"
    },
    "matanzas": {
        "calimete": "Calimete",
        "cardenas": "Cárdenas",
        "cienaga-de-zapata": "Ciénaga de Zapata",
        "colon": "Colón",
        "jaguey-grande": "Jagüey Grande",
        "jovellanos": "Jovellanos",
        "limonar": "Limonar",
        "los-arabos": "Los Arabos",
        "marti": "Martí",
        "matanzas": "Matanzas",
        "pedro-betancourt": "Pedro Betancourt",
        "perico": "Perico",
        "union-de-reyes": "Unión de Reyes"
    },
    "cienfuegos": {
        "abreus": "Abreus",
        "aguada-de-pasajeros": "Aguada de Pasajeros",
        "cienfuegos": "Cienfuegos",
        "cruces": "Cruces",
        "cumanayagua": "Cumanayagua",
        "lajas": "Lajas",
        "palmira": "Palmira",
        "rodas": "Rodas"
    },
    "villa-clara": {
        "caibarien": "Caibarién",
        "camajuani": "Camajuaní",
        "cifuentes": "Cifuentes",
        "corralillo": "Corralillo",
        "encrucijada": "Encrucijada",
        "manicaragua": "Manicaragua",
        "placetas": "Placetas",
        "quemado-de-guines": "Quemado de Güines",
        "ranchuelo": "Ranchuelo",
        "san-juan-de-los-remedios": "San Juan de los Remedios",
        "sagua-la-grande": "Sagua la Grande",
        "santa-clara": "Santa Clara",
        "santo-domingo": "Santo Domingo"
    },
    "sancti-spiritus": {
        "cabaiguan": "Cabaiguán",
        "fomento": "Fomento",
        "jatibonico": "Jatibonico",
        "la-sierpe": "La Sierpe",
        "sancti-spiritus": "Sancti Spíritus",
        "taguasco": "Taguasco",
        "trinidad": "Trinidad",
        "yaguajay": "Yaguajay"
    },
    "ciego-de-avila": {
        "baragua": "Baraguá",
        "bolivia": "Bolivia",
        "chambas": "Chambas",
        "ciego-de-avila": "Ciego de Ávila",
        "ciro-redondo": "Ciro Redondo",
        "florencia": "Florencia",
        "majagua": "Majagua",
        "moron": "Morón",
        "primero-de-enero": "Primero de Enero",
        "venezuela": "Venezuela"
    },
    "camaguey": {
        "camaguey": "Camagüey",
        "carlos-m-de-cespedes": "Carlos M. de Céspedes",
        "esmeralda": "Esmeralda",
        "florida": "Florida",
        "guaimaro": "Guáimaro",
        "jimaguayu": "Jimaguayú",
        "minas": "Minas",
        "najasa": "Najasa",
        "nuevitas": "Nuevitas",
        "santa-cruz-del-sur": "Santa Cruz del Sur",
        "sibanicu": "Sibanicú",
        "sierra-de-cubitas": "Sierra de Cubitas",
        "vertientes": "Vertientes"
    },
    "las-tunas": {
        "amancio": "Amancio",
        "colombia": "Colombia",
        "jesus-menendez": "Jesús Menéndez",
        "jobabo": "Jobabo",
        "las-tunas": "Las Tunas",
        "majibacoa": "Majibacoa",
        "manati": "Manatí",
        "puerto-padre": "Puerto Padre"
    },
    "holguin": {
        "antilla": "Antilla",
        "baguanos": "Báguanos",
        "banes": "Banes",
        "cacocum": "Cacocum",
        "calixto-garcia": "Calixto García",
        "cueto": "Cueto",
        "frank-pais": "Frank País",
        "gibara": "Gibara",
        "holguin": "Holguín",
        "mayari": "Mayarí",
        "moa": "Moa",
        "rafael-freyre": "Rafael Freyre",
        "sagua-de-tanamo": "Sagua de Tánamo",
        "urbano-noris": "Urbano Noris"
    },
    "granma": {
        "bartolome-maso": "Bartolomé Masó",
        "bayamo": "Bayamo",
        "buey-arriba": "Buey Arriba",
        "campechuela": "Campechuela",
        "cauto-cristo": "Cauto Cristo",
        "guisa": "Guisa",
        "jiguani": "Jiguaní",
        "manzanillo": "Manzanillo",
        "media-luna": "Media Luna",
        "niquero": "Niquero",
        "pilon": "Pilón",
        "rio-cauto": "Río Cauto",
        "yara": "Yara"
    },
    "santiago-de-cuba": {
        "contramaestre": "Contramaestre",
        "guama": "Guamá",
        "mella": "Mella",
        "palma-soriano": "Palma Soriano",
        "san-luis": "San Luis",
        "santiago-de-cuba": "Santiago de Cuba",
        "segundo-frente": "Segundo Frente",
        "songo-la-maya": "Songo-La Maya",
        "tercer-frente": "Tercer Frente"
    },
    "guantanamo": {
        "baracoa": "Baracoa",
        "caimanera": "Caimanera",
        "el-salvador": "El Salvador",
        "guantanamo": "Guantánamo",
        "imias": "Imías",
        "maisi": "Maisí",
        "manuel-tames": "Manuel Tames",
        "niceto-perez": "Niceto Pérez",
        "san-antonio-del-sur": "San Antonio del Sur",
        "yateras": "Yateras"
    },
    "isla-de-la-juventud": {
        "isla-de-la-juventud": "Isla de la Juventud"
    }
}


def validate_business_area(
    province_id: str,
    province_name: str,
    municipality_id: str,
    municipality_name: str,
) -> dict[str, str]:
    expected_province = PROVINCE_NAMES.get(province_id)
    if not expected_province:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provincia no válida.",
        )
    if province_name.strip() != expected_province:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de la provincia no coincide.",
        )

    municipalities = MUNICIPALITIES_BY_PROVINCE.get(province_id, {})
    expected_municipality = municipalities.get(municipality_id)
    if not expected_municipality:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Municipio no válido para la provincia seleccionada.",
        )
    if municipality_name.strip() != expected_municipality:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre del municipio no coincide.",
        )

    return {
        "province_id": province_id,
        "province_name": expected_province,
        "municipality_id": municipality_id,
        "municipality_name": expected_municipality,
    }
